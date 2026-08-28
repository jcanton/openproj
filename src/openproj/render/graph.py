"""The plan as nodes and edges."""

from __future__ import annotations

from markupsafe import Markup

from ..index import Index
from ..model import KINDS as KIND_LADDER
from ..vendor import _library
from .controls import _FILTER_JS, _facets_html, _summary_html
from .env import _compiled
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
// corridor, they are one grey line of one width with one arrowhead and the eye
// cannot follow any of them to its end. So each edge gets its own shade, its own
// head and its own weight — from a hash of the two ids, so the same dependency
// looks the same on every load and on everybody's screen.
//
// Deliberately a small range. jcanton, 2026-08-21: "without going over the top,
// just slightly different shades of grey (not too light otherwise invisible)".
// The shades are `--line-strong` mixed towards the page's ink and towards its
// muted grey, never towards the background; the widths are within half a pixel
// of each other; and the line stays SOLID, because dashed is what an uncommitted
// connection looks like on this canvas and that meaning is not for sale.
// Six inks, from the page's own tokens rather than from six greys. Greys within
// one family are not separable at 1.5px on a busy canvas — jcanton, 2026-08-21,
// "shades are too similar to distinguish to a human eye... otherwise we should
// use theme colours (also shades) which gives us more options" — and every token
// here is one this app already holds legible against the page in both themes and
// under every colour scheme, mixed halfway to the line colour so a canvas of
// them reads as a drawing rather than as a chart.
//
// One arrowhead for all of them, restored: "it's only one arrowhead per edge, it
// doesn't help figuring out where the edge starts by looking at the end only".
const EDGE_INKS = [
  '--line-strong', '--accent', '--ok', '--pri-medium', '--danger', '--st-shaping-line',
];

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
  const name = EDGE_INKS[edgeSeed(edge) % EDGE_INKS.length];
  const hue = token(name);
  if (!hue) return token('--line-strong');
  // Halfway to the line colour: the tokens are chip and status inks and are
  // meant to carry a word, which is louder than a 1.5px line needs to be. Mixed,
  // they stay this drawing's greys while being six of them rather than one.
  return inSRGB(`color-mix(in oklab, ${hue} 62%, ${token('--line-strong')})`);
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

// Lay the visible graph out and draw the answer. Asynchronous, and the callers
// treat it as such: the filter awaits nothing, it simply asks again.
async function relayout() {
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

const cy = cytoscape({
  container: document.getElementById('cy'),
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
    // codebases — gt4py under icon4py, dace, pmap — and it holds no work of its
    // own, so an empty outline is what it actually is.
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
        'width': 1.5 } },
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
                             'target-arrow-color': edge => edgeInk(edge)})
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

const NOTHING = document.getElementById('nothing');
const CLEAR = document.getElementById('clear-filters');

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
  }
  NOTHING.querySelector('.headline').textContent = headline;
  NOTHING.querySelector('.hint').textContent = detail;
  CLEAR.hidden = !clearable;
}

function applyFilter() {
  const keep = new Set();
  cy.nodes().forEach(node => { if (matches(node.data())) keep.add(node.id()); });
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

  // Only when the set actually changed: re-running dagre on every keystroke in
  // the search box moves every box under the hand that is typing.
  const now = cy.nodes(':visible').map(node => node.id()).sort().join(',');
  if (now === laidOut || !keep.size) return;
  laidOut = now;
  relayout();
}

// The first drawing. The constructor used to carry `layout:` and did this on the
// way up; ELK is asked directly now, so it is asked here — and asked here rather
// than left to `applyFilter`, which lays out only when the visible set has
// CHANGED, and on the first pass it has not.
relayout();

addEventListener('openproj:filter', applyFilter);
CLEAR.onclick = clearFilters;
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
cy.on('drag pan zoom', () => { onLabelOf = null; hideCardNow(); });

if (CONNECT) {
  CONNECT.onclick = () => {
    const dropped = connecting ? pending().length + dropping().length : 0;
    if (dropped) { cy.remove(pending()); dropping().removeClass('dropping'); }
    connecting = !connecting;
    blocker = null;
    cy.nodes().removeClass('picked');
    CONNECT.textContent = connecting ? 'Discard and exit' : 'Edit dependencies';
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
      // What this card is called on the canvas it was just dragged on. `label` is
      // the record's title — the same ink `labelOf` draws inside the box — so the
      // sentence in the live region names the thing the reader is looking at
      // instead of the id under it, which is drawn nowhere on this page. The id
      // is the fallback for the same reason the table's `titleOf` has one: a
      // record hand-written in git can carry no title at all.
      const name = node.data('label') || id;
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
  if (!blocker) {
    blocker = node;
    node.addClass('picked');
    tally(`${node.id()} must finish first — now click what waits for it`);
    return;
  }
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
        padding: .35rem .5rem; border-radius: 3px;
        background: color-mix(in srgb, var(--bg) 82%, transparent); }
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
  .keys { left: .75rem; align-items: stretch; }
  .keys .legends { display: block; }
  .keys .legends .legend { display: flex; }
}
"""


def render_graph(index: Index, links: Links = STATIC, base_commit: str | None = None) -> str:
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
    body = _compiled(_GRAPH).render(
        editable=base_commit is not None,
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
    return _page("openproj — graph", body, _graph_css(), links, "graph", index.unreadable)
