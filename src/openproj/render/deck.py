"""The review deck: one cycle, one slide to a page."""

from __future__ import annotations

import re
from collections.abc import Callable
from functools import lru_cache

from markupsafe import Markup

from ..index import Index, _people_on
from ..model import (
    Config,
    Record,
    Slide,
    bet_of,
    checklist_items,
    cycle_of,
    lead_text,
    only_sections,
    sections,
    size_weeks,
    slide_chunks,
    slide_title,
    without_checklist,
    without_comments,
    without_emptied_headings,
)
from .cycles import _proposed
from .env import _compiled
from .markdown import _drop_repeated_title, _inlined_assets, _markdown, _markdown_line, _pr_link
from .shell import ROUTES, Links, _page
from .styles import _DETAIL_STYLE
from .tokens import PRIORITY_GLYPH, STATUS_GLYPH, TEMPLATES, _priority_class, _status_class

# --------------------------------------------------------------------------- #
# The review deck
#
# At the end of a cycle the team stands up and walks a slide deck. It was built by
# hand in Google Slides from records that are already here, which is the same
# two-copies-of-one-fact this tool exists to end: the deck said "PR#2427, under
# review" beside a task whose `prs` and `status` said so already, and the copy in
# the deck went stale the moment either changed.
#
# What the real deck (cycle 37) does, and what this keeps:
#
#   - A title slide with the cycle and the word Review, and nothing else on it.
#   - One slide per piece of work, headed `[Area] Topic` — the bracket is the
#     thing the work belongs to, and it is what makes a deck skimmable when four
#     consecutive slides are all GT4Py. Here the bracket is the pitch, which is
#     what a task belongs to, so nobody types it.
#   - Bulleted points under it, the pull requests among them as links, and a
#     screenshot or a table where somebody had one.
#
# And what it drops: the free-form nesting, and the two slides in sixteen that
# were a heading over an empty page. A generated deck is the floor somebody edits
# up from, not the ceiling.
#
# Not in the nav. The nav names the views of the whole plan; a deck is of one
# cycle and is reached from that cycle's page, where the person who is about to
# present it already is.
# --------------------------------------------------------------------------- #

_DECK = """
{#- Screen furniture, and the first thing `@media print` takes away: a deck is
    printed to reach the people who were not in the room, and neither a back link
    nor a Present button is part of it. -#}
<p class="back deckbar"><a href="{{ links.cycle }}{{ d.number }}">\u2190 cycle {{ d.number }}</a>
  {#- Drawn by the server and not by the script that runs it, so it is on the page
      for a reader whose JavaScript has not arrived yet rather than appearing
      under their cursor a moment later. `hidden` until the script claims it: a
      control that cannot do anything is worse than one that is not there, and
      presenting is the one thing on this page that genuinely cannot work without
      the script. -#}
  <button type="button" id="present" class="ghost" hidden>Present</button>
</p>

<div class="deckwrap">
  {#- The rail. Built from the sheets beside it rather than rendered twice — see
      `_DECK_SCRIPT`, which clones each slide into its own thumbnail. Two
      renderings of one slide is two things to keep in step, and the thumbnail is
      the one nobody would notice going stale. -#}
  <nav class="rail" id="rail" aria-label="Slides in this deck" hidden>
    <ol id="thumbs"></ol>
  </nav>

  <div class="sheets" id="sheets">
<article class="slide title" data-id="title" data-key="title">
  <h1>Cycle {{ d.number }}</h1>
  <p class="lead">Review</p>
  <p class="when">{% if d.reviews_on %}{{ on(d.reviews_on) }}{% if d.assumed_review %}
    <span class="assumed">\u2014 assumed: this cycle names no review meeting</span>
    {% endif %}{% else %}No review meeting recorded{% endif %}</p>
  {#- The goal, because a review opens by saying what the cycle was for and the
      team already wrote that down on the cycle record. The real deck's title
      slide is bare only because its goal lived in a different tool. -#}
  {% if d.goal %}<div class="doc goal">{{ d.goal }}</div>{% endif %}
</article>

{% for s in d.slides %}
{#- `data-id` is the record, and it is what the rail reorders by and what the
    live refresh keeps its place by. Deliberately the record id and not the
    slide's index: a deck that reloaded under a presenter would otherwise land
    them on whatever is now third rather than on what they were talking about.
    `data-at` distinguishes a record's continuations from each other. -#}
<article class="slide{{ ' skipped' if s.skip }}" data-id="{{ s.id }}" data-at="{{ s.at }}"
  data-key="{{ s.id }}:{{ s.at }}"
  {% if s.skip %}data-skip="1"{% endif %}>
  {#- The bracket first and smaller, exactly as `[GT4Py] Features` reads: what
      this belongs to, then what it is. Omitted where the work IS the bet, since
      a bracket repeating the line under it says nothing. -#}
  {% if s.under %}<p class="under">{{ s.under }}</p>{% endif %}
  <h2>{{ s.title }}</h2>
  <p class="who">
    {#- The chip carries its MARK as well as its word, which is what the table
        has drawn since the glyphs existed and what this had not. A slide is read
        from the third row of a room, off a projector somebody has turned the
        contrast down on, and possibly in a photocopy: the fill is the channel
        that dies first and the one the deck already gives up (see the flattening
        rule in `_DECK_STYLE`), so without a mark the status was carried by the
        word alone. Same notation as the table, the graph and the legend. -#}
    <span class="chip {{ s.status_class }}"><span class="chipmark"
        aria-hidden="true">{{ s.glyph }}</span><span
        class="chipword">{{ s.status|human }}</span></span>
    {#- Priority, which the slide simply did not carry. It is on every other view
        of a record and it is the second thing anybody asks about a piece of work
        in a review. -#}
    {% if s.priority %}<span class="chip pri {{ s.priority_class }}"><span class="chipmark"
        aria-hidden="true">{{ s.priority_glyph }}</span><span
        class="chipword">{{ s.priority|human }}</span></span>{% endif %}
    <span class="tally">{{ s.size }} wk</span>
    {% if s.people %}<span class="tally">{{ s.people }}</span>{% endif %}
    {% if s.text %}<span class="tally">{{ s.text }}
      <span class="meter" role="img"
            aria-label="{{ s.percent }} per cent of this is done"
        ><span style="width: {{ s.percent }}%"></span></span></span>{% endif %}
    {#- The record, because the slide deliberately does not carry the shaping
        argument and somebody in the room will ask. Printed as well as linked:
        on a handout the id is what tells you which file to go and read. -#}
    <a class="record" href="{{ links.record }}{{ s.id }}">{{ s.id }}</a>
  </p>

  {% if s.points %}
  <ul class="points">
    {% for point in s.points %}
    <li class="{{ 'ticked' if point.done else '' }}"><span class="box"
      aria-hidden="true">{{ '\u2611' if point.done else '\u2610' }}</span>{{ point.text }}</li>
    {% endfor %}
  </ul>
  {% endif %}

  {% if s.prs %}
  <ul class="prs">{% for pr in s.prs %}<li>{{ pr }}</li>{% endfor %}</ul>
  {% endif %}

  {% if s.body %}<div class="doc">{{ s.body }}</div>{% endif %}
  {#- The author's own words, which the record does not carry and which are the
      whole point of the slide editor. After the record's own document, because
      the generated part is the report and this is what somebody adds to it. -#}
  {% if s.extra %}<div class="doc extra">{{ s.extra }}</div>{% endif %}
  {#- What the slide did, when what it did is not simply "printed the record":
      the plan cut to fit, or a record with nothing written on it. On the sheet,
      because the sheet is the copy that leaves the room and a slide that
      silently dropped half a section looks exactly like a finished one. -#}
  {% if s.note %}<p class="note">{{ s.note }}</p>{% endif %}
</article>
{% else %}
{#- Empty is not broken, and it is not a failure either: this cycle exists and
    holds no work. The way out is the cycle's own page, which is where work gets
    bet into it. -#}
<article class="slide empty" data-id="empty" data-key="empty">
  <h2>Nothing is bet into cycle {{ d.number }}</h2>
  <p>A deck is one slide per piece of work in the cycle, and this cycle holds
     none yet. Bet something into it on
     <a href="{{ links.cycle }}{{ d.number }}">the cycle {{ d.number }} page</a>
     and it will have a slide here.</p>
</article>
{% endfor %}
  </div>
</div>
"""


_DECK_STYLE = """
/* A slide is a sheet of paper, and paper does not have a theme.
   Defined once, in bare `:root`, which every reader matches — so this is not a
   colour whose only definition sits in a block half of them never see. It is a
   colour that is deliberately the same in all of them: these slides are white on
   the projector, white in the PDF and white on the printer, and a deck that came
   out ink-on-black for whoever had chosen dark would have been discovered in
   front of the room. The app around the slides stays themed. */
:root {
  --paper: #ffffff; --paper-ink: #14211f; --paper-muted: #5a6b70;
  --paper-line: #dce4e5; --paper-link: #0f5c6b; --paper-tint: #f5f8f8;
  /* The one word on a slide that is a warning, and it is on paper too:
     `--warn` is measured against the reader's ground, and the dark theme's is
     a pale amber that all but disappears on white. */
  --paper-warn: #8a5308;
}
#main { max-width: none; }
.slide {
  background: var(--paper); color: var(--paper-ink);
  border: 1px solid var(--paper-line); border-radius: 4px;
  max-width: 62rem; margin: 0 auto 1.25rem; padding: 2rem 2.5rem;
  /* The FALLBACK geometry, and it is what this rule has always been: a floor,
     so a slide whose notes run long grows rather than clipping. It is what a
     reader without JavaScript gets, and what `@media print` keeps.

     The fixed canvas is `.sized .slide` below and is switched on by the script,
     because it needs a number no stylesheet can compute — see the comment
     there. Kept as two rules rather than one so that the page a reader lands on
     is complete before anything runs, which is the same reason the Present
     button is drawn `hidden` rather than created. */
  min-height: 34rem;
}

/* --- The slide as a fixed canvas ----------------------------------------- *
   A slide is 1280x720 and nothing it holds may change that — jcanton,
   2026-08-25: "content should not be allowed to change the size of a slide
   canvas nor spill out of it". Everything inside is laid out in that one
   coordinate space and the whole box is then scaled to whatever it is being
   drawn in: the page column, a rail thumbnail, the editor's preview pane, or the
   full screen of a projector. One layout, four sizes, so what somebody approves
   in the editor is what the room sees — which is the entire argument for
   generating a deck rather than retyping one.

   This OVERTURNS the `min-height` rule above, whose comment argued against a
   fixed height on the grounds that clipping is the worse failure. That argument
   was right about paper and wrong about a projector: a screen has no scrollbar
   and a wall has no second sheet, so "spills honestly" spills onto nothing at
   all. What replaces it is not silence — `.spills` below marks a slide that does
   not fit, in the editor and on the rail, so the overflow is found by the author
   at the desk instead of by the room.

   `zoom` and not `transform: scale()`, and the difference is the whole reason
   this works without a wrapper element: `zoom` scales the used values, so the
   flow box shrinks with the content and the slides stack correctly down the
   page. A transform leaves a 720px hole behind every slide and needs a negative
   margin per slide to close it, computed from the same number, in a second
   place. Presentation mode does use a transform, and can: there the slide is
   taken out of flow entirely, so there is no layout left to preserve. */
.sized .slide {
  width: 1280px; height: 720px; max-width: none; min-height: 0;
  padding: 3rem 3.5rem;
  zoom: var(--fit, 1);
  /* The clip. Without it the fixed height is a suggestion and a long code block
     hangs out of the border, which is the drawing this rule exists to prevent. */
  overflow: hidden;
}
/* Code is the content most likely to be wider than the canvas, and a scrollbar
   is no answer on a wall. Wrapped rather than scrolled, so an over-long line
   costs vertical room — which `.spills` can see and a horizontal overflow
   cannot. */
.sized .slide pre, .sized .slide code { white-space: pre-wrap; overflow-wrap: anywhere; }
.sized .slide table { width: 100%; table-layout: fixed; }
/* A picture may not push the sheet open either. `max-height` in the slide's own
   coordinate space, so a tall screenshot is fitted rather than paginated. */
.sized .slide .doc img { max-width: 100%; max-height: 26rem; object-fit: contain; }
/* Every link on a slide, against paper rather than against the theme's ground.
   `.slide a` is (0,1,1) against the shell's `a, a:visited` at (0,0,1) and (0,0,2)
   and wins on specificity in both themes, whichever order they are inlined in. */
.slide a, .slide a:visited { color: var(--paper-link); }
.slide .doc { border-top: 1px solid var(--paper-line); padding-top: 1rem; }
.slide .doc code, .slide code { background: var(--paper-tint); }
.slide .meter { background: var(--paper-line); }
.slide .meter > span { background: var(--paper-link); }
/* The status, as the word and not as the ladder. The five status fills are a
   luminance ladder against the PAGE, so on a white slide under the dark theme
   the chip came out a solid dark pill among hairlines — the app's own device,
   drawn against a ground it was not measured on. The ladder exists because a
   graph node and a timeline bar have no words in them; a slide has nothing but
   words, and "IN PROGRESS" says it in every theme and to every reader.
   (0,3,0) against the shell's `.chip.st-ready` at (0,2,0), so this wins on
   specificity rather than on the order the two stylesheets happen to be inlined
   in — and it beats all five rungs with one rule. */
.slide .who .chip {
  background: transparent; color: var(--paper-muted); border: 1px solid var(--paper-line);
}

.slide.title { display: flex; flex-direction: column; justify-content: center; }
.slide.title h1 { font-size: 3rem; line-height: 1.1; margin: 0; }
.slide.title .lead { font-size: 2rem; color: var(--paper-muted); margin: .25rem 0 1rem; }
.slide.title .when { color: var(--paper-muted); margin: 0; }
.slide.title .assumed { color: var(--paper-warn); }
.slide.title .goal { margin-top: 2rem; }

/* The bracket, at label size above the title. Uppercase and tracked, because on
   a projector it has to read as a category rather than as a first line. */
.slide .under {
  margin: 0 0 .35rem; font-size: 12px; font-weight: 600; letter-spacing: .06em;
  text-transform: uppercase; color: var(--paper-muted);
}
/* The slide's OWN heading, and a child combinator rather than a descendant one.
   `.slide h2` and `_DETAIL_STYLE`'s `.doc h2` are both (0,1,1); this stylesheet
   is inlined second, so it took the tie and drew every heading inside the notes
   at the size of the slide's title — a `## Solution` shouting over the line it
   belongs under. Scoped to the direct child it does not enter `.doc` at all, and
   `.doc h2`'s 1rem wins by being the only rule that matches. */
.slide > h2 { font-size: 1.9rem; line-height: 1.15; margin: 0 0 .6rem; }
.slide .who { display: flex; flex-wrap: wrap; gap: .4rem .9rem; align-items: center;
              margin: 0 0 1rem; }
.slide .who .tally { color: var(--paper-muted); font-size: 13px; }
/* Last on the row and out of the way: a slide is about the work, not about the
   file it is kept in — but the file is the answer to the question the missing
   shaping argument raises, so it is on the sheet rather than only in the app. */
.slide .who .record { margin-left: auto; font-family: var(--font-mono); font-size: 12px; }

.slide .points { list-style: none; margin: 0 0 1rem; padding: 0; font-size: 1.15rem; }
.slide .points li { display: flex; gap: .5rem; margin: .3rem 0; line-height: 1.35; }
/* Struck through AND ticked. The box is the channel that survives a projector
   with the contrast turned down; the strike is the one that survives somebody
   reading it from the third row. */
.slide .points li.ticked { color: var(--paper-muted); text-decoration: line-through; }
.slide .points .box { flex: none; text-decoration: none; }

.slide .prs { list-style: none; margin: 0 0 1rem; padding: 0; font-size: 1.15rem; }
.slide .prs li { margin: .2rem 0; }
.slide .doc img { max-width: 100%; height: auto; }
/* The line about the slide rather than about the work. Muted and at label size,
   because it is not what the presenter is there to say — but printed, because
   the alternative is a sheet that cannot be told from a complete one. */
.slide .note { margin: .6rem 0 0; color: var(--paper-muted); font-size: 13px; }
.slide.empty { display: flex; flex-direction: column; justify-content: center; }

/* --- The rail ------------------------------------------------------------ *
   A column of thumbnails down the left, the way every slide tool puts one
   there. Each thumbnail is the real slide cloned and scaled, never a picture of
   one: a rasterised thumbnail is a second rendering that goes stale silently,
   and this page's whole argument is against a second copy of anything. */
.deckwrap { display: flex; gap: 1.25rem; align-items: flex-start; }
.sheets { flex: 1 1 auto; min-width: 0; }
.rail {
  flex: none; width: 13rem;
  position: sticky; top: 1rem; max-height: calc(100vh - 2rem);
  overflow-y: auto; overscroll-behavior: contain;
}
.rail ol { list-style: none; margin: 0; padding: 0; counter-reset: slide; }
.rail li {
  position: relative; margin: 0 0 .5rem; border: 1px solid var(--line);
  border-radius: 4px; overflow: hidden; cursor: grab; background: var(--paper);
}
/* The number, which is what a presenter says out loud ("go back two"). Drawn by
   the stylesheet off a counter rather than written into each thumbnail, so it
   renumbers itself the moment a drag reorders the list — a number the script had
   to rewrite is a number that would be wrong for the frame after every drop. */
.rail li::before {
  counter-increment: slide; content: counter(slide);
  position: absolute; top: 0; left: 0; z-index: 2;
  font-size: 10px; font-family: var(--font-mono); line-height: 1;
  padding: 3px 5px; background: var(--paper-ink); color: var(--paper);
  border-bottom-right-radius: 4px;
}
.rail li[aria-current="true"] { outline: 2px solid var(--accent); outline-offset: 1px; }
/* Being dragged, and where it would land. Both are `opacity` and a rule rather
   than a movement: the app animates in exactly two places and
   `test_the_app_moves_in_two_places` is the inventory of them, so a rail that
   eased its rows into position would be a third. A drag is already continuous
   feedback — the thing under the cursor IS the animation — and adding a
   transition to it would fight the pointer rather than follow it. */
.rail li.dragging { opacity: .4; cursor: grabbing; }
.rail li.over { border-color: var(--accent); }
/* The slide inside a thumbnail: inert, unclickable, and scaled by the SAME rule
   the page column uses. `--fit` is a custom property and custom properties
   inherit, so the rail simply declares its own value and `.sized .slide`'s
   `zoom: var(--fit)` picks it up — one geometry rule, two scales, and no
   equal-specificity tie between them to be resolved by which rule happens to be
   written second. That tie is this repository's characteristic failure and it
   was in the first draft of this block. */
.rail { --fit: .14; }
.rail .slide { margin: 0; border: 0; border-radius: 0; pointer-events: none; }
/* Dropped from the deck: greyed rather than hidden, on the rail and on the page,
   because a slide nobody can see is a slide nobody can put back. Presentation
   mode is where it is actually absent. */
.rail li.skipped, .slide.skipped { opacity: .38; }
.slide.skipped { filter: grayscale(1); }
/* Too much content for a fixed canvas, said where the author is rather than
   where the room is. The mark is on the rail and on the sheet in the editor's
   preview; it is deliberately NOT drawn in presentation mode, where it would be
   furniture on a wall, and not in print, which spills honestly instead. */
.rail li.spills::after, .sized .slide.spills::after {
  content: "does not fit"; position: absolute; z-index: 2;
  bottom: 0; right: 0; font-size: 10px; line-height: 1; padding: 3px 5px;
  background: var(--paper-warn); color: var(--paper);
  border-top-left-radius: 4px;
}
.sized .slide.spills { position: relative; }
.sized .slide.spills::after { font-size: 12px; }

/* --- Presenting ---------------------------------------------------------- *
   One slide, filling the screen, and the app gone from around it. A class on
   the root rather than a separate page: the deck is already the document, and a
   second route rendering the same slides would be the second copy this file
   argues against on every other line. */
:root.presenting body > nav, :root.presenting .deckbar,
:root.presenting .rail, :root.presenting #unreadable,
:root.presenting body > a.skip { display: none !important; }
:root.presenting, :root.presenting body { background: #000; overflow: hidden; }
:root.presenting #main { margin: 0; padding: 0; max-width: none; }
:root.presenting .slide { display: none; }
:root.presenting .slide.showing {
  display: block; position: fixed; inset: 0; margin: auto;
  /* The transform, not `zoom`, because there is no flow left to preserve here
     and a transform composites on the GPU — which is what keeps a 1280x720 sheet
     of text sharp when it is thrown at a 4K projector. */
  zoom: 1; transform: scale(var(--show, 1)); transform-origin: center center;
  border: 0; border-radius: 0;
}
/* Where the presenter is in the deck, small and in the corner, in the app's ink
   rather than the paper's — it is furniture ON the projection and not part of
   the slide, and it is the one thing in this mode that is not the document. */
.presenting #counter { display: block; }
#counter {
  display: none; position: fixed; right: .75rem; bottom: .6rem; z-index: 5;
  font-family: var(--font-mono); font-size: 12px; color: #7c8b90;
}

@page { size: A4 landscape; margin: 12mm; }
@media print {
  /* Paper, whatever the reader chose to look at the app in. `color-scheme` is
     what paints the canvas under everything the stylesheet draws, so a deck
     printed from the dark theme came out as white slides on a black page — a
     cartridge of toner per handout, and the margins of every sheet solid black.
     Both selectors, because `:root[data-theme="dark"]` is (0,1,1) and a bare
     `:root` at (0,1,0) loses to it however late it is inlined; the second one
     matches that weight and wins on order. */
  :root, :root[data-theme="dark"] { color-scheme: light; }
  /* The app is not part of the deck. `nav` and the banner are drawn by the shell
     on every page and belong on a screen, not in a handout. */
  nav, .skip, .deckbar, #unreadable { display: none !important; }
  #main { margin: 0; padding: 0; }
  html, body { background: var(--paper); color: var(--paper-ink); }
  /* The fixed canvas is a screen and a projector decision, and print is neither.
     `.sized .slide` is (0,2,0) and would otherwise carry 1280x720 and its clip
     onto paper — a page holding one shrunken card in its top-left corner, and a
     slide whose last two points had been cut away rather than spilled. Paper has
     a second sheet, so on paper the old bargain still holds and is still the
     right one: it spills, honestly. Both selectors carry the reset so the weight
     matches whichever of the two is switched on. */
  .sized .slide, .slide {
    width: auto; height: auto; zoom: 1; overflow: visible;
    max-width: none; margin: 0; padding: 0; border: 0; border-radius: 0;
    min-height: 0;
    /* One slide, one page. `break-inside: avoid` is a request and not a promise:
       a slide with more notes than fits still runs onto a second sheet, which is
       the honest failure — the alternative is clipping, and a deck that silently
       drops the last two points of a slide is worse than one that spills. */
    break-after: page; break-inside: avoid;
  }
  .slide:last-of-type { break-after: auto; }
}
"""


# The deck's own script: the fixed canvas, the rail, presenting, and the live
# refresh a review depends on. One block, because all four read the same list of
# `<article class="slide">` elements and splitting them would mean four walks of
# it that can disagree about what a slide is.
_DECK_SCRIPT = """
<div id="counter"></div>
<script>
(() => {
const NUMBER = {{ d.number|tojson }};
const BASE = {{ base_commit|tojson }};
const MAY_WRITE = {{ may_write|tojson }};
const DETAIL = {{ links.record|tojson }};
const SHEETS = document.getElementById('sheets');
const WRAP = document.querySelector('.deckwrap');
const RAIL = document.getElementById('rail');
const THUMBS = document.getElementById('thumbs');
const PRESENT = document.getElementById('present');
const COUNTER = document.getElementById('counter');
// The slide's own coordinate space. Everything on a slide is laid out against
// these two numbers and the whole box is then scaled, which is what makes the
// editor's preview, the rail's thumbnail and the projector the same drawing.
// Written here and in `_DECK_STYLE`'s `.sized .slide`, which is twice — so the
// stylesheet is the one that decides and this reads it back rather than
// declaring a second copy that could drift.
const SLIDE_W = 1280, SLIDE_H = 720;

const slides = () => [...SHEETS.querySelectorAll('.slide')];

// --- The fixed canvas ---------------------------------------------------
// Switched on here rather than in the stylesheet because the scale is the
// container's width over the slide's, and no stylesheet can divide by a length
// it cannot name. Until this runs the page carries the fluid `min-height` rule,
// which is a complete slide rather than a broken one — the reason it is two
// rules and not one.
function fit() {
  WRAP.classList.add('sized');
  const room = SHEETS.clientWidth;
  if (room > 0) SHEETS.style.setProperty('--fit', String(room / SLIDE_W));
  const rail = THUMBS.clientWidth;
  if (rail > 0) RAIL.style.setProperty('--fit', String(rail / SLIDE_W));
  marked();
  if (presenting()) show(at);
}

// Which slides hold more than fits. Asked of the browser and never of the
// markup: whether 300 words fit in 720px depends on the font, the wrapping and
// the pictures, and the only thing that knows all three is the thing doing the
// layout. `scrollHeight` is the content's height and `clientHeight` the box's,
// so this is the one question that answers it — and it is asked AFTER a fit,
// because both change with the scale.
//
// Marked, not clipped-and-forgotten: the clip is what stops the projector
// drawing a broken sheet, and the mark is what lets the author fix it first.
function marked() {
  for (const slide of slides()) {
    // Read before write, all of them, then write: interleaving them makes every
    // slide after the first re-run layout, which on an eleven-slide deck full of
    // data-URI screenshots is a visible stall.
    slide.dataset.spills = slide.scrollHeight > slide.clientHeight + 1 ? '1' : '';
  }
  for (const slide of slides()) slide.classList.toggle('spills', !!slide.dataset.spills);
  for (const item of THUMBS.children) {
    const of = SHEETS.querySelector(`[data-key="${CSS.escape(item.dataset.key)}"]`);
    item.classList.toggle('spills', !!(of && of.dataset.spills));
  }
}

// --- The rail -----------------------------------------------------------
// Built by cloning the slides beside it. A thumbnail that was rendered
// separately is a second rendering of one slide, and the one nobody would
// notice going stale is the small one nobody reads.
function railed() {
  THUMBS.textContent = '';
  for (const slide of slides()) {
    const item = document.createElement('li');
    item.dataset.key = slide.dataset.key;
    item.dataset.id = slide.dataset.id;
    item.tabIndex = 0;
    // Named for what it is, because a list of eleven scaled pictures announces
    // itself as eleven list items otherwise. The heading is the slide's own.
    const heading = slide.querySelector('h1, h2');
    item.setAttribute('role', 'button');
    item.setAttribute('aria-label',
      `Slide: ${heading ? heading.textContent.trim() : 'untitled'}`
      + (slide.dataset.skip ? ' (not presented)' : ''));
    item.classList.toggle('skipped', !!slide.dataset.skip);
    if (MAY_WRITE && slide.dataset.id !== 'title') item.draggable = true;
    const copy = slide.cloneNode(true);
    copy.removeAttribute('id');
    // `inert` and not merely `pointer-events: none`: the copy holds the same
    // links the sheet does, and without this every one of them is a tab stop
    // that goes nowhere, eleven times over. A rail of thumbnails must cost a
    // keyboard reader one stop each, not one per link on the deck.
    copy.inert = true;
    item.append(copy);
    THUMBS.append(item);
  }
  RAIL.hidden = false;
  fit();
}

// Where the reader is, so the rail says it. Scroll position and not a click:
// the sheets are the page and somebody scrolling them is navigating.
const spy = new IntersectionObserver(entries => {
  for (const entry of entries) {
    if (!entry.isIntersecting) continue;
    const key = entry.target.dataset.key;
    for (const item of THUMBS.children)
      item.setAttribute('aria-current', String(item.dataset.key === key));
  }
}, {rootMargin: '-45% 0px -45% 0px'});

function watch() { for (const slide of slides()) spy.observe(slide); }

// --- Reordering ---------------------------------------------------------
// Hand-rolled, and the audit that says why is in the commit: the gesture is one
// dimension, in one container, with no nesting and no cross-container drop —
// none of the properties that made the graph's refile a library's job. What a
// library would not have brought is the keyboard path below, which the quality
// floor requires and which SortableJS does not ship.
let held = null;

function order() {
  return [...THUMBS.children].map(item => item.dataset.id).filter(id => id !== 'title');
}

async function save() {
  // Deduplicated, because a record with `\\newslide` has more than one thumbnail
  // and the stored order is a list of RECORDS. Two entries for one id would come
  // back from `_deck_order` as one slide drawn and one id ignored, which is a
  // deck that quietly disagrees with the rail that saved it.
  const ids = [...new Set(order())];
  const answer = await fetch('/api/cycle/' + NUMBER, {
    method: 'PUT',
    headers: {'content-type': 'application/json'},
    body: JSON.stringify({base_commit: BASE, fields: {deck_order: ids}}),
  });
  if (!answer.ok) {
    // Said out loud rather than swallowed. A drag that appeared to work and did
    // not is the failure a presenter finds in front of the room.
    announce('That order could not be saved. Reload and try again.');
    return;
  }
  announce(`Slide order saved, ${ids.length} slides.`);
}

function announce(said) {
  const live = document.getElementById('said');
  if (live) live.textContent = said;
}

THUMBS.addEventListener('dragstart', event => {
  const item = event.target.closest('li');
  if (!item) return;
  held = item;
  item.classList.add('dragging');
  event.dataTransfer.effectAllowed = 'move';
  // Firefox refuses to start a drag at all without data on the transfer.
  event.dataTransfer.setData('text/plain', item.dataset.id);
});

THUMBS.addEventListener('dragover', event => {
  if (!held) return;
  event.preventDefault();
  const over = event.target.closest('li');
  if (!over || over === held) return;
  // Which half of the row the pointer is in decides which side of it the held
  // slide lands on. Without the midpoint the row flickers between two positions
  // whenever the pointer sits near a boundary, because every move re-inserts.
  const box = over.getBoundingClientRect();
  const after = event.clientY > box.top + box.height / 2;
  // The title slide is not orderable and is always first, so nothing may be
  // dropped in front of it.
  if (!after && over.dataset.id === 'title') return;
  THUMBS.insertBefore(held, after ? over.nextSibling : over);
});

THUMBS.addEventListener('dragend', () => {
  if (!held) return;
  held.classList.remove('dragging');
  held = null;
  redraw();
  save();
});

// The keyboard path. Alt with an arrow, because the bare arrows move focus
// between thumbnails and a reader must be able to look before they move
// anything. Enter opens the slide's editor, which is what a double-click does
// with a pointer.
THUMBS.addEventListener('keydown', event => {
  const item = event.target.closest('li');
  if (!item) return;
  if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault();
    open(item);
    return;
  }
  const step = event.key === 'ArrowUp' ? -1 : event.key === 'ArrowDown' ? 1 : 0;
  if (!step) return;
  event.preventDefault();
  const rows = [...THUMBS.children];
  const from = rows.indexOf(item);
  const to = from + step;
  if (to < 0 || to >= rows.length) return;
  if (!event.altKey) { rows[to].focus(); return; }
  if (!MAY_WRITE || item.dataset.id === 'title' || rows[to].dataset.id === 'title') return;
  THUMBS.insertBefore(item, step < 0 ? rows[to] : rows[to].nextSibling);
  item.focus();
  redraw();
  save();
});

// The sheets follow the rail. Reordering the thumbnails and leaving the page
// below them in the old order would be two answers to one question on one
// screen — and the sheets are the ones that get presented.
function redraw() {
  for (const item of THUMBS.children) {
    const slide = SHEETS.querySelector(`[data-key="${CSS.escape(item.dataset.key)}"]`);
    if (slide) SHEETS.append(slide);
  }
}

function open(item) {
  if (item.dataset.id === 'title' || item.dataset.id === 'empty') return;
  location.href = DETAIL + item.dataset.id + '?view=slide';
}

THUMBS.addEventListener('dblclick', event => {
  const item = event.target.closest('li');
  if (item) open(item);
});

// A single click is navigation, which is what a rail is mostly for.
THUMBS.addEventListener('click', event => {
  const item = event.target.closest('li');
  if (!item) return;
  const slide = SHEETS.querySelector(`[data-key="${CSS.escape(item.dataset.key)}"]`);
  if (slide) slide.scrollIntoView({block: 'center'});
});

// --- Presenting ---------------------------------------------------------
// The slides that are actually presented: everything the author did not drop.
// Read fresh each time rather than held in a variable, because the live refresh
// below replaces the sheets under it.
const shown = () => slides().filter(slide => !slide.dataset.skip);
let at = 0;

function show(to) {
  const on = shown();
  if (!on.length) return;
  at = Math.max(0, Math.min(on.length - 1, to));
  // Scaled to whichever of the two dimensions runs out first, so the whole
  // slide is on the wall whatever shape the projector is. `min`, never a fit to
  // width alone: a 4:3 projector would have cut the bottom off every sheet.
  const scale = Math.min(innerWidth / SLIDE_W, innerHeight / SLIDE_H);
  for (const slide of slides()) slide.classList.remove('showing');
  on[at].classList.add('showing');
  on[at].style.setProperty('--show', String(scale));
  COUNTER.textContent = `${at + 1} / ${on.length}`;
}

function present(on) {
  document.documentElement.classList.toggle('presenting', on);
  PRESENT.setAttribute('aria-pressed', String(on));
  if (on) {
    // Requested, never assumed: a browser may refuse full screen (a policy, a
    // gesture it did not count) and the mode has to work anyway — everything
    // above is CSS on the root element, so a refusal costs the browser chrome
    // and nothing else. Swallowed for the same reason: there is nothing a
    // presenter can do about it and a red line in the console is not news.
    document.documentElement.requestFullscreen?.().catch(() => {});
    show(at);
  } else {
    for (const slide of slides()) slide.classList.remove('showing');
    if (document.fullscreenElement) document.exitFullscreen?.().catch(() => {});
  }
}

const presenting = () => document.documentElement.classList.contains('presenting');
PRESENT.hidden = false;
PRESENT.addEventListener('click', () => present(!presenting()));

addEventListener('keydown', event => {
  if (!presenting()) return;
  const key = event.key;
  if (key === 'Escape') { present(false); return; }
  if (key === 'ArrowRight' || key === 'PageDown' || key === ' ' || key === 'Enter') {
    event.preventDefault(); show(at + 1); return;
  }
  if (key === 'ArrowLeft' || key === 'PageUp' || key === 'Backspace') {
    event.preventDefault(); show(at - 1); return;
  }
  if (key === 'Home') { event.preventDefault(); show(0); return; }
  if (key === 'End') { event.preventDefault(); show(shown().length - 1); }
});

// Leaving full screen by the browser's own gesture — F11, Esc on some
// platforms, the window manager — has to leave the mode too. Without this the
// page stays black-on-black with the nav hidden and no way back that looks like
// one, which is the state somebody reports as "the deck broke".
addEventListener('fullscreenchange', () => {
  if (!document.fullscreenElement && presenting()) present(false);
});

// --- The live refresh ---------------------------------------------------
// A record edited while the room is walking the deck has to reach the deck. The
// shell already opens the one `EventSource` this page gets and answers a change
// with a "reload" banner — which is the right answer on every other page and the
// wrong one here: a banner over a projection, and a reload that would drop the
// presenter out of the deck and back to slide one.
//
// So the deck takes the same signal and swaps instead. It re-fetches ITSELF and
// replaces the sheets, which reuses the one renderer rather than adding a second
// one that would have to agree with it.
//
// Keyed by `data-key` and not by position, because the order can move under a
// presenter too — a re-fetch that kept "slide 4" would land them on whatever is
// now fourth rather than on what they were talking about.
let refreshing = false;

async function refresh() {
  if (refreshing) return;
  refreshing = true;
  try {
    const answer = await fetch(location.pathname, {headers: {'accept': 'text/html'}});
    if (!answer.ok) return;
    const fresh = new DOMParser().parseFromString(await answer.text(), 'text/html');
    const box = fresh.getElementById('sheets');
    if (!box) return;
    const key = shown()[at]?.dataset.key;
    SHEETS.replaceChildren(...box.children);
    railed();
    watch();
    // Back to the slide they were on, by name. Gone entirely — the record was
    // deleted or dropped from the cycle mid-review — lands on the nearest slide
    // that still exists rather than on slide one.
    if (presenting()) {
      const on = shown();
      const found = on.findIndex(slide => slide.dataset.key === key);
      show(found >= 0 ? found : at);
    }
  } finally {
    refreshing = false;
  }
}

// Two signals, and the poll is the backbone rather than the comfort. Cloud Run
// recycles the event stream every 300s with no replay, so an event proves a
// change and its absence proves nothing; `/api/health` reports the plan's head
// and is what notices a stream that has quietly gone away. Same argument, and
// the same numbers, as the pile banner in the shell.
let head = null;
const POLL_MS = 60000;

async function asked() {
  try {
    const health = await (await fetch('/api/health')).json();
    if (head !== null && health.head !== head) await refresh();
    head = health.head;
  } catch { /* offline for a moment is not news on this page */ }
}

addEventListener('openproj:landed', () => { asked(); });
// The shell's EventSource dispatches nothing for an ordinary plan change, so
// this page listens for the change the shell's own banner reacts to by watching
// the head instead. Cheap: one small JSON body a minute, and the deck is the
// heaviest page here — re-fetching it on a timer that knows nothing has changed
// would be megabytes of data-URI screenshots for nothing.
setInterval(asked, POLL_MS);
asked();

// --- Go -----------------------------------------------------------------
railed();
watch();
addEventListener('resize', fit);
// Fonts land after the first layout and change every wrap on the page, so a
// `spills` mark computed before they arrive is computed against the wrong
// drawing. The one thing on this page that is measured has to be measured after
// the thing it measures has stopped moving.
document.fonts?.ready.then(fit);
})();
</script>
"""


# The section of the team's own task template that is about what HAPPENED. It is
# the one heading a review is written under, so it is the one heading the deck
# keeps out of the set below rather than dropping with the rest of the template.
# Its checklist is already lifted to the points at the top of the slide; what is
# left under it is the sentence somebody wrote about how the week went.
_REVIEW_HEADINGS = frozenset({"progress"})

# The plan, and therefore the only part of the bet a review can be measured
# against: Problem is why, Appetite is how long, Rabbit holes and No-gos are the
# edges. Solution is what was going to be done, which is the question the room
# is in fact asking. Read out when the record says nothing else.
_PLAN_HEADINGS = frozenset({"solution"})

# How much of a sheet the plan may take when it is standing in for a review
# nobody wrote. Measured rather than guessed, with Chrome `--print-to-pdf` at the
# A4 landscape this stylesheet asks for: a slide carrying six points and two pull
# requests crosses onto a second sheet between 201 and 211 rendered words, and
# one carrying neither holds more than 300. 120 leaves the rest of the sheet to
# the points and the pull requests, which are the record's own report of the
# cycle and outrank a quotation of what was going to happen.
#
# Bounded here and deliberately nowhere else. What somebody wrote under
# `## Progress` is their report and the words they are about to say, so all of it
# prints and `@media print` already says what happens if it does not fit — it
# spills, honestly, because clipping a person's own report is the worse failure.
# The Solution is not that. It was written for the betting table, and the deck is
# quoting it only because the record said nothing else; a quotation has no
# business pushing the presenter's slide onto a second sheet.
_PLAN_WORDS = 120

# Where one sentence ends and the next begins, with the gap captured so the text
# goes back together exactly as it was written. Cutting on a word instead lands
# inside `[the driver](assets/0123…)` or a pair of backticks often enough to
# matter, and a slide printing broken markdown is a worse lie than one that runs
# long; rejoining a list's items with a plain space would silently make them a
# paragraph.
_SENTENCE = re.compile(r"(?<=[.!?])(\s+)")

# The one line on a slide that is about the slide rather than about the work.
# Both are on the SHEET and not merely in the app: the sheet is what leaves the
# room, and a slide that quietly printed half a section, or nothing at all, is a
# lie nobody in the room is in a position to catch.
_PLAN_CUT = "Cut to fit the sheet — the rest of the plan is on the record."
_NOTHING_SAID = "Nothing is written on this record."


@lru_cache(maxsize=1)
def _bet_headings() -> frozenset[str]:
    """The sections that argue for the work, read out of the templates.

    Read and not listed, so a section added to `TEMPLATES` reaches this on the
    commit that adds it. A list written down by hand is a list that goes stale,
    and going stale here means the deck putting a whole shaping argument on a
    slide again.

    Minus the review headings, which are in the template too and are the exact
    thing a review slide is for. Subtracting them here rather than at the call
    site is what keeps "which sections are the bet" one answer: `_review_html`
    asks for what is not the bet, and the fallback asks for one section of it.
    """
    every = frozenset(name for body in TEMPLATES.values() for name in sections(body))
    return every - _REVIEW_HEADINGS


def _to_fit(text: str, budget: int) -> tuple[str, bool]:
    """As much of `text` as `budget` words buys, and whether any was left behind.

    Cut between blocks, and inside a block too long to fit on its own between
    sentences — the two boundaries markdown survives being cut on. The first
    block goes in whatever it costs, because it is the section's own heading and
    a heading with the paragraph under it cut away is the blank slide again.

    So this is a bound and not a limit: the last block admitted may run over it.
    That is the trade. A hard cut at the 120th word is a cut inside whatever the
    120th word was part of, and a link sawn in half prints as its own source.
    """
    blocks = [block for block in text.split("\n\n") if block.strip()]
    kept: list[str] = []
    spent = 0
    for block in blocks:
        if kept and spent >= budget:
            break
        words = len(block.split())
        if not kept or spent + words <= budget:
            kept.append(block)
            spent += words
            continue
        # sentence, gap, sentence, gap, … so every gap goes back where it was.
        pieces = _SENTENCE.split(block)
        said = ""
        for at in range(0, len(pieces), 2):
            count = len(pieces[at].split())
            if said and spent + count > budget:
                break
            said += (pieces[at - 1] if said else "") + pieces[at]
            spent += count
        kept.append(said)
        break
    return "\n\n".join(kept), spent < sum(len(block.split()) for block in blocks)


def _said(record: Record) -> str:
    """The record's document, minus what the slide draws for itself.

    Lifted out of `_review` when the slide editor needed the same text to build
    its checkboxes from: the list of sections somebody may tick has to be the
    list of sections the slide can actually draw, and two walks of one body is
    two answers that agree until a heading is emptied by one of them and not the
    other.

    Comments are stripped BEFORE the emptied-heading prune inside
    `without_checklist`, or a `## Solution` holding nothing but the template's
    own guidance survives as a heading over a blank.
    """
    return without_checklist(without_comments(_drop_repeated_title(record.body, record.title)))


def choosable(record: Record) -> list[tuple[str, bool]]:
    """Every section of this record a slide may draw, and whether it is the bet.

    What the slide editor puts a checkbox beside, in the order the body writes
    them — which is the order the author is reading while they tick. Read off
    the record rather than off anything stored, so a section added after the
    slide was last saved is offered the next time somebody opens the editor.
    That reconciliation happens on OPEN and writes nothing: a GET that commits
    would fire for every reader of the page and 403 the ones who may not write.

    The flag is what the editor uses to seed a record nobody has personalised —
    a bet section starts unticked, everything else starts ticked, which is
    exactly the slide the deck draws today. It is not used for a record that HAS
    been personalised: there, jcanton's rule holds and a newly-discovered section
    arrives unticked whatever it is.
    """
    bet = _bet_headings()
    return [
        (name, name in bet)
        for name, text in sections(_said(record)).items()
        if text.strip()
    ]


def _seeded(record: Record) -> Slide:
    """The slide settings that reproduce what the deck draws for an unpersonalised record.

    The one place the generated deck and the editor's opening state are the same
    answer. Without it the editor would have had to restate "everything except
    the bet" in checkbox form, and the two would drift the first time
    `_bet_headings` moved — which it does automatically, off `TEMPLATES`.
    """
    return Slide(sections=[name for name, is_bet in choosable(record) if not is_bet])


def _resolved(record: Record) -> tuple[Slide, bool]:
    """This record's slide settings, and whether a person chose them.

    The second value is the whole reason this returns a pair. A chosen slide is
    final: an author who ticked nothing meant nothing, and the fallback chain
    below must not put the shaping argument back on a sheet they deliberately
    cleared. An inferred one is the floor somebody edits up from, and it keeps
    every fallback it has always had.
    """
    if record.slide is not None:
        return record.slide, True
    return _seeded(record), False


def _review(
    record: Record, slide: Slide, chosen: bool, links: Links, assets: dict[str, str]
) -> tuple[Markup, str]:
    """What the slide says under its points: what happened, and never nothing.

    The team stands up and says how the work went, so the slide is built out of
    the record in the order a person would say it: the title, the points with
    their ticks, the pull requests, and then whatever the document says that the
    room has not already heard.

    **Not the shaping argument.** Problem, Appetite, Solution, Rabbit holes,
    No-gos were written before the work started, to win the bet at the betting
    table, and everybody in the room argued them there. Printed on a slide they
    are two pages of 11px prose nobody can read from the third row, and three of
    seven slides ran onto a second sheet.

    **Not the checklist**, because the slide lifts those points to the top and
    ticks them; left here as well they print twice. The detail page avoids that
    duplication by not lifting a leaf's checklist at all (`_progress_view`), and
    a deck cannot make that trade — `[x]` read from the back of a room is not a
    tick.

    **But never nothing.** Selecting by *taking the template away* was upside
    down: a well-shaped record IS the template, so the sections it names were the
    whole document and five of the seven slides in the demo's own cycle 37 came
    out as a heading, a chip, a size, an owner and an id over blank paper. A deck
    of blank paper is worse than a deck that says too much, because there is
    nothing on the sheet to talk from. So when a record kept no notes, the slide
    falls back to its Solution: the plan, in the team's own words, which is what
    the presenter is about to say happened or did not. It carries its own heading
    so that nobody mistakes the plan for a report of it — bounded, because a
    fallback that re-admits the overflow re-admits the thing a deck must not do.

    **And it says which of those it did.** The second return is the line printed
    under the document: that the plan was cut and where the rest is, or that the
    record has nothing written on it at all. A slide that silently drops half a
    section, or that comes out blank because there was nothing to draw, looks
    exactly like a slide that is finished — and the person holding the sheet is
    the one person who cannot go and check.
    """
    said = _said(record)
    # The chosen sections in BODY order, not in the order the list happens to be
    # stored in — `only_sections` walks the document once and keeps what matches.
    # The author ticked boxes down a list that was itself in body order, so this
    # is the order they were looking at; `Slide.sections` says the same thing on
    # the field.
    #
    # Pruned again after the drop, because dropping a section is the other way to
    # empty a heading and `without_checklist` has already run by then: a
    # `## Notes` whose only content was a `### Solution` under it was left as
    # `<h2>Notes</h2>` over nothing, which is truthy enough to suppress the
    # fallback below.
    picked = without_emptied_headings(only_sections(said, slide.sections))
    opening = lead_text(said) if slide.lead else ""
    happened = "\n\n".join(part for part in (opening, picked) if part)
    if happened:
        return _markdown(happened, links, assets), ""
    # **A chosen slide is final.** Everything below is the floor a GENERATED
    # slide falls back to, and putting it under a personalised one would undo the
    # personalisation: an author who cleared every box meant the sheet to be the
    # heading and the chips, and a deck that answered by printing the shaping
    # argument they had just removed would be arguing with them in front of the
    # room. `chosen` is the whole reason `_resolved` returns a pair.
    if chosen:
        return Markup(""), ""
    plan, cut = _to_fit(only_sections(said, _PLAN_HEADINGS), _PLAN_WORDS)
    if plan:
        return _markdown(plan, links, assets), _PLAN_CUT if cut else ""
    # `checklist_items` and not a second reading of the same lines: the points at
    # the top of the slide are this exact call, so the sentence and the sheet
    # cannot disagree about whether anything up there has words on it. A box with
    # nothing beside it is what the empty template ships and is not something a
    # person can stand up and read out.
    if any(text for _, text in checklist_items(record.body)):
        return Markup(""), ""
    return Markup(""), _NOTHING_SAID


def slides_of(index: Index, record: Record, links: Links, assets: dict[str, str]) -> list[dict]:
    """One record, as the slides somebody would have typed out of it.

    A list and not one slide, because `\\newslide` in the author's own prose
    opens another — jcanton, 2026-08-25. The first carries everything the record
    contributes (the chips, the points, the pull requests, the chosen sections)
    and the first chunk of prose; each continuation after it carries the next
    chunk under the same title, numbered from `(2)`. Never empty: a record with
    no prose at all is one chunk, which is one slide, so no caller has to ask.

    Every number is read from where the site already keeps it: the tick and the
    percentage from `index.progress`, which counted them once for the table, the
    detail page and this; the links from `_pr_link`, which is what makes a
    reference in a fact row a link somebody can follow.

    Public, unlike the `_slide` it replaces, because the slide editor's preview
    pane draws the same slides from a record that has not been saved yet. One
    builder, so what the author is shown and what the room is shown cannot
    disagree — which is the whole reason this tool exists.
    """
    counted = index.progress.get(record.id)
    size, defaulted = size_weeks(record, Config(default_task_effort=index.default_task_effort))
    bet = bet_of(record, index.plan)
    slide, chosen = _resolved(record)
    body, note = _review(record, slide, chosen, links, assets)
    chunks = slide_chunks(slide.body)
    facts = {
        "id": record.id,
        # The `[GT4Py]` of the real deck. Blank where this record IS the bet —
        # an orphan chore, or a pitch nobody has broken into tasks — because a
        # bracket repeating the heading under it is furniture.
        "under": bet.title if bet is not None and bet.id != record.id else "",
        "status": record.status,
        "status_class": _status_class(record.status),
        # The two channels that are not colour, which is what a slide has to
        # carry: `_DECK_STYLE` flattens every chip to an outline on purpose,
        # because the five status fills are a luminance ladder measured against
        # the APP's ground and came out as solid dark pills on white under the
        # dark theme. A glyph and a block survive a projector, a photocopier and
        # deuteranopia, and they are the same marks the table draws — jcanton,
        # 2026-08-25, on the deck's chips being outdated: same vocabulary,
        # measured against paper.
        "glyph": STATUS_GLYPH.get(record.status, ""),
        "priority": record.priority,
        "priority_class": _priority_class(record.priority),
        "priority_glyph": PRIORITY_GLYPH.get(str(record.priority), ""),
        "people": ", ".join(_people_on(record)),
        "size": f"{size:g}" + ("*" if defaulted else ""),
        # `counted.text` and `counted.fraction`, not a division written here: the
        # panel on the detail page and the meter in the table read the same two,
        # and a third arithmetic is a third answer.
        "text": counted.text if counted is not None else "",
        "percent": round(100 * counted.fraction) if counted is not None else 0,
        "skip": slide.skip,
    }
    return [
        {
            **facts,
            "at": at,
            "title": slide_title(record.title, at),
            # The record's own contribution goes on the FIRST slide only.
            # Repeating the points and the pull requests under every
            # continuation would put the same five ticks on the screen three
            # times, which is the duplication `without_checklist` exists to
            # stop, arriving through a different door.
            "lead": at == 0,
            "points": [
                {"done": done, "text": _markdown_line(said, links, assets)}
                for done, said in checklist_items(record.body)
            ] if at == 0 and slide.progress else [],
            "prs": [_pr_link(ref) for ref in record.prs] if at == 0 and slide.prs else [],
            "body": body if at == 0 else Markup(""),
            "extra": _markdown(chunk, links, assets) if chunk else Markup(""),
            "note": note if at == 0 else "",
        }
        for at, chunk in enumerate(chunks)
    ]


def _deck_order(records: list[Record], listed: list[str]) -> list[Record]:
    """The cycle's records in the order somebody dragged them into, then the rest.

    Both halves matter and the second is the one worth the function. A stored
    order is a photograph of a moment: a record bet into the cycle after it was
    taken is in none of it, and an id left in it by a record that has since moved
    out points at nothing. Neither is a fault — somebody re-bets while a deck tab
    is open — and both are handled by construction rather than by validating the
    list, so there is no state in which a slide silently leaves the deck.

    An id that names a record twice is taken once. The rail deduplicates before
    it saves, so this only sees a hand-edited file — where the honest reading of
    a repeated id is that somebody meant that record, once.

    The default order — bet, then title — is what the caller sorted by, and it is
    what the trailing records keep. A cycle nobody has ordered is therefore
    exactly the deck it was before this field existed.
    """
    by_id = {record.id: record for record in records}
    seen: set[str] = set()
    first = [
        by_id[one] for one in listed
        if one in by_id and not (one in seen or seen.add(one))
    ]
    return first + [record for record in records if record.id not in seen]


def _deck_view(
    index: Index,
    number: int,
    links: Links,
    asset: Callable[[str], bytes | None] | None = None,
) -> dict:
    """The title slide, then one slide per piece of work in the cycle.

    **Leaves only.** A pitch with tasks under it is a rollup — its progress IS
    those tasks and its people are their people — so giving it a slide of its own
    puts the same work on the screen twice, once as a summary nobody can act on
    and then again five slides later. It is the same exclusion `Index.load` makes
    when it adds up who is full, and for the same reason. A pitch nobody has
    broken up is a leaf and gets its slide.

    **Everything bet into the cycle, whatever its status.** A review is about what
    happened, so `done` is the most interesting thing on it and `shelved` is a
    decision the room took and will be asked about. `counts_in` is the wrong
    question here: it drops both, because it exists to add up weeks still to be
    spent.

    Ordered by the bet, so the four slides that are all one pitch are four
    consecutive slides — which is what the bracket in the real deck's titles was
    doing by hand.
    """
    plan = index.plans.get(number)
    # `_proposed` and not a second reading of the record: the cycle page resolves
    # an unwritten cycle to what Save would write, and a deck naming a review date
    # the cycle page disagrees with is the same fact in two places again.
    proposed = plan or _proposed(index, number, index.cycles.get(number))

    def order(pair: tuple[str, Record]) -> tuple[str, str, str]:
        record_id, record = pair
        bet = bet_of(record, index.plan)
        return (bet.title.casefold(), bet.id, record_id) if bet else ("", "", record_id)

    chosen = _deck_order(
        [
            record
            for record_id, record in sorted(index.plan.items(), key=order)
            if cycle_of(record, index.plan) == number and not index.children.get(record_id)
        ],
        plan.deck_order if plan else [],
    )
    # Only the documents this deck actually draws. Reading every asset in the plan
    # would put a screenshot from cycle 30 inside a deck for cycle 37, and a deck
    # is already the heaviest page here.
    #
    # The slides' own prose is in `assets`' reach too: a figure somebody embedded
    # in the slide editor lives in the same `assets/` directory as one embedded in
    # a record, and a deck that inlined the second and linked the first would lose
    # half its pictures the moment it was saved and sent on.
    bodies = (
        [record.body for record in chosen]
        + [record.slide.body for record in chosen if record.slide is not None]
        + ([plan.body] if plan else [])
    )
    assets = _inlined_assets(bodies, asset) if asset else {}
    slides = [one for record in chosen for one in slides_of(index, record, links, assets)]
    return {
        "number": number,
        "reviews_on": proposed.reviews_on.isoformat() if proposed.reviews_on else "",
        "assumed_review": proposed.assumed_review,
        # The FIELD, not the body — the same as the cycle page reads
        # (`cycles.py`, `"goal": plan.goal`), and as text rather than markdown
        # for the reason written there: a sentence the room agreed on does not
        # want a heading level.
        #
        # This drew `plan.body` and called it the goal. `Cycle.goal` exists
        # precisely so the two are different documents — `model.py` on the
        # field: "What the cycle is FOR ... a field rather than the first line
        # of the body ... Sharing one box meant the goal was whatever happened
        # to be at the top of a growing document." The deck was the one page
        # that never got the field.
        #
        # It was invisible because the corpus hid it: the seed's cycle record had
        # no `goal:` key and a 26-word body that WAS the goal, so reading the
        # body returned the right sentence. The moment the corpus grew a real
        # `goal:` and a body of betting-table notes, the title slide carried 477
        # words against the ~206-word cliff `_to_fit` measures, and an
        # eleven-slide deck printed on twelve sheets.
        "goal": plan.goal if plan else "",
        "slides": slides,
    }


def render_deck(
    index: Index,
    number: int,
    links: Links = ROUTES,
    asset: Callable[[str], bytes | None] | None = None,
    base_commit: str | None = None,
    may_write: bool = False,
) -> str:
    """One cycle's review deck: a page that prints one slide to a page.

    A page and not an export. The export writes one file per view of the whole
    plan and takes no arguments; a deck is of ONE cycle, and the number has to
    come from somewhere. It is also the page most likely to be saved and sent on,
    which is why `asset` is here: every screenshot in it travels inside the file
    as a `data:` URI, so a deck opened from a download folder still has its
    pictures. Everything else it needs — the policy, the typeface, the tokens —
    the shell already inlines into every page.

    `asset` reads the bytes for one asset name. Optional, because the one caller
    that has no repository to read from — the test that renders every entry point
    — must still get a page rather than a TypeError, and a deck with a picture
    drawn as a path is a worse deck rather than a broken one.

    `base_commit` and `may_write` are what the rail needs to SAVE an order, and
    they are separate for the reason the detail page keeps them separate: a
    reader still wants the rail, because it is how you find slide nine of eleven,
    and offering them a drag whose every drop is a 403 is a control that is a
    refusal in disguise. Both default to the read-only answer so that the static
    export and the render-every-entry-point test get a deck rather than a
    TypeError, the same bargain `asset` already makes.
    """
    view = _deck_view(index, number, links, asset)
    return _page(
        f"openproj — cycle {number} review",
        _compiled(_DECK + _DECK_SCRIPT).render(
            d=view,
            links=links,
            base_commit=base_commit or "",
            # Both, and not `may_write` alone. The rail's Save needs a commit to
            # compare against, and a page rendered without one has nothing to
            # send — so a drag would appear to work and then 422. The two facts
            # are separate on the way in and one answer here.
            may_write=bool(may_write and base_commit),
        ),
        _DETAIL_STYLE + _DECK_STYLE,
        links,
        # A deck is of a cycle, and the Cycles listing is the listing of cycles.
        # Same reasoning as `/cycle/<n>`: the item that got you here stays lit.
        "cycles",
        index.unreadable,
    )
