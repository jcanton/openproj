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
    bet_of,
    checklist_items,
    cycle_of,
    only_sections,
    sections,
    size_weeks,
    without_checklist,
    without_comments,
    without_emptied_headings,
    without_sections,
)
from .cycles import _proposed
from .env import _compiled
from .markdown import _drop_repeated_title, _inlined_assets, _markdown, _markdown_line, _pr_link
from .shell import ROUTES, Links, _page
from .styles import _DETAIL_STYLE
from .tokens import TEMPLATES, _status_class

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
    printed to reach the people who were not in the room, and a back link is not
    part of it. -#}
<p class="back deckbar"><a href="{{ links.cycle }}{{ d.number }}">← cycle {{ d.number }}</a></p>

<article class="slide title">
  <h1>Cycle {{ d.number }}</h1>
  <p class="lead">Review</p>
  <p class="when">{% if d.reviews_on %}{{ d.reviews_on }}{% if d.assumed_review %}
    <span class="assumed">— assumed: this cycle names no review meeting</span>
    {% endif %}{% else %}No review meeting recorded{% endif %}</p>
  {#- The goal, because a review opens by saying what the cycle was for and the
      team already wrote that down on the cycle record. The real deck's title
      slide is bare only because its goal lived in a different tool. -#}
  {% if d.goal %}<div class="doc goal">{{ d.goal }}</div>{% endif %}
</article>

{% for s in d.slides %}
<article class="slide">
  {#- The bracket first and smaller, exactly as `[GT4Py] Features` reads: what
      this belongs to, then what it is. Omitted where the work IS the bet, since
      a bracket repeating the line under it says nothing. -#}
  {% if s.under %}<p class="under">{{ s.under }}</p>{% endif %}
  <h2>{{ s.title }}</h2>
  <p class="who">
    <span class="chip {{ s.status_class }}">{{ s.status|human }}</span>
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
      aria-hidden="true">{{ '☑' if point.done else '☐' }}</span>{{ point.text }}</li>
    {% endfor %}
  </ul>
  {% endif %}

  {% if s.prs %}
  <ul class="prs">{% for pr in s.prs %}<li>{{ pr }}</li>{% endfor %}</ul>
  {% endif %}

  {% if s.body %}<div class="doc">{{ s.body }}</div>{% endif %}
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
<article class="slide empty">
  <h2>Nothing is bet into cycle {{ d.number }}</h2>
  <p>A deck is one slide per piece of work in the cycle, and this cycle holds
     none yet. Bet something into it on
     <a href="{{ links.cycle }}{{ d.number }}">the cycle {{ d.number }} page</a>
     and it will have a slide here.</p>
</article>
{% endfor %}
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
  /* A floor and not an aspect-ratio. 16:9 of the width above is about this, so a
     card on screen is the shape of the page it prints on — but a slide whose
     notes run long has to GROW. `aspect-ratio` would have fixed the height and
     let the overflow spill out of the border, drawing a slide that looks
     finished with a paragraph hanging off the bottom of it. */
  min-height: 34rem;
}
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
  .slide {
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


def _review(record: Record, links: Links, assets: dict[str, str]) -> tuple[Markup, str]:
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
    said = without_checklist(without_comments(_drop_repeated_title(record.body, record.title)))
    # Comments are stripped BEFORE the emptied-heading prune inside
    # `without_checklist`, or a `## Solution` holding nothing but the template's
    # own guidance survives as a heading over a blank — which is the same defect
    # in a smaller place.
    #
    # And pruned AGAIN after the bet comes out, because dropping a section is the
    # other way to empty a heading and `without_checklist` has already run by
    # then: a `## Notes` whose only content was a `### Solution` under it was
    # left as `<h2>Notes</h2>` over nothing, which is truthy enough to suppress
    # the fallback below.
    happened = without_emptied_headings(without_sections(said, _bet_headings()))
    if happened:
        return _markdown(happened, links, assets), ""
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


def _slide(index: Index, record: Record, links: Links, assets: dict[str, str]) -> dict:
    """One record, as the slide somebody would have typed out of it.

    Every number is read from where the site already keeps it: the tick and the
    percentage from `index.progress`, which counted them once for the table, the
    detail page and this; the links from `_pr_link`, which is what makes a
    reference in a fact row a link somebody can follow.
    """
    counted = index.progress.get(record.id)
    size, defaulted = size_weeks(record, Config(default_task_effort=index.default_task_effort))
    bet = bet_of(record, index.plan)
    body, note = _review(record, links, assets)
    return {
        "id": record.id,
        "title": record.title,
        # The `[GT4Py]` of the real deck. Blank where this record IS the bet —
        # an orphan chore, or a pitch nobody has broken into tasks — because a
        # bracket repeating the heading under it is furniture.
        "under": bet.title if bet is not None and bet.id != record.id else "",
        "status": record.status,
        "status_class": _status_class(record.status),
        "people": ", ".join(_people_on(record)),
        "size": f"{size:g}" + ("*" if defaulted else ""),
        # `counted.text` and `counted.fraction`, not a division written here: the
        # panel on the detail page and the meter in the table read the same two,
        # and a third arithmetic is a third answer.
        "text": counted.text if counted is not None else "",
        "percent": round(100 * counted.fraction) if counted is not None else 0,
        "points": [
            {"done": done, "text": _markdown_line(said, links, assets)}
            for done, said in checklist_items(record.body)
        ],
        "prs": [_pr_link(ref) for ref in record.prs],
        "body": body,
        "note": note,
    }


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

    chosen = [
        record
        for record_id, record in sorted(index.plan.items(), key=order)
        if cycle_of(record, index.plan) == number and not index.children.get(record_id)
    ]
    # Only the documents this deck actually draws. Reading every asset in the plan
    # would put a screenshot from cycle 30 inside a deck for cycle 37, and a deck
    # is already the heaviest page here.
    bodies = [record.body for record in chosen] + ([plan.body] if plan else [])
    assets = _inlined_assets(bodies, asset) if asset else {}
    slides = [_slide(index, record, links, assets) for record in chosen]
    return {
        "number": number,
        "reviews_on": proposed.reviews_on.isoformat() if proposed.reviews_on else "",
        "assumed_review": proposed.assumed_review,
        "goal": _markdown(without_comments(plan.body), links, assets) if plan else Markup(""),
        "slides": slides,
    }


def render_deck(
    index: Index,
    number: int,
    links: Links = ROUTES,
    asset: Callable[[str], bytes | None] | None = None,
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
    """
    view = _deck_view(index, number, links, asset)
    return _page(
        f"openproj — cycle {number} review",
        _compiled(_DECK).render(d=view, links=links),
        _DETAIL_STYLE + _DECK_STYLE,
        links,
        # A deck is of a cycle, and the Cycles listing is the listing of cycles.
        # Same reasoning as `/cycle/<n>`: the item that got you here stays lit.
        "cycles",
        index.unreadable,
    )
