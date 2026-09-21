"""The plan as nodes and edges."""

from __future__ import annotations

from markupsafe import Markup

from ..index import Index
from ..model import KINDS as KIND_LADDER
from ..vendor import _library
from .controls import _FILTER_JS, _facets_html, _summary_html
from .env import _compiled
from .pop import _POP_STYLE, _pop_js
from .rows import _row
from .shell import STATIC, Links, _page, _titles
from .tokens import PRIORITIES, PRIORITY_GLYPH, PRIORITY_LEVEL, STATUS_GLYPH, STATUSES


def _elements(index: Index) -> list[dict]:
    elements: list[dict] = []
    for record_id, record in index.plan.items():
        # The same row the table filters on, not a graph-shaped subset of it. The
        # facet bar is one control bar over one `matches()`, and a node carrying
        # only what cytoscape draws is how a dropdown ends up filtering the table
        # and quietly doing nothing here.
        data = _row(index, record_id) | {
            # The title alone, under the key cytoscape draws. The id is on every
            # other page and in the URL the node opens; on a box 150px wide it
            # cost a line of the only text anybody reads the graph for.
            "label": record.title,
            # Carried so a new edge is added to what is there rather than replacing
            # it: a PATCH sends the whole field, and depends_on is a list.
            #
            # Plan members only, like the edge list below: `blocked_by` is total
            # over records, and a hand-written edge to an unplanned record must
            # not put that record's id on a plan page — nor hand cytoscape an
            # edge whose source is a node it was never given. The graph already
            # drops an edge to an id no record has, and an edge the plan cannot
            # draw is the same case; the record page is where the full field is
            # read and edited.
            "depends_on": [b for b in index.blocked_by[record_id] if b in index.plan],
            # Whether the stored field holds MORE than the list above — a
            # hand-written dependency on a record this page cannot draw. A
            # boolean and never the ids (the exclusion sweep forbids an inbox
            # id in this page's bytes): it is what lets the canvas refuse an
            # edge edit that would rebuild `depends_on` from the filtered list
            # and silently delete somebody's line.
            "off_plan_deps": any(b not in index.plan for b in index.blocked_by[record_id]),
        }
        # No parent guard of its own: `_row` already resolves `parent` against
        # the plan and nulls what it cannot draw, and a second spelling of that
        # rule here is the drift this file keeps paying for. Cytoscape treats a
        # null parent as a top-level node.
        elements.append({"data": data})
    for record_id in index.plan:
        for blocker in index.blocked_by[record_id]:
            if blocker in index.plan:
                elements.append(
                    {"data": {"source": blocker, "target": record_id, "kind": "depends"}}
                )
    return elements


# One hint, in both modes, and at the far end of the search box's line rather
# than on a row of its own. There used to be a second paragraph that swapped in
# on entering edit mode, saying what edit mode is for — but the status text
# beside the button already says it, in the place you are looking when you press
# the button, so the page explained one mode twice and moved the whole canvas
# down a line to do it. The remaining one was still a row, and a row here is
# canvas: it stood between the heading and the filters with nothing beside it.
_GRAPH_HINT = Markup(
    '<p class="hint" id="panhint">Double-click a node to open it. Drag to pan, '
    "scroll to zoom, drag a node to move it.</p>"
)

_GRAPH = """
{#- Announced, not drawn: the lit nav item says this already. See `.sr-only`. -#}
<h1 class="sr-only">Graph</h1>
{{ facets }}
{#- The key and the count are one row. The key is the one thing on this canvas
    that is not a word — every swatch is the token the node is actually filled
    with and carries the glyph the node's title is prefixed with, so it cannot
    drift from the graph and it keys both channels rather than only the one a
    dichromat cannot use. The count says how much of the plan survived the
    filters. Neither is a control, and between them they were two of the six rows
    that left 268px of an 806px window for the drawing. -#}
{% if editable %}
{#- Above the drawing it writes, which is where every other page now keeps the
    control that commits it — jcanton, 2026-08-20, "consistency!". It was under
    the canvas, on F15's argument that a commit action belongs below the form it
    commits; what that argument actually bought was reachability, and the sticky
    it shipped alongside is what delivers that from either edge.

    Moving it costs the drawing nothing, and that is measured rather than
    asserted: `measureRoom` sizes the canvas to `innerHeight - above - below` off
    the laid-out page, so a bar that crosses from `below` to `above` moves itself
    from one term to the other. `--room` went 595px to 607px at 1400x900 — the
    canvas GAINED twelve pixels, because up here the bar's 1.5rem top margin
    collapses with the filter row's and down there it did not. What the move
    actually buys is the short window: below 430px the page finally scrolls, and a
    bar last in the markup under a `top: 0` shell rule is a bar you cannot see
    from the top of the page. Measured at 1400x380, both ways. -#}
<div class="commitbar" id="commitbar">
  <button type="button" id="connect">Edit dependencies</button>
  {#- A mode, for the same reason the other one is: a plain drag on this canvas
      means "move the node" and always has, so the gesture that files one record
      inside another has to say which it is. What is new is that the dragging,
      the drop target and the highlighting are the extension's now — the version
      of this written here could not tell the reader where the node would land,
      because the box it would land in moves with the node. -#}
  <button type="button" id="save" hidden>Save</button>
  <button type="button" id="discard" hidden>Reset</button>
  <span id="state" role="status"></span>
  <input type="hidden" id="base" value="{{ base_commit }}">
</div>
{% endif %}
<div class="canvas">
{#- Over the drawing rather than above it — jcanton, 2026-08-20, to get the
    vertical space back. The canvas is the tallest thing on the page and the
    two key rows were costing it two lines before it started. Top right, out
    of the way of a layout that runs left to right and top down, and it stops
    taking pointer events so it cannot swallow a click on a node beneath it. -#}
<div class="keys">
{#- Priority first, on the left, because that is the one nobody could see —
    jcanton, 2026-08-20, having noticed one project drawn with a thicker line and
    had to ask why. The encoding was already there and legible; the page simply
    never said what it meant, and an encoding nobody has been told is decoration.

    The key SHOWS the thickness rather than standing for it with a glyph. An
    arrow or a set of bars would be a second thing to learn on top of the thing
    it explains, and it would appear nowhere on the drawing — this way the key
    and the node are the same picture at two sizes. -#}
{#- Status first, priority under it — jcanton, 2026-08-24, on seeing the two
    paired from the right: "put the status row on top of the priority row,
    better!" The status row is the longer of the two now, so the longer row leads
    and the shorter one hangs under its right end, which reads as one block
    rather than as a step.
    The two rows in ONE grid, so a key in the priority row and the key above it
    in the status row start at the same x. Two lists side by side sized each key
    to its own word and the rows came out staggered — jcanton, three times, most
    recently "the legend is still wonky: not aligned (make it a table with two
    rows maybe?)". This is that table: `display: contents` on each list hands its
    keys to the grid, so the markup stays two labelled lists and the layout is
    one set of columns. -#}
<div class="legends">
<ul class="legend" aria-label="What a node's colour and mark mean">
  <li class="legendname">status</li>
  {% for status in statuses %}
  <li><span class="swatch st-{{ status }}" aria-hidden="true">{{ glyph(status) }}</span
    >{{ status|human }}</li>
  {% endfor %}
</ul>
<ul class="legend shorter" aria-label="What a node's line thickness means">
  <li class="legendname">priority</li>
  {#- Reversed: the meter fills to the RIGHT, so the key reads low to high the way
      the bars grow — jcanton, 2026-08-20. `PRIORITIES` itself stays highest-first,
      because that is the order a dropdown offers them in and the order the table
      sorts by, and neither wants the quietest thing at the top of the list. -#}
  {% for priority in priorities|reverse %}
  <li><span class="swatch pri pri-{{ priority }}" aria-hidden="true"><span
      class="primark">{{ pri(priority) }}</span></span>{{ priority|human }}</li>
  {% endfor %}
</ul>
</div>
{#- **No count here.** It rode with the keys from 2026-08-20, when taking it out
    of a row of its own was worth a corner of the canvas. jcanton, 2026-08-25,
    asked for the three plan views to share one bar — "search box+description (to
    each its own)+problems+N/M shown" — and once the count is in that bar,
    a second copy over the drawing is the same number in two places. It is in
    `#controls .searching` now, through `_summary_html`, and `#context` — the
    sentence about how many nodes are faded — went with it. -#}
</div>

  {#- The way out of a focused subtree, and the only one there is. The focus is
      page state and not a query parameter — `matches()` (`controls.py`) answers
      about one row at a time, and "is filed under this box" is a question about
      the tree rather than about a row — so `showTheWayOut` cannot see it and the
      facet bar's own Clear does not draw itself for it. A narrowing with nothing
      on screen to undo it is a one-way door, so this bar is up for exactly as
      long as the focus is, it names what is being shown, and its button is the
      whole of the undo.

      Drawn for a reader as well: focusing hides nodes and writes nothing, so it
      belongs to the same half of this page as panning, zooming and the filters,
      which the rendered export has always had. -#}
  <div class="focusbar" id="focusbar" hidden>
    <span class="focusname"></span>
    <button type="button" id="unfocus">Show the whole plan</button>
  </div>

  {#- `data-fills`: this is the box the shell measures the window into. A canvas
      has no size of its own — whatever it is told, it draws — so of the three
      boxes the shell measures (the table's, this one, the timeline's) it is
      the one that takes a `height` rather than a cap. -#}
  <div id="cy" data-fills></div>
  {#- Written by the script, because which emptiness this is is not known until
      the payload has been parsed and the filter has run. -#}
  <div id="nothing" hidden>
    <p class="headline"></p>
    <p class="hint"></p>
    <button type="button" id="clear-filters" hidden>Clear filters</button>
  </div>
</div>
<script id="elements" type="application/json">{{ elements|tojson }}</script>
{#- `model.PARENT_KINDS`: which kind may hold which. The extension asks before it
    lets go, so a drop the server would refuse is one the canvas never offers. -#}
<script>{{ cytoscape }}</script>
{#- ELK rather than dagre, because dagre does not know what a nested node is: it
    lays a plan whose pitches hold tasks out as though it were flat, and the
    result was measured on the real plan at 7% of the canvas with three of six
    dependency edges drawn across a box they are not attached to. ELK's layered
    algorithm is hierarchy-aware and put the same plan on the same canvas with
    none of them crossing. It is the one vendored file that is not permissively
    licensed — EPL-2.0, notice beside it in `static/`, see `VENDOR.md`. -#}
<script>{{ elk }}</script>
{#- Filing one thing inside another was written here by hand, shipped, and
    removed the same day: a compound's outline follows the child being dragged,
    so the drop looked like nothing happening until the page reloaded. This
    extension is 14 KB, has no dependencies, and had solved it — see `Look for it
    before you write it` in AGENTS.md, which this is the worked example of.
    Its sibling `cytoscape-edgehandles` was audited and refused in the same pass:
    it wants two lodash modules as globals to replace a gesture that works. -#}
{{ filters }}
{#- The right-click menu, ABOVE this page's own script and not below it. Both are
    classic scripts sharing one global scope and a function in a later block is
    not hoisted into an earlier one, so the `popServes(...)` call further down
    needs this block to have already run. -#}
{{ pop }}
<script>

// A payload that did not survive the trip is a third kind of empty, and an empty
// canvas looks the same whichever one it is: a bordered box with nothing in it,
// which reads as a graph that failed to draw. Parsed defensively so the page can
// tell the three apart — without the guard a truncated payload threw here and
// took the whole script with it, leaving the box and no explanation at all.
let ELEMENTS = null;
try {
  ELEMENTS = JSON.parse(document.getElementById('elements').textContent);
} catch (error) { ELEMENTS = null; }
const LOADED = ELEMENTS !== null;

// Read from the stylesheet rather than repeated here, so one token set decides
// what a status looks like on the timeline, in the table and on this canvas.
//
// Resolved through a probe element rather than read straight off the root. A
// custom property's computed value is the token stream it was written as, so a
// colour scheme's `--st-done: color-mix(in oklab, #859900 42%, #002b36)` comes
// back as that whole string — which CSS understands and cytoscape does not: it
// failed to parse every fill and drew the entire graph in its default grey, with
// the borders still correct, which is a drawing that looks deliberate.
//
// Resolved through a canvas rather than through `getComputedStyle`, which hands
// back the mix in the space it was mixed in — `oklab(0.42 -0.05 0.03)` — and
// that is one more thing cytoscape cannot read. A 1x1 fill is the browser's own
// conversion to sRGB, whatever the value was written as, and it costs one
// context that is made once.
const dye = document.createElement('canvas').getContext('2d', {willReadFrequently: true});
const inSRGB = value => {
  dye.clearRect(0, 0, 1, 1);
  dye.fillStyle = '#000';
  dye.fillStyle = value;              // ignored if the browser cannot read it
  dye.fillRect(0, 0, 1, 1);
  const [r, g, b] = dye.getImageData(0, 0, 1, 1).data;
  return `rgb(${r}, ${g}, ${b})`;
};
const token = name => {
  const raw = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return raw && raw.includes('(') ? inSRGB(raw) : raw;
};
// The ladder itself, handed over rather than retyped — and it was retyped, three
// times, in the three maps below. They were five-key object literals written out
// by hand, and the day the ladder gained `thinking` all three answered
// `undefined` for it: cytoscape took `background-color: undefined`, logged it and
// drew its own #999, which is close enough to `shelved` to be read as it, on the
// one surface where the fill is the whole status channel. It did not throw and it
// did not look broken. `GLYPH` and `LEVELS` on this page were already derived
// from the same vocabulary; these three are now too, so a rung arrives on the
// canvas on the commit that adds it.
const STATUS_LADDER = {{ statuses|tojson }};
const byStatus = suffix => Object.fromEntries(
  STATUS_LADDER.map(status => [status, token(`--st-${status}${suffix}`)]));
const COLOUR = () => byStatus('');
// A label's colour belongs to the fill it sits on, not to the page. In dark mode
// these fills are light shapes carrying dark ink, so the text on a node flips
// with its own background rather than with the theme's foreground — white on
// them would be exactly the failure the light theme avoids.
const INK = () => byStatus('-ink');
// The edge of a status shape, the same token the timeline strokes its bars with
// and the same one the legend below draws round its keys. Read through token()
// and re-read on themechange like the other two: a border resolved once at build
// time is a light theme's border still on the boxes after the toggle.
const LINE = () => byStatus('-line');
// The fill is the only status channel on this canvas, and five fills on a
// luminance ladder are separable without being nameable: you can see that one
// box is darker than the next and still not know which state that is. So a
// node's own title carries the status glyph in front of it — the same glyph the
// timeline draws at a bar's left edge and the legend below shows in its swatch.
// Not a token: a shape, so it survives a screenshot, a projector and deuteranopia.
const GLYPH = {{ glyphs|tojson }};
// A card's name, and the two marks in front of it: the priority block, then the
// status glyph, then the title — the same order and the same characters the
// table's two chips carry, on one line.
//
// The priority mark was an image in the corner of the card, on the grounds that
// cytoscape draws a label with the font it is given and no fallback chain, so a
// block element came out as a .notdef box. That is not what happens: asked on a
// canvas with this page's own stack, `\u2585` measures 10px against 6.56px for a
// private-use codepoint, which is the browser falling back per glyph exactly as
// it does in HTML. jcanton, 2026-08-21: "the priority tofu should be just a
// glyph in line with the status glyph, currently it's separate and vertically
// aligned".
//
// What it costs: a label is one colour, so the rung's colour is not on the card.
// The border's thickness still carries it — that is the channel the legend keys —
// and the colour is on the same mark everywhere it can be, which is the table,
// the detail page and the key itself.
const PRIGLYPH = {{ priglyphs|tojson }};
const LEVELS = {{ levels|tojson }};

// A card's name, and its two marks — as a picture rather than as two characters
// in front of the title, because a cytoscape label is ONE ink and jcanton wants
// the marks coloured the way the table colours them: the priority block in its
// rung's colour, the status glyph in the status's own line colour.
//
// So the label is the title alone and the marks are a `data:` SVG at the card's
// left edge, vertically centred against the text. That is the same arrangement
// as the characters they replace on a one-line title, and on a two-line one the
// pair sits level with the middle of the block rather than with its first line —
// which is the cost of colour, and it is the only place cytoscape leaves.
// A card's title alone — its marks are the image below, which is how they get a
// colour each. A box's title with both marks written into it, which is how they
// get onto its line at all: a compound's name is drawn on the box's own top edge
// with an opaque background behind it, and an image placed in a compound's
// rectangle is positioned against the rectangle rather than against that line —
// it lands in the corner, under the name's background and clipped by the box's
// own radius. Tried, looked at, and not worth the pixel-chasing.
//
// So a box's marks are the same two characters in the box's own ink. jcanton
// asked for the boxes to have them too, and this is the half of that a canvas
// will give: the shape is there, the colour is not.
const labelOf = node => node.isChildless()
  ? (node.data('label') || '')
  : [PRIGLYPH[node.data('priority')] || '', GLYPH[node.data('status')] || '',
     node.data('label') || ''].filter(Boolean).join(' ');

// TELLING ONE EDGE FROM ANOTHER. Where several dependencies run through the same
// corridor, they are one line of one width with one arrowhead and the eye cannot
// follow any of them to its end. So each edge gets its own ink and its own
// weight, from a hash of the two ids, so the same dependency looks the same on
// every load and on everybody's screen.
//
// **Three inks and three weights, nine buckets, and the numbers are why.** The
// six inks this had before were mixed 62% towards `--line-strong` to keep them
// quiet, and measured against the categorical-palette checks that mix put every
// one of them BELOW the chroma floor -- they were six greys. Worst pair 2.8 dE
// under deuteranopia and 6.6 dE to normal vision, where 15 is the floor at which
// two colours can be told apart at all. jcanton, 2026-09-21: "they hardly are:
// they all appear the same". They were not distinguishable, and no amount of
// looking at them was going to say so.
//
// Unmixing them is not enough: the raw tokens score 10.6 dE, and no subset of
// the six passes in both themes. They are status and chip inks and were never a
// categorical palette. These three -- teal, amber, purple -- are the best trio
// the tokens hold: 14.5 dE under protanopia and 19.8 to normal vision in light,
// 15.1 and 19.1 in dark. Both clear their floors with room.
//
// `--ok` and `--danger` are gone from here for a second reason, which is a bug
// rather than a measurement. `--ok` IS the colour of `edge.pending` and
// `--danger` sits beside `edge.dropping`'s `--sev-blocker`, so one ordinary edge
// in six was drawn in the ink that means "not committed yet". A status colour is
// reserved; it cannot also be series four.
//
// **More hues would be worse, and that was measured too.** Four evenly spaced
// hues drop to 6.2 dE under deuteranopia -- half the separation of these three --
// and being derived rather than tokens they would look identical under Gruvbox,
// Solarized and the rest, which is the harmony this page is built on. Weight is
// the axis that costs nothing: three widths give nine buckets with every colour
// pair still at 14.5 dE.
//
// The line stays SOLID and the arrowhead stays one shape. Dashed is what an
// uncommitted connection looks like here and that meaning is not for sale;
// jcanton on the heads: "it's only one arrowhead per edge, it doesn't help
// figuring out where the edge starts by looking at the end only".
const EDGE_INKS = ['--accent', '--pri-medium', '--st-shaping-line'];
// Far enough apart to be read as different weights rather than as antialiasing,
// and the heaviest still thin enough to be a drawn line rather than a bar.
const EDGE_WIDTHS = [1.2, 2.0, 3.0];

// Relative luminance, sRGB, for the one question this page asks of a colour:
// whether a line in it can be seen against the page at all. `--line-strong` is
// held at 3:1 in both themes and that is the bar an edge inherits.
const LUMA = value => {
  const [r, g, b] = inSRGB(value).match(/\d+/g).map(Number).map(c => {
    const u = c / 255;
    return u <= 0.03928 ? u / 12.92 : Math.pow((u + 0.055) / 1.055, 2.4);
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
};
const CONTRAST = (one, two) => {
  const [a, b] = [LUMA(one), LUMA(two)].sort((x, y) => y - x);
  return (a + 0.05) / (b + 0.05);
};

// Lifted towards the page's own text colour until it clears 3:1, and not one step
// further. `--st-shaping-line` under the dark theme is 2.39:1 against the
// surface -- a dependency you can see is the whole point of colouring it -- while
// the same token is fine in light and fine as a chip everywhere. So the lift is
// computed against whatever theme is actually loaded rather than written into
// one of them, which is also what keeps this honest under the eight colour
// schemes nobody measured.
const legible = hue => {
  const page = token('--bg');
  // Through `inSRGB` on every path, including the one that changes nothing.
  // `token` hands back a raw value when it holds no `(`, so a scheme whose
  // --accent is a plain hex would reach cytoscape as `#0f5c6b` while a scheme
  // that derives it arrives as `rgb(...)` — and what this canvas may be handed
  // is the invariant `test_the_drawing_gets_colours_it_can_actually_read` was
  // written for. One shape out of here, whatever came in.
  if (!page || CONTRAST(hue, page) >= 3) return inSRGB(hue);
  for (let step = 20; step <= 80; step += 20) {
    const lifted = inSRGB(`color-mix(in oklab, ${hue}, ${token('--fg')} ${step}%)`);
    if (CONTRAST(lifted, page) >= 3) return lifted;
  }
  return inSRGB(token('--line-strong'));
};

function edgeSeed(edge) {
  // FNV-ish over the two ids: stable across loads, and different for two edges
  // that share an end.
  const key = edge.data('source') + '>' + edge.data('target');
  let hash = 2166136261;
  for (let i = 0; i < key.length; i++) {
    hash ^= key.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  return Math.abs(hash);
}

function edgeInk(edge) {
  const hue = token(EDGE_INKS[edgeSeed(edge) % EDGE_INKS.length]);
  return hue ? legible(hue) : token('--line-strong');
}

// A different slice of the same hash, so ink and weight do not travel together:
// off one number, every teal edge would be the same width and the nine buckets
// would be three.
function edgeWidth(edge) {
  return EDGE_WIDTHS[Math.floor(edgeSeed(edge) / EDGE_INKS.length) % EDGE_WIDTHS.length];
}

// The two marks, as the two CHARACTERS they are everywhere else on the site, each
// with its own fill — which is what jcanton pictured and what a label cannot do:
// cytoscape draws a label into a canvas with one `color` for the whole string,
// and there is no rich text on a node. An SVG can hold two `<text>` elements and
// two fills, so that is where they go, and it comes out looking like the thing
// that could not be written.
//
// The block and the glyph are the same characters `PRIORITY_GLYPH` and
// `STATUS_GLYPH` write into a chip, a menu and a legend key: one notation for one
// fact, drawn five ways and read as one.
function marksImage(node) {
  const priority = node.data('priority'), status = node.data('status');
  const block = PRIGLYPH[priority] || '';
  const glyph = GLYPH[status] || '';
  const hue = token('--pri-' + String(priority).replace(/_/g, '-')) || token('--fg');
  // The BORDER's colour and not the chip ink the table uses: the ground behind
  // this glyph is the status fill itself, and the border is the one token already
  // held legible against it — it is drawn round this very shape.
  const ink = LINE()[status] || token('--fg');
  const stack = token('--font-sans').replace(/"/g, "'");
  const safe = one => one.replace(/&/g, '&amp;').replace(/</g, '&lt;');
  // Both sit on one baseline. The block character draws from the baseline
  // downwards in most faces, so the two are placed at the same y and the block's
  // own metrics put it where a chip puts it.
  const marks = [
    block ? `<text x="0" y="11" font-family="${stack}" font-size="12" `
            + `fill="${hue}">${safe(block)}</text>` : '',
    glyph ? `<text x="13" y="11" font-family="${stack}" font-size="11" `
            + `font-weight="700" fill="${ink}">${safe(glyph)}</text>` : '',
  ].join('');
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="14" `
    + `viewBox="0 0 24 14">${marks}</svg>`;
  return 'data:image/svg+xml;utf8,' + encodeURIComponent(svg);
}

// Cytoscape aligns a left-aligned label by its RIGHT edge against the box's left
// edge, so putting a group's name inside its own box means knowing how wide the
// name is. There is no API for that and character counts put an "i" and a "W" in
// different places, so it is measured on a canvas in the font the graph draws in.
const ruler = document.createElement('canvas').getContext('2d');
const GROUP_SIZE = 12;
const GROUP_MAX = 300;    // the width the label is told to ellipsise at
function groupWidth(node) {
  ruler.font = `600 ${GROUP_SIZE}px ${token('--font-sans')}`;
  // The string the box is actually labelled with, glyph included. Measuring the
  // bare title put every group name a glyph's width off the box it belongs to.
  return Math.min(GROUP_MAX, ruler.measureText(labelOf(node)).width);
}

// Named once: filtering re-runs it, and a second copy of the options is how the
// graph comes to lay itself out one way at load and another way afterwards.
//
// EACH BOX IS LAID OUT OVER ITS OWN CHILDREN AND FROZEN AS A RECTANGLE, and then
// the rectangles are laid out. That is ELK's recursive engine — what it does when
// `hierarchyHandling` is left alone — and it is what makes grouping the layout's
// primary objective rather than something a later pass has to repair.
//
// `INCLUDE_CHILDREN` was here and is gone. It flattens the hierarchy into one
// layered pass, which ranks children of different boxes against each other and
// leaves a box to be whatever rectangle its children ended up needing. Measured
// on the real plan against the recursive engine, both with `packComponents` gone:
// 0 overlapping boxes either way, but sibling sparseness 1.4 against 4.7-13.1
// once the pack was in play. The pack is the story; see the note where it was.
//
// `RIGHT` and not `DOWN` for the reason `TB` beat `LR` under dagre — the shape of
// this plan, not a preference. Most records depend on nothing, and the direction
// decides whether that pile becomes a column or a row; measured, `DOWN` came out
// at 23% of the canvas against 69%.
//
// An edge here is a dependency and only ever a dependency. What holds what is
// drawn as a box around its contents — the table draws the same relationship as a
// tree, and neither view turns it into an arrow.
//
// MEASURED AT SIZE, 2026-08-20, on plans built by `tests/plans.py` at 1900x820.
// Containment holds all the way up — 0 overlapping boxes and 0 foreign cards at
// 31, 52, 208 and 518 records — and what degrades is the zoom, because root
// `layered` puts every top-level box in ONE ROW:
//
//     records   zoom, root layered   zoom, root rectpacking
//         31           0.80                 0.80
//        208           0.24                 0.36
//        518           0.16                 0.27
//
// `algorithm: 'rectpacking'` here, keeping `layered` per parent below, is
// therefore the switch for a plan too wide for one row. It is NOT the default,
// and the reason is worth the four lines: reverse every dependency in the corpus
// and root `layered` still draws 6 of 6 arrows left to right — it genuinely
// re-ranks — while `rectpacking` drops to 2 of 6, because a packer reads no edges
// at all and was only ever following the order the records came in. On a view
// whose edges mean blocks/blocked-by, an arrow that reads backwards is the view
// lying. Take the zoom when a plan actually outgrows the row, and know what it
// costs.
// ELK is asked directly, not through `cytoscape-elk`. The adapter reads node
// positions out of the answer and never looks at an edge's `sections`, and going
// round it buys the two things this layout needs and it cannot give:
//
//   * an edge on the box that HOLDS it rather than at the root, and
//   * ghost edges, which are the whole reason the boxes come out in order.
//
// GHOST EDGES. ELK's recursive engine lays each box out over its own children and
// then lays the boxes out. The pass that places the boxes therefore cannot see a
// dependency between two records INSIDE two different boxes — it sees boxes. So
// for every dependency, an invisible edge is added between the two children of
// its lowest common ancestor, which is the edge that pass can act on.
//
// At every level and not only at the root, because the problem repeats all the
// way down: two tasks in two different pitches of one project need those pitches
// ordered, and only the project's own layout pass can do it. Measured on a
// generated plan of 518 records — `tests/plans.py` — dependencies drawn backwards
// went 24 of 189 with no ghosts, to 18 with ghosts only at the root, to 3 with
// them at every level. On the real plan it is 0 either way, which is luck of
// shape: its two cross-project dependencies are top-level edges that carry the
// order themselves.
//
// The ghosts never reach cytoscape. They exist in the object handed to ELK and
// nowhere else, which is what makes them safe: a layout-only edge that got into
// the graph would be tappable in edit mode, would be walked by the cycle check,
// would fade an unrelated project in the filter, and would be sent to the server
// by Save.
//
// The three left over at 518 are group-level ambiguity rather than a bug: if
// something in A blocks something in B and something in B blocks something in A,
// the ghost graph has a cycle the record graph does not, and one of the two
// arrows has to come out backwards.
const LAYOUT_OPTIONS = {
  'elk.algorithm': 'layered',
  'elk.direction': 'RIGHT',
  'elk.spacing.nodeNode': '30',
  'elk.layered.spacing.nodeNodeBetweenLayers': '50',
  // No `elk.edgeRouting`. ELK computes bend points for an edge it can see both
  // ends of and returns none at all for one that spans the hierarchy — measured
  // on a 208-record plan, ORTHOGONAL, POLYLINE and SPLINES each gave bend points
  // to ZERO of 76 edges. Nothing here draws bends anyway: an edge is a straight
  // line under the boxes. Asking for a routing that would arrive empty and be
  // thrown away is a setting that reads as though it does something.
};

// 25 and not ELK's default 12, because the box ELK reserves and the box this page
// draws are not the same box: `:parent` is styled with `padding: 20` plus a label
// band above it. Measured, the drawn box came out 21px larger in each dimension
// than the one ELK planned, which is exactly enough for two boxes ELK considered
// separate to touch. THAT PADDING AND THIS NUMBER HAVE TO MOVE TOGETHER.
const BOX_PADDING = '[top=25,left=25,bottom=25,right=25]';

// The chain from the outermost box down to the node itself.
const chainOf = node => [...node.ancestors().toArray().reverse(), node].map(n => n.id());

// One node, as ELK wants it. A leaf carries the size cytoscape drew it at; a box
// carries none, because its size is what ELK is being asked to work out.
function elkNode(node) {
  const kids = node.children();
  if (kids.length) {
    return {id: node.id(), children: kids.map(elkNode),
            layoutOptions: {'elk.padding': BOX_PADDING}};
  }
  const box = node.boundingBox({includeLabels: false});
  return {id: node.id(), width: box.w, height: box.h};
}

// Which container each edge belongs to. A real edge goes on the box that holds
// BOTH its ends, so ELK routes it among that box's children with them as
// obstacles; at the root a whole project is one opaque rectangle and the edge is
// drawn straight through everything inside it.
function edgesByContainer(edges) {
  const real = {};
  const ghosts = {};
  const weight = new Map();     // container|a>b  ->  how many dependencies run that way
  const where = new Map();      // container|a>b  ->  the three ids that made it
  const dropped = new Set();
  edges.forEach(edge => {
    const from = chainOf(edge.source());
    const to = chainOf(edge.target());
    const together = from.length === to.length
      && from.slice(0, -1).join() === to.slice(0, -1).join();
    const holder = together && from.length > 1 ? from[from.length - 2] : 'root';
    (real[holder] = real[holder] || []).push({
      id: edge.id(), sources: [edge.source().id()], targets: [edge.target().id()],
    });

    let deep = 0;
    while (deep < from.length && deep < to.length && from[deep] === to[deep]) deep++;
    const a = from[deep], b = to[deep];
    if (!a || !b || a === b) return;
    // Already the edge that level will see: nothing to add.
    if (a === edge.source().id() && b === edge.target().id()) return;
    const on = deep === 0 ? 'root' : from[deep - 1];
    const key = on + '|' + a + '>' + b;
    // Counted, not deduplicated. When two boxes depend on each other the ghosts
    // form a cycle, and how many dependencies run each way is what decides which
    // direction is worth keeping.
    weight.set(key, (weight.get(key) || 0) + 1);
    where.set(key, {on, a, b});
  });

  // A cycle in the ghosts is not a cycle in the plan: two projects can each hold
  // work waiting on the other, with nothing circular about any single record.
  // ELK cannot rank both, so it breaks one arbitrarily and an arrow comes out
  // backwards — measured on a generated plan of 518 records, two of them, between
  // one pair of projects with two dependencies running one way and one the other.
  //
  // So the WEAKER direction is dropped before ELK ever sees it. The majority then
  // ranks correctly and only the minority reads backwards, which is the honest
  // answer: those records really are waiting on each other, and no arrangement of
  // two boxes on a line can say so.
  //
  // Two-cycles only. A longer ring — A waits on B waits on C waits on A — is left
  // for ELK to break, because choosing which edge of a ring to sacrifice is a
  // judgement about the plan rather than about the drawing, and a wrong guess
  // there is worse than an arbitrary one.
  for (const [key, {on, a, b}] of where) {
    const other = on + '|' + b + '>' + a;
    if (!where.has(other)) continue;
    const mine = weight.get(key), theirs = weight.get(other) || 0;
    // Ties keep both and let ELK choose: there is nothing to prefer.
    if (mine < theirs) continue;
    if (mine === theirs && key > other) continue;
    dropped.add(other);
  }
  for (const [key, {on, a, b}] of where) {
    if (dropped.has(key)) continue;
    (ghosts[on] = ghosts[on] || []).push({id: 'ghost:' + key, sources: [a], targets: [b]});
  }
  return {real, ghosts};
}

const elk = new ELK();

// Which arrangement is the current one. `relayout` awaits ELK in the middle, so
// two of them can be in flight at once and the one that finishes LAST wins —
// which is not the one that was asked for last: `cy.fit` at the bottom fits
// whatever is visible now, so a stale run ends by fitting the new drawing around
// the old drawing's positions. Nothing here can cancel a layout that has already
// started, so the answer is thrown away instead of applied.
let laying = 0;

// Lay the visible graph out and draw the answer. Asynchronous, and the callers
// treat it as such: the filter awaits nothing, it simply asks again.
async function relayout() {
  const mine = ++laying;
  const nodes = cy.nodes(':visible');
  const edges = cy.edges(':visible');
  if (!nodes.length) return;
  const {real, ghosts} = edgesByContainer(edges);
  const graph = {
    id: 'root',
    layoutOptions: {...LAYOUT_OPTIONS,
                    'elk.aspectRatio': String(cy.width() / cy.height())},
    children: nodes.filter(node => !node.isChild()).map(elkNode),
    edges: [...(real.root || []), ...(ghosts.root || [])],
  };
  const hang = node => {
    const mine = [...(real[node.id] || []), ...(ghosts[node.id] || [])];
    if (mine.length) node.edges = [...(node.edges || []), ...mine];
    (node.children || []).forEach(hang);
  };
  graph.children.forEach(hang);

  let laid;
  try {
    laid = await elk.layout(graph);
  } catch (error) {
    // A layout that will not run must not take the page with it: the nodes are
    // already on the canvas and cytoscape will draw them where they are.
    say('this plan could not be laid out — the drawing is unarranged');
    return;
  }
  // A newer layout started while this one was in ELK, so this answer is about a
  // graph that is no longer on the canvas. Dropped rather than drawn: applying
  // it moves nodes to where an older visible set wanted them, and the `cy.fit`
  // below then frames the current drawing around those positions.
  if (mine !== laying) return;

  // A child's x and y are relative to its parent, so the walk carries the offset.
  const at = {};
  const walk = (node, dx, dy) => {
    const x = (node.x || 0) + dx, y = (node.y || 0) + dy;
    at[node.id] = {x, y, w: node.width, h: node.height};
    (node.children || []).forEach(kid => walk(kid, x, y));
  };
  (laid.children || []).forEach(kid => walk(kid, 0, 0));

  // Only the leaves are placed. A compound's position in cytoscape is derived
  // from its children, so setting it as well moves its contents twice.
  cy.batch(() => {
    nodes.filter(node => node.isChildless()).forEach(node => {
      const where = at[node.id()];
      if (where) node.position({x: where.x + where.w / 2, y: where.y + where.h / 2});
    });
  });

  cy.fit(undefined, 24);
}

// THE ROUTER THAT WAS HERE, and why the drawing is straight lines now.
//
// It was a Hanan grid and an A* per edge, run over ELK's absolute positions, to
// send each dependency ROUND the cards between its ends rather than under them —
// because at the level ELK works, the route between two boxes is genuinely
// unobstructed, the cards it appears to cross being inside other boxes that are
// opaque at that level.
//
// It worked, in the sense that the paths it produced were correct. Getting them
// on screen was the part that never held: cytoscape takes bends as a distance
// from a reference line and a fraction along it, so drawing one meant knowing
// which line — and the answers were, in order, the line between the centres
// (wrong: it is the line clipped at the two shapes), a perpendicular of one sign
// (wrong: it is the other, so every route was drawn as its own reflection), and
// anchors on the border (wrong: cytoscape calls those endpoints degenerate and
// draws nothing at all). Each was found by a screenshot, each fix was measured,
// and the drawing came back wrong in a new way. jcanton, 2026-08-21: "the graph
// is in worse shape than it was before... I'm thinking we should go back to a
// simpler option with straight edges drawn underneath the nodes."
//
// So: cytoscape's own `round-taxi`, drawn beneath every box. A line under a card
// cannot be a line through it, which is the whole thing the router was for — and
// the turn is the library's, so there are no bends of ours to place and nothing
// to re-place when a node moves. What is gone with it: `routeAround`,
// `anchorsFor`, `routeEdges`, `drawRoutes`, `clippedLine`, `route` — which
// overrode `taxi-direction` per edge — and the settle timer.

// `packComponents` was here and is the reason this page looked the way it did.
//
// It ran after ELK, split the drawing with `cy.elements(':visible').components()`
// and arranged the pieces into rows. `components()` is connectivity over EDGES —
// and an edge here is a dependency, never containment, which is the whole design
// of this view. So a box was not one piece: the real plan's 31 records came out
// as 25 of them, six of the eight boxes had their children spread across more
// than one, and the loop then moved only the childless nodes. Siblings were dealt
// into different rows and each parent's rectangle — which in cytoscape is nothing
// but the bounding box of wherever its children landed — stretched across
// everything in between. One project's box went from 400x713 to 1753x1207.
//
// Measured on the real plan, immediately before and immediately after that one
// function: 0 overlapping box pairs became 17-21, 0 cards drawn inside a box they
// do not belong to became 29-70, and sibling sparseness went from 1.30 to between
// 4.7 and 13.1. Every screenshot of this page that looked wrong was a picture of
// those eight lines.
//
// It was written for a real problem, which is now solved a level up: the
// flattened hierarchy left the pieces of a disconnected plan in one long line at
// 7% of the canvas. ELK's recursive engine — what it does when `hierarchyHandling`
// is left alone — arranges the boxes itself, so there is nothing left to repair.
// Do not reintroduce a post-layout pass here without measuring what it does to
// containment: a unit of work that cannot see the boxes will take them apart.

// Before the canvas is built, not after. Cytoscape measures its container once,
// here, and the first layout fits the plan into whatever it measured — so a
// canvas that gets its real height a frame later has already centred the plan in
// a box it no longer has. Everything this reads is above or below in the same
// document and has already been parsed: the heading, the filter bar, the key row
// and the commit bar are all written out before this script tag.
fitRoom();

// Named rather than looked up inline, because the right-click menu wants this
// same element: cytoscape's own `contextmenu` binding is on the container it was
// handed, and the shift-through listener has to be on that element and no other.
const CYBOX = document.getElementById('cy');

const cy = cytoscape({
  container: CYBOX,
  elements: ELEMENTS || [],
  // Filtering re-fits what is left to the window, and two boxes fitted to a
  // 1400px canvas came out at nearly 3x — the same graph reading as a different
  // app. Zooming in by hand stops at the same place, which at a 10px label is
  // still twice as large as anybody needs.
  maxZoom: 2,
  style: [
    { selector: 'node', style: {
        'label': labelOf, 'font-size': 10, 'shape': 'round-rectangle',
        // One typeface for the whole app, this canvas included — and the ruler
        // above measures group labels in it, so a second stack here would put
        // every group label a few pixels off the box it belongs to.
        'font-family': token('--font-sans'),
        // text-wrap alone does nothing: without a max width the label just
        // overflows the box it is supposed to sit inside.
        // The two marks, drawn at the card's left edge and level with the middle
        // of its title. `background-fit: none` and an explicit size, or cytoscape
        // scales the image to the node and a wide card gets a stretched one.
        'background-image': node => node.isChildless() ? marksImage(node) : 'none',
        'background-image-opacity': 1,
        'background-width': 24, 'background-height': 14,
        'background-position-x': 8, 'background-position-y': '50%',
        'background-fit': 'none', 'background-clip': 'node',
        'background-image-containment': 'inside',
        // Narrower than the card and pushed right by the marks' own width, so the
        // two share the line without sharing any pixels.
        'text-wrap': 'wrap', 'text-max-width': 106, 'text-margin-x': 15,
        'background-color': e => COLOUR()[e.data('status')],
        // A rank, not arithmetic on the value: priority became a word, and
        // `4 - 'high'` is NaN, which cytoscape draws as no border at all.
        'border-width': e => ({very_high: 6, high: 4, medium: 2, low: 1.5,
                               very_low: 1})[e.data('priority')] ?? 2,
        // The status's own boundary token, not the accent and no longer the ink.
        // The fills are a luminance ladder, so one border colour for all five is
        // 2:1 against the darkest of them — and this border is how priority is
        // drawn, which makes it a channel that has to be legible on every rung,
        // not only the middle ones. --st-X-line is exactly that value, and using
        // it here is what makes a node the same shape as its bar on the timeline
        // and its key in the legend.
        'border-color': e => LINE()[e.data('status')],
        'color': e => INK()[e.data('status')], 'text-valign': 'center',
        'width': 150, 'height': 44 } },
    { selector: '.picked', style: {
        'border-color': token('--danger'), 'border-width': 5 } },
    // The name of a group used to be 9px of --muted sitting ON the box's border,
    // where every edge crossing the box ran straight through it. Inside, top
    // left, on its own ground: a box whose name you cannot read is a box that
    // says only that something is grouped, not what by.
    // A product is not a project, and the drawing says so before the label is
    // read — jcanton, 2026-08-20: "can we give it another shape? ellipse instead
    // of rounded square? or some other line style to differentiate it?"
    //
    // Three channels rather than one, because a box holding other boxes is mostly
    // empty and a single cue in the middle of it is a cue nobody sees: a dashed
    // boundary, a heavier corner radius, and no fill at all. A product groups
    // codebases — griddle under kiln4py, hearth, roastref — and it holds no work of
    // its own, so an empty outline is what it actually is.
    { selector: 'node[kind = "product"]', style: {
        'shape': 'round-rectangle', 'border-style': 'dashed', 'border-width': 2,
        'background-opacity': 0, 'border-color': token('--line-strong'),
    } },
    { selector: ':parent', style: {
        // 20 here and `elk.padding: 25` in LAYOUT, and the two have to move
        // together: ELK reserves the room and this draws the box, and when the
        // drawn one is bigger than the reserved one two boxes ELK considered
        // separate touch.
        'background-opacity': .08, 'padding': 20,
        'font-size': GROUP_SIZE, 'font-weight': 600, 'color': token('--fg'),
        // Ellipsis rather than wrap: the offset below is measured on one line,
        // and a label that wrapped would be positioned as if it had not.
        'text-wrap': 'ellipsis', 'text-max-width': GROUP_MAX,
        'text-valign': 'top', 'text-halign': 'left',
        // `groupWidth` measures the label including its marks — it is given the
        // same string `labelOf` builds — so nothing is added here for them.
        'text-margin-x': e => groupWidth(e) + 12, 'text-margin-y': 17,
        'text-background-color': token('--surface'), 'text-background-opacity': 1,
        'text-background-padding': 3, 'text-background-shape': 'roundrectangle' } },
    // On the canvas only because something that did match points at it. Faded
    // rather than removed, so no arrow leaves for a box you cannot see.
    { selector: 'node.aside', style: { 'opacity': .32 } },
    // Edges are drawn OVER the cards, not behind them. A line that disappears
    // behind a card and comes out the other side reads as two edges meeting it —
    // jcanton, 2026-08-20: "to a distracted human not noticing that there are no
    // arrowheads, [it] may make it seem like it depends on where the edge comes
    // from". A line you can see crossing is a line you can see is not connected.
    //
    // The alternative was an automatic layout that never puts a card on a line,
    // and that is not reachable with what is vendored: ELK emits bend points for
    // an edge whose obstacles are at the level it is working on, and none at all
    // for one that spans the hierarchy — measured, zero of 76 on a 208-record
    // plan, in each of its three routing modes.
    { selector: 'edge', style: {
        // BENEATH the boxes, which is the whole design of the drawing now: a
        // straight line from one card to another passes under whatever is in
        // between, and a line under a card cannot be read as a line through it.
        // `bottom` and not a z-index: with compound nodes the draw order is by
        // compound depth first, so an edge between two cards inside two
        // different boxes is otherwise painted over both boxes whatever its
        // z-index says.
        'z-compound-depth': 'bottom',
        // Right angles with rounded corners, and CYTOSCAPE's, not ours. The
        // whole difference from what was here before is `taxi-direction: auto`:
        // the old code overrode it per edge with a hand-rolled guess at which way
        // each one should turn, on top of a router that placed the bends itself.
        // Left to decide for itself, against edges drawn underneath the boxes, it
        // draws the shape the router was written to produce — with none of the
        // code, and none of the four separate ways of getting bends onto the
        // screen wrong.
        //
        // Chosen off a gallery of every curve style cytoscape has, rendered on
        // the real plan and looked at: jcanton, 2026-08-21, "can you serve
        // 11-round-taxi-under? it's the same but rounded".
        'curve-style': 'round-taxi', 'taxi-direction': 'auto',
        'taxi-turn': '50%', 'taxi-turn-min-distance': 12, 'taxi-radius': 8,
        // Trimmed towards the other end's shape rather than to the line between
        // the centres — on a compound the two differ by the width of the box, and
        // an arrow that stops short of the border reads as an arrow pointing at
        // nothing.
        'source-endpoint': 'outside-to-node', 'target-endpoint': 'outside-to-node',
        // --line-strong, not --st-ready. An arrow was drawn in the ready fill
        // back when that fill was a dark blue; the light theme's fills are tints
        // now and #83b8e9 on a white page is 2.10:1 — a dependency you cannot
        // see. An arrow is not a status, it is a drawn boundary, and this is the
        // token that is held at 3:1 against the page in both themes.
        'line-color': edge => edgeInk(edge),
        'target-arrow-color': edge => edgeInk(edge),
        'target-arrow-shape': 'triangle',
        // The second channel, and the one that costs nothing: see EDGE_WIDTHS.
        // `edge.pending` and `edge.dropping` set their own below and mean it --
        // a connection that is not committed yet is not one of nine buckets.
        'width': edge => edgeWidth(edge) } },
    // The two uncommitted states, told apart by colour rather than by dash
    // pattern: both are dashed, because dashed is what "not in the plan yet"
    // looks like here, and one is being added while the other is being taken
    // away. `--ok` and `--sev-blocker` are the two tokens this app already uses
    // for exactly that pair of meanings, and both are held against the page at
    // 3:1 in either theme — a green that only reads as green on a white
    // background is a green half the room does not have.
    { selector: 'edge.pending', style: {
        'line-color': token('--ok'), 'target-arrow-color': token('--ok'),
        'line-style': 'dashed', 'width': 2.5 } },
    { selector: 'edge.dropping', style: {
        'line-color': token('--sev-blocker'), 'target-arrow-color': token('--sev-blocker'),
        'line-style': 'dashed', 'width': 2.5 } },
  ],
});

// The style above was resolved from tokens once, at build time. Flipping the
// theme changes the tokens, not the resolved values, so every one of them is
// re-read — the ink and the border with the fill, because all three differ per
// status and per theme, and a box that keeps one of the three from the theme it
// was built in is a box wearing two palettes at once.
function paint() {
  cy.style()
    .selector('node').style({'background-color': e => COLOUR()[e.data('status')],
                             'border-color': e => LINE()[e.data('status')],
                             'color': e => INK()[e.data('status')]})
    // The marks are drawn with tokens too, so they are rebuilt with everything
    // else the theme moves.
    .selector('node').style({'background-image': e =>
        e.isChildless() ? marksImage(e) : 'none'})
    .selector('.picked').style({'border-color': token('--danger')})
    .selector(':parent').style({'color': token('--fg'),
                                'text-background-color': token('--surface'),
                                'text-margin-x': e => groupWidth(e) + 12})
    .selector('edge').style({'line-color': edge => edgeInk(edge),
                             'target-arrow-color': edge => edgeInk(edge),
                             // Repainted on a theme change like the inks, because
                             // `legible` lifts against the theme that is loaded:
                             // a width is not theme-dependent but the call that
                             // sets it alongside the colour has to run again.
                             'width': edge => edgeWidth(edge)})
    .selector('edge.pending').style({'line-color': token('--ok'),
                                     'target-arrow-color': token('--ok')})
    .selector('edge.dropping').style({'line-color': token('--sev-blocker'),
                                      'target-arrow-color': token('--sev-blocker')})
    .update();
}
addEventListener('themechange', paint);

// Dragging, which is the half of the complaint no layout choice can fix. A
// compound's rectangle in cytoscape is the bounding box of its children and
// nothing else, so a card dragged out of its box does not leave the box — it
// STRETCHES it, across whatever the box now has to reach. Measured on a clean
// layout, one card dragged 250x120: 0 overlapping box pairs became 2, and 0 cards
// inside a foreign box became 5. The drawing was correct until somebody touched it.
//
// So a card goes back inside the box it was picked up from. Not by re-running the
// layout, which is the obvious answer and a worse one: ELK ignores current
// positions and is deterministic, so a re-run puts every card back exactly where
// it already was and the drag simply vanishes — a stranger thing to watch than a
// card sliding home.
// Nothing is clamped and nothing is ungrabbable. A card dragged out of its box
// stretches the box, which is why the clamp existed — but an automatic layout
// that never puts a card on an edge is not reachable here (see `LAYOUT_OPTIONS`:
// ELK returns bend points for none of the edges that span the hierarchy, in any
// of its three routing modes), so somebody has to be able to move a card off the
// line it is sitting on. jcanton, 2026-08-20, having watched the clamp put a card
// straight back onto the line it had been dragged off: "let people drag".
//
// The clamp contributed nothing to the drawing you arrive at. It ran on
// `dragfree` and nowhere else, so the starting view has always been the layout
// alone — worth writing down, because the obvious guess is otherwise, and it was
// the guess made when this was agreed.
//
// A box can be picked up again for the same reason. Cytoscape moves a parent
// rigidly with its whole subtree, so dragging one shoves it across its
// neighbours and nothing re-lays-out — which was the argument for `ungrabify`,
// and is now the argument against it: shoving a box out of the way is exactly
// what somebody needs to do when two of them are drawn on top of each other.
// The face is inlined but still swaps in asynchronously, and a group label
// measured against the fallback stays where the fallback put it.
if (document.fonts) document.fonts.ready.then(paint);

// One filter model, three views — the graph's answer to it is which boxes are on
// the canvas. Hiding a node takes its edges with it, and an arrow leaving for
// something you filtered out is the one thing a dependency graph must not draw,
// so: a node that matches is drawn; anything it depends on or that depends on it
// is drawn faded, because "this is blocked by something you filtered out" is
// exactly the fact you were filtering for; a box containing either is kept, or
// its contents float outside the group they belong to. Everything else leaves
// the layout, and an edge is drawn when both of its ends are still on the
// canvas — which, by construction, every edge of a matching node is.
let laidOut = cy.nodes().map(node => node.id()).sort().join(',');

// One arrangement per PAUSE in the typing, not one per set change.
//
// `laidOut` above stops a keystroke that changed nothing from moving anything,
// and it was enough while a bare word was a substring: a substring can only ever
// narrow as a word grows, so the set changed once or twice per word and then
// stopped. A subsequence does not behave that way. Measured on `seed/` on
// 2026-08-28, typing `otherwise` one character at a time: 27, 2, 2, 11, 3, 0, 0,
// 0, 0 records kept — the drawing arranged itself three times over, once at the
// eleven records it had just expanded to and again at the three it collapsed
// back to, all of it before the fifth of nine characters.
//
// **The filter is not delayed and must not be.** Which nodes are faded, how many
// are shown and whether the "nothing matches" box is up are what a reader looks
// at while typing, and they are a pass over the canvas rather than a layout.
// What costs is `await elk.layout(graph)` over the whole visible subgraph, and
// what a reader cannot use is a drawing that rearranges under the hand — so the
// arrangement is what waits, and a further keystroke resets the wait.
let pendingLayout = null;
function layoutSoon() {
  clearTimeout(pendingLayout);
  // A pause between keystrokes, and not a measured layout time: how long ELK
  // takes is a function of the plan and this number is about the hand. What it
  // buys, measured the same day: `otherwise` typed straight through costs one
  // arrangement instead of three, and typed with a stop after every character
  // still costs one per change of the set — the wait delays a layout, it never
  // swallows one. Short enough that the stop at the end of a word is not a page
  // that has quietly stopped answering.
  pendingLayout = setTimeout(relayout, 150);
}

const NOTHING = document.getElementById('nothing');
const CLEAR = document.getElementById('clear-filters');

// --- one record and what is inside it ---------------------------------------
//
// **Containment, never connectivity.** A subtree here is `descendants()` — the
// compound hierarchy cytoscape already holds, which is `parent` and nothing else
// — and deliberately not `successors()`, which walks EDGES. An edge on this
// canvas is a dependency and is never containment, and the one function on this
// page that forgot the difference took every box on the drawing apart:
// `packComponents` split the plan by `components()`, and the real plan's 31
// records came out as 25 pieces with six of the eight boxes spread across more
// than one of them. The note where it used to be is the long version.
//
// **The focus is a filter, and it is the one that is not in the query string.**
// Every other control here keeps its state in `params` so a narrowed view can be
// pasted to somebody; this one cannot, because `matches()` (`controls.py`) is
// asked one row at a time and "is filed under that box" is a question about the
// tree. What that costs is written up at `#focusbar`, which is the answer to it.
let FOCUS = null;
const FOCUSBAR = document.getElementById('focusbar');
const UNFOCUS = document.getElementById('unfocus');

// What a node is called. `label` is the record's title — the same ink the box is
// drawn with — and the id is the fallback for the reason the table's `titleOf`
// has one: a record hand-written in git can carry no title at all.
const nameOf = node => node.data('label') || node.id();

// The ids a focus keeps: the record, and everything filed under it however deep.
// `null` when nothing is focused, and also when the focused record is no longer
// on this canvas — which nothing can do while the page stands, and which would
// otherwise be a focus that hides the entire plan.
function focusKeeps() {
  if (!FOCUS) return null;
  const root = cy.getElementById(FOCUS);
  if (!root.length) return null;
  return new Set([FOCUS, ...root.descendants().map(node => node.id())]);
}

function focusOn(id) {
  // The guard is what lets `Clear filters` ask for this unconditionally: a press
  // with nothing focused must not cost the canvas a second filter pass.
  if (FOCUS === id) return;
  FOCUS = id;
  drawFocus();
  applyFilter();
}

function drawFocus() {
  FOCUSBAR.hidden = !FOCUS;
  if (!FOCUS) return;
  // `textContent`, never `innerHTML`: this is a record's own title, and this is
  // the JavaScript half of the app's one escaping boundary.
  FOCUSBAR.querySelector('.focusname').textContent =
    `Only "${nameOf(cy.getElementById(FOCUS))}" and what is inside it`;
}

UNFOCUS.onclick = () => focusOn(null);

// Three ways for a canvas to be empty, and they drew one picture. Which one it
// is decides what to do next, so the box says which one it is — the same three
// sentences the table gives, because it is the same three facts about the same
// plan. Only the filtered one offers a way out: there is nothing to clear when
// the plan is empty or the payload never arrived.
function drawNothing() {
  let headline = 'No record matches these filters.';
  let detail = 'Every node is filtered out by the controls above.';
  let clearable = true;
  if (!LOADED) {
    headline = 'The plan could not be loaded.';
    detail = 'This page arrived without its data, so there is nothing to draw or filter.';
    clearable = false;
  } else if (!cy.nodes().length) {
    headline = 'This plan has no records yet.';
    detail = 'Nothing has been pitched, shaped or scheduled.';
    clearable = false;
  } else if (FOCUS) {
    // Two things are narrowing this canvas and only one of them is a control the
    // reader can see, so blaming the filters alone sends them to the wrong one.
    // A focus on its own can never empty the canvas — the focused record always
    // matches its own focus — so getting here means the controls above are set
    // as well, and Clear drops both.
    headline = `Nothing inside "${nameOf(cy.getElementById(FOCUS))}" matches these filters.`;
    detail = 'The focus and the controls above are both narrowing this canvas, '
      + 'and Clear filters drops both.';
  }
  NOTHING.querySelector('.headline').textContent = headline;
  NOTHING.querySelector('.hint').textContent = detail;
  CLEAR.hidden = !clearable;
}

function applyFilter() {
  const keep = new Set();
  // The focus narrows the kept set and nothing else, so everything below is
  // unchanged by it: the containing boxes are still drawn, because a group's
  // name is how you know where the cards inside it live, and a dependency
  // outside the focus is still faded rather than hidden — with `#context`
  // already saying how many and why. "Only what is inside this box" is the
  // answer to what is SHOWN; what that work waits on is the second half of the
  // same question and has never been a thing this canvas takes away.
  const focused = focusKeeps();
  cy.nodes().forEach(node => {
    if (focused && !focused.has(node.id())) return;
    if (matches(node.data())) keep.add(node.id());
  });
  const aside = new Set();
  for (const id of keep)
    cy.getElementById(id).neighborhood('node').forEach(near => {
      if (!keep.has(near.id())) aside.add(near.id());
    });
  // A container earns its place by what it holds, so it is never the faded one:
  // the group's name is how you know where the boxes inside it live.
  const boxes = new Set();
  for (const id of [...keep, ...aside])
    cy.getElementById(id).ancestors().forEach(box => {
      if (!keep.has(box.id()) && !aside.has(box.id())) boxes.add(box.id());
    });
  const on = id => keep.has(id) || aside.has(id) || boxes.has(id);

  cy.batch(() => {
    cy.nodes().forEach(node => {
      node.style('display', on(node.id()) ? 'element' : 'none');
      node.toggleClass('aside', aside.has(node.id()));
    });
    cy.edges().forEach(edge => {
      const both = on(edge.source().id()) && on(edge.target().id());
      edge.style('display', both ? 'element' : 'none');
    });
  });

  document.getElementById('shown').textContent = keep.size;
  document.getElementById('context').textContent = aside.size
    ? ` · ${aside.size} more faded, because what is shown depends on ` +
      (aside.size === 1 ? 'it' : 'them')
    : '';
  // An empty canvas is indistinguishable from a graph that failed to draw.
  NOTHING.hidden = keep.size > 0;
  if (!keep.size) drawNothing();

  // Only when the set actually changed: re-running the layout on every keystroke
  // in the search box moves every box under the hand that is typing. What is
  // asked for here is an arrangement rather than an arrangement OF THIS SET —
  // `relayout` reads `cy.nodes(':visible')` when it runs — so a delayed one is
  // always about what is on the canvas at the moment it fires.
  const now = cy.nodes(':visible').map(node => node.id()).sort().join(',');
  if (now === laidOut || !keep.size) return;
  laidOut = now;
  layoutSoon();
}

// The first drawing. The constructor used to carry `layout:` and did this on the
// way up; ELK is asked directly now, so it is asked here — and asked here rather
// than left to `applyFilter`, which lays out only when the visible set has
// CHANGED, and on the first pass it has not.
relayout();

addEventListener('openproj:filter', applyFilter);
// Clear drops the focus as well as the query string. Both narrow this canvas,
// and a control that says "clear" while leaving half the narrowing in place is
// the control this repository keeps rediscovering — one that teaches people it
// is decoration. `clearFilters` ends in `openproj:filter`, so the redraw above
// is what actually re-runs the filter; `focusOn(null)` returns immediately when
// there is nothing focused, which is the ordinary press.
CLEAR.onclick = () => { focusOn(null); clearFilters(); };
applyFilter();

// The canvas changed shape. Cytoscape holds the size it measured when it was
// built and goes on drawing at it, so the box and the drawing disagree until it
// is told — a wider window drew the same picture in the same corner with a white
// margin beside it, and a shorter one kept nodes below the fold of a canvas that
// no longer reaches there.
//
// Re-fitted as well as re-measured: a window that changed size is a new answer to
// "how much of this fits", and keeping the old zoom against a smaller box is how
// nodes end up outside the canvas with nothing on screen to say they exist. The
// same padding the layout fits with, so a resize and a filter leave the plan in
// the same place.
addEventListener('openproj:room', () => {
  cy.resize();
  const drawn = cy.elements(':visible');
  if (drawn.length) cy.fit(drawn, 30);
});

const CONNECT = document.getElementById('connect');
const SAVE = document.getElementById('save');
const DISCARD = document.getElementById('discard');
let connecting = false;
// `blocker`, not `source`: two classic scripts on one page share one global
// scope, and the shell's `const source = new EventSource(...)` below threw on a
// name this file had already taken — which killed the plan-changed banner on
// this page and nowhere else.
let blocker = null;

// The shell's live region does the placing: `#state` where the page has one — a
// rendered file has no edit mode and so no bar to put it in — and the hidden
// region on every page otherwise. Drawing it without announcing it is how a
// refused dependency became a sentence only half the room could read.
function say(message) { announce(message); }

function pending() {
  return cy.edges('.pending');
}

// Edges that are on the canvas because they are in the plan, and are marked to
// come out of it. Drawing one and removing one are the same job — "what waits
// for what is wrong on this diagram" — and a mode that could only add was a mode
// you had to leave, and open a record, to finish the thought.
function dropping() {
  return cy.edges('.dropping');
}

function tally(extra) {
  const n = pending().length;
  const gone = dropping().length;
  SAVE.hidden = DISCARD.hidden = !connecting;
  SAVE.disabled = n === 0 && gone === 0;
  const drawn = n === 0 && gone === 0 ? 'nothing changed yet' : [
    n === 1 ? '1 dependency drawn' : n > 1 ? `${n} dependencies drawn` : '',
    gone === 1 ? '1 to remove' : gone > 1 ? `${gone} to remove` : '',
  ].filter(Boolean).join(', ') + ' — press Save to commit';
  say(connecting ? (extra ? extra + ' · ' + drawn : drawn) : (extra || ''));
  // Save and Reset appear here, and at a narrow window that is a second line of
  // commit bar. The bar is what the canvas has to clear, so a bar that grew is a
  // canvas that has to give the row back — this is the one thing on any of these
  // pages that changes the height below the box without the window changing.
  fitRoom();
}

// **Which mode the canvas is in, set in one place.** Four facts — the flag, the
// half-drawn edge's blocker, the ring on whatever it was going to be drawn from,
// and the word on the button that leaves the mode — and they are one mode. The
// menu's `Add dependency from here` is the second way in, and a mode entered
// from two places with the button still reading "Edit dependencies" is a canvas
// in edit mode offering no way out of it.
//
// Only ever called where `#commitbar` exists: `CONNECT.onclick` is inside
// `if (CONNECT)`, and the menu item is built only when `CONNECT` is there to
// build it with. The rendered export ships this same script with no bar to
// reach, which is what makes it inert there.
function connectingIs(on) {
  connecting = on;
  blocker = null;
  cy.nodes().removeClass('picked');
  CONNECT.textContent = connecting ? 'Discard and exit' : 'Edit dependencies';
}

// The first tap of the gesture: this node is what must finish first. The menu's
// `Add dependency from here` is that same tap made from a box instead of from
// the canvas, and it calls this rather than carrying a copy — the sentence is
// the instruction for the tap AFTER it, and one gesture described two ways is
// how the two descriptions come to disagree.
function pickBlocker(node) {
  blocker = node;
  node.addClass('picked');
  tally(`${node.id()} must finish first — now click what waits for it`);
}

// Opening is on double-click: a single tap is also the first half of drawing an
// edge, and on a graph you drag around, one stray click should not navigate away.
cy.on('dbltap', 'node', evt => {
  if (!connecting) location.href = '{{ links.record }}' + evt.target.id();
});

// The card, on the view that needs it most: a node carries a title and a status
// glyph and nothing else, so everything a row knows about itself is a page away.
// The same card the timeline and the table draw — see `_SHELL`.
//
// Placed from the pointer rather than from the node, and `position: fixed` rather
// than inside the canvas, because this canvas pans and zooms: a card anchored to
// a node slides out from under the pointer the moment somebody scrolls, and one
// inside the transformed layer is drawn at whatever size the zoom happens to be.
//
// Not while drawing an edge. In that mode the pointer is doing something else
// entirely, and a box following it covers the node it is being dragged towards.
// A box is hit over its whole area, and most of that area belongs to the records
// inside it. So a compound answers for its label and not for its acres — jcanton,
// 2026-08-20 — or reading a project's tasks means dragging the pointer through a
// card about their parent, which is in the way of the thing being read.
//
// The label's rectangle, worked out from the style that draws it rather than
// guessed: `text-halign: left` with `text-margin-x: groupWidth + 12` puts its
// left edge twelve pixels inside the box, and `text-valign: top` with
// `text-margin-y: 17` puts it just under the top edge. The band is generous on
// purpose — it is the title bar somebody is aiming at, not the glyphs.
function labelBand(node) {
  const box = node.boundingBox({includeLabels: false});
  return {
    x1: box.x1, x2: box.x1 + groupWidth(node) + 24,
    y1: box.y1, y2: box.y1 + GROUP_SIZE + 16,
  };
}
function onLabel(node, at) {
  const band = labelBand(node);
  return at.x >= band.x1 && at.x <= band.x2 && at.y >= band.y1 && at.y <= band.y2;
}

// Which box the pointer is currently over the label of. `queueCard` restarts its
// own delay on every call, so asking it on every `mousemove` would mean a card
// that never appears while the pointer is still moving: it is asked on the
// crossing, once, and `hideCard` on the way back out.
let onLabelOf = null;

// Which kinds a hover has anything to say about. Off the ladder in `model.py`,
// where a product declares `carded: false` — jcanton asked for no card on one,
// and the reason it is a property rather than a check written here is that the
// same question is asked on the table and the timeline.
const CARDED = {{ carded|tojson }};

cy.on('mouseover', 'node', evt => {
  if (connecting) return;
  const node = evt.target;
  // A product carries a title and a sentence and nothing else — no owner, no
  // dates, no appetite, no document. A card of it would be a box of dashes,
  // which teaches a reader that cards are not worth hovering for.
  if (CARDED[node.data('kind')] === false) return;
  if (node.isParent()) {
    if (!onLabel(node, evt.position)) return;
    onLabelOf = node.id();
  }
  // `data()` and not a lookup: a node's data IS the row — `_elements` builds it
  // from the same `_row` the table is drawn from — and this page has no `DATA` of
  // its own to look anything up in. The first version of this read `DATA.rows`
  // and drew nothing at all, on the one view the card was added for.
  queueCard(node.data(), evt.originalEvent.clientX, evt.originalEvent.clientY);
});

// Entering a box below its title is not entering its label, and the pointer can
// reach the label afterwards without ever crossing the box's edge again.
cy.on('mousemove', 'node', evt => {
  if (connecting) return;
  const node = evt.target;
  if (!node.isParent()) return;
  if (onLabel(node, evt.position)) {
    if (onLabelOf === node.id()) return;
    onLabelOf = node.id();
    queueCard(node.data(), evt.originalEvent.clientX, evt.originalEvent.clientY);
  } else if (onLabelOf === node.id()) {
    onLabelOf = null;
    hideCard();
  }
});

cy.on('mouseout', 'node', evt => {
  if (evt.target.isParent() && onLabelOf === evt.target.id()) onLabelOf = null;
  hideCard();
});
// A node dragged out from under a card, and a canvas panned or zoomed under one:
// the pointer never leaves the node, so `mouseout` does not fire and the card
// stays describing a node that is no longer there.
//
// The menu goes with them, and in the SAME handler rather than a second
// `cy.on('drag pan zoom', popClose)` beside it: one signal, one listener, or the
// next person to add a box here adds a third. `#pop` is `position: fixed` and
// never moves once placed — see `pop.py` — so a pan leaves it pointing at ground
// the node has left, and `relayout()` ends in `cy.fit()`, which moves everything
// at once. `popClose` takes no arguments and moves no focus, which is what makes
// it safe to call from a handler cytoscape also passes its own event object to.
cy.on('drag pan zoom', () => { onLabelOf = null; hideCardNow(); popClose(); });

// --- the right-click menu, on a node --------------------------------------
//
// `cxttap` and nothing else. The first shape of this offered `taphold` as well,
// on the grounds that cytoscape already fires it — jcanton, 2026-09-18: **"make
// all desktop only then, no touch longpresses, better."** There is a second
// reason not to reach for it, worth writing down because the feature is gone and
// the trap is not: cytoscape's mousedown branches `if (3 == t.which) {
// cxttapstart } else if (1 == t.which) { … tapholdTimeout = setTimeout(…, 500) }`
// — **the taphold timer is armed by the LEFT button.** On a canvas whose primary
// gesture is dragging a node, an unguarded `taphold` opens a menu every time
// somebody presses a node and thinks for half a second before moving it.
//
// **Viewport coordinates, off `originalEvent`.** Cytoscape offers a tap three
// answers and two of them are wrong for this box: `evt.position` is model
// coordinates, which pan and zoom out from under the reader, and
// `evt.renderedPosition` is relative to the canvas, which sits below a nav, a
// filter row and — when there is a server — a commit bar. `#pop` is `position:
// fixed`, so it wants the viewport. That is the same question `queueCard` above
// answers and the same way it answers it, three handlers up: one answer to it on
// this page rather than two that agree today.
//
// No `preventDefault` at this call site, unlike the table's and the timeline's.
// `cxttap` is cytoscape's own event and has no default to prevent, and the
// browser's menu over this canvas was already suppressed before we arrived —
// `registerBinding(container, "contextmenu", e => e.preventDefault())`, read out
// of `static/cytoscape.min.js` rather than taken on trust.
//
// The whole order, from a trusted right press through CDP on this page,
// 2026-09-18: `mousedown` (`which` 3) → `cxttapstart` → `contextmenu` →
// `mouseup` → `cxttap`. So this box opens last, after `pop.py`'s capture-phase
// `pointerdown` — earlier still — has closed whichever menu was up. A second
// right-click on a second node therefore shuts the first menu and opens the
// second, in that order, and there is no window in which one press closes the
// box it has just opened. Driven, and it does: menu on node A, press node B,
// `popAbout()` answers B.
cy.on('cxttap', 'node', evt => {
  // Shift falls through to the browser's own menu, and this is half of that
  // promise: the capture listener below stops cytoscape from eating the native
  // menu, and this line stops ours from opening on top of it. A press on a node
  // is the one place that reaches both.
  if (evt.originalEvent.shiftKey) return;
  // Not while an edge is being drawn — `dbltap`'s guard, for `dbltap`'s reason.
  // `Open` navigates, and a canvas holding drawn-but-unsaved edges loses them
  // without a word; the pointer is also mid-gesture, picking a blocker and then
  // what waits for it, and a box opening under it covers the node being aimed
  // at. The hover card declines here for the second half of that already.
  if (connecting) return;
  // No label-band restriction, although a compound is hit over its whole area
  // here exactly as it is for the card. What the card is giving back there is
  // TRANSIT: reading a project's tasks means dragging the pointer through its
  // acreage, and a box that opens on the way is in front of the thing being
  // read. A right-click is never transit — it lands where it was aimed — and the
  // empty ground inside a box is the box's own.
  popMenu(evt.originalEvent.clientX, evt.originalEvent.clientY, evt.target.id());
});

// **Shift+right-click reaches the browser on this page too**, and this is the
// only view where that needed anything. Cytoscape binds `contextmenu` on the
// container in the BUBBLE phase — `registerBinding` passes its fourth argument
// through as the capture flag and that call site has no fourth argument, so the
// options are `{capture: false}`; both facts read out of the vendored file on
// 2026-09-18 rather than assumed. A capture-phase listener on the same element
// therefore runs first, and stopping the bubble there means the `preventDefault`
// never happens and the native menu opens.
//
// `stopPropagation` and not `stopImmediatePropagation`: the listener that must
// not run is on this same element in a LATER phase, so stopping the bubble is
// enough, and stopping it immediately would be a claim about listener order
// within the capture phase that nothing here needs to make.
//
// Driven with two witnesses rather than asserted, because "the native menu
// opened" is the one thing a page cannot see — a headless browser's own menu is
// not in the DOM. So the claim is put as what the PAGE did to the event. Two
// extra listeners on this same element, one in capture after this one and one in
// bubble after cytoscape's, trusted right presses through CDP, 2026-09-18:
// shift held, the capture witness sees `shiftKey: true, defaultPrevented:
// false` and the bubble witness never runs at all — the event reaches the end of
// its life with its default intact. Without shift, the capture witness sees
// `defaultPrevented: false` and the bubble witness sees `true`, which is
// cytoscape eating the menu exactly as it has since before any of this.
CYBOX.addEventListener('contextmenu', event => {
  if (event.shiftKey) event.stopPropagation();
}, true);

// Asked and answered, so nobody asks it twice: `#nothing` is `position:
// absolute; inset: 0` with an opaque background and it eats every pointer event
// while it is up — and it does not matter here. It is only up when `keep.size`
// is 0, so there is no node under it to open a menu about; and it is a SIBLING
// of `#cy` inside `.canvas`, not a child, so a press on it reaches neither this
// listener nor cytoscape's, and a reader right-clicking an empty canvas gets the
// browser's own menu. Which is the right answer for a box whose whole content is
// a sentence and a Clear filters button.

// --- this view's own two items ----------------------------------------------
//
// Spliced into the menu between the write half and Open — `pop.py` holds the
// slot and decides the order. Built on every open and never stored, which is
// `attachDrawing`'s rule and the reason an item can refuse against state that
// has moved since the last press.

// The first half of the connecting gesture, started from a box instead of from
// the canvas: turn the mode on, and pick this node as what must finish first.
// Both halves already existed, and this item calls them rather than repeating
// them — cut 2 made the menu refuse to open at all while `connecting` is already
// true, so this run always starts from a canvas that is not in the mode.
//
// **Deliberately not refused for `off_plan_deps`.** That refusal belongs to the
// record that WAITS: Save rebuilds the whole `depends_on` of every waiter out of
// what this canvas can draw, so a record whose stored field also names something
// off the plan must not be the second tap, or the save silently deletes a line
// nobody was shown. This item makes the node the BLOCKER, and no Save here
// writes the blocker's file at all — `wanted` is keyed by `edge.target()`. The
// canvas already says the same thing by refusing the second tap for it and the
// first tap for nothing whatever. A refusal here would be a second rule, wider
// than the one it mirrors, telling a reader their off-plan dependencies are in
// the way while nothing of theirs is being edited.
function graphDependencyItem(node) {
  return {kind: 'add-dependency', text: 'Add dependency from here',
          run: () => { connectingIs(true); pickBlocker(node); }};
}

// Show this record and everything filed under it. Not refused on a record that
// holds nothing: a leaf focused on its own is this canvas answering "what does
// this one thing touch" — it stays drawn, its containing boxes stay drawn, and
// what it waits on is faded beside it, which is a reading of the plan and not an
// empty screen.
function graphFocusItem(node) {
  if (FOCUS === node.id())
    return {kind: 'focus-subtree', text: 'Focus subtree',
            why: `This canvas is already showing only ${nameOf(node)} and what is `
                 + 'inside it.'};
  return {kind: 'focus-subtree', text: 'Focus subtree', run: () => focusOn(node.id())};
}

// The host contract — registered once, and this page then knows nothing else
// about the menu. `pop.py` has the whole of it.
popServes({
  // This page has no `EDITABLE` and is deliberately not given one. `editable`
  // decides exactly one thing here — whether `#commitbar` is drawn — and
  // `if (CONNECT)` below is already how this script asks whether there is a
  // server it may write to; the rendered export ships the same JavaScript with
  // no bar to reach. A second spelling of one server flag is the drift this file
  // has paid for before: three hand-written status maps beside the ladder, all
  // three answering `undefined` the day it gained a rung.
  //
  // Not called in cut 2 — nothing in the reader's menu writes.
  may: () => !!CONNECT,
  // **A node's `data()` IS the row.** `_elements` builds it from the same
  // `rows.py:_row` the table is drawn from, so this page has no `DATA` to look
  // anything up in — the first version of the hover card read `DATA.rows` here
  // and drew nothing at all, on the one view it was added for.
  //
  // An id this canvas does not hold gives an empty collection, whose `data()` is
  // `undefined` and not a throw — checked against the vendored build,
  // 2026-09-18 — which is the falsy `popMenu` asks for before it opens anything.
  rows: id => cy.getElementById(id).data(),
  // The same two the table registers, asked of the canvas. `cy.nodes()` is every
  // record this drawing holds, filtered or not — a faded node is still a legal
  // parent — and `visible()` is cytoscape's own answer to whether one can be seen,
  // which is what a receipt about where a new child landed has to be about.
  all: () => cy.nodes().map(node => node.data()),
  shows: id => cy.getElementById(id).visible(),
  extras: row => {
    const node = cy.getElementById(row.id);
    // `Add dependency from here` only where there is a bar to save it with, and
    // NOT drawn refused the way a row's own refusals are. What is missing on a
    // reader's page is not this record's state but the whole mode: `#commitbar`
    // is not rendered at all, so an item explaining why dependencies cannot be
    // edited would be the only thing on that page mentioning that they ever can
    // be. `Focus subtree` moves nothing and is a reader's item as much as a
    // writer's, so it is drawn on every render including the export.
    //
    // This is also what keeps `connectingIs` safe to call: the item that calls
    // it exists only where `CONNECT` does.
    const items = CONNECT ? [graphDependencyItem(node)] : [];
    items.push(graphFocusItem(node));
    return items;
  },
  // **A write from the menu has to redraw the node**, and this page's answer is
  // the one its own Save already gives. The PATCH answers a commit and a
  // `pushed` flag and no record (`web.py`), the elements block is built by the
  // server out of `_row`, and a node's fill, its glyph and its ring are all
  // styled off `data()` — so there is nothing on the wire to update them from
  // and nothing this page could re-read them with. Without this a status written
  // from the menu leaves the node drawn in the colour it used to have, which is
  // the failure this canvas is least able to show: a graph that is wrong looks
  // exactly like a graph that is right.
  //
  // `popWrite` has already closed the box and given the keyboard back before
  // this runs, so nothing here is destroying the element focus was returned to —
  // the whole document is going.
  wrote: () => { location.reload(); },
});

if (CONNECT) {
  CONNECT.onclick = () => {
    const dropped = connecting ? pending().length + dropping().length : 0;
    if (dropped) { cy.remove(pending()); dropping().removeClass('dropping'); }
    connectingIs(!connecting);
    // The hint under the heading stays put in both modes. It was swapped for a
    // second paragraph on the way in and back again on the way out, so pressing
    // the button reflowed the page under the pointer — and everything it says is
    // still true in edit mode: you still pan, still zoom, still drag a node.
    // What edit mode adds is said once, beside the button that turned it on.
    tally(connecting
      ? 'click what must finish first, then what waits for it — or click an arrow to remove it'
      : dropped ? `discarded ${dropped}` : '');
  };

  DISCARD.onclick = () => {
    cy.remove(pending());
    dropping().removeClass('dropping');
    blocker = null;
    cy.nodes().removeClass('picked');
    tally('reset');
  };

  // One PATCH per dependent, because depends_on lives on the record that waits.
  // Each write moves HEAD, so the base for the next one is the commit this one
  // returned — reusing the page's base would make every write after the first a
  // conflict against a commit this same button just created.
  SAVE.onclick = async () => {
    SAVE.disabled = true;
    const wanted = new Map();
    // Both halves are grouped by the record that WAITS, because that is the
    // record `depends_on` is stored on — an edge removed is a line taken out of
    // the dependent's own file, exactly like an edge added is one put into it.
    const unwanted = new Map();
    for (const edge of pending()) {
      const target = edge.target().id();
      wanted.set(target, [...(wanted.get(target) || []), edge.source().id()]);
    }
    for (const edge of dropping()) {
      const target = edge.target().id();
      unwanted.set(target, [...(unwanted.get(target) || []), edge.source().id()]);
      if (!wanted.has(target)) wanted.set(target, []);
    }
    const base = document.getElementById('base');
    let written = 0;
    for (const [id, sources] of wanted) {
      const node = cy.getElementById(id);
      // What this card is called on the canvas it was just dragged on, so the
      // sentence in the live region names the thing the reader is looking at
      // instead of the id under it, which is drawn nowhere on this page.
      const name = nameOf(node);
      const gone = new Set(unwanted.get(id) || []);
      // Added first and removed second, so a dependency drawn and then marked in
      // one session comes out as removed rather than as whichever the loops ran
      // in. `depends_on` is sent whole because a PATCH of a list replaces it —
      // there is no "and also remove this" on the wire, and inventing one would
      // be a second way to say the same thing.
      const fields = {depends_on:
        [...new Set([...(node.data('depends_on') || []), ...sources])]
          .filter(one => !gone.has(one))};
      // Declared before the request and answered in `finally`, because the server
      // announces a commit to the event stream before it answers the request that
      // made it — so this tab can hear about its own write first. Announced even
      // on a refusal, or one rejected edge holds every later event forever.
      dispatchEvent(new Event('openproj:writing'));
      let committed = null;
      try {
        const response = await fetch(`/api/record/${encodeURIComponent(id)}`, {
          method: 'PATCH', headers: {'content-type': 'application/json'},
          body: JSON.stringify({base_commit: base.value, fields, body: null}),
        });
        const answer = await answerOf(response);
        if (!response.ok) {
          // The validator refuses an edge onto an ancestor, and a cycle. Say which,
          // and say what did get written: stopping silently after three of five
          // would leave the page disagreeing with the repository. The shell's
          // `refusal` because an edge saved against a moved HEAD comes back 409,
          // and this said "refused" where the answer held the whole report.
          const why = refusal(answer, response.status);
          say(`${name}: ${why}${written ? ` — ${written} already saved` : ''}`);
          SAVE.disabled = false;
          return;
        }
        committed = answer.commit;
        base.value = answer.commit;
        written += 1;
      } catch (error) {
        // The connection went mid-batch. With no `catch` the rejection escaped
        // and took `location.reload()` with it, so the canvas was left holding
        // drawn-but-unsaved edges with Save disabled and nothing said — while
        // the records before this one really had been committed, one per commit.
        //
        // Save comes back and the reload does not happen, so what is on the
        // canvas is still what has not been written. No claim about what reached
        // the server: a fetch rejects when the answer is lost as readily as when
        // the request never left.
        //
        // The repeat is safe because it is the SAME write — the canvas still
        // holds the same edges, so the same `depends_on` goes out — and not
        // because the store would refuse it. `_merge_frontmatter` skips every key
        // whose stored value already equals the one being sent, so a record that
        // did land merges with itself and answers 200. This sentence used to
        // promise a refusal the store does not give.
        say(`${name}: not saved — ${error.message}`
            + (written ? ` — ${written} already saved` : '')
            + '. Press Save again: it sends the same links, so a record that did '
            + 'land is not written twice.');
        SAVE.disabled = false;
        return;
      } finally {
        dispatchEvent(new CustomEvent('openproj:wrote', {detail: committed}));
      }
    }
    location.reload();
  };
}

// An edge is a decision like a node is, so in edit mode it answers to a click.
// A dependency that was drawn in this session and not saved is simply undrawn;
// one that is in the plan is marked, and Save takes it out of the `depends_on`
// it is stored on. Marked rather than removed on the spot, because until Save
// nothing has happened and the canvas has to be able to say what it is about to
// do — the same rule the drawn ones follow.
// --- refiling ---------------------------------------------------------------
//
// Refiling is not on this canvas. It was written by hand, removed, brought back
// through `cytoscape-compound-drag-and-drop`, and removed again on 2026-08-20 —
// jcanton, after using it: "no need to do this in the graph, let's leave it to
// the table". Dragging a node here moves it in a drawing whose whole arrangement
// is computed, so a record dropped into a box is a record whose position is
// about to be recomputed anyway; the table's rows do not move under you, and a
// row dragged onto another row is a gesture with one meaning.
//
// The extension went with it. A vendored library nothing calls is a library
// nobody checks — see `static/VENDOR.md`.

cy.on('tap', 'edge', evt => {
  if (!connecting) return;
  const edge = evt.target;
  if (edge.hasClass('pending')) {
    cy.remove(edge);
    tally('undrawn');
    return;
  }
  // The one refusal the server cannot make for us. Save PATCHes the waiter's
  // whole `depends_on` rebuilt from what this canvas carries, and the canvas
  // deliberately carries only what it can draw — so on a record whose stored
  // field also names something off the plan (a hand-written dependency on an
  // issue), that save would silently delete somebody's line. The server
  // cannot tell it from the record page legitimately removing that target,
  // so the canvas is the only gate: refused here, where the other impossible
  // edges are refused, with the way out named.
  if (edge.target().data('off_plan_deps')) {
    tally(`${edge.target().id()} waits on something this graph cannot draw — `
          + 'its dependencies are edited on its own page');
    return;
  }
  edge.toggleClass('dropping');
  tally(edge.hasClass('dropping')
    ? `${edge.source().id()} → ${edge.target().id()} will be removed`
    : 'kept');
});

cy.on('tap', 'node', evt => {
  const node = evt.target;
  if (!connecting) return;
  if (!blocker) { pickBlocker(node); return; }
  const from = blocker;
  blocker = null;
  from.removeClass('picked');

  if (from.id() === node.id()) { tally('a record cannot wait for itself'); return; }
  // Same refusal as the edge handler above, for the same record: the new edge
  // would be saved as this waiter's whole `depends_on` rebuilt from the
  // canvas, and the canvas cannot see the hand-written off-plan line it
  // would be deleting.
  if (node.data('off_plan_deps')) {
    tally(`${node.id()} waits on something this graph cannot draw — `
          + 'its dependencies are edited on its own page');
    return;
  }
  if (cy.edges().some(e => e.source().id() === from.id() && e.target().id() === node.id())) {
    tally('that dependency is already there');
    return;
  }
  // Checked here as well as on the server so a batch fails while you are drawing
  // it rather than at Save, when some of it has already been committed.
  if (node.successors().some(e => e.id() === from.id())) {
    tally(`${node.id()} already has to finish before ${from.id()}`);
    return;
  }
  if (node.ancestors().some(e => e.id() === from.id())) {
    tally('a record cannot wait for what contains it');
    return;
  }

  cy.add({group: 'edges', classes: 'pending',
          data: {source: from.id(), target: node.id(), kind: 'depends'}});
  tally();
});
</script>
"""


def _graph_css() -> str:
    """The graph's stylesheet, with the one number in it that is a fact about the
    vocabularies rather than a choice.

    `_page` takes a style as a finished string, so a `{{ }}` left in the constant
    is literal text in the CSS and silently does nothing — which is how the
    right-pairing rule below first shipped as a no-op. Same shape as
    `_timeline_css`, and for the same reason: the number has to be derived, and a
    constant cannot derive.
    """
    return _compiled(_GRAPH_STYLE).render(statuses=STATUSES, priorities=PRIORITIES)


_GRAPH_STYLE = """
/* The two key rows, over the drawing instead of above it. The canvas is the
   tallest thing on this page and they were costing it two lines before it began.
   Top right, because the layout runs left to right and top down, so that corner
   is the emptiest one on almost every plan.

   `pointer-events: none` on the box and back on for the rows: a key floating
   over a node must not swallow the double-click that opens it, but the rows
   themselves still need to be selectable text. */
.canvas { position: relative; }
.keys { position: absolute; top: .5rem; right: .75rem; z-index: 5;
        display: flex; flex-direction: column; align-items: flex-end; gap: .1rem;
        pointer-events: none;
        padding: .35rem .5rem; border-radius: 3px; }
.keys .legend { margin: 0; pointer-events: auto; gap: .2rem .45rem; }
/* Both rows the same length — jcanton, 2026-08-20. Each row is five keys and a
   name, so five keys of one width and a name of one width is two rows of one
   length, whatever the words inside them happen to be. Without it the rows are
   as long as their vocabulary: "Very high, High, Medium, Low, Very low" against
   "Shaping, Ready, In progress, Done, Shelved" came out 55px apart, and two
   ragged rows in a corner read as two unrelated things. */
/* Tight, and the rows come out near enough the same length by having the same
   number of keys in them. Two earlier attempts at making them EXACTLY equal both
   cost more than the equality was worth: `min-width` on every key padded them all
   to the width of "In progress", and a grid of five equal columns did the same
   thing by another route — jcanton, 2026-08-20: "there is too much horizontal
   space between cards in the legend". A key is as wide as what is in it. */
.keys .legend li { margin-right: .35rem; }
.keys .legend li.legendname { margin-right: .5rem; }
/* The rows pair from the RIGHT. `.legends` sizes its columns from the status
   count, so with six statuses and five priorities the priority row used to land
   in columns 2-6 and the status row in 2-7 — which put `High` in the same column
   as `In progress` and 58px of air between two priority keys, the exact fault
   jcanton reported once already ("there is too much horizontal space between
   cards in the legend").
   Pairing from the right instead puts `Medium` against `In progress`, which he
   chose knowingly on 2026-08-24: "we keep the legend a little wider: pair from
   the right, with medium against in progress. we can change later if necessary."
   The shorter row's NAME takes the slack, so the last key of each row shares a
   column and the rows still end where the eye already is. Derived from the two
   vocabularies rather than written as a number, so a seventh status or a sixth
   priority moves it without an edit here. */
.keys .legends .legend.shorter .legendname {
  grid-column: 1 / span {{ statuses|length - priorities|length + 1 }}; }
/* The legend leads and the count hangs under it — jcanton, 2026-08-24: "move it
   below the legend ... this way the legend can move a little upwards into the
   corner." The shell gives `.legends` `margin: .75rem 0 0 auto` for the pages
   that stack it under their controls; here that .75rem was the air between the
   count and the legend, and with the legend now first it would hold the legend
   12px off the corner the move is meant to reach. Zeroed at (0,2,0), which beats
   the shell's bare `.legends` (0,1,0) on specificity — order never decides it,
   although this sheet is inlined after the shell's anyway. The `auto` left
   margin goes with it; `align-items: flex-end` on `.keys` already puts every
   row on the right edge. */
.keys .legends { margin: 0; }

.canvas { position: relative; }
/* The room the window actually has left, not 78vh of it. A fraction of the window
   knows nothing about the rows above the canvas or the sticky commit bar below,
   and at an 806px window this ran 140px past the top of that bar with two nodes
   drawn underneath it — and scrolled the page as well, so the bar the canvas had
   to clear moved every time you scrolled to look at what it was covering.
   `height` and not `max-height`: a canvas has no size of its own to be capped at,
   so this is the one of the three boxes that is actually the size of the room.
   Under the floor the shell reports, the page scrolls and the sticky bar goes
   back to floating over what it covers — at a window that short there is no
   arrangement that fits. */
#cy { height: var(--room); border: 1px solid var(--line); }
/* Over the canvas rather than instead of it: cytoscape measures its container
   when it is built, and a container that was display:none at that moment comes
   back sized zero. */
#nothing { position: absolute; inset: 0; display: flex; flex-direction: column;
           align-items: center; justify-content: center;
           background: var(--bg); text-align: center; }
#nothing[hidden] { display: none; }
#nothing .headline { margin: 0 0 .25rem; font-size: 15px; }
#nothing .hint { margin: 0 0 .75rem; }
/* The way out of a focused subtree. An OVERLAY for the reason the keys are one:
   `#cy` is `height: var(--room)`, so a bar in the flow costs the drawing exactly
   the height it is drawn in, and the room is what this page has least of. Top
   left, because the keys hold the top right and the layout runs left to right,
   so this is the emptier of the two corners that are left.

   Above `#nothing` rather than beside it — z-index 6 against its `auto`, and the
   only place on this page that has to outrank it. A focus and a query can empty
   the canvas between them, and the box that then covers it is `inset: 0` with an
   opaque background: without this the one control that undoes half of what
   emptied the canvas would be painted over by the sentence explaining it. */
.focusbar { position: absolute; top: .5rem; left: .75rem; z-index: 6;
            display: flex; align-items: center; gap: .5rem;
            padding: .35rem .5rem; border-radius: 3px; }
/* The one wash, for both overlays. They are the same veil over the same canvas
   for the same reason — a box floating on the drawing has to be readable over
   whatever node is under it without hiding that node — and written twice they
   are two numbers that will be tuned once. AGENTS.md: two constants that are the
   same number are the same defect. */
.keys, .focusbar { background: color-mix(in srgb, var(--bg) 82%, transparent); }
/* Written out, because `[hidden]`'s UA rule loses to any author `display` on
   cascade origin alone — the same trap `#nothing` above is guarded against, and
   the one `.drawmenu` was reported for on 2026-08-26. Without it a bar saying
   the canvas is focused would stand over a canvas that is not. */
.focusbar[hidden] { display: none; }
/* A title is a record's own words and can be a sentence long. Clamped so it
   cannot grow this bar across the canvas into the keys — the ellipsis is the
   same bargain `#pop .poptext` makes, with the control that is the way out
   never being the part that shrinks. */
.focusbar .focusname { overflow: hidden; text-overflow: ellipsis;
                       white-space: nowrap; max-width: 18rem; }
/* **A corner is not a width.** `.keys` is pinned by its right edge and sized by
   its content, and its content is a grid of `auto repeat(6, max-content)` — a
   row of six status keys and their name, which measures about 620px whatever the
   canvas underneath it is. At a 390px viewport that box ran from -262 to 358:
   two thirds of the legend hung off the LEFT edge of the page, clipped by the
   document and unreachable, so the reader saw four keys out of eleven and no
   sign that there were more. Nothing overflowed to the right and no scrollbar
   appeared, which is why this survived — the page looked intact.

   The fix is to give it both edges and let it wrap. With `left` set beside the
   `right` it already had, the box is as wide as the canvas rather than as wide
   as its longest row, and the two lists inside go back to being what the shell
   makes of a legend that is on its own: `display: flex; flex-wrap: wrap`. That
   is `.legend`'s own rule, undone here only by `.legends .legend { display:
   contents }` handing the keys to the grid — so this is the grid being switched
   off, not a second layout being invented.

   The cascade, stated rather than guessed: `.keys .legends` is (0,2,0) against
   the shell's `.legends` (0,1,0), and `.keys .legends .legend` is (0,3,0)
   against `.legends .legend` (0,2,0). Both win on specificity, so neither
   depends on this sheet being inlined after the shell's — which it is.

   `align-items: stretch` because `flex-end` was right for rows the box was
   sized to and wrong for rows that now fill it.

   It stays an overlay. A legend that pushes the canvas down costs the plan the
   height it is drawn in, and `#cy` is `height: var(--room)` — the room is
   already the thing a phone has least of. Five wrapped rows over the top of the
   graph is the cheaper trade, and it is still pannable underneath. */
@media (max-width: 40rem) {
  /* The keys take both edges here, so they take the top of the canvas with them
     — five wrapped rows of it — and a bar pinned to the top left would be drawn
     on top of them. The bottom edge is the corner that is still free at this
     width, and the focus bar is the shorter of the two boxes.

     Both edges for the same reason the keys were given both: **a corner is not a
     width.** A box pinned by one edge and sized by its content is as wide as a
     record's title plus a button, and the one below measured 406px against a
     390px page — which is how two thirds of the legend came to hang off the left
     of this canvas, clipped by the document, with nothing overflowing to the
     right and no scrollbar to say so. With both edges the bar is as wide as the
     canvas and the title inside it takes the ellipsis it is already set up for,
     while the button — the way out — keeps its whole width. */
  .focusbar { top: auto; bottom: .5rem; right: .75rem; }
  .keys { left: .75rem; align-items: stretch; }
  .keys .legends { display: block; }
  .keys .legends .legend { display: flex; }
}
"""


def render_graph(
    index: Index,
    links: Links = STATIC,
    base_commit: str | None = None,
    may_write: bool = False,
) -> str:
    """The plan as nodes and edges, with the three libraries that draw it inlined.

    The libraries are template variables, like the data is. They arrived as
    `@@name@@` markers replaced in the finished page, which is a substitution over
    text that already held every title in the plan: naming a marker was enough to
    inline 796 KB a second time, blow the data block past what `json.loads` would
    read, and leave the graph with nothing to draw. Before that the markers were
    undelimited and replaced in sequence, and `DAGRE_JS` being a substring of
    `CYTOSCAPE_DAGRE_JS` ate the tail of the longer one. Rendering them as values
    ends both failures for the same reason: Jinja substitutes into the template,
    never into what a value expanded to.
    """
    # "There is a server behind this page AND this person may write". A local
    # rather than an argument spelled twice, because two things now ask it: the
    # template, for `#commitbar`, and the menu, for whether to bake its schema.
    editable = base_commit is not None and may_write
    body = _compiled(_GRAPH).render(
        # The first half of that alone shipped here, exactly as it had on the
        # table before the `reader-table` branch: a signed-out visitor was served
        # "Edit dependencies", drew edges onto the canvas, pressed Save and
        # collected a 403 for each of them. `/table` has asked this question
        # since that branch; `/graph` never did, and took no `request` to ask it
        # with.
        #
        # `design/QUEUE.md`'s table entry predicted the flag would have to SPLIT
        # rather than narrow, and on the table it narrowed. Here it narrows
        # further: this flag has only ever drawn `#commitbar`, so the reader's
        # canvas keeps panning, zooming, filtering, the hover card, the dbltap
        # into a record and the whole legend without a line moving.
        #
        # The script below is deliberately NOT behind this. The rendered-file
        # export has shipped the same JavaScript with no `#commitbar` to reach it
        # since the day it existed — `if (CONNECT)` is what makes it inert, and
        # nothing can turn `connecting` on without `CONNECT` in its hand: the
        # button's own handler is inside that guard, and the menu's `Add
        # dependency from here` is only built where `CONNECT` is there to build
        # it. Two tests read `SAVE.onclick` and the node `tap` handler straight
        # out of `graph.html`. A reader's served page is that page.
        editable=editable,
        base_commit=base_commit or "",
        facets=_facets_html(
            index.facets,
            aside=_GRAPH_HINT,
            titles=_titles(index),
            # Every planned record: this canvas draws all of them, and the
            # filtered count is what the script writes over the top of it.
            summary=_summary_html(index, len(index.plan)),
        ),
        filters=_FILTER_JS,
        # A function and not a constant, because the one server-decided value in
        # that script is where a record's page lives — `/detail/` here and
        # `detail.html#` in an export — and `Open` has to land exactly where this
        # canvas's own `dbltap` lands.
        #
        # **The index goes with it wherever this page may write**, because that
        # is what bakes `POP_SCHEMA` — the status ladders, the gates, the labels
        # and the people the write half is built out of. `popServes({may})` here
        # answers `!!CONNECT`, which is true on exactly the renders `editable` is
        # true on, and a menu asked to draw a write half with no schema says so
        # in the box rather than quietly drawing a reader's menu to somebody who
        # may write. `None` otherwise keeps about 5.4 kB off a reader's page and out of
        # the static export, which has nothing to write to.
        pop=_pop_js(links, index if editable else None),
        statuses=STATUSES,
        priorities=PRIORITIES,
        glyphs=STATUS_GLYPH,
        # The priority character, for the mark in front of a card's title. The
        # same map the table's menus write, so a card and a cell say the rung with
        # the same glyph.
        priglyphs=PRIORITY_GLYPH,
        levels=PRIORITY_LEVEL,
        carded={rung.name: rung.carded for rung in KIND_LADDER},
        total=len(index.plan),
        links=links,
        elements=_elements(index),
        cytoscape=_library("cytoscape.min.js"),
        elk=_library("elk.bundled.js"),
    )
    # Concatenated here rather than shared, because there is no sheet to share it
    # in: `.drawmenu` lives in `_DETAIL_STYLE`, which this page does not load, and
    # the only stylesheet all three of the menu's hosts already carry is the
    # shell's, which ships on all twelve pages for a thing three of them draw.
    # Exactly what `table.py` already does with `_SUGGEST_STYLE`.
    return _page(
        "openproj — graph", body, _graph_css() + _POP_STYLE, links, "graph", index.unreadable
    )
