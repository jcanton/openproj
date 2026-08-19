"""The three static pages: a filterable table, a dependency graph, a timeline.

Each page is one self-contained file. Libraries are inlined from `static/` rather
than linked, so a page works on a train and cannot be broken by a CDN. There is no
build step and no npm; the only JavaScript written here is vanilla.

Filter state lives in the query string. That makes every view a shareable URL,
makes the back button work, and deletes the entire saved-views feature request.

Derived values are drawn differently from stated ones throughout. A date the tool
computed, a size it guessed and work nobody owns are all forecasts, and a forecast
that looks like a commitment is how a timeline stops being believed.
"""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
from collections.abc import Callable, Iterable, Sequence
from datetime import date
from functools import cache, lru_cache
from pathlib import Path
from urllib.parse import quote

from jinja2 import Environment
from markdown_it import MarkdownIt
from markdown_it.renderer import RendererHTML
from markdown_it.rules_core import StateCore
from markdown_it.token import Token
from markupsafe import Markup, escape
from pydantic import BaseModel

from .index import (
    COMPUTED_PREDICATES,
    Index,
    _matches_predicate,
    _people_on,
    _project_of,
    cascade_of,
)
from .model import (
    ISSUE_STATUS,
    NOTE_STATES,
    NOTE_STATUS,
    PARENT_KINDS,
    Config,
    Cycle,
    Entity,
    Issue,
    Note,
    Pitch,
    Project,
    Task,
    Unreadable,
    bet_of,
    checklist,
    checklist_items,
    cycle_of,
    days_after,
    is_bettable,
    only_sections,
    required_at,
    sections,
    size_weeks,
    what_json_can_carry,
    without_checklist,
    without_comments,
    without_emptied_headings,
    without_sections,
)
from .schedule import build_end


def _static_dir() -> Path:
    """Where the vendored JS lives, in a checkout or in a container.

    `parents[2]/static` is right for a source tree and wrong for an installed
    wheel, where it resolves past site-packages to a directory that does not
    exist — and `_inline` is a bare read_text, so the first GET /graph became an
    uncaught FileNotFoundError. Found by building a wheel rather than by reading
    the path. OPENPROJ_STATIC exists so a deployment can say where they are
    instead of hoping.
    """
    candidates = [
        Path(os.environ["OPENPROJ_STATIC"]) if "OPENPROJ_STATIC" in os.environ else None,
        Path(__file__).resolve().parents[2] / "static",
        Path(__file__).resolve().parent / "static",
    ]
    for candidate in candidates:
        if candidate is not None and candidate.is_dir():
            return candidate
    raise RuntimeError(
        "the vendored static/ directory is missing. It is not part of the wheel, so an "
        "installed layout must be told where it is with OPENPROJ_STATIC."
    )

_DAY_PX = 6
_ROW_PX = 22
_LEFT_PX = 250
_PLOT_PX = 1100
# The widest window the plot will draw over. Past the day-width floor below the
# SVG simply gets wider, so a window reaching the end of the calendar — one
# `done` entity dated 9999-12-31, or a `?to=` anybody can type — came out as
# 4.7 million pixels of drawing and 95,686 month ticks, fourteen megabytes that
# is a hung tab rather than a page. Forty years is longer than any plan this
# tool will hold and still twenty screens of scrolling at the default scale;
# bars outside it are dropped the way any bar outside the window is, and the
# page already reports how many it is not showing.
_MAX_PLOT_DAYS = 40 * 366
# The header is two bands, not one. Cycle labels used to be drawn at y=10 and month
# labels at y=18 inside the same 26px strip, so a cycle boundary landing near the
# first of a month wrote one word on top of the other.
_BAND_PX = 18
_HEADER_PX = _BAND_PX + 22
# Room under the last bar, so the today rule's label has somewhere to sit and the
# last row is not flush against the frame. Named because three places have to
# agree on it: the plot's height here, the height the filter script recomputes
# after hiding rows, and the label column beside the plot — which is a separate
# element and would otherwise end 20px short of the bars it names.
_PLOT_FOOT_PX = 20
# A one-day span at the fitted day width is 1.6px of target. Nobody hovers that,
# and nobody clicks it either, so the shortest bar is still a thing you can hit.
_MIN_BAR_PX = 3
# A bar is shorter than its row, so it is centred in it. Drawn at the top of the
# row it sat four pixels above the label naming it, all the way down the chart.
_BAR_PX = 14
_BAR_TOP = (_ROW_PX - _BAR_PX) // 2
# The status glyph sits on a baseline inside the bar, not at its top edge, so the
# server and the filter script both have to place it from the same offset. A 9px
# glyph is about 6.5px of cap height, centred in a 14px bar.
_GLYPH_DY = 10.5
# Narrower than this and the glyph is wider than the bar it names, so it spills
# onto the page — a mark in a status colour sitting on no status colour. A bar
# that short has already lost its fill as a channel too; the tooltip and the label
# beside it are what is left, and both still say the status in words.
_GLYPH_MIN_PX = 11
_LABEL_CHARS = 40
# What the hatching over a bar means, in the words the legend uses for it. The
# hatch is a texture and the outline is a stroke, so neither reaches a reader who
# is not looking at the plot — the row beside it has to say them.
_MARK_WORDS = {"estimated": "appetite assumed", "unowned": "nobody on it"}
# Per level of containment. Enough to read as a step at 11px, small enough that a
# task three deep still has most of the 250px label column to write its name in.
_INDENT_PX = 12


def _clip(text: str) -> str:
    return text if len(text) <= _LABEL_CHARS else text[: _LABEL_CHARS - 1] + "\u2026"
# A status is a class, not a colour baked into the markup: the same rect has to
# be one colour on a white ground and another on a dark one, and a `fill`
# attribute written at render time cannot change when somebody flips the toggle.
#
# It is also the *only* way a status is allowed to reach a class attribute.
# `status` is deliberately a permissive `str` — a file written before a
# vocabulary change has to load and be reported, not take the index down — so it
# holds whatever is in the file. Escaping it would have been enough to stop the
# injection and would still have written `class="chip st-ready&#34; onmouseover"`
# into the page; folding it to a rung of the ladder means an attribute that
# names a rule the stylesheet actually has.
def _status_class(status: str) -> str:
    return f"st-{status}" if status in STATUSES else "st-ready"


def _inline(name: str) -> str:
    return (_static_dir() / name).read_text(encoding="utf-8")


@cache
def _library(name: str) -> Markup:
    """A vendored library, read once, as the markup it is.

    The three graph libraries used to arrive as `@@name@@` markers substituted
    into the *finished* page, which is a substitution over text that by then held
    every title, tag and login in the plan — so an entity titled
    `@@cytoscape.min.js@@` re-inlined 796 KB into the graph's data block and the
    page loaded with no plan at all. A template variable cannot do that: Jinja
    renders a value, it does not rescan it.

    `Markup` because this genuinely is trusted script text — a file shipped in
    `static/`, pinned by `SHA256SUMS`, containing no `</script` (which
    `test_injection` holds it to, because a re-vendoring could change it). Cached
    because every graph page carries 670 KB of it and the read is not free.
    """
    return Markup(_inline(name))


# The two lines of `yjs.bundle.mjs` that are not JavaScript this page can run,
# spelled out so a re-vendoring that changes either fails here rather than
# shipping a page whose only script is a SyntaxError.
_YJS_IMPORT = 'import __Process$ from "/node/process.mjs";'
_YJS_EXPORT = "export{"


@cache
def _yjs() -> Markup:
    """Yjs as a classic script — the one form nobody publishes.

    Every other vendored library here is inlined byte for byte. This one cannot
    be, and it is worth saying exactly why rather than leaving it to look like
    carelessness. Yjs 13.6.32 ships `dist/yjs.mjs` with twenty bare `lib0/*`
    imports; jsDelivr's `+esm` rewrites those to CDN paths, which is precisely
    what `test_no_page_reaches_the_network` exists to catch. The one published
    artifact with lib0 bundled in is esm.sh's `es2020/yjs.bundle.mjs`, and it is
    still a module: it opens with one `import` and closes with one `export{…}`,
    and a page assembled from inlined `<script>` blocks has no module graph to
    hand either to. The bytes in `static/` stay upstream's and stay checksummed;
    those two lines become an IIFE here, and
    `test_the_yjs_bundle_inlines_as_a_classic_script` asserts the result holds no
    `import` and no `export` at all.

    The import is bound to `undefined`, and that is not a stub standing in for
    the real thing — it *is* the real answer. The bundle dereferences
    `__Process$` in one place that is not already guarded, lib0's
    `typeof __Process$ < "u" && __Process$.release && /node|io\\.js/.test(...)`,
    which asks one question: am I running under Node? In a page the answer is no,
    and every other use of the binding sits behind that answer. The design
    costed vendoring esm.sh's `node/process.mjs` beside the bundle; measuring it
    showed it is not a leaf — it imports `node/events.mjs` and `node/tty.mjs`,
    another 12,807 bytes, and joining four modules by rewriting each one's
    imports is a bundler, written here, at render time. Its `release()` returns
    `{}` in any case, so the polyfill answers the same "no" that `undefined`
    does, twenty kilobytes later.
    """
    source = _inline("yjs.bundle.mjs")
    before, found, after = source.partition(_YJS_IMPORT)
    if not found:
        raise ValueError(f"static/yjs.bundle.mjs no longer opens with {_YJS_IMPORT!r}")
    body = f"{before}const __Process$ = undefined;{after}"
    start = body.rindex(_YJS_EXPORT)
    end = body.index("};", start)
    trailing = body[end + 2 :].strip()
    if trailing and not trailing.startswith("//# sourceMappingURL="):
        raise ValueError("static/yjs.bundle.mjs has code after its export clause")
    # `export{a as b}` becomes `{b: a}`, so the names the page uses are upstream's
    # names and a bundle exporting something new needs no edit here.
    exported = []
    for part in body[start + len(_YJS_EXPORT) : end].split(","):
        halves = part.split(" as ")
        exported.append(f"{halves[-1].strip()}:{halves[0].strip()}")
    # `YJS` and not `Y`, which lib0 uses for `Array.from` inside the closure and
    # which a second `const` of on this page would make a SyntaxError for the
    # whole document rather than for one line.
    return Markup(
        f"const YJS = (() => {{\n{body[:start]}\nreturn {{{','.join(exported)}}};\n}})();"
    )


# The three characters that can end a `<script>` block, spelled as JSON escapes.
# A translation table rather than a chain of `str.replace`: same result, and this
# file no longer substitutes anything into text a person could have typed.
_JSON_ESCAPES = str.maketrans({"<": "\\u003c", ">": "\\u003e", "&": "\\u0026"})


def _json(data: object) -> str:
    """JSON for a `<script>` block, with the characters that can end one escaped.

    Every page ships its data inlined, and `json.dumps` leaves `<` alone — so an
    entity titled `</script>...` closed the block it was sitting in and everything
    after it became live markup on the page. `\\u003c` is ordinary JSON: the parser
    reads back the same string, and the character never reaches the HTML tokeniser.

    The double quote is spelled out too. Nothing writes JSON into an attribute
    today, so this is belt and braces — but it costs one pass and it means the
    result carries no character that can end anything it might be put inside.

    U+2028 and U+2029 need no handling here: they are line terminators in
    JavaScript source and legal inside a JSON string, and `json.dumps` escapes
    them already because it escapes everything outside ASCII.

    `allow_nan=False`, which is how a non-finite number gets caught rather than
    written out as `Infinity` — a JavaScript literal that `json.dumps` emits by
    default and `JSON.parse` refuses. Every block on every page is read back
    with `JSON.parse`, so one `effort_weeks: .inf` in one file emptied the table
    and the graph for everybody. Tried first and repaired second because the
    check is inside the C encoder and costs nothing, where the walk is a Python
    pass over the whole payload and no ordinary plan needs it.
    """
    try:
        dumped = json.dumps(data, allow_nan=False)
    except ValueError:
        dumped = json.dumps(what_json_can_carry(data), allow_nan=False)
    # The quote cannot be translated with the other three: the same character
    # both delimits every string in the document and appears inside them as
    # `\\"`, and only the second kind may be respelled. `\\` is the only place a
    # backslash occurs in `json.dumps` output, so walking the escapes tells the
    # two apart exactly — where a blind replace of `\\"` would eat the closing
    # quote of any string ending in a backslash.
    #
    # Guarded, because the walk is a Python loop over the whole payload and most
    # plans contain no quoted title at all: 0.6 ms against 17 for a 400 KB table.
    # If the two characters never occur together there is nothing to respell.
    if '\\"' in dumped:
        out: list[str] = []
        at = 0
        while at < len(dumped):
            if dumped[at] == "\\":
                pair = dumped[at : at + 2]
                out.append("\\u0022" if pair == '\\"' else pair)
                at += 2
                continue
            out.append(dumped[at])
            at += 1
        dumped = "".join(out)
    return dumped.translate(_JSON_ESCAPES)


def _script_json(data: object) -> Markup:
    """`_json`, typed as what it is, for a template to render as a data block.

    Every JSON block on every page is a template variable now. Under autoescaping
    a plain `str` would come out with its structural quotes spelled `&#34;`, and
    a script element is raw text — the entities are not decoded, so `JSON.parse`
    would fail on every page. `Markup` is the honest statement of what `_json`
    guarantees: no `<`, `>`, `&` or bare `"` survives it, so there is nothing
    left for an HTML escaper to do and nothing that can end the block.
    """
    return Markup(_json(data))


def _inline_font(name: str) -> str:
    """A woff2 as a data: URI. Binary, so not _inline's read_text.

    Linked the ordinary way this would be one more thing a CDN, a proxy or a
    train tunnel can take away, and the static export has to work from file://
    where a relative font URL resolves against whatever directory somebody
    dropped the page in. Base64 costs a third more bytes than the file; the
    whole face is 48 KB, and the pages already inline 650 KB of graph library.
    """
    raw = (_static_dir() / name).read_bytes()
    return "data:font/woff2;base64," + base64.b64encode(raw).decode("ascii")


@lru_cache(maxsize=1)
def _font_uri() -> str:
    """Cached, because every served page carries it and the encode is not free."""
    return _inline_font("inter-latin-wght-normal.woff2")


# Three staggered bars: a schedule, which is what this whole application draws.
# Sized on a 16-unit grid because 16px is where a favicon is actually judged, and
# one mid teal rather than the theme's two — the tab strip is painted by the
# browser in a theme this page is not told about, so a colour that survives both
# grounds beats a colour that is right on one of them.
_ICON = (
    "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'>"
    "<rect x='1' y='2' width='10' height='3.2' rx='1.6' fill='#27899e'/>"
    "<rect x='4' y='6.4' width='11' height='3.2' rx='1.6' fill='#27899e'/>"
    "<rect x='2' y='10.8' width='7' height='3.2' rx='1.6' fill='#27899e'/>"
    "</svg>"
)


@lru_cache(maxsize=1)
def _icon_uri() -> str:
    """The mark as a data: URI, so the tab has an icon and nothing is fetched.

    Without a `<link rel="icon">` a browser goes and asks for `/favicon.ico` on
    its own, which is a 404 in the log of every page load — and over `file://`,
    where the static export lives, it is a console error against a path that
    could never exist. An inline SVG answers the question before it is asked.

    A served route would fix the first and not the second, and would be one more
    thing the export has to carry as a separate file. Percent-encoded rather than
    base64 so the source above stays a picture somebody can read and edit.
    """
    return "data:image/svg+xml," + quote(_ICON, safe="")


def _reviewers_under(index: Index, entity_id: str) -> list[str]:
    """`model.reviewers_under`, over the index's own child map.

    The map the validator walks is built from entities and skips shelved ones;
    this one is `index.children`, which is ids. Two shapes of the same fact, so
    the walk is here and the rule is there — and the rule is the one that decides
    whether anything is wrong, which is why this function only draws.

    A `seen` set for the same reason `reviewers_under` has one: a parent cycle is
    a blocker this tool reports rather than a plan it refuses to load, so this map
    really can hold A whose child is B whose child is A — and a walk without it
    never comes back.
    """
    found: list[str] = []
    seen: set[str] = {entity_id}
    stack = list(index.children.get(entity_id, []))
    while stack:
        child = index.entities.get(stack.pop())
        if child is None or child.status == "shelved" or child.id in seen:
            continue
        seen.add(child.id)
        found += child.reviewers
        stack += index.children.get(child.id, [])
    return list(dict.fromkeys(found))


def _row(index: Index, entity_id: str) -> dict:
    entity = index.entities[entity_id]
    span = index.spans.get(entity_id)
    size, defaulted = size_weeks(entity, Config(default_task_effort=index.default_task_effort))
    counted = index.progress.get(entity_id)
    return {
        "id": entity.id,
        "title": entity.title,
        "kind": entity.kind,
        # Not a column — the tree is drawn by the graph and the project facet —
        # and the row needs it anyway, because a row is now something you can
        # drop another one onto. Without it the page cannot tell a move from a
        # gesture that changes nothing, and cannot offer to take a row out of
        # something it is not in.
        "parent": entity.parent,
        "status": entity.status,
        "owner": entity.owner,
        "assignees": entity.assignees,
        "reviewers": entity.reviewers,
        "review_waived": entity.review_waived,
        "priority": entity.priority,
        "cycle": entity.cycle,
        "size": None if defaulted else size,
        "start": span.start.isoformat() if span else None,
        "end": span.end.isoformat() if span else None,
        # Every date on this page was computed. Saying so in the payload keeps the
        # column able to style itself differently from anything a human typed.
        "derived": span is not None,
        "estimated": bool(span and span.estimated),
        "unowned": bool(span and span.unowned),
        "overruns": span.overruns_cycle_weeks if span else None,
        "blocked_by": len(index.blocked_by[entity_id]),
        # Two keys for one fact: the ratio is what a column sorts by, the text is
        # what it prints. Sorting on "7/12" as a string puts 10/12 before 7/12.
        "progress": round(counted.fraction, 4) if counted else None,
        "progress_text": counted.text if counted else "",
        "prs": entity.prs,
        "tags": entity.tags,
        # Who reviews the work filed under this record, when it names nobody
        # itself. A pitch with reviewed tasks under it IS reviewed — the rule in
        # `model.py` says so and stops asking — and this is the same fact drawn
        # rather than enforced. Kept separate from `reviewers` on purpose: that
        # key is what the file holds and what the cell editor starts from, and
        # merging the two would make opening the editor an accidental way to
        # write somebody else's name into this record.
        "reviewers_from": _reviewers_under(index, entity_id) if not entity.reviewers else [],
        # Three fields that are not columns and are not drawn anywhere on this
        # page. They are here because the gate names them: a status the table can
        # set demands them, and a row has to be able to answer whether it already
        # holds one — `size` is the appetite *or the default*, so it cannot
        # answer for `person_weeks`, and the other two are on no row at all.
        "assigned_on": entity.assigned_on.isoformat() if entity.assigned_on else None,
        "person_weeks": getattr(entity, "person_weeks", None),
        "shaped_by": getattr(entity, "shaped_by", None) or [],
        # Not a column, but the control bar offers it: a dropdown whose value the
        # client cannot see is a filter that changes the URL and does nothing.
        "project": _project_of(entity, index.entities),
        "predicates": [p for p in COMPUTED_PREDICATES if _matches_predicate(index, entity_id, p)],
        # What the box searches, built once by `searchable` (`index.py`) and
        # carried rather than rebuilt: the browser used to search
        # `row.title + ' ' + row.tags` while the server searched four fields and
        # every shaping document, so the same query answered differently
        # depending on whether it arrived in a link or through the keyboard.
        # `search` is the key the people, issues and notes rows already use for
        # exactly this, which is why it is spelled that way here.
        "search": index.search_blob[entity_id],
    }


# Columns the table shows that are computed rather than owned, each with what the
# cell answers when somebody tries to edit it. `size` is the least obvious: it
# shows person_weeks *or an assumed default*, so a control on it would let
# somebody commit the assumption without meaning to.
#
# The names and the sentences are one map because they were two: the script
# carried its own literal list of four, so a fifth derived column would have kept
# its editor open and refused with `undefined`. A cell that will not be edited and
# will not say why is indistinguishable from a cell that is broken.
_TABLE_WHY = {
    "size": "Derived from the pitch appetite or the task effort, and from the default "
    "when neither is set.",
    "start": "Derived from assigned_on, from what blocks it, and from what the people "
    "on it are already doing.",
    "end": "Derived from the start and the appetite.",
    "blocked_by": "Counted from depends_on.",
    "progress": "Counted from the task list in the body. Tick the boxes there.",
}
_TABLE_DERIVED = tuple(_TABLE_WHY)

# Every column the table draws, in the order it draws them, and whether it sorts.
# One list rather than three: the header row, the `keys` the cells are built from
# and the width the empty row spans were a Jinja loop and two JavaScript literals
# that had to be edited together, with a comment saying so. Nothing enforced it,
# and index-parallel lists that drift shift every cell one column left. The word
# in each header comes from LABELS, so the column and the facet naming the same
# field cannot be given two different words.
_TABLE_COLUMNS = (
    ("id", True), ("title", True), ("priority", True), ("status", True),
    ("owner", True), ("assignees", True), ("reviewers", True), ("cycle", True),
    ("size", True), ("start", True), ("end", True), ("blocked_by", True),
    ("progress", True), ("prs", False), ("tags", False),
)


def _columns_for(index: Index) -> tuple[tuple[str, bool], ...]:
    """The columns this plan has anything to put in.

    Only `progress` is conditional, and it earns the exception: it is counted out
    of the body rather than stored, so a plan where nobody keeps a checklist would
    carry a permanently empty column across fifteen others — which reads as a
    broken column, not as an unused one. It appears the moment one body has a
    list, and the column that was never there is not a feature anybody has to
    turn off.
    """
    if index.progress:
        return _TABLE_COLUMNS
    return tuple(column for column in _TABLE_COLUMNS if column[0] != "progress")


def _payload(index: Index) -> dict:
    return {
        "rows": {i: _row(index, i) for i in index.entities},
        # No `facets` and no `predicates`: the control bar is server-rendered from
        # `index.facets` and the script reads its own `<select>`s, so both keys
        # were the whole facet index inlined into every table page and read by
        # nothing. Two tests had grown to protect the weight.
        # Flat, exactly as the validator produced them, and grouped by the page.
        # Grouped here as well, the table would have carried two copies of one
        # aggregation — the one rendered into the rows and the one it has to
        # rebuild after every save from /api/index.json, which returns this same
        # flat list. Only the first would ever have been tested.
        "problems": [p.model_dump() for p in index.problems],
        # One list of what a person may change, shared with the detail page. Two
        # lists drift the first time a field is added, and silently.
        "editable": {k: v for k, v in EDITABLE.items() if k not in _TABLE_DERIVED},
        "suggests": SUGGESTS,
        "choices": {"status": list(STATUSES), "priority": list(PRIORITIES)},
        # Which statuses demand which fields, derived from the gate itself by
        # `required_at` (`model.py`). The detail page has had this since it grew
        # the marks beside its labels; the table had nothing, so moving a row to
        # `in_progress` was a refusal naming a field the table does not show, and
        # the way out was to open the record and come back.
        #
        # Per kind, because a row is one kind: merged, the map says a project is
        # missing `person_weeks` at `ready` and a project has no such field. The
        # form keeps the merge, because its kind can still be switched.
        "required": {kind: required_at(kind) for kind in _KIND_MODELS},
        # What a row that does not exist yet can be typed into, per kind.
        "new_row": _new_row_fields(),
        # And what it holds before anybody types anything, read off the model
        # rather than written down here. The row being filled in shows the status
        # and the priority it will be created with: a blank cell that turns into
        # `shaping` on save is the row lying about what it is about to write.
        "defaults": {
            name: _KIND_MODELS["task"].model_fields[name].default
            for name in ("status", "priority")
        },
        # Which kind may hold which, from the model's own map. It decides what a
        # drop does *before* the drop: a row that cannot take this one is drawn
        # as refusing it while the mouse is still down, which is the difference
        # between a rule and a 422.
        "parent_kinds": {kind: list(kinds) for kind, kinds in PARENT_KINDS.items()},
        # The same three templates `/new` offers. An entity created from the
        # table is the same document as one created from the form — a plan where
        # a pitch has a shaping template only if you happened to make it on the
        # other page is a plan with two kinds of pitch in it.
        "templates": TEMPLATES,
        # The word a reader gets, shipped rather than baked into the cells: the
        # rows are drawn by script, and a status the script renders has to reach
        # the same map the server-rendered pages read.
        "human": HUMAN,
        "labels": LABELS,
    }


def _elements(index: Index) -> list[dict]:
    elements: list[dict] = []
    for entity_id, entity in index.entities.items():
        # The same row the table filters on, not a graph-shaped subset of it. The
        # facet bar is one control bar over one `matches()`, and a node carrying
        # only what cytoscape draws is how a dropdown ends up filtering the table
        # and quietly doing nothing here.
        data = _row(index, entity_id) | {
            # The title alone, under the key cytoscape draws. The id is on every
            # other page and in the URL the node opens; on a box 150px wide it
            # cost a line of the only text anybody reads the graph for.
            "label": entity.title,
            # Carried so a new edge is added to what is there rather than replacing
            # it: a PATCH sends the whole field, and depends_on is a list.
            "depends_on": index.blocked_by[entity_id],
        }
        if entity.parent in index.entities:
            data["parent"] = entity.parent
        elements.append({"data": data})
    for entity_id in index.entities:
        for blocker in index.blocked_by[entity_id]:
            elements.append(
                {"data": {"source": blocker, "target": entity_id, "kind": "depends"}}
            )
    return elements


def _containment_rows(index: Index, drawn: set[str]) -> list[tuple[str, int]]:
    """Ids in reading order — a project, then its pitches, then their tasks — and
    the depth each one sits at.

    Sorted by start date, the rows said nothing the table's start column does not
    say better, and threw away the one thing a Gantt has that a table has not: a
    project's work as a block you can see at once. Siblings still order by date,
    so within a parent the reading is unchanged.

    Depth is counted through the whole containment chain, not only the drawn part
    of it: a parent whose span fell outside the window still holds its children,
    and a task that jumps to the left margin when you narrow the dates reads as a
    task that changed parents.
    """
    kids: dict[str, list[str]] = {i: [] for i in index.entities}
    roots: list[str] = []
    for entity_id, entity in index.entities.items():
        # `parent not in entities` covers both a root and an orphan pointing at an
        # id that no longer exists. Dropping the orphan would lose a real bar.
        if entity.parent in index.entities:
            kids[entity.parent].append(entity_id)
        else:
            roots.append(entity_id)

    when: dict[str, date] = {}

    def earliest(entity_id: str, seen: frozenset[str]) -> date:
        """When a subtree starts, so a parent sorts with the work inside it."""
        if entity_id in when:
            return when[entity_id]
        if entity_id in seen:               # a parent cycle in the files, not a tree
            return date.max
        seen = seen | {entity_id}
        span = index.spans.get(entity_id)
        best = span.start if span and entity_id in drawn else date.max
        for kid in kids[entity_id]:
            best = min(best, earliest(kid, seen))
        when[entity_id] = best
        return best

    def ordered(ids: list[str]) -> list[str]:
        return sorted(ids, key=lambda i: (earliest(i, frozenset()), i))

    rows: list[tuple[str, int]] = []

    def walk(entity_id: str, depth: int) -> None:
        if entity_id in drawn:
            rows.append((entity_id, depth))
        for kid in ordered(kids[entity_id]):
            walk(kid, depth + 1)

    for entity_id in ordered(roots):
        walk(entity_id, 0)
    # Anything the walk could not reach is in a parent cycle. It still has a span
    # and still belongs on the chart; a row silently missing from a plan is worse
    # than a row drawn at the margin.
    placed = {i for i, _ in rows}
    return rows + [(i, 0) for i in sorted(drawn - placed)]


def _timeline(
    index: Index, window: tuple[date | None, date | None] = (None, None), zoom: float | None = None
) -> dict:
    """Geometry for the hand-rolled SVG Gantt.

    No Gantt library: hatching, cycle rules and per-bar explanations are all custom,
    and the scheduler emits exact spans, so the renderer is the small part.

    Zoom is a day width the server draws at, not a transform the browser applies.
    Scaling the finished SVG horizontally would stretch every month label and every
    rounded corner with it; recomputing costs one render and keeps the text upright.
    A bar reaching past the window is clipped to it rather than dropped — a row that
    disappears when you narrow the dates reads as work that went away.
    """
    total = len(index.entities)
    drawn = {i: s for i, s in index.spans.items() if not s.unscheduled}
    if not drawn:
        # An empty plot and a plot that failed are the same picture, and which one
        # it is decides what to do next. Nothing here is about the filters, so
        # neither copy offers to clear them.
        blank = (
            {"headline": "This plan has no entities yet.",
             "detail": "Nothing has been pitched, shaped or scheduled."}
            if not total
            else {"headline": "Nothing in this plan has dates.",
                  "detail": "Every entity is done, shelved, or waiting on something "
                            "that has not been scheduled."}
        )
        return {
            "bars": [], "cycles": [], "months": [], "today_x": None, "header": _HEADER_PX,
            "band": _BAND_PX, "width": _LEFT_PX, "height": _ROW_PX, "origin": None,
            "last": None, "zoom": "", "rows": {}, "total": total, "offscreen": total,
            "blank": blank,
        }

    starts = [s.start for s in drawn.values()] + [w[0] for w in index.cycles.values()]
    ends = [s.end for s in drawn.values()] + [w[1] for w in index.cycles.values()]
    origin, last = min(*starts, index.today), max(*ends, index.today)
    origin, last = window[0] or origin, window[1] or last
    if last <= origin:                      # a backwards window would invert every bar
        # `days_after`, because `from` is a query parameter: `?from=9999-12-31`
        # is a link anybody can send and it walked one day off the calendar,
        # which was a 500 on `/timeline` with nothing committed at all.
        last = days_after(origin, 1)
    last = min(last, days_after(origin, _MAX_PLOT_DAYS))
    drawn = {i: s for i, s in drawn.items() if s.end >= origin and s.start <= last}

    # A corpus can span ten months. At a fixed day width that is 1800px of
    # coordinate space, and an SVG with no viewBox CLIPS rather than scales, so
    # everything past the fold silently vanished. Scale the day instead, floored
    # so a short plan does not turn into a hairline.
    days = max((last - origin).days, 1)
    day_px = zoom if zoom else max(1.6, min(_DAY_PX, _PLOT_PX / days))

    def x(day: date, plus_days: int = 0) -> float:
        # Plot coordinates only. The label column is HTML beside the SVG, not
        # inside it, so that it can stay put while the plot scrolls.
        #
        # `plus_days` rather than handing this `day + timedelta(days=1)`: a bar
        # and a cycle band are both inclusive of their last day, and building
        # that day as a `date` raises OverflowError once a span reaches
        # `date.max` — which it does the moment somebody commits a size larger
        # than the calendar, and the timeline was the one page that still 500'd
        # after the scheduler stopped raising. The offset is a coordinate, so it
        # is added in days instead of by naming a date that cannot exist.
        return round(((day - origin).days + plus_days) * day_px, 1)

    config = Config(default_task_effort=index.default_task_effort)
    bars, rows = [], {}
    for row, (entity_id, depth) in enumerate(_containment_rows(index, set(drawn))):
        span = drawn[entity_id]
        visible_start, visible_end = max(span.start, origin), min(span.end, last)
        entity = index.entities[entity_id]
        # Hatched, not outlined: the outline says "overruns its cycle", and one
        # channel carrying three different facts is a channel that says none of
        # them. A guess and a commitment have to be told apart at a glance. The
        # hatch is a second rect over the bar, so the class on the bar stays a
        # statement about the span rather than an instruction about paint.
        marks = [name for name in ("estimated", "unowned") if getattr(span, name)]
        classes = ["bar", *marks]
        if span.overruns_cycle_weeks:
            classes.append("late")
        width = round(
            max(_MIN_BAR_PX, day_px, x(visible_end, 1) - x(visible_start)),
            1,
        )
        explanation = index.explanations.get(entity_id)
        why = explanation.text if explanation else "Starts as soon as it can."
        # Everything the drawing says, in words, for the list beside the plot.
        # A fill, a width, a hatch and an outline are four channels a screen
        # reader has none of, and the dates are the entity's own rather than the
        # clipped ones: a window narrower than the plan does not move a deadline.
        notes = [_MARK_WORDS[name] for name in marks]
        if span.overruns_cycle_weeks:
            notes.append("overruns its cycle")
        bars.append(
            {
                "id": entity_id,
                "label": _clip(entity.title),
                "full": f"{entity.title} ({entity_id})",
                "reads": " ".join(
                    part
                    for part in (
                        f"{entity.title} ({entity_id}).",
                        f"{_human(entity.status)}.",
                        f"{span.start} to {span.end}.",
                        f"{', '.join(notes).capitalize()}." if notes else "",
                        why,
                    )
                    if part
                ),
                "depth": depth,
                "indent": depth * _INDENT_PX,
                "classes": " ".join(classes),
                "marks": marks,
                "x": x(visible_start),
                "y": row * _ROW_PX + _HEADER_PX + _BAR_TOP,
                "width": width,
                "colour": _status_class(entity.status),
                # The channel that is not colour. Five fills on a luminance ladder
                # are separable; they are not nameable, and nothing on a bar says
                # the word. Empty on a bar too narrow to hold the mark inside it.
                "glyph": STATUS_GLYPH.get(entity.status, "") if width >= _GLYPH_MIN_PX else "",
            }
        )
        size, _ = size_weeks(entity, config)
        # The table's own row, so the shared `matches()` reads the same fields on
        # this page as on the other two, plus the two things only a bar wants to
        # say: what it is holding, and why it starts when it does.
        rows[entity_id] = _row(index, entity_id) | {"weeks": round(size, 2), "tip": why}
    cycles = []
    config = Config(cooldown_weeks=index.cooldown_weeks, plans=index.plans)
    for number, (opens, closes) in sorted(index.cycles.items()):
        if closes < origin or opens > last:
            continue
        left = x(max(opens, origin))
        # Where building stops. This is the date an overrun is measured against
        # (`schedule._overrun`), and the chart used to draw its only rule at the
        # end of the *window* — two weeks of cool-down further right. A bar could
        # finish visibly before the line and still be flagged amber, which is the
        # kind of contradiction that ends a timeline's credit with a room.
        builds_until = build_end(number, (opens, closes), config)
        cycles.append(
            {
                "number": number,
                "label": f"cycle {number}",
                "x": left,
                "width": round(max(1.0, x(min(closes, last), 1) - left), 1),
                "build_x": x(builds_until) if origin <= builds_until <= last else None,
                # The dashed rule only where the cycle really closes. Drawn at a
                # clamped edge it would claim a cycle ends where the window does.
                "rule_x": x(closes) if origin <= closes <= last else None,
                # The cool-down runs from the build rule to the closing rule, and
                # is shaded: work is not meant to land there, and an unmarked
                # fortnight at the end of every cycle reads as more building time.
                "cool_x": x(builds_until) if builds_until < closes else None,
                "cool_width": round(
                    max(0.0, x(min(closes, last), 1) - x(builds_until)), 1
                ),
            }
        )
    return {
        "bars": bars,
        "rows": rows,
        "cycles": cycles,
        "months": _month_ticks(origin, last, x),
        # A window that excludes today has no today line. Drawing it at a clamped
        # coordinate would put "now" on an edge it is not on.
        "today_x": x(index.today) if origin <= index.today <= last else None,
        "origin": origin.isoformat(),
        "last": last.isoformat(),
        "zoom": zoom or "",
        "header": _HEADER_PX,
        "band": _BAND_PX,
        "width": x(last) + 24,
        "height": len(bars) * _ROW_PX + _HEADER_PX + _PLOT_FOOT_PX,
        "total": total,
        "offscreen": total - len(bars),
        # Which emptiness this page can arrive at. With bars on it the only way to
        # empty it is the control bar, and that is the one emptiness a button can
        # undo; with none, the dates are what is wrong and clearing a filter would
        # not bring a single one back.
        "blank": {
            "headline": "No entity matches these filters.",
            "detail": "Every bar is filtered out by the controls above.",
        } if bars else {
            "headline": "Nothing is scheduled in this window.",
            "detail": "Every dated entity in this plan falls outside it.",
        },
    }


def _month_ticks(origin: date, last: date, x) -> list[dict]:
    """A bar chart with no dates on it is a picture, not a plan.

    The year only where it changes: "Aug 2026" on every tick spends a third of a
    narrow month restating what the tick before it already said.

    December 9999 has no month after it, and building one raised ValueError —
    twelve lines after the `x()` helper that was fixed for this exact failure.
    `assigned_on: 9999-12-31` on a done entity, typed into the detail page,
    committed and then answered 500 on `/timeline` for good, with `openproj
    check` reporting nothing wrong and `openproj render` writing no files at
    all, so neither tool you would reach for could tell you why. The walk stops
    at the last month the calendar has instead; the loop would end there anyway,
    since the month after it is past `last` by construction.
    """
    ticks, cursor = [], date(origin.year, origin.month, 1)
    while cursor <= last:
        if cursor >= origin:
            year = not ticks or cursor.month == 1
            ticks.append({"x": x(cursor), "label": cursor.strftime("%b %Y" if year else "%b")})
        if (cursor.year, cursor.month) == (date.max.year, date.max.month):
            break
        cursor = date(cursor.year + cursor.month // 12, cursor.month % 12 + 1, 1)
    return ticks


class Links(BaseModel):
    """Where the pages point at each other.

    Static output links to sibling files; the server links to routes. Everything
    else about the pages is identical, so this is the only thing that knows which
    mode it is in.
    """

    table: str = "index.html"
    detail: str = "detail.html"
    graph: str = "graph.html"
    timeline: str = "timeline.html"
    people: str = "people.html"
    entity: str = "detail.html#"  # prefix, then the entity id
    new: str = ""  # only the server can create; a rendered file has nowhere to post
    cycles: str = "cycles.html"
    cycle: str = "cycles.html#"  # prefix, then the cycle number
    issues: str = "issues.html"
    issue: str = "issues.html#"  # prefix, then the issue id
    notes: str = "notes.html"
    note: str = "notes.html#"  # prefix, then the note id
    asset: str = "assets/"  # a rendered file sits beside the assets it names
    # Prefix, then the entity id: where the hover card asks for a shaping
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
    table="/", detail="/detail", graph="/graph", timeline="/timeline",
    entity="/detail/", new="/new", people="/people",
    cycles="/cycles", cycle="/cycle/", issues="/issues", issue="/issue/",
    notes="/notes", note="/note/",
    asset="/assets/", deck="/deck/", body="/api/body/",
)

_MD = MarkdownIt("commonmark", {"html": False}).enable("table")
_PR = re.compile(r"\b([\w.-]+/[\w.-]+)#(\d+)\b")


def _pr_link(ref: str) -> Markup:
    """A dead PR reference teaches people the field is decorative.

    `Markup(...).format` and not an f-string. Called from `_after_markdown` the
    reference has already been through the markdown escaper and is harmless;
    called from the facts list it is `entity.prs`, which is free text a member
    types and nothing validates, and an f-string put it straight into an `href`
    and a link text. That is the whole of the difference between a decorative
    field and a script that runs for everybody who opens the page.
    """
    repo, _, number = ref.partition("#")
    return Markup('<a href="https://github.com/{}/pull/{}">{}</a>').format(repo, number, ref)


# What an asset is, and what a `data:` URI has to call it. One enumeration, with
# the pattern built from it: written twice, a fifth format added to the regex and
# forgotten in the map is an image that draws on the site and silently stops
# travelling inside a deck. `web.py`'s `IMAGE_TYPES` answers a different question
# — what may be uploaded — and is deliberately not this.
_ASSET_MEDIA = {
    ".png": "image/png", ".jpg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp",
}
# Written as a repository-relative path so the markdown reads the same in git, on
# GitHub and in the tool; only the prefix in front of it changes.
_ASSET_SRC = re.compile(
    r"assets/([0-9a-f]{16}(?:" + "|".join(re.escape(s) for s in _ASSET_MEDIA) + "))"
)


def _pr_refs(state: StateCore) -> None:
    """`org/repo#12`, in prose, becomes a link to the pull request.

    A core rule over the token stream, because the substitution this replaces ran
    over markdown-it's *finished* HTML and had no idea what it was inside. A
    reference already inside a link — `[a pr link](https://github.com/org/repo#12)`
    — came back as an anchor nested in an `href`, which a tokeniser turns into one
    anchor wearing junk valueless attributes; a reference inside backticks became
    a link, which is the opposite of what backticks are for.

    Over tokens both contexts are skipped by construction rather than by a lookahead
    that has to be got right: a code span is a `code_inline` token and never a
    `text` one, a fenced block never reaches an inline token at all, and a link's
    contents are exactly what sits between `link_open` and `link_close`.

    Pushed last, after `text_join`, so the text tokens it walks are the final ones
    and a reference cannot be split across two of them.
    """
    for token in state.tokens:
        if token.type != "inline" or "#" not in token.content:
            continue
        depth = 0
        children: list[Token] = []
        for child in token.children or []:
            if child.type == "link_open":
                depth += 1
            elif child.type == "link_close":
                depth -= 1
            if child.type == "text" and depth == 0 and _PR.search(child.content):
                children.extend(_pr_tokens(child))
            else:
                children.append(child)
        token.children = children


def _pr_tokens(token: Token) -> list[Token]:
    """One text token, split into the text around its PR references and the links.

    `html_inline` is how a rule adds markup of its own: the renderer writes its
    content out verbatim, and `html: false` is a statement about what the *parser*
    accepts from a member, not about what this file may emit.
    """
    pieces: list[Token] = []
    at = 0
    for match in _PR.finditer(token.content):
        if match.start() > at:
            pieces.append(_inline_token("text", token.content[at : match.start()], token.level))
        pieces.append(_inline_token("html_inline", str(_pr_link(match.group(0))), token.level))
        at = match.end()
    if at < len(token.content):
        pieces.append(_inline_token("text", token.content[at:], token.level))
    return pieces


def _inline_token(kind: str, content: str, level: int) -> Token:
    token = Token(kind, "", 0)
    token.content = content
    token.level = level
    return token


def _image(
    self: RendererHTML, tokens: Sequence[Token], idx: int, options: object, env: dict
) -> str:
    """Where an image points, decided on the token rather than on the finished tag.

    A remote image would make the page fetch from the network, which is exactly
    what inlining every library was for. Remote images become links instead: the
    reference survives, the dependency does not.

    **An allowlist, and it has to be.** This asked whether the source began with
    `http://` or `https://`, which is a list of the two ways somebody would write it
    on purpose and none of the ways they would not. `//host/a.png` inherits the
    page's scheme and `HTTP://host/a.png` is the same URL to a browser and a
    different string to `startswith`; both drew a live `<img>`, and a real Chrome
    fetched both, referer included. In a plan anybody can write to, that is one line
    of markdown turning a shaping document into a tracking pixel aimed at everyone
    who opens it — and it survived into the static export, where there is no origin
    to appeal to. There is no denylist of URL spellings that is finished, so the
    question is asked the other way round: an image is drawn only if it is an asset
    this tool stored, and everything else is a link.

    An image stored in the plan is a different thing — it is in the repository, it
    travels with the clone, and it is served from the same origin as the page.
    Those are drawn, with the one prefix that differs between a served page and a
    rendered file put in front of the path the markdown states.

    `env` carries the links because a renderer is shared and a prefix is not: the
    preview, the detail page and the export all render the same document and only
    this differs between them. `_markdown` always sets it; the default is the one
    every other function in this file takes when nobody says.

    `env["assets"]` is the third answer, and only the deck asks for it: the bytes
    themselves, as a `data:` URI. Every other page names a path because it sits
    beside the directory the path resolves against — a served page has `/assets/`
    and an exported one has the copied folder. A deck is a file somebody mails to
    the people who were not in the room, and a screenshot that only resolves next
    to its repository is a screenshot that does not arrive.
    """
    token = tokens[idx]
    source = token.attrGet("src") or ""
    links = env.get("links", STATIC)
    asset = _ASSET_SRC.fullmatch(source)
    if not asset:
        alt = self.renderInlineAsText(token.children, options, env) if token.children else ""
        return str(Markup('<a href="{}">{} (external image)</a>').format(source, alt or "image"))
    # `or` and not an `if`: an asset the reader could not fetch falls back to the
    # path, which is what every other page draws. Missing bytes must cost the
    # picture and not the page.
    inlined = env.get("assets", {}).get(asset.group(1))
    token.attrSet("src", inlined or links.asset + asset.group(1))
    return RendererHTML.image(self, tokens, idx, options, env)


_MD.core.ruler.push("openproj_pr_refs", _pr_refs)
_MD.add_render_rule("image", _image)


def _markdown(text: str, links: Links, assets: dict[str, str] | None = None) -> Markup:
    """A shaping document, rendered, exactly as every view of it renders.

    One entry point because the preview has to show what the page will show.
    Written twice, the preview drew an uploaded image against the current URL — so
    a figure that renders fine on `/detail/task-x` was a broken image in the
    preview of that same document, which is the one place somebody checks it.

    `Markup` because `_MD` runs with `html: false`: everything a member typed
    reached the tokeniser as text and left it escaped, and the only markup in the
    result is markup this file put there. That is what lets `{{ e.body }}` render
    without a `|safe` beside it.

    `assets` is asset name to `data:` URI, for the one view that has to carry its
    pictures inside it. See `_image` and `_inlined_assets`.
    """
    return Markup(_MD.render(text, {"links": links, "assets": assets or {}}))


def _markdown_line(text: str, links: Links, assets: dict[str, str] | None = None) -> Markup:
    """One line of a document, rendered as itself rather than as a paragraph.

    A checklist point is a line of markdown that a slide lifts out of its list,
    and it is written like one: the corpus has `` `jsbach_setup` `` and
    `C2SM/icon4py#1403` inside points, and the real deck links exactly those
    references from exactly those bullets. Taken as plain text they came out as
    literal backticks and a dead reference — the field looking decorative, which
    is the whole reason `_pr_link` exists.

    `_MD` and not a second parser, so a point renders the way the document it was
    written in renders: the same PR rule, the same image rule, the same
    `html: false`. `renderInline` skips the block chain, so the line arrives
    without a `<p>` wrapped round it and stays on the row with its own tick.
    """
    return Markup(_MD.renderInline(text, {"links": links, "assets": assets or {}}))


# A leading `# Title` line, with the optional closing hashes ATX headings allow.
_LEADING_HEADING = re.compile(r"\A\s*#{1,6}[ \t]+(.+?)[ \t]*#*[ \t]*(?:\r?\n|\Z)")


def _drop_repeated_title(body: str, title: str) -> str:
    """The shaping document's own first heading, when the page already is it.

    Nearly every doc in the corpus opens by restating its title, because in git
    that heading is the only thing naming the file. On the page it lands directly
    under an `<h1>` saying the same words at the same weight, which reads as a
    rendering fault rather than as a convention. The file keeps its heading — that
    is what git holds and what the editor shows — and only the reading view drops
    it. Whitespace is normalised before comparing so a wrapped or double-spaced
    heading still counts; anything else is somebody's real first section.
    """
    match = _LEADING_HEADING.match(body)
    if not match:
        return body
    same = " ".join(match.group(1).split()).casefold() == " ".join(title.split()).casefold()
    return body[match.end() :].lstrip("\n") if same else body


def _body_html(entity: Entity, links: Links = STATIC) -> Markup:
    return _markdown(
        without_comments(_drop_repeated_title(entity.body, entity.title)), links
    )


def _inlined_assets(bodies: Iterable[str], read: Callable[[str], bytes | None]) -> dict[str, str]:
    """Every asset these documents name, as a `data:` URI, read once each.

    Scanned off the markdown source rather than off the rendered page, because
    the rendered page is where the decision has already been taken: `_image` asks
    this map for a source before it falls back to a path. That does mean a name
    written inside a code fence is fetched and never drawn — a few kilobytes for
    a case that has not happened, against a second parse of every body to find
    out.

    Bytes that will not come back cost the picture and nothing else: the name
    stays out of the map and `_image` draws the path, which is what the other
    pages draw and what a reader beside the repository can still resolve.
    """
    found: dict[str, str] = {}
    for body in bodies:
        for name in _ASSET_SRC.findall(body):
            if name in found:
                continue
            data = read(name)
            if data is None:
                continue
            media = _ASSET_MEDIA["." + name.rsplit(".", 1)[1]]
            found[name] = f"data:{media};base64,{base64.b64encode(data).decode('ascii')}"
    return found


_ENV = Environment(autoescape=True)
# Jinja ships a `tojson`, and it is nearly this: `htmlsafe_json_dumps` spells out
# `<`, `>`, `&` and `\'` for the same reason `_json` does. Replaced rather than
# added beside, because two JSON filters on one environment is two guarantees to
# keep in step — and every `{{ x|tojson }}` already written on these pages is a
# data block in a `<script>`, which is exactly what `_json` is for.
_ENV.filters["tojson"] = _script_json


def _fragment(template: str, **values: object) -> Markup:
    """One rendered piece of a page, typed as the markup it is.

    Autoescaping is only half a boundary while the pieces come back as `str`:
    every page then had to write `{{ facets|safe }}`, and `|safe` on a variable
    is a claim about whatever that variable holds *today*. `{{ row.display }}`
    beside `{{ e.body }}` beside `{{ e.parent_link }}` all read alike and one of
    them was a title somebody typed. With the fragments typed instead, a value
    that is markup renders and a value that is not gets escaped — which is the
    same rule for every page, enforced by the type rather than by remembering.
    """
    return Markup(_ENV.from_string(template).render(**values))


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
// The only way in and out of localStorage, for every script on every page.
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
const remembered = {
  get(key, fallback = null) {
    try {
      const held = localStorage.getItem(key);
      return held === null ? fallback : held;
    } catch (e) { return fallback; }
  },
  // The one structured thing this app stores is the table's widths, and
  // `JSON.parse` throws on a half-written or hand-edited entry exactly where the
  // bare read did — so the parse belongs behind the same door as the read. A
  // stored value that is not an object is not a map of widths either.
  map(key) {
    try {
      const held = JSON.parse(localStorage.getItem(key));
      return held && typeof held === 'object' ? held : {};
    } catch (e) { return {}; }
  },
  // Writing throws too, and for a second reason: Safari's private mode reports a
  // quota of zero, so the first setItem raises QuotaExceededError. A width
  // nobody can save is still a width.
  set(key, value) {
    try { localStorage.setItem(key, value); } catch (e) { /* not remembered */ }
  },
  forget(key) {
    try { localStorage.removeItem(key); } catch (e) { /* nothing to forget */ }
  },
};

// Before the first paint, or the page renders light and then turns dark in front
// of whoever chose dark — which is worse than not having the choice.
// A name nothing else on any page uses: this is the global lexical scope every
// classic script shares, and a second `const` of the same name anywhere on the
// page is a SyntaxError rather than a shadowing — the whole page, not one line.
const storedTheme = remembered.get('openproj:theme');
if (storedTheme) document.documentElement.dataset.theme = storedTheme;
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
     The five fills are a *luminance ladder*, not five hues at one lightness:
     hue is the channel a dichromat loses, and on the graph and the timeline the
     fill used to be the only channel there was. Work gets more solid as it
     advances — done is furthest from the page, parked is nearest — so the order
     survives every kind of colour vision.
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
     --st-X-ink is one value on all five here, because a ladder of tints has one
     ink that reads on every rung. Five tokens are kept rather than collapsed to
     one: a status added later may sit somewhere that needs its own. */
  --st-shaping: #d2c5ee; --st-shaping-ink: #101416; --st-shaping-line: #7e61c2;
  --st-shaping-soft: #efedf5; --st-shaping-text: #5e3eaa;
  --st-ready: #83b8e9; --st-ready-ink: #101416; --st-ready-line: #275e92;
  --st-ready-soft: #ecf1f6; --st-ready-text: #22578a;
  --st-in_progress: #e18606; --st-in_progress-ink: #101416; --st-in_progress-line: #603a04;
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
  --band: #c3d6de;
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
       what the light one has now been rebuilt to be; the fills below are
       unchanged.
       --st-X-line here is not the fill's own value. It could have been — every
       fill already clears 3.23:1 against this ground, so nothing needs the
       border for separation. But the graph draws PRIORITY as border *width*,
       and a border the colour of the box it surrounds is a width nobody can
       read: high and low priority would differ only by the size of the node.
       So each border is the contrast midpoint between its own fill and the
       page — the same ratio either side, which is the most an edge can be worth
       when it has to read against both. `shelved` gets 1.79 and 1.81 because
       its fill is only 3.23 from the ground and there is no more room there.
       --st-shelved-ink stays white. The brief that inverted the light theme
       said this one clears 6.03:1 on #101416 and could join the others; it is
       3.34:1, and this ink is the node's label and the bar's glyph, which is
       text and owes 4.5. Lifting the fill instead would put it 1.10 from
       `shaping` and collapse the top of the ladder. */
    --st-shaping: #9077cb; --st-shaping-ink: #101416; --st-shaping-line: #56477a;
    --st-shaping-soft: #262034; --st-shaping-text: #b09fd8;
    --st-ready: #7aacdc; --st-ready-ink: #101416; --st-ready-line: #44607a;
    --st-ready-soft: #1d2a38; --st-ready-text: #87b3dd;
    --st-in_progress: #f9c275; --st-in_progress-ink: #101416; --st-in_progress-line: #82663d;
    --st-in_progress-soft: #3b2d19; --st-in_progress-text: #daaf74;
    --st-done: #d7f4e6; --st-done-ink: #101416; --st-done-line: #6a7972;
    --st-done-soft: #1d372b; --st-done-text: #5cce97;
    --st-shelved: #5e6a73; --st-shelved-ink: #ffffff; --st-shelved-line: #3c4449;
    --st-shelved-soft: #242b30; --st-shelved-text: #a6b1ba;
    --sev-blocker: #e0796a; --sev-blocker-soft: #2b1b17;
    --sev-warn: #d9a557; --sev-warn-soft: #332409;
    --drop: #1e3a2b;
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
  --st-shaping: #9077cb; --st-shaping-ink: #101416; --st-shaping-line: #56477a;
  --st-shaping-soft: #262034; --st-shaping-text: #b09fd8;
  --st-ready: #7aacdc; --st-ready-ink: #101416; --st-ready-line: #44607a;
  --st-ready-soft: #1d2a38; --st-ready-text: #87b3dd;
  --st-in_progress: #f9c275; --st-in_progress-ink: #101416; --st-in_progress-line: #82663d;
  --st-in_progress-soft: #3b2d19; --st-in_progress-text: #daaf74;
  --st-done: #d7f4e6; --st-done-ink: #101416; --st-done-line: #6a7972;
  --st-done-soft: #1d372b; --st-done-text: #5cce97;
  --st-shelved: #5e6a73; --st-shelved-ink: #ffffff; --st-shelved-line: #3c4449;
  --st-shelved-soft: #242b30; --st-shelved-text: #a6b1ba;
  --sev-blocker: #e0796a; --sev-blocker-soft: #2b1b17;
  --sev-warn: #d9a557; --sev-warn-soft: #332409;
  --drop: #1e3a2b;
  --band: #2a3941;
}
/* cv05 gives the l a tail, so l/1/I are three shapes in a login; ss03 fixes the
   spacing of the curly quotes and slashes that PR refs and paths are full of. */
body { font-family: var(--font-sans); font-size: 14px; line-height: 1.5;
       font-feature-settings: "cv05" 1, "ss03" 1;
       margin: 0; padding: 1rem 1.25rem 3rem;
       background: var(--bg); color: var(--fg); }
nav { display: flex; gap: 1rem; margin-bottom: 1rem; font-size: 13px; align-items: center; }
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

   Five page headings wear this, one per view whose whole heading was the single
   word already sitting in the nav two rows above it. The nav now says which page
   you are on in the item it lights, so on screen that heading was a row of space
   spent saying nothing new. It stays in the document because a page with no
   top-level heading cannot be announced by name, cannot be found in a heading
   list, and leaves the skip link nowhere to land — the fix round six made, which
   this must not undo.

   A heading that names what you are looking at rather than which route you are on
   is not clipped and is not here: an entity's own title, a cycle's number, the
   listing of the whole plan, and the create form, whose nav item does not exist
   and whose heading is therefore the only thing on it that says what it makes.

   Nothing in this comment quotes a heading or a control by its exact words. The
   stylesheet is inlined into every page, so a phrase written here is a phrase in
   the served bytes of all eight of them, and two tests that search a page for the
   copy of a control it must not offer found it in this block instead. */
.sr-only { position: absolute; width: 1px; height: 1px; margin: -1px; padding: 0;
           overflow: hidden; clip-path: inset(50%); white-space: nowrap; border: 0; }
/* The right end of the nav, as one group rather than two things each pushing
   themselves over. The toggle asked for `margin-left: auto` on its own and was
   the only thing out there; with the identity beside it, two auto margins split
   the free space and put the pair in the middle of the row. */
.corner { margin-left: auto; display: flex; align-items: center; gap: .6rem; }
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
   for. z-index 6 clears the table's own furniture: its header is 3, the frozen
   pair 4, and the drop label 5. */
/* `:not([hidden])` on the display, and it is not decoration: the browser's own
   `[hidden] { display: none }` is (0,1,0) in the UA sheet, and ANY author rule
   setting `display` beats it. Without this every menu on the bar is open the
   moment the page loads — which is what shipped for ten minutes, over the plan
   it is meant to filter. `#unparent` two hundred lines down settles the same
   question the same way and says so; this is the second time. */
.facetmenu:not([hidden]) {
  position: absolute; z-index: 6; top: 100%; left: 0; margin-top: .2rem;
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
   window, the cycle page's three settings, the state picker on Issues and Notes.
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
#card .card-body { margin: .4rem 0 0; padding-top: .35rem; max-height: 12em;
                   overflow-y: auto; border-top: 1px solid var(--line); }
#card .card-body > :first-child { margin-top: 0; }
#card .card-body > :last-child { margin-bottom: 0; }
#card .card-body :is(h1, h2, h3, h4) { font-size: 12px; margin: .5rem 0 .2rem; }
#card .card-body p, #card .card-body ul, #card .card-body ol { margin: .2rem 0; }
#card .card-body pre { overflow-x: auto; }
#card .card-body img { max-width: 100%; }
.hint { color: var(--muted); font-size: 12px; }
.empty { color: var(--empty); }
.num { font-variant-numeric: tabular-nums; }
/* The two lines every view writes about itself: the count under the controls of
   what is on screen, and the place a refusal or a receipt is written into. Four
   pages drew `#summary` and three drew `#state`, and the copies had already come
   apart — the table's summary was the one that never got the margin or the size
   the other three share, so this is theirs. `#shown` was three copies of `.num`
   under a different name; it wears `.num` now. */
#summary { color: var(--muted); font-size: 13px; margin: .5rem 0 .25rem; }
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
    reads until a chip turns white on white. -#}
{% for s in statuses %}
.chip.st-{{ s }} { background: var(--st-{{ s }}-soft); color: var(--st-{{ s }}-text); }
{%- endfor %}
/* Kind never competes with status for attention: no hue, only a hairline. One
   rule for all three, because three kinds drawn three ways read as two of them
   being special rather than as three answers to one question — a project used to
   carry the accent and extra weight, a pitch a plain hairline, and a task no
   border at all, which is the first thing anybody noticed about the id column.
   The word inside the chip is what says which kind it is. */
.chip.kind-project, .chip.kind-pitch, .chip.kind-task {
  color: var(--kind-ink); border: 1px solid var(--kind-line);
}
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
  border-radius: 2px;
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
.legend { display: flex; flex-wrap: wrap; gap: .25rem 1rem; align-items: center;
          list-style: none; margin: .75rem 0 0; padding: 0;
          font-size: 12px; color: var(--muted); }
.legend li { display: flex; align-items: center; gap: .35rem; }
/* border-box so a key that carries a border is the same 20x11 as one that does
   not: every status swatch grew a border with the shapes it keys, and on
   content-box the row of keys came out at three different heights. */
.legend .swatch { width: 20px; height: 11px; border-radius: 2px; flex: none;
                  box-sizing: border-box; }
/* inline-flex on the span only. Two of these swatches are <svg>, where a flex
   display on the root would be laying out a replaced element as a box. */
.legend span.swatch { display: inline-flex; align-items: center; justify-content: center;
                      font-family: var(--font-sans); font-weight: 700;
                      font-size: 9px; line-height: 1; }
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
.keyrow > .legend, .keyrow > #summary { margin: 0; }
.keyrow > #summary { margin-left: auto; text-align: right; }
/* The row a page's own controls stand in: the table's create link, the cycle
   page's "back to all cycles" and its "add somebody", the two rows of the cycles
   index's create form. Three pages draw one and the rule was in _DETAIL_STYLE —
   which the cycle pages load and the table does not, so on the table it was a
   `<p>` with the browser's default margin and the create action sat in it as a
   bare inline link. */
/* `flex-wrap`, because the row now ends in the control that acts on it rather
   than in the last field: unwrapped, a narrow window squeezed three date boxes
   to make room for a button instead of putting the button underneath them. */
.editbar { display: flex; flex-wrap: wrap; gap: .4rem; align-items: center;
           margin: .4rem 0 1rem; }
/* A link that is a control. The only rule was `.tl-controls .button`, scoped to
   the timeline's filter bar, so the table's create link — the one way to bring
   an entity into existence from the UI — rendered as underlined blue text.
   `:visited` as well as the base state, because the shell colours every visited
   link with `a:visited`, which is (0,1,1) and would beat a bare `.button`: the
   button turned back into a link the moment somebody had used it once. Written
   in link-visited-hover order, so the states later in the list win the ties they
   are supposed to. */
.button, .button:visited { font: inherit; font-size: 13px; line-height: 1.4;
                           padding: .2rem .7rem; border-radius: 2px; cursor: pointer;
                           border: 1px solid var(--line-strong); background: var(--surface);
                           color: var(--fg); text-decoration: none; }
.button:hover { border-color: var(--accent); color: var(--accent); }
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
#clear-filters { font: inherit; font-size: 13px; padding: .2rem .6rem; border-radius: 2px;
                 border: 1px solid var(--line-strong); background: var(--surface);
                 color: var(--fg); cursor: pointer; }
#clear-filters:hover { border-color: var(--accent); color: var(--accent); }
/* The one action that writes, on every page that writes. It follows the form it
   commits instead of sitting above it, and it is sticky rather than merely last:
   these forms are the length of the plan, and a Save at the far end of one is a
   Save you go looking for while holding an unsaved decision in your head.
   Defined here rather than per page because four pages have one, and four copies
   of a commit bar is four answers to "have I saved this yet". */
.commitbar {
  /* Under the suggestion popup (20) and under the shell's banner (40): a bar
     that is always on screen is always in front of something. */
  position: sticky; bottom: 0; z-index: 10;
  display: flex; gap: .6rem; align-items: baseline; flex-wrap: wrap;
  margin: 1.5rem 0 0; padding: .5rem .75rem;
  background: var(--surface); border: 1px solid var(--line); border-radius: 3px;
}
/* Unsaved work is a warning, not decoration: this is the state in which closing
   the tab loses something. */
.commitbar.dirty { border-color: var(--warn); }
#unsaved { font-size: 12px; color: var(--muted); }
.commitbar.dirty #unsaved { color: var(--warn); font-weight: 600; }
#save, .commitbar button { font: inherit; font-size: 13px; padding: .25rem .8rem;
        border-radius: 2px; border: 1px solid var(--line-strong);
        background: var(--surface); color: var(--fg); cursor: pointer; }
#save:disabled { color: var(--muted); cursor: default; }
#save:not(:disabled) { border-color: var(--accent); color: var(--accent); }
/* What the status chosen in this form will make the server refuse it without.
   A warning colour because it is a refusal waiting to happen, and a word rather
   than an asterisk because an asterisk means "required" only to people who have
   already been told. */
.req { font-size: 11px; letter-spacing: .04em; text-transform: uppercase;
       color: var(--sev-warn); font-weight: 600; }
/* Every date the plan renders is ISO; every `<input type=date>` renders in the
   browser's locale. So one reader edits 2026-09-01 as 01/09/2026 and the next as
   09/01/2026, and neither can tell which. The box keeps its locale — that is
   what it is typed in — and the value the file holds is echoed beside it. */
.iso { display: block; font-family: var(--font-mono); font-size: 11px;
       color: var(--muted); font-variant-numeric: tabular-nums; }
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
   plan instead of about an entity. */
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
/* A reader who has told their operating system they want less motion gets none.
   It is a system setting and not a preference this app keeps, so there is no
   toggle for it and nothing in `remembered` — the browser answers, every page.

   One blanket block rather than a `transition: none` beside the single animated
   rule the app owns, because the next person to write a transition will not come
   back here to add it. That rule is `#grip::before` on the detail page, the width
   handle's fade, and it is the only one: `transition`, `animation` and
   `@keyframes` across `src/` return it and nothing else.

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
<script>
// Declared before the content, because the pages' own scripts are inside it and
// some of them announce while loading — the cycle page's receipt, the detail
// page's restored draft. A function in a later <script> is not hoisted into an
// earlier one, so defining this alongside the theme toggle below would have made
// those two messages a ReferenceError instead.
const ANNOUNCE = document.getElementById('announce');

// Stored text into markup, for every script on every page. Five of these pages
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

// Bodies already fetched, by id. A pointer crossing a column of rows asks for the
// same document several times a second otherwise — and the answer cannot change
// under a page that has not been reloaded, because a save reloads the rows.
const CARD_BODIES = new Map();

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
    ['Scheduled', row.start && row.end
      ? `<span class="num">${esc(row.start)}</span> to <span class="num">${esc(row.end)}</span>`
      : CARD_DASH],
    ...((row.tags || []).length ? [['Tags', esc(row.tags.join(', '))]] : []),
    ...extra,
  ];
  // The class attributes are escaped too, and not only the words beside them.
  // They were not: a status reading `ready" onmouseover=alert(1) x="` came back
  // out of this line as a real event handler that fired on hover, on the one
  // element of the box a pointer is guaranteed to cross.
  return `<p class="card-title">${esc(row.title)}</p>` +
    `<p class="card-chips"><span class="chip ${stClass(row.status)}">` +
    `${esc(cardWord(row.status))}</span> ` +
    `<span class="chip kind-${esc(row.kind)}">${esc(cardWord(row.kind))}</span></p>` +
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
  return CARD_BODY_URL ? fillCardBody(row.id) : Promise.resolve();
}

// A pointer crossing a table on its way somewhere else is not a question, and a
// card that answers it anyway flashes a box over every row on the way past. So
// hovering ASKS for a card and waits; the wait is cancelled by leaving.
//
// 400ms is the delay every hover-intent control settles on: long enough that
// crossing a row does not open one, short enough that pointing at a row and
// stopping does not feel broken. The keyboard path on the timeline does not go
// through here — focus is deliberate, and a delay after a deliberate act is a
// page that ignored you.
const CARD_DELAY = 400;
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
  // Already showing this one: the pointer moved inside the same row, which is
  // not a new question. Notably it does NOT move the card — a box that follows
  // the pointer is a box you cannot put the pointer into.
  if (!CARD.hidden && cardShowing === row.id) return;
  cardTimer = setTimeout(() => showCard(row, x, y, extra), CARD_DELAY);
}

async function fillCardBody(id) {
  if (!CARD_BODIES.has(id)) {
    try {
      const response = await fetch(CARD_BODY_URL + encodeURIComponent(id));
      // A refusal is not a document. `ok` and not a `catch` alone: a 404 is a
      // resolved promise with an error page in it, and `.json()` on that throws
      // somewhere far away from the request that caused it.
      CARD_BODIES.set(id, response.ok ? (await response.json()).html || '' : '');
    } catch (error) {
      // Offline, or a policy that refuses the request. The card keeps what it
      // already drew; the row's own fields are the part that was never in doubt.
      CARD_BODIES.set(id, '');
    }
  }
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
  // Both in viewport coordinates, so the scroll cancels out of the subtraction.
  // `document.body` and not `ROOT.scrollHeight`, which is clamped upwards to the
  // window height: on a page shorter than its window that clamp reads as content
  // nobody has, and the box would be capped below the room it is being given.
  const below = document.body.getBoundingClientRect().bottom - rect.bottom;
  // Floor, not round. These are sub-pixel measurements and the whole point of the
  // number is that the page does not scroll: half a pixel rounded up is a
  // scrollbar, and half a pixel rounded down is invisible.
  const value = Math.max(ROOM_FLOOR, Math.floor(innerHeight - above - below)) + 'px';
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
  if (measureRoom() && passes > 1) requestAnimationFrame(() => settleRoom(passes - 1));
}
function fitRoom() { settleRoom(4); }
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
{{ content }}
</main>
<script>
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

// The one format that never moves. A date box is drawn by the browser in the
// reader's locale, so the same stored 2026-09-01 reads as 01/09/2026 here and
// 09/01/2026 one desk over, while every date the plan *prints* is ISO. The echo
// carries the class the box carries, so it appears and disappears with it rather
// than repeating a value that is already on screen in read mode.
for (const box of document.querySelectorAll('input[type=date]')) {
  // Except on the create form, where the two boxes are the only dates on screen
  // and the echo under each label reads as a second, differently-formatted copy
  // of a value you are in the middle of typing. The ambiguity this exists to
  // settle is between a printed date and a box beside it; there is nothing to
  // compare against there.
  if (box.closest('#create')) continue;
  const echo = document.createElement('span');
  echo.className = box.classList.contains('field') ? 'iso field' : 'iso';
  const show = () => { echo.textContent = box.value || '—'; };
  show();
  box.addEventListener('input', show);
  box.addEventListener('change', show);
  box.insertAdjacentElement('afterend', echo);
}

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

function showMoved({commit, changed}) {
  if (movedOurs.has(commit)) return;
  movedShowing = commit;
  // What this page is looking at. A page showing one entity has it in its URL;
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
  if (movedWriting) movedHeld.push(message); else showMoved(message);
};
</script>
{% endif %}
</body></html>
"""

# The control bar, for every view that filters something. The field list is a
# parameter because the people page filters by role, kind and status while the
# plan's three views filter by nine fields and a flag — and that page used to
# draw the whole bar again by hand, which is how a search box comes to be labelled
# on one page and not on the next.
_FACETS = """
<div id="controls">
  <div class="searching">
  {#- A placeholder is not a name: it is gone the moment anything is typed, and
      it never reaches the accessibility tree as one. Every dropdown beside this
      box is wrapped in its `<label>`; the search box was the one control in the
      bar that had nothing to say what it searches. -#}
  <input id="q" type="search" aria-label="{{ search }}" placeholder="{{ search }}">
  {#- What is wrong with what is in the box. Here rather than in each view,
      because the box is in the bar and the bar is shared: the table can say it
      again over its own empty rows, and does, but the graph and the timeline
      draw pictures and have nowhere to put a sentence at all.
      `role="status"` and polite: a query is typed a character at a time, and a
      reader who is told about every half-finished bracket as an alert is a
      reader who turns the page off. -#}
  <span id="query-error" role="status" aria-live="polite" hidden></span>
  {#- The way out, beside the box that gets you in. Drawn only when something is
      actually set: a Clear that is always there is a control that does nothing
      most of the time, and the reader has to read it to find that out. It is not
      `#clear-filters` — the table draws one of those inside its own empty state,
      where a reader who has filtered everything away is looking, and two elements
      cannot share an id. -#}
  <button type="button" id="unfilter" hidden>Clear filters</button>
  {#- The far end of the search box's line, for what a page has to say about the
      view it draws. A slot rather than a sentence, because the three views say
      different things there — how to pan the graph, which window the timeline is
      showing — and not one of them is worth a row of its own on a page whose
      whole point is the drawing underneath. -#}
  {% if aside %}<div class="aside">{{ aside }}</div>{% endif %}
  </div>
  <div class="facets">
  {#- A field is a button and a list of checkboxes, and not a `<select>`, because
      the filter underneath has always been able to answer more than a select can
      ask: `apply_filters` ORs within a field and ANDs across them, and the URL
      has always carried a field twice. The menu was the only thing insisting on
      one value, and a control that can express less than the thing it controls
      is a control that hides half the tool.

      Checkboxes and not a `<select multiple>`: the native one costs four rows of
      height per field on a bar of ten of them, and de-selecting is ctrl-click,
      which is folklore. Real `<input type="checkbox">` inside real `<label>`s
      rather than a listbox with `aria-selected`, because a checkbox already
      means "several of these, independently" to every reader and every screen
      reader, and the roles this would otherwise need are the part people get
      wrong. -#}
  {% for field in fields %}
  <div class="facet" data-field="{{ field }}">
    <button type="button" class="facetopen" id="facet-{{ field }}" aria-expanded="false">
      <span class="facetname">{{ label(field) }}</span>
      {#- What is chosen, in the control rather than only in the popup: a filter
          you cannot see is a filter you forget you set, and this bar spends most
          of its life closed. -#}
      <span class="facetsaid">all</span>
    </button>
    <div class="facetmenu" role="group" aria-labelledby="facet-{{ field }}" hidden>
      {% for value in facets.get(field, []) %}
      {#- The value is what the filter matches and what the URL carries; the word
          beside it is what a person reads. They are the same string for a status
          and a login and are not for a project, whose values are ids — `Project:
          proj-370001` is a menu that asks you to know the plan by heart. -#}
      <label><input type="checkbox" value="{{ value }}">{{
        titles.get(value) or value|human }}</label>{% endfor %}
    </div>
  </div>
  {% endfor %}
  </div>
</div>
"""

# The plan's own filters, in the order the bar draws them. `predicate` is last and
# is a field like any other here: its values are `index.facets["predicate"]`, so
# the select it needs is the select every other field gets.
_PLAN_FACETS = (
    "kind", "priority", "status", "owner", "assignees", "reviewers",
    "cycle", "project", "tags", "predicate",
)

# The filter model itself, shared by every view that offers the bar above. The
# README has always said three views filter the same plan the same way; while
# `matches` lived inside the table's script, that was true of one of them, and a
# second copy of it is how a facet comes to mean something different per page.
_FILTER_JS = Markup(r"""
<script>
const params = new URLSearchParams(location.search);

// Every field the control bar offers. A field in one list and not the other is a
// dropdown that changes the URL and filters nothing.
const FILTERS = ['kind','status','owner','assignees','reviewers','priority',
                 'cycle','project','tags'];

// The menu option that means "this field is empty". Spelled here as a literal
// and in `index.NO_VALUE` in Python, because this block is a constant rather
// than a template — `test_empty_is_spelled_the_same_on_both_sides_of_the_wire`
// is what stops the two drifting, and a drift would filter differently in the
// browser than on the server with neither one erroring.
const NO_VALUE = '(none)';

function wanted(field) { return params.getAll(field).filter(Boolean); }

// --- the query language ----------------------------------------------------
//
// The second implementation of `query.py`, and it has to be a second one: the
// static export has no server to ask and this table filters without one. The
// two are pinned together by results rather than by source — a corpus of
// queries run through both in `tests/test_search.py` — because that is the only
// claim worth making about two parsers.
//
// Every rule here is argued in `query.py`. The short version: adjacency is AND,
// `not` binds tightest then `and` then `or`, an unknown field matches nothing
// rather than everything, and a query that cannot be read matches nothing and
// says why.

// The fields a query may name, and the alias each is asked by. Written out
// rather than derived from the row, because a row also carries `progress`,
// `derived` and eleven other things nobody would type — and because the same
// list exists in `index.py`, where `test_the_two_field_lists_are_the_same` holds
// the two together.
const QUERY_FIELDS = ['kind','status','owner','priority','cycle','assignees',
                      'reviewers','tags','project','id','title','prs','predicate'];
const ALIASES = {tag: 'tags', assignee: 'assignees', reviewer: 'reviewers',
                 pr: 'prs', person: 'owner'};
// Free text, matched by substring; everything else is a vocabulary and is
// matched whole, so `cycle:3` does not answer for cycle 30.
const FREE_TEXT = ['title', 'prs'];

// One record's values per field, lowered — the same map `query_fields` builds in
// `index.py`, so both parsers are asked about identical data and a disagreement
// between them is the language rather than the plan.
function queryFields(row) {
  const fields = {};
  for (const name of QUERY_FIELDS) {
    // `predicates` on the row, `predicate` in the language: the menu is named
    // for the question and the row for its answers.
    const held = name === 'predicate' ? row.predicates : row[name];
    fields[name] = [].concat(held ?? []).map(String).map(v => v.toLowerCase())
      .filter(v => v !== '');
  }
  return fields;
}

// `[text, wasQuoted]` per token, with the brackets as their own. Quoting is
// tracked and not forgotten: `"and"` is a word rather than the operator, and the
// colon inside `title:"a: b"` belongs to the value. The NUL marks the one colon
// that splits the term, found here rather than searched for again later.
function queryTerms(text) {
  const tokens = [];
  let i = 0;
  while (i < text.length) {
    if (/\s/.test(text[i])) { i++; continue; }
    if (text[i] === '(' || text[i] === ')') { tokens.push([text[i], false]); i++; continue; }
    let buffer = '', quoted = false, colon = -1;
    while (i < text.length && !/\s/.test(text[i]) && text[i] !== '(' && text[i] !== ')') {
      if (text[i] === '"') {
        const closes = text.indexOf('"', i + 1);
        if (closes < 0) throw new QueryError('a quote is opened and never closed');
        buffer += text.slice(i + 1, closes);
        quoted = true;
        i = closes + 1;
        continue;
      }
      if (text[i] === ':' && colon < 0) colon = buffer.length;
      buffer += text[i];
      i++;
    }
    tokens.push([colon < 0 ? buffer
      : buffer.slice(0, colon) + '\u0000' + buffer.slice(colon + 1), quoted]);
  }
  return tokens;
}

class QueryError extends Error {}

function queryTerm(raw, quoted) {
  const colon = raw.indexOf('\u0000');
  if (colon >= 0) {
    const name = raw.slice(0, colon).toLowerCase(), value = raw.slice(colon + 1);
    if (!name || !value)
      throw new QueryError('a field and a value both have to be there, as `field:value`');
    return {field: ALIASES[name] || name, value: value.toLowerCase()};
  }
  if (!raw) throw new QueryError('there is nothing between the quotes');
  return {word: raw.toLowerCase()};
}

function queryTree(text) {
  const tokens = queryTerms(text);
  let at = 0;
  const peek = () => at < tokens.length ? tokens[at] : null;
  const keyword = word => {
    const token = peek();
    return !!token && !token[1] && token[0].toLowerCase() === word;
  };
  const done = () => { const token = peek(); return !token || (token[0] === ')' && !token[1]); };

  function either() {
    let node = both();
    while (keyword('or')) {
      at++;
      if (done()) throw new QueryError('`or` needs something on both sides of it');
      node = {either: [node, both()]};
    }
    return node;
  }
  function both() {
    let node = unary();
    for (;;) {
      if (keyword('and')) {
        at++;
        if (done()) throw new QueryError('`and` needs something on both sides of it');
      } else if (done() || keyword('or')) {
        return node;
      }
      node = {both: [node, unary()]};
    }
  }
  function unary() {
    if (keyword('not')) {
      at++;
      if (done()) throw new QueryError('`not` needs something to take away');
      return {not: unary()};
    }
    const token = peek();
    if (!token) throw new QueryError('the query stops in the middle');
    if (token[0] === '(' && !token[1]) {
      at++;
      // Asked here and not left to the parse inside: `kind:task and (` is a
      // bracket somebody just opened, and being told the query stops in the
      // middle is true and useless.
      if (!peek()) throw new QueryError('a bracket is opened and never closed');
      if (peek()[0] === ')') throw new QueryError('there is nothing inside the brackets');
      const node = either();
      const closing = peek();
      if (!closing || closing[0] !== ')')
        throw new QueryError('a bracket is opened and never closed');
      at++;
      return node;
    }
    if (token[0] === ')' && !token[1])
      throw new QueryError('a bracket is closed that was never opened');
    const word = token[1] ? '' : token[0].toLowerCase();
    if (word === 'and' || word === 'or')
      throw new QueryError('`' + word + '` needs something on both sides of it');
    at++;
    return queryTerm(token[0], token[1]);
  }

  if (!tokens.length) return null;
  const node = either();
  if (peek() !== null) throw new QueryError('a bracket is closed that was never opened');
  return node;
}

function answers(node, fields, text) {
  if (node === null) return true;
  if ('word' in node) return text.includes(node.word);
  if ('not' in node) return !answers(node.not, fields, text);
  if ('both' in node)
    return answers(node.both[0], fields, text) && answers(node.both[1], fields, text);
  if ('either' in node)
    return answers(node.either[0], fields, text) || answers(node.either[1], fields, text);
  // A field this plan has not got: nothing, and not everything. Filter state is
  // hand-editable, and a typo that widens a result set is worse than one that
  // visibly empties it.
  if (!(node.field in fields)) return false;
  const held = fields[node.field];
  if (node.value === NO_VALUE) return !held.length;
  if (FREE_TEXT.includes(node.field)) return held.some(value => value.includes(node.value));
  return held.includes(node.value);
}

// Parsed once per query and not once per row: the table redraws on every
// keystroke over as many rows as the plan has, and parsing `kind:task` two
// hundred times to answer one question is two hundred parses.
let ASKED = {text: null, tree: null, error: ''};
function asked() {
  const text = params.get('q') || '';
  if (text === ASKED.text) return ASKED;
  try {
    ASKED = {text, tree: queryTree(text), error: ''};
  } catch (error) {
    if (!(error instanceof QueryError)) throw error;
    ASKED = {text, tree: null, error: error.message};
  }
  return ASKED;
}

// What is wrong with what is in the box, or '' if nothing is. The views draw
// this beside the rows: a query somebody is halfway through typing must not look
// like a plan with nothing in it.
function queryError() { return asked().error; }

// AND between fields, OR inside one: two owners means either of them, an owner
// and a status means both. Anything shaped like a table row can be asked — the
// graph hands it a node's data, which is that same row.
function matches(row) {
  // The query language, over `row.search` for a bare word — what is searchable is
  // decided once, by `SEARCH_FIELDS` in `index.py`, and shipped on the row. This
  // line used to read `row.title + ' ' + row.tags`, which is neither what
  // `apply_filters` searched nor what the placeholder promised: a table that
  // quietly searches less than the link you were sent is a table that lies twice.
  const query = asked();
  if (query.error) return false;
  if (!answers(query.tree, queryFields(row), row.search || '')) return false;
  for (const field of FILTERS) {
    const values = wanted(field);
    if (!values.length) continue;
    // `held` is empty for a field nobody has filled in, which no value in the
    // menu can ever match — so emptiness gets its own option, and it asks about
    // the list rather than looking inside it. Server-side `apply_filters` in
    // index.py answers the same question the same way; the sentinel is spelled
    // once, in `NO_VALUE` there, and reaches here through the template.
    const held = [].concat(row[field] ?? []).map(String).filter(v => v !== '');
    const empty = values.includes(NO_VALUE) && !held.length;
    if (!empty && !values.some(v => held.includes(v))) return false;
  }
  const preds = wanted('predicate');
  if (preds.length && !preds.some(p => row.predicates.includes(p))) return false;
  return true;
}

// The controls take their state from the query string rather than from
// themselves, so a filtered view somebody pasted to you opens with its dropdowns
// already set.
function syncFilters() {
  // Every control takes its state from the query string rather than from itself,
  // so a filtered view somebody pasted to you opens with its boxes already
  // ticked — and so a Clear is one `params.delete` rather than a sweep of the
  // DOM that has to find every control it drew.
  for (const facet of document.querySelectorAll('.facet[data-field]')) {
    const chosen = params.getAll(facet.dataset.field).filter(Boolean);
    for (const box of facet.querySelectorAll('input[type=checkbox]'))
      box.checked = chosen.includes(box.value);
    facet.querySelector('.facetsaid').textContent = facetSummary(facet, chosen);
    // The class the accent hangs off. On the wrapper and not the button, so a
    // field that is set reads as set whether its menu is open or closed.
    facet.classList.toggle('chosen', chosen.length > 0);
    // The button says what is set, and the button is also what a reader who
    // cannot see it hears — so the count goes in the accessible name too, and
    // not only in the ink.
    facet.querySelector('.facetopen').setAttribute(
      'aria-label', `${facetLabel(facet)}: ${facetSummary(facet, chosen)}`);
  }
  document.getElementById('q').value = params.get('q') || '';
  sayQueryError();
  showTheWayOut();
}

// Whether anything is set at all, asked of the query string rather than of the
// controls: the query string is the state, and the people page's `role` is a
// field the entity list below has never heard of.
function showTheWayOut() {
  const out = document.getElementById('unfilter');
  if (!out) return;
  const fields = [...document.querySelectorAll('.facet[data-field]')]
    .map(facet => facet.dataset.field);
  const set = [...fields, 'q', 'predicate']
    .some(field => params.getAll(field).filter(Boolean).length);
  out.hidden = !set;
}

function facetLabel(facet) {
  return facet.querySelector('.facetname').textContent.trim();
}

// `all`, the value itself, or how many.
//
// `facetSummary` and not `summarise`: the table already has a `summarise` that
// writes "17 of 17 shown", and these two scripts are two `<script>` blocks in one
// global scope. The first version of this function was named that, and the table's
// won — so every field's button said `undefined` while nothing threw. Everything
// this block declares is named for the bar for that reason; see
// `test_no_two_scripts_on_a_page_declare_the_same_name`. One value is named because naming it is
// the whole point of a closed control saying anything; three are counted because
// three tag names do not fit in a button on a bar of ten of them.
//
// The word comes off the checkbox the server drew rather than from a map: this
// script is shared by five pages and `HUMAN` is the table's payload, so a `human`
// of its own here would be the same vocabulary written twice — and `in_progress`
// would read as itself on the one page that had not been given the map.
function facetSummary(facet, chosen) {
  if (!chosen.length) return 'all';
  if (chosen.length > 1) return `${chosen.length} chosen`;
  const box = facet.querySelector(`input[type=checkbox][value="${CSS.escape(chosen[0])}"]`);
  return box ? box.parentNode.textContent.trim() : chosen[0];
}

// The half of "a malformed query says so and matches nothing" that says so. The
// other half is `matches`, which keeps every row out — and on its own that is a
// plan that looks empty, which is the failure this repository keeps finding in
// new places.
function sayQueryError() {
  const where = document.getElementById('query-error');
  if (!where) return;
  const said = queryError();
  where.textContent = said;
  where.hidden = !said;
}

// replaceState rather than pushState: a filter is not a page you want to walk
// back out of one dropdown at a time. The view redraws on the event instead of
// being called from here, because each one draws something different out of the
// same answer.
function settled() {
  history.replaceState(null, '', '?' + params.toString());
  syncFilters();
  dispatchEvent(new Event('openproj:filter'));
}

function update(field, value) {
  if (value) params.set(field, value); else params.delete(field);
  settled();
}

// One value of one field, on or off, leaving the field's other values alone.
// `delete` then `append` per value rather than a `set`, because `set` is the one
// value a select could hold and this control's whole point is that a field can
// be asked about twice.
function chooseValue(field, value, wanted) {
  const chosen = params.getAll(field).filter(Boolean).filter(v => v !== value);
  if (wanted) chosen.push(value);
  params.delete(field);
  for (const one of chosen) params.append(field, one);
  settled();
}

function clearFilters() {
  // Every control the page actually draws, and not only the entity fields above:
  // the people page filters by role, which is not a field of an entity, and a
  // Clear that left it set is a Clear that did not clear.
  const onPage = [...document.querySelectorAll('.facet[data-field]')]
    .map(facet => facet.dataset.field);
  // Not the sort order: clearing the filters and losing the column somebody
  // sorted by is a second surprise on top of the one they were undoing.
  for (const field of [...FILTERS, ...onPage, 'predicate', 'q']) params.delete(field);
  settled();
}

document.getElementById('q').addEventListener('input', e => update('q', e.target.value));
const UNFILTER = document.getElementById('unfilter');
if (UNFILTER) UNFILTER.onclick = clearFilters;

// --- opening and closing a field -------------------------------------------
//
// One listener on the bar rather than one per control: the bar is drawn once by
// the server and never rebuilt, but a listener per checkbox on a plan with two
// hundred tags is two hundred listeners for a thing that can be asked once.

const FACET_BAR = document.getElementById('controls');

function openFacet(facet, open) {
  facet.querySelector('.facetmenu').hidden = !open;
  facet.querySelector('.facetopen').setAttribute('aria-expanded', String(open));
}

function closeFacets(except) {
  for (const facet of document.querySelectorAll('.facet[data-field]'))
    if (facet !== except) openFacet(facet, false);
}

if (FACET_BAR) {
  FACET_BAR.addEventListener('click', event => {
    const opener = event.target.closest('.facetopen');
    if (opener) {
      const facet = opener.closest('.facet');
      const open = opener.getAttribute('aria-expanded') !== 'true';
      closeFacets(facet);
      openFacet(facet, open);
      return;
    }
    // A click anywhere else inside the bar that is not in a menu closes the
    // menus: the labels and the search box are in here too.
    if (!event.target.closest('.facetmenu')) closeFacets(null);
  });

  FACET_BAR.addEventListener('change', event => {
    const box = event.target.closest('.facetmenu input[type=checkbox]');
    if (box) chooseValue(box.closest('.facet').dataset.field, box.value, box.checked);
  });

  // Escape closes the menu and hands the keyboard back to the button that opened
  // it. Without the second half, Escape drops focus on `<body>` and the next Tab
  // starts from the top of the page — which is the same defect the draft row's
  // Escape had, in a different control.
  FACET_BAR.addEventListener('keydown', event => {
    if (event.key !== 'Escape') return;
    const facet = event.target.closest('.facet');
    if (!facet || facet.querySelector('.facetmenu').hidden) return;
    event.stopPropagation();
    openFacet(facet, false);
    facet.querySelector('.facetopen').focus();
  });
}

// Outside the bar entirely. `pointerdown` and not `click`, so a menu that is over
// the thing somebody is reaching for is gone before the press lands on it.
addEventListener('pointerdown', event => {
  if (!event.target.closest('.facet')) closeFacets(null);
});

syncFilters();
</script>
""")

_TABLE = """
{#- Announced, not drawn: the lit nav item says this already. See `.sr-only`. -#}
<h1 class="sr-only">Table</h1>
{#- Both of these used to be on the rendered files too, where `links.new` is the
    empty string — so the button was a link back to the page you were already on,
    and the hint promised an editor that has no server to save to. A read-only
    export must not offer a control that cannot work: the first time one of them
    does nothing is the moment the rest of the page stops being believed. -#}
{#- The count rides at the far end of this row rather than owning one below it,
    which is the same move the graph and the timeline make — there it is the key's
    row, here it is the page's own controls, because the table has no key and this
    is the last row it has to offer. The instruction beside New entity was already
    inline and already costs nothing, so it stays where it is: it belongs next to
    the control it shares a subject with. -#}
{#- Three gestures in one line, because a page that teaches them one at a time
    teaches the third to nobody: a drag has no name written on it anywhere, and
    the grip beside an id is 8px of dotted rule. The `+` row at the bottom says
    what it is by being a control. -#}
<p class="editbar">{% if editable %}<a class="button" href="{{ links.new }}">New entity</a>
   <span class="hint">double-click a cell, or press Enter on it, to edit it ·
     drag a row by the grip beside its id onto another to file it there</span>
   {% endif %}<span id="state" role="status"></span><span id="summary">
  {#- Two numbers, because the count is of problems and the link filters
      entities: "3 blocking problems" opening a table of 2 rows is the exact way
      a count stops being believed. The second number is the one the link keeps
      its promise about. -#}
  <a id="blockers" href="?predicate=has_blocker"><strong id="blocker-count">{{ blockers
    }}</strong> <span id="blocker-word">blocking problem{{
    "" if blockers == 1 else "s" }}{% if blockers %} on {{ blocked }} {{
    "entity" if blocked == 1 else "entities" }}{% endif %}</span></a> ·
  {# Both numbers are written by the script as well as rendered here. The second
     used to be the template's alone, which was true until the page could add a
     row to the plan without reloading: creating one read "18 of 17 shown", and a
     count that contradicts itself inside one sentence is the whole of what a
     count is for.
     Neither delimiter here strips the whitespace around it, unlike every other
     comment in this file: the separator above is a lone middle dot at the end of
     its line, and eating that newline glued it to the digit — the bar read
     "0 blocking problems ·9". A comment must not be able to do that. #}
  <span id="shown" class="num">{{ payload.rows|length }}</span> of <span
    id="total">{{ payload.rows|length }}</span> shown</span></p>
{{ facets }}
{#- role="grid" only where the cells are editable. It is a claim about who owns
    the arrow keys — a screen reader hands them to the page inside a grid and
    keeps them for its own cursor inside a table — and on a rendered file there
    is no editor for them to reach. -#}
<div class="table-scroll" data-fills><table id="rows"{% if editable %} role="grid"{%
  endif %}><thead><tr>
  {#- A real button inside every sortable header, not a click handler on the cell:
      there is no way to tab to a table cell, so sorting was mouse-only. The
      columns that cannot be sorted have no button, which is the difference said
      out loud. data-col names the field the column stands for, so the narrow
      breakpoint and the sticky rules pick columns by name rather than by
      counting them — and so does the remembered width, which is why the header
      word is free to be the reader's word rather than the field's. -#}
  {% for column, sortable in columns %}
  {%- if sortable %}<th data-col="{{ column }}" data-sort="{{ column }}" aria-sort="none"
    ><button type="button">{{ label(column) }}<span class="dir"
      aria-hidden="true"></span></button></th>
  {%- else %}<th data-col="{{ column }}">{{ label(column) }}</th>{% endif %}
  {%- endfor %}
</tr></thead><tbody></tbody></table></div>
{% if editable %}
<input type="hidden" name="base_commit" id="base" value="{{ base_commit }}">
{#- A conflict is the one answer that means the save did not land. It was a
    box that appeared, and nothing more. -#}
<div id="row-conflict" role="status" aria-live="polite" hidden></div>
{#- What the status about to be saved demands and the row has not got. A panel
    and not a column: `assigned_on` beside `start` and `end` is a third date on a
    row that already carries two derived ones, and the question is only ever
    asked at the moment the status moves. -#}
<div id="askfor" hidden></div>
{% endif %}
<script id="payload" type="application/json">{{ payload|tojson }}</script>
{% if editable %}{{ combobox }}{% endif %}
{{ filters }}
<script>
// A payload that did not survive the trip is a third kind of empty, and it used
// to look exactly like the other two: a header row over a void. A truncated
// response is a different thing to do next from an empty plan, so the page has
// to be able to tell them apart rather than rendering nothing three ways.
let DATA = null;
try {
  DATA = JSON.parse(document.getElementById('payload').textContent);
} catch (error) { DATA = null; }
const LOADED = DATA !== null;
if (!LOADED) DATA = {rows: {}, problems: [], choices: {}, suggests: {}, human: {},
                     labels: {}, editable: null};

const tbody = document.querySelector('#rows tbody');
const HUMAN = DATA.human;
const FIELD_LABELS = DATA.labels;

// The reader's word for a stored identifier. Anything unknown comes back
// unchanged, so a status added to the model still renders — badly, but it
// renders, which beats a blank cell.
const human = value => HUMAN[value] ?? (value ?? '');

// `esc` comes from the shell, which declares it before this script runs. It was
// declared here as well as in the timeline, and the third page that needed it —
// the combobox, on four pages — had neither copy in scope.

// The same list the header row above was drawn from, emitted rather than
// retyped: these were two literals that had to stay index-parallel, with a
// comment asking whoever edited one to remember the other, and nothing enforcing
// it at runtime. One column out of step shifts every cell one column left.
const keys = {{ columns|map(attribute=0)|list|tojson }};

// Which column carries a complaint about a field the table has no column for.
// Anything still unplaced falls to the id cell, because a row that says
// something is wrong and will not say what is worse than no marker at all.
const MARK_COLUMN = {person_weeks: 'size', depends_on: 'blocked_by'};
const SEV_CLASS = {blocker: 'blocker', warning: 'warn'};

let MARKS = {};     // entity id -> column -> {severity, messages}
let TROUBLE = {};   // entity id -> the worst severity found on it
let BLOCKERS = 0;   // blocking problems
let BLOCKED = 0;    // entities carrying at least one of them — what the link opens

// The problems arrive flat, exactly as the validator produced them, and are
// grouped here rather than on the server: /api/index.json hands back the same
// flat list after a save, so one grouping serves both and the after-a-save path
// cannot drift from the at-load one.
function regroup(problems) {
  MARKS = {};
  TROUBLE = {};
  BLOCKERS = problems.filter(problem => problem.severity === 'blocker').length;
  for (const problem of problems) {
    const id = problem.entity_id;
    if (problem.severity === 'blocker' || !TROUBLE[id]) TROUBLE[id] = problem.severity;
    const column = MARK_COLUMN[problem.field]
      || (keys.includes(problem.field) ? problem.field : 'id');
    const columns = MARKS[id] || (MARKS[id] = {});
    const mark = columns[column]
      || (columns[column] = {severity: problem.severity, messages: []});
    if (problem.severity === 'blocker') mark.severity = 'blocker';
    mark.messages.push(problem.message);
  }
  // Two predicates are read straight off this list (index.py,
  // `_matches_predicate`), so they are the two a save can change. Recomputed
  // here, filling in a missing owner takes the row out of the filter that caught
  // it instead of leaving it there until somebody reloads.
  for (const [id, row] of Object.entries(DATA.rows)) {
    row.predicates = row.predicates
      .filter(name => name !== 'missing_required_fields' && name !== 'has_blocker');
    if (MARKS[id]) row.predicates.push('missing_required_fields');
    if (TROUBLE[id] === 'blocker') row.predicates.push('has_blocker');
  }
  // Counted off the same pass that decides the predicate, so the number beside
  // the link and the rows behind it cannot come apart.
  BLOCKED = Object.values(TROUBLE).filter(severity => severity === 'blocker').length;
}

function summarise() {
  document.getElementById('blocker-count').textContent = BLOCKERS;
  // How many rows there are to be shown *of*. It moves when a row is created
  // here, which is the only thing that changes it without a reload.
  document.getElementById('total').textContent = Object.keys(DATA.rows).length;
  // The count is of problems and the link filters entities. One entity can hold
  // three of them, so the population the link opens is named as well — a count
  // that opens a table of a different size is a count nobody trusts again.
  document.getElementById('blocker-word').textContent = BLOCKERS
    ? `blocking problem${BLOCKERS === 1 ? '' : 's'} on ${BLOCKED} ` +
      `${BLOCKED === 1 ? 'entity' : 'entities'}`
    : 'blocking problems';
  // Danger at zero is danger nobody reads. A plan with nothing wrong with it was
  // shouting in the same colour as one that is on fire.
  document.getElementById('blockers').classList.toggle('none', BLOCKERS === 0);
}

// What the cell holds, as opposed to what it shows. A status cell shows a chip
// reading "In progress" and a tags cell shows one tag and a count; both used to
// be read back off the DOM when the editor opened, which would now save the
// label in place of the value.
function stored(row, key) {
  const value = row[key];
  return Array.isArray(value) ? value.join(', ') : (value ?? '');
}

// Why a computed column refuses a double-click. A cell that silently ignores one
// is indistinguishable from a cell that is broken, and every one of these is the
// scheduler's output: typing over a forecast is how a plan stops being believed.
// Shipped from `_TABLE_WHY`, which is also the list of columns the payload
// withholds an editor for — written out again here, a fifth derived column would
// have arrived with no class and no sentence.
const WHY = {{ why|tojson }};

// Which kind may hold which — `model.PARENT_KINDS`, shipped rather than retyped.
// It decides three things on this page: which rows grow a handle, which rows
// light up as a drop would land, and which refuse before anything is sent.
const PARENT_KINDS = DATA.parent_kinds || {};
// Whether this row has anywhere to go. A project belongs to nothing, so it can
// neither be filed under something nor taken out of it, and every control that
// would say otherwise is left undrawn rather than drawn and then refused.
const movable = row => (PARENT_KINDS[row.kind] || []).length > 0;
// What a kind may be filed under, in the validator's own words. `a pitch or a
// project`, `nothing` — the sentence `_containment_problems` builds when it has
// already happened, said here before it can.
const holders = kind =>
  (PARENT_KINDS[kind] || []).map(one => 'a ' + one).join(' or ') || 'nothing';
const moveTip = row => movable(row)
  ? `Drag by the grip, or press Enter, to file this under ${holders(row.kind)}`
  : `A ${row.kind} belongs to nothing, so there is nothing to file it under`;
// The handle itself. Two dotted rules drawn by the stylesheet and not a glyph:
// `⠿` is the conventional one and is not in the vendored face's latin subset, so
// on a machine with no webfont it is a tofu box — which is the same argument
// STATUS_GLYPH settles the other way, because those five had to be text.
// `aria-hidden`, because the keyboard does not reach for this: the cell it sits
// in is the tab stop and Enter on that cell is the same move (see `startMoving`).
const GRIP = '<span class="rowgrip" draggable="true" aria-hidden="true"></span>';

// Five tags wrapped to five lines and every row on screen grew to match, so one
// line and a count. The count is exact: "+2" means two you cannot see, not two
// the browser might have fitted in anyway.
//
// Written for tags, then needed again the moment tags were fixed: a task with
// three merged PRs is 128px tall against a 50px row, so the column that sets the
// height of the plan had simply moved one to the left. Any list in a cell has
// this shape, so the clamp takes rendered pieces and the noun to count them by.
//
// `pieces` are already markup — a caller hands it `list.map(esc)` or
// `list.map(prLink)` — which makes this the one function here that must NOT
// escape what it is given. Everything it adds of its own is a literal or a
// count, so nothing else on this line can carry stored text.
//
// The one visible piece is wrapped even when there is no badge beside it, because
// the wrapper is what can be given an ellipsis: the badge is the promise the
// clamp makes — "there are two more, here is where they are" — and it was the
// part being cut, by a third of itself under about 128px and by 368px on a
// sixty-character login. `.first` is the flex item that shrinks; the badge never
// does. See `td.clamp` in the stylesheet.
//
// Both words for the thing being counted, because the badge names a number of
// them and `+1` is as ordinary as `+4`. It used to be the singular and an `s`,
// which is how the control offering to show two more people offered "2 more
// persons".
//
// The badge is a *toggle*: `classList.add('open')` was the whole of the reveal
// and nothing anywhere took the class off again, so an expanded cell could only
// be collapsed by reloading the page. One cell is cheap enough to live with;
// with the column control beside it, one click opens seventeen and a one-way
// control that doubles the height of the table is a trap. So it carries both of
// its names — a control says exactly what it will do, and what this one will do
// changes with the cell it is in — and the sign in front of the count is drawn
// by the stylesheet from the same class that opens the cell, which is how the
// glyph and the state cannot come apart.
function clamped(pieces, one, many) {
  if (!pieces.length) return '';
  const [first, ...rest] = pieces;
  const shown = `<span class="first">${first}</span>`;
  if (!rest.length) return shown;
  const word = rest.length === 1 ? one : many;
  const expand = `Show ${rest.length} more ${word}`;
  return `${shown}<span class="rest">, ${rest.join(', ')}</span>` +
    `<button type="button" class="more" aria-label="${expand}" data-expand="${expand}"` +
    ` data-collapse="Show ${rest.length} fewer ${word}">${rest.length}</button>`;
}

function shown(row, key) {
  const value = row[key];
  // The title is the way into the shaping doc; the id is the way to cite it.
  // A cell can be a link and still be editable. Making everything editable first
  // is what silently turned the PR column into plain text.
  if (key === 'title') return `<a href="{{ links.entity }}${esc(row.id)}">${esc(row.title)}</a>`;
  if (key === 'prs') return clamped((value || []).map(prLink), 'pull request', 'pull requests');
  // No kind chip here. `pitch-0c0001` already says pitch, in a prefix the model
  // guarantees agrees with the kind, so the chip was restating the first word of
  // the cell it sat in — seventeen times, in a column that is otherwise the
  // narrowest thing on the row. The id string is not boxed in its place either:
  // it is monospace, which is already what marks it as a token to be cited, and a
  // border round every id is the same noise wearing a different hat. Kind stays
  // filterable in the KIND facet, which is where "show me only tasks" is asked,
  // and stays a chip on the detail, people and cycle pages, where no id is
  // present to carry it.
  //
  // The grip in front of it is where a row is picked up from. Not the row
  // itself: a `draggable` row cannot have its text selected, and an id is the
  // one thing on this page people copy out of it — and the cell editor puts an
  // `<input>` inside a cell, which a draggable ancestor interferes with. So the
  // handle is a thing of its own, in the column that is the row's own name, and
  // it is in the frozen pair, so it is on screen however far the table is
  // scrolled sideways. A row that can go nowhere gets none: a project is the top
  // of the tree, and the missing handle is that said without a sentence.
  if (key === 'id')
    return (EDITABLE && movable(row) ? GRIP : '') + `<span class="eid">${esc(row.id)}</span>`;
  if (key === 'status')
    return `<span class="chip ${stClass(row.status)}">${esc(human(row.status))}</span>`;
  if (key === 'priority') return esc(human(row.priority));
  // Counted out of the body's own checklist. Empty where there is no checklist,
  // rather than "0/0" — a body nobody has written a list in has no progress to
  // report, which is not the same as no progress.
  if (key === 'progress')
    return row.progress === null ? '' :
      `${esc(row.progress_text)}<span class="meter"><span style="width: ` +
      `${Math.round(row.progress * 100)}%"></span></span>`;
  if (key === 'tags') return clamped((value || []).map(esc), 'tag', 'tags');
  // Nobody named here, and somebody named underneath: a pitch whose tasks each
  // have a reviewer is reviewed, and the validator has stopped asking it for one
  // of its own. Drawn rather than left blank, because a column that is empty on
  // the row and answered a level down is a column that reads as a gap.
  if (key === 'reviewers' && !(value || []).length && (row.reviewers_from || []).length)
    return clamped(row.reviewers_from.map(esc), 'person', 'people');
  // Every list in the table clamps, for the same reason and by the same badge.
  // These two were the last that did not, and they were most of the wrapping
  // left: `OngChia, nfarabullini, jcanton` took three lines in a 159px column and
  // the whole row grew to match, which is the defect the tags clamp was written
  // for. The owner is the name that matters and it has its own column; the rest
  // are one click away, where they always were.
  if (key === 'assignees' || key === 'reviewers')
    return clamped((value || []).map(esc), 'person', 'people');
  // Unreachable for `reviewers`, which is handled above — kept as one line so
  // the two list columns stay one branch.
  return esc(stored(row, key));
}

// What a clamped cell is not showing, in words, for the cell's own tooltip.
//
// Four columns draw one value and a `+N`, and the only way to read the rest was
// to click the badge — while hovering the cell answered a question nobody had
// asked, "Double-click to edit assignees". So the answer to the question they did
// ask goes first. The badge is untouched: this adds a way to *read* the hidden
// values, it does not replace the way to reveal them.
//
// Capped, because a native tooltip has no scrollbar and cannot be scrolled: sixty
// tags in one is a wall of text with the instruction lost at the bottom of it. The
// cap is on characters rather than on a count, because the values differ by an
// order of magnitude in width — `ci` and `C2SM/icon4py#1223` are both one item —
// and what has to fit is a line, not a number of things. At least one always
// prints, however long it is, or a single very long value would come back as
// nothing but a count of itself.
const TIP_CHARS = 160;
function hiddenBy(row, key) {
  if (!CLAMPED.has(key)) return '';
  // The stored values, not the rendered ones: a PR cell draws `#1223` because the
  // repository never varies, but a tooltip has room to say which one it is.
  const rest = [].concat(row[key] ?? []).map(String).slice(1);
  if (!rest.length) return '';
  const fits = [];
  let length = 0;
  for (const value of rest) {
    if (fits.length && length + value.length + 2 > TIP_CHARS) break;
    fits.push(value);
    length += value.length + 2;
  }
  const over = rest.length - fits.length;
  // `+2 more`, in the badge's own words, so the line reads as the answer to the
  // badge the reader is looking at rather than as a list from nowhere.
  return `+${rest.length} more: ${fits.join(', ')}${over ? ` … and ${over} not shown` : ''}`;
}

// The four shapes a level of the tree can be drawn as. An allowlist and not a
// pass-through, because `treeHtml` is called a second time with a value read
// back off the DOM — see `openEditor` — and this page's rule is that a value
// crossing back into markup is checked against what it is allowed to be rather
// than against what it must not.
const TREE_RUNGS = new Set(['line', 'blank', 'tee', 'end']);

// One space-separated rung name per level, as the drawing. One function, because
// the cell editor has to put the drawing back: `openEditor` replaces the whole
// of a cell's contents with an input, and a connector that disappears for as
// long as somebody is typing a title reads as the tree having lost the row.
function treeHtml(rungs) {
  const each = String(rungs || '').split(' ').filter(one => TREE_RUNGS.has(one));
  if (!each.length) return '';
  return '<span class="tree" aria-hidden="true">' +
    each.map(one => `<span class="rung ${one}"></span>`).join('') + '</span>';
}

function cell(row, key, place) {
  const mark = (MARKS[row.id] || {})[key];
  const note = mark ? mark.messages.join(' · ') : '';
  const ground = mark ? 'sev-cell-' + SEV_CLASS[mark.severity] : '';
  // role="img" with a name, not a bare character: the message was reachable only
  // by hovering the row, and a tooltip is not something a table gets hovered for.
  const glyph = mark
    ? ` <span class="sev-mark sev-mark-${SEV_CLASS[mark.severity]}" role="img"` +
      ` aria-label="${esc(note)}" title="${esc(note)}">⚠</span>`
    : '';
  // A clamped cell is one line laid out in a row: the value, which gives up
  // width, and then the badge and the severity glyph, which do not. The wrapper
  // is what makes that a row — a `td` cannot be the flex container itself
  // without ceasing to be a table cell — and it holds the glyph too, or the mark
  // that says which cell is wrong drops to a second line and takes the row's
  // height with it.
  // The tree, in the column that holds the row's own words. Not the id column
  // beside it: an id is a token to be cited, monospace and the same width on
  // every row, and indenting it would make the one column that is a straight
  // list of names into a ragged one. The title is a sentence and already ragged.
  //
  // `aria-hidden`, and it is a wrapper around empty spans rather than characters:
  // there is nothing here to read out. A screen reader gets the tree from the
  // rows themselves — the parent is a field of the record and the title opens it
  // — and what it would get from the drawing is "box drawings light up and
  // right" in front of every child's title.
  //
  // Drawn first inside the cell and taken out of flow by the stylesheet, so the
  // link keeps the whole of the cell's content box: the indent is padding on the
  // cell, which is what puts it in the fit's measurement of the column.
  const rungs = key === 'title' && place ? place.rungs.join(' ') : '';
  const body = treeHtml(rungs) + (CLAMPED.has(key)
    ? `<span class="clamped">${shown(row, key)}${glyph}</span>`
    : shown(row, key) + glyph);
  const editable = EDITABLE && key in EDITABLE;
  // One class list rather than three returns. The tags clamp used to be written
  // only into the editable branch, so on a rendered file the column kept the
  // reveal button and showed every tag beside it anyway.
  const classes = [
    editable ? 'edit' : '',
    !editable && key in WHY ? 'derived' : '',
    CLAMPED.has(key) ? 'clamp' : '',
    // Inherited, not typed. The ground says the value came from the work under
    // this record rather than from its own file, which is the difference between
    // "these are the reviewers" and "these are the reviewers, and changing them
    // means changing the tasks".
    key === 'reviewers' && !(row.reviewers || []).length
      && (row.reviewers_from || []).length ? 'inherited' : '',
    ground,
  ].filter(Boolean).join(' ');
  const named = (FIELD_LABELS[key] || key).toLowerCase();
  // Three lines at most, in the order of what a reader wants: what is wrong here,
  // what is hidden here, what can be done here. A native `title` takes newlines,
  // so they are three lines and not a run-on sentence.
  //
  // The problem no longer *replaces* the rest, it goes first. It used to be the
  // whole tooltip, which meant that a cell with a blocker on it and a `+2` beside
  // it answered neither "who are the other two" nor "how do I fix this" — and the
  // fix for most of these problems is to edit the cell the sentence is on.
  //
  // A cell hiding nothing gets no second line: every tooltip in the table growing
  // a redundant sentence is how a tooltip stops being read at all.
  //
  // The id column's line is what the handle beside it cannot say: a drag is a
  // gesture with no name on it, and the same cell is where Enter picks the row
  // up. A row that can go nowhere says that instead, which is also why it has no
  // handle to explain.
  const tip = [note, hiddenBy(row, key),
               key === 'reviewers' && !(row.reviewers || []).length
                 && (row.reviewers_from || []).length
                 ? 'From the work filed under this record. Editing names reviewers of its own.'
                 : '',
               editable ? 'Double-click to edit ' + named
                        : key === 'id' && EDITABLE ? moveTip(row) : WHY[key] || '']
    .filter(Boolean).join('\\n');
  // Reachable without a mouse. This table is the app's primary editing surface
  // and it was double-click-only, so half the room could not change a single
  // field on it. `-1` rather than `0`: `rove()` promotes exactly one cell, so
  // the grid is one tab stop with the arrows moving inside it — fourteen columns
  // times forty rows is 560 stops if every cell takes one, which is not a
  // keyboard path, it is a maze.
  //
  // The id cell joins them, and it is not editable: it is the one place a move
  // can be started without a mouse, and a gesture that only a mouse can make is
  // a gesture half the room does not have.
  const reachable = EDITABLE && (editable || key in WHY || key === 'id');
  // `row.id` is escaped like anything else here. An id that fails its pattern is
  // a *reported* blocker and not a refusal, so the entity still loads and still
  // draws a row: one shaped `task-000001"><img src=x onerror=…>` put ten
  // elements into the table body while the text beside them read correctly.
  return `<td data-col="${key}"` +
    `${editable ? ` data-entity="${esc(row.id)}" data-field="${key}"` : ''}` +
    `${!editable && key in WHY ? ` data-why="${esc(WHY[key])}"` : ''}` +
    `${rungs ? ` data-rungs="${esc(rungs)}"` : ''}` +
    `${reachable ? ' tabindex="-1"' : ''}` +
    ` class="${classes}"${tip ? ` title="${esc(tip)}"` : ''}>${body}</td>`;
}

// `#1223`, not `C2SM/icon4py#1223`. Every reference in a plan is to the repository
// the plan is about, so the owner and the name were seventeen rows of the same
// eleven characters — the widest column on the page spent on the part that never
// varies. It cost the sentence beside it: `title` was squeezed to its floor while
// `prs` kept 172px, and at the window this was reported on the table still would
// not fit. The whole reference is in the link's title, and the detail page prints
// it in full, so nothing is lost — a plan that does span two repositories reads a
// little thinner here and exactly the same everywhere else.
function prLink(ref) {
  const [repo, number] = ref.split('#');
  return `<a href="https://github.com/${esc(repo)}/pull/${esc(number)}"` +
    ` title="${esc(ref)}">#${esc(number)}</a>`;
}

function rowHtml(place) {
  const row = place.row;
  // The stripe says "something on this row is wrong" before a single cell is
  // read; the glyph in the cell says which thing. The message used to live only
  // in a native tooltip on the row, where it was found by accident or not at all.
  // Both survive the dimming below: a row kept only as context can still be the
  // row with the problem on it.
  const worst = TROUBLE[row.id];
  const classes = [
    worst ? 'sev-row-' + SEV_CLASS[worst] : '',
    place.depth ? 'd' + place.depth : '',
    place.context ? 'context' : '',
    // A write this row is waiting on. Against a plan on the other side of the
    // world that is a fetch, a commit and a push — seconds — and for all of them
    // the page said nothing at all and the row sat where it was, which reads as
    // a drop that did not take.
    row.id === WRITING ? 'writing' : '',
  ].filter(Boolean).join(' ');
  return `<tr data-id="${esc(row.id)}"${classes ? ` class="${classes}"` : ''}>` +
    keys.map(key => cell(row, key, place)).join('') + '</tr>';
}

// Three ways for a table to be empty, and they rendered identically: a header
// row over nothing, which reads as a broken app whichever one it is. Which one
// it is decides what to do next, so the table says which one it is.
function emptyRow() {
  let headline = 'No entity matches these filters.';
  let detail = 'Every row is filtered out by the controls above.';
  let clearable = true;
  if (!LOADED) {
    headline = 'The plan could not be loaded.';
    detail = 'This page arrived without its data, so there is nothing to filter or sort.';
    clearable = false;
  } else if (!Object.keys(DATA.rows).length) {
    headline = 'This plan has no entities yet.';
    detail = 'Nothing has been pitched, shaped or scheduled.';
    clearable = false;
  } else if (queryError()) {
    // A fourth way to be empty, and the only one the reader caused a keystroke
    // ago. Said here as well as in the bar because this is where the rows were:
    // one sentence, from one function, in the two places a person is looking.
    headline = 'That search cannot be read.';
    detail = esc(queryError()) + '.';
  }
  return `<tr class="nothing"><td colspan="${keys.length}">` +
    `<p class="headline">${headline}</p><p class="hint">${detail}</p>` +
    (clearable ? '<button type="button" id="clear-filters">Clear filters</button>' : '') +
    '</td></tr>';
}

// --------------------------------------------------------------------------
// The tree
//
// A plan is a tree — a project holds pitches, a pitch holds tasks, and a task
// can hang straight off a project — and the table drew it as a flat list of
// seventeen rows sorted by id, which is the tree's own order with the shape
// rubbed off it. Three things put the shape back, and each is narrower than it
// first looks.
// --------------------------------------------------------------------------

// The deepest indent drawn. `PARENT_KINDS` bounds the real answer at two — a
// task under a pitch under a project — and a task hanging off a project is one,
// so this is a cap on a hand-edited file rather than a design for four levels.
// A row deeper than this is drawn at this depth: the indent is a hint about
// where a row sits, and it is not worth a title column's width to be exact about
// a shape the validator is already complaining about.
const TREE_DEPTH = 3;

// Every ancestor of every match, whether or not it matched.
//
// An entity that is not an answer to what was asked but *holds* one stays on the
// table, dimmed: filtering to `owner=ann` and getting three tasks with no pitch
// over them is a list of tasks, not a plan, and the row that says which pitch
// they are part of is the one a person is about to want. It is a record like any
// other while it is there — its title still opens it, its cells still edit — it
// simply is not an answer, and `summarise` never counts it as one.
function withAncestors(rows) {
  const kept = new Map(rows.map(row => [row.id, row]));
  for (const row of rows) {
    // Guarded, because a parent chain somebody hand-edited into a loop is a hang
    // rather than a blocker, and the page would take the whole plan with it.
    const seen = new Set([row.id]);
    let at = DATA.rows[row.parent];
    while (at && !seen.has(at.id)) {
      seen.add(at.id);
      kept.set(at.id, at);
      at = DATA.rows[at.parent];
    }
  }
  return [...kept.values()];
}

// Roots in id order, children in id order under each root, depth first.
//
// A childless project sits exactly where its id puts it: this is one rule and
// not five buckets, and "projects with children, then projects without" would be
// a second ordering nobody asked for on top of the one that is on screen.
//
// Descending reverses the siblings at every level and never the walk: a tree
// with the children above their parent is not the same tree upside down, it is a
// list of rows in an order that means nothing.
function ordered(rows, descending) {
  const by = new Map(rows.map(row => [row.id, row]));
  const kids = new Map();
  const roots = [];
  for (const row of rows) {
    const parent = by.has(row.parent) ? row.parent : null;
    if (parent) kids.set(parent, (kids.get(parent) || []).concat(row.id));
    else roots.push(row.id);
  }
  const order = ids =>
    [...ids].sort((a, b) => a.localeCompare(b) * (descending ? -1 : 1));
  const out = [];
  const drawn = new Set();
  const walk = (id, depth) => {
    if (drawn.has(id)) return;
    drawn.add(id);
    out.push({row: by.get(id), depth: Math.min(depth, TREE_DEPTH), rungs: [], context: false});
    for (const child of order(kids.get(id) || [])) walk(child, depth + 1);
  };
  for (const id of order(roots)) walk(id, 0);
  // A loop in the parent chain leaves its members with no root to be reached
  // from. They are drawn flat at the end rather than dropped: a row missing from
  // the table is a row nobody can use the table to fix the loop with.
  for (const id of order(by.keys())) walk(id, 0);
  return out;
}

// Which connector each row draws, computed from the rows that are actually being
// drawn and never from the plan.
//
// That is the whole of this function's difficulty. A pitch whose last task the
// filter removed would otherwise keep a `├─`, promising a sibling under a row
// that ends the branch, and the row above the gap would carry a `└─` that is
// simply untrue. What is on screen is what the connectors describe.
//
// `line` is a level whose branch continues past this row, `blank` one whose
// branch is finished, `tee` a child with a sibling still to come and `end` the
// last child drawn. They are class names: the glyphs are drawn as borders in the
// stylesheet, because `├─` and `└─` only line up in a monospace face — this
// column is proportional — and a screen reader says "box drawings light up and
// right" before every child's title.
function connectors(placed) {
  // Whether each row is the last one drawn at its own level. Depth first means a
  // row's own subtree is the run of deeper rows after it, so the next row that
  // is not deeper answers it.
  const last = placed.map((one, i) => {
    for (let j = i + 1; j < placed.length; j++) {
      if (placed[j].depth < one.depth) return true;
      if (placed[j].depth === one.depth) return false;
    }
    return true;
  });
  const continues = [];
  placed.forEach((one, i) => {
    const rungs = [];
    for (let level = 1; level < one.depth; level++)
      rungs.push(continues[level] ? 'line' : 'blank');
    if (one.depth) rungs.push(last[i] ? 'end' : 'tee');
    continues[one.depth] = !last[i];
    one.rungs = rungs;
  });
}

function draw() {
  const sort = params.get('sort') || 'id';
  const descending = params.get('desc') === '1';
  // A status and a priority are sequences, not words: sorted as text, `done`
  // heads the status column and `high, low, medium` is not an order anybody
  // means by priority. Everything else really is alphabetical.
  const rank = DATA.choices[sort];
  const key = rank
    ? row => String(rank.indexOf(row[sort])).padStart(3, '0')
    : row => String(row[sort] ?? '');
  const found = Object.values(DATA.rows).filter(matches);
  // The tree is the id sort's, and no other column's. Sorted by owner, a parent
  // is wherever its owner's name falls and its children are three screens away:
  // an indent that does not point at the row above it is a decoration, and a
  // connector drawn between two rows that are not related is a lie about the
  // plan. So every other column sorts flat — no indent, no connectors, and no
  // ancestors kept for a context they could not provide — which is what those
  // columns were always for.
  let placed;
  if (sort === 'id') {
    placed = ordered(withAncestors(found), descending);
    connectors(placed);
    const answers = new Set(found.map(row => row.id));
    for (const one of placed) one.context = !answers.has(one.row.id);
  } else {
    const rows = found.slice().sort((a, b) => key(a).localeCompare(key(b)));
    if (descending) rows.reverse();
    placed = rows.map(row => ({row, depth: 0, rungs: [], context: false}));
  }
  // Where the keyboard is, asked before `innerHTML` detaches the cell holding
  // it. A save redraws twice, so without this every commit dropped a keyboard
  // reader at the top of the page. Asked of the document rather than assumed:
  // the cell somebody has moved to since is where they are, and pulling them
  // back to the one that was edited is a second surprise on top of the redraw.
  // Except when a key closed the editor — Tab already said where to go.
  const focused = EDITABLE && tbody.contains(document.activeElement)
    ? document.activeElement.closest('td[tabindex]') : null;
  const held = EDITABLE && (RETURN || !!focused);
  if (focused && !RETURN) rove(focused);
  // The `+` row is drawn after whatever the filters left, including after the
  // three empty states: a plan with nothing in it is exactly when the way to put
  // something in it has to be on screen. It is never filtered — it stands for a
  // row that does not exist yet, and nothing that does not exist can match a
  // filter — and on a rendered file it is not drawn at all, because a file has
  // no server to create anything with.
  tbody.innerHTML = (placed.length ? placed.map(rowHtml).join('') : emptyRow())
    + (EDITABLE ? adderHtml() : '');
  if (EDITABLE) {
    rove(null, held);
    RETURN = false;
    sayDraft();
    markTargets();
    // Every element the last row holds is new, so what it is saying has to be
    // said again — this is the redraw that used to blank it mid-move.
    sayMoveOut();
  }
  // How many rows answered the question, which is not how many are drawn: an
  // ancestor kept for context is on screen because of something else that
  // matched, and counting it would make "4 of 17 shown" mean two things at once
  // — the second of which nobody asked for.
  document.getElementById('shown').textContent = found.length;
  // Sorting redraws without reloading, so the marker has to move with it. Set
  // once at load, it stayed on whatever the URL said when the page opened.
  for (const th of headers) {
    th.classList.toggle('sorted', th.dataset.sort === sort);
    if (!th.dataset.sort) continue;
    // The direction was invisible, so a column looked the same sorted either
    // way. Announced as well as drawn: aria-sort is all a screen reader has.
    const here = th.dataset.sort === sort;
    th.setAttribute('aria-sort', here ? (descending ? 'descending' : 'ascending') : 'none');
    th.querySelector('.dir').textContent = here ? (descending ? '▾' : '▴') : '';
  }
  // Every cell here is new, so every one of them is closed: the column controls
  // are told what they are looking at rather than left saying `−` over a column
  // a sort just collapsed. It is also the whole of "this does not persist" — a
  // redraw is where the state goes, and there is nowhere else it is kept.
  syncExpanders();
}
// The control bar changed the query string; what that means to a table is a
// redraw, and to the graph beside it a different set of nodes.
addEventListener('openproj:filter', draw);

// --- the card, on the title ------------------------------------------------
//
// The body is the one field a row does not show, and in this tool the shaping
// document IS the record — so the title is the cell it hangs off. The same card
// the graph and the timeline draw; see `_SHELL`.
//
// Outside `if (EDITABLE)` on purpose: a rendered file is the copy somebody reads
// on a train, and it is the copy that most needs a way to see what a row is about
// without opening seventeen documents. There the card has no server to ask for a
// body and draws the row's own fields, and the title beside it is still a link
// into `detail.html#id`.
tbody.addEventListener('pointerover', event => {
  const cell = event.target.closest('td[data-col="title"]');
  const row = cell && cell.closest('tr[data-id]');
  // Not over an open editor, and not in the middle of a move: in both the
  // pointer is doing something, and a box under it is in the way of the thing
  // being done.
  if (!row || cell.querySelector('input, textarea') || MOVING) return hideCard();
  const held = DATA.rows[row.dataset.id];
  if (held) queueCard(held, event.clientX, event.clientY);
});
tbody.addEventListener('pointerout', event => {
  if (event.target.closest('td[data-col="title"]')) hideCard();
});
// A cell that opens for editing under a card, and a redraw that replaces the row
// the card is describing: neither is a pointer leaving anything, so neither fires
// `pointerout`.
addEventListener('openproj:filter', hideCardNow);

// The row a write is in the air for, or null. One at a time, because one drag is
// one drop: this is not a queue, it is the row the reader is looking at.
//
// Declared out here rather than beside `reparent`, which is where it is set, and
// outside the editable branch, which is where writes live. `rowHtml` reads it on
// the first draw: further down the file it is in its dead zone then, and inside
// the branch it does not exist at all on a rendered file — both of which are a
// page that throws before a single row is drawn.
let WRITING = null;

{% if not editable %}
// A rendered file has no server to save to, so the table is a table.
const EDITABLE = null;
{% else %}
const BASE = document.getElementById('base');
const EDITABLE = DATA.editable;
const SUGGESTS = DATA.suggests;
const CHOICES = DATA.choices;

function coerce(type, raw) {
  raw = raw.trim();
  if (type === 'bool') return raw === 'true';
  // Deduplicated: picking a name already in the list is a slip, not an intent to
  // have it twice, and a duplicate reviewer reads as two people.
  if (type === 'list')
    return raw ? [...new Set(raw.split(',').map(s => s.trim()).filter(Boolean))] : [];
  if (type === 'number') {
    if (raw === '') return null;
    const n = Number(raw);
    if (Number.isNaN(n)) throw new Error(`must be a number, not "${raw}"`);
    return n;
  }
  return raw === '' ? null : raw;
}

// The validator and the scheduler run on the server, so what a save did to the
// problems is not something this page can work out for itself: it used to leave
// the count and the row markers stale until somebody reloaded, which is exactly
// when a count stops being read. Only the problems are re-read — dates are a
// forecast, and re-forecasting under somebody who is mid-edit is worse than
// being one reload behind.
async function refreshProblems() {
  const response = await fetch('/api/index.json');
  if (!response.ok) return;
  regroup((await response.json()).problems);
  summarise();
}

// What this status will make the server refuse the row without, and the row has
// not got. `DATA.required` is `required_at()`, which is derived from the gate
// rather than written beside it — the same map the detail page marks its labels
// from.
//
// `review_waived` is honoured here for the reason it is honoured there: it is the
// escape hatch from the reviewer rule, and asking for reviewers on a row that has
// waived them is a nag rather than a question.
function missingFor(row, status) {
  return Object.entries((DATA.required || {})[row.kind] || {})
    .filter(([field, statuses]) => statuses.includes(status))
    .map(([field]) => field)
    .filter(field => EDITABLE[field] && !(field === 'reviewers' && row.review_waived))
    .filter(field => {
      const held = row[field];
      return held === null || held === undefined || held === ''
        || (Array.isArray(held) && held.length === 0);
    });
}

// Fields a span is computed from. Editing one of these from the table changes
// `start` and `end`, which are columns nothing in the browser can work out — so
// the rows are re-read from the server rather than patched in place.
const DERIVES_DATES = new Set(['assigned_on', 'person_weeks', 'cycle']);

// Today, in the reader's own timezone. `toISOString` is UTC, so on a laptop east
// of Greenwich in the evening it offers tomorrow — which is a date somebody
// accepts without reading, because it is prefilled and it is nearly right.
function today() {
  const now = new Date();
  return new Date(now.getTime() - now.getTimezoneOffset() * 60000)
    .toISOString().slice(0, 10);
}

// The one question a status change is allowed to ask. It is asked BEFORE the
// write, so the answer travels in the same PATCH as the status: a row that goes
// `in_progress` and then has a date added is two commits, and for the length of
// the first one the plan holds a record the validator refuses.
function askFor(cell, status, fields) {
  const panel = document.getElementById('askfor');
  const named = fields.map(field => {
    const label = FIELD_LABELS[field] || field;
    const type = EDITABLE[field] === 'date' ? 'date' : 'text';
    const value = field === 'assigned_on' ? today() : '';
    return `<label>${esc(label)}` +
      `<input type="${type}" data-field="${esc(field)}" value="${esc(value)}"></label>`;
  }).join('');
  panel.innerHTML =
    `<p class="asking">${esc(human(status))} needs ${fields.length === 1 ? 'this' : 'these'}` +
    `</p>${named}` +
    `<span class="acts"><button type="button" id="asked" class="primary">Save</button>` +
    `<button type="button" id="unasked">Cancel</button></span>`;
  panel.hidden = false;
  const box = cell.getBoundingClientRect();
  panel.style.left = Math.max(8, Math.min(box.left, innerWidth - panel.offsetWidth - 8)) + 'px';
  panel.style.top = Math.min(box.bottom + 6, innerHeight - panel.offsetHeight - 8) + 'px';
  panel.querySelector('input').focus();
  panel.querySelector('input').select();

  // The keyboard goes back to the cell the question was asked about. `rove` is
  // what this table hands focus with everywhere else, and it survives the redraw
  // that a save causes.
  const shut = () => { panel.hidden = true; panel.innerHTML = ''; rove(cell, true); };
  panel.querySelector('#unasked').onclick = () => { shut(); announce('nothing was changed'); };
  panel.querySelector('#asked').onclick = () => {
    const extra = {};
    for (const input of panel.querySelectorAll('input')) {
      if (!input.value.trim()) {
        announce(`${FIELD_LABELS[input.dataset.field] || input.dataset.field} is needed`);
        input.focus();
        return;
      }
      extra[input.dataset.field] = input.value.trim();
    }
    panel.hidden = true;
    panel.innerHTML = '';
    saveCell(cell, status, extra);
  };
  // Enter saves and Escape gives up, which is what every other box on this page
  // answers to — a panel that has to be dismissed with the mouse is a panel that
  // stops the keyboard path this table is built around.
  panel.onkeydown = event => {
    if (event.key === 'Enter') { event.preventDefault(); panel.querySelector('#asked').click(); }
    if (event.key === 'Escape') { event.preventDefault(); panel.querySelector('#unasked').click(); }
  };
}

async function saveCell(cell, value, extra) {
  const field = cell.dataset.field;
  const box = document.getElementById('row-conflict');
  // Cleared here and nowhere else. This page redraws instead of reloading, so
  // nothing else ever took the banner down: one 409 left "somebody changed this
  // before you" standing over every save that landed afterwards.
  box.hidden = true;
  box.textContent = '';
  let coerced;
  try {
    coerced = coerce(EDITABLE[field], value);
  } catch (error) {
    announce(`${field} ${error.message}`);
    return;
  }
  // The banner in the shell has to know a write is in the air before it starts:
  // the server announces a commit to the event stream before it answers the
  // request that made it, so the news of your own save can arrive before you
  // know its sha.
  // A status that demands what this row has not got is a question before it is a
  // write. Asked once — `extra` is what came back from asking, and a second pass
  // through here with it must not ask again.
  if (field === 'status' && !extra) {
    const wanted = missingFor(DATA.rows[cell.dataset.entity] || {}, coerced);
    if (wanted.length) { askFor(cell, value, wanted); return; }
  }
  let sending;
  try {
    sending = {[field]: coerced};
    for (const [name, raw] of Object.entries(extra || {}))
      sending[name] = coerce(EDITABLE[name], raw);
  } catch (error) {
    announce(`${field} ${error.message}`);
    return;
  }
  dispatchEvent(new Event('openproj:writing'));
  let committed = null;
  try {
    // One key, taken from the cell. Sending the row would overwrite whatever
    // somebody else changed while this tab was open, and would turn two people
    // editing two different columns into a conflict field-level merge exists to
    // make invisible. No body: an empty string is a replacement, not an omission,
    // and would blank the shaping doc attached to the row.
    //
    // The id is encoded, here and at the three other write sites. A malformed id
    // is a *reported* blocker and not a refusal, so an id with a `#` or a `?` in
    // it does reach the page — and raw in a path, the first one truncates it, so
    // the save somebody pressed on one record addresses something else entirely.
    const response = await fetch(`/api/entity/${encodeURIComponent(cell.dataset.entity)}`, {
      method: 'PATCH', headers: {'content-type': 'application/json'},
      body: JSON.stringify({base_commit: BASE.value, fields: sending, body: null}),
    });
    const answer = await answerOf(response);
    if (response.status === 409) {
      box.hidden = false;
      box.textContent = refusal(answer, 409);
      return;
    }
    if (!response.ok) {
      announce(refusal(answer, response.status));
      return;
    }
    // The page moves forward with the repository, or its next save collides with
    // the commit it just made.
    committed = answer.commit;
    BASE.value = answer.commit;
    Object.assign(DATA.rows[cell.dataset.entity], sending);
    // A date the schedule is derived FROM has moved, so every date derived from
    // it on this row is now wrong on screen — and `start` and `end` are two
    // columns away from the one that was edited. Re-read rather than recomputed:
    // the scheduler is the server's, and a second copy of it here is the thing
    // this codebase has paid for three times already.
    if (extra && Object.keys(extra).some(name => DERIVES_DATES.has(name))) {
      await refreshRows();
    }
    // Twice: once to put the typed value back into the cell rather than leaving
    // an open editor sitting there for the length of a second round trip, and
    // once when the server has said what that value did to the problems.
    draw();
    await refreshProblems();
    draw();
  } finally {
    // Announced even when the save was refused, or one 409 leaves every event
    // after it held back and the banner never appears again.
    dispatchEvent(new CustomEvent('openproj:wrote', {detail: committed}));
  }
}

// Where the keyboard is in the grid, kept across the redraw a save triggers.
// `AT` is a row id and a column rather than an element, because `draw()` replaces
// every cell and the element that had focus no longer exists by the time the
// keyboard needs to go back to it.
let AT = null;
// Whether it should go back. `blur()` moves focus to <body> before the save it
// causes has even started, so this cannot be read off the document at redraw
// time — it is decided by the key that closed the editor.
let RETURN = false;

function stops() { return [...tbody.querySelectorAll('td[tabindex]')]; }

// One tab stop for the whole grid: exactly one cell is tabbable and the arrows
// move it. `rove` is the only thing that writes tabIndex, so the invariant
// cannot come apart across a redraw.
function rove(cell, focus) {
  const all = stops();
  if (!all.length) { AT = null; return; }
  const at = cell
    || (AT && all.find(td => td.dataset.col === AT.col
                             && td.parentNode.dataset.id === AT.id))
    || all[0];
  for (const td of all) td.tabIndex = td === at ? 0 : -1;
  AT = {id: at.parentNode.dataset.id, col: at.dataset.col};
  if (focus) at.focus();
}

function openEditor(cell) {
  // A computed column answers rather than swallowing the key, exactly as it
  // answers a double-click: a cell that ignores Enter is indistinguishable from
  // a cell that is broken.
  if (!cell.classList.contains('edit')) { refuse(cell); return; }
  if (cell.querySelector('input, select')) return;
  rove(cell);
  const field = cell.dataset.field;
  // The record this cell is part of, or the one that does not exist yet: a cell
  // with no `data-entity` is a cell of the row being typed, and there is exactly
  // one of those. One editor for both, because a second one is a second set of
  // rules about what a list separator is and which values get selected on open —
  // and the create form is already proof that a differently-shaped way to write
  // the same fields is how a tool comes to feel like two tools.
  const was = stored(cell.dataset.entity ? DATA.rows[cell.dataset.entity] : DRAFT.fields, field);
  const suggest = SUGGESTS[field];
  const closed = CHOICES[EDITABLE[field]];
  // The name the editor answers to. The cell it replaces carries its column in
  // a header a screen reader reads on the way in; a box conjured inside that
  // cell carries nothing at all unless it is told what it is editing.
  const named = esc(FIELD_LABELS[field] || field);
  // A closed set is chosen, never typed. Free text over three options is a way
  // to write `in progres` into the corpus. The option's value is the stored
  // identifier and its text is the word for it, so picking "In progress"
  // still writes `in_progress`.
  // Every interpolation escaped, including the ones that are a closed set today.
  // A rule with an exception in it is a rule nobody applies to the next line.
  // The tree first, rebuilt from the cell's own `data-rungs` rather than kept:
  // this is the one cell whose contents are replaced without a redraw, and the
  // connector belongs to the row rather than to what is in the cell at the time.
  cell.innerHTML = treeHtml(cell.dataset.rungs) + (closed
    ? `<select data-type="text" aria-label="${named}">${closed.map(o =>
        `<option value="${esc(o)}" ${o === was ? 'selected' : ''}>${esc(human(o))}</option>`
      ).join('')}</select>`
    : `<input value="${esc(was)}" data-type="${esc(EDITABLE[field])}" aria-label="${named}"` +
      `${suggest ? ` data-suggest="${esc(suggest)}"` : ''} autocomplete="off">`);
  const input = cell.querySelector('select, input');
  // The table gets the autocomplete the detail page has. Suggestions that only
  // appear in one of the two places are suggestions nobody relies on.
  if (suggest) attachSuggest(input);
  input.focus();
  // A single-value cell selects everything, because a double-click leaves the
  // caret where it landed and typing would interleave. A list must NOT: typing
  // over a selected "jcanton, halungge" deletes both reviewers to write one.
  if (EDITABLE[field] !== 'list' && input.select) input.select();
  else if (input.setSelectionRange)
    input.setSelectionRange(input.value.length, input.value.length);

  let abandoned = false;
  input.onblur = () => {
    // A stored cell writes a commit; a draft cell writes into the row nobody has
    // created yet, which is a change to a variable and not to the repository.
    // Same editor, same key handling, one branch at the end of it.
    if (abandoned || input.value === was) draw();
    else if (cell.dataset.entity) saveCell(cell, input.value);
    else stage(field, input.value);
  };
  input.onkeydown = e => {
    if (e.key === 'Enter') { RETURN = true; input.blur(); }
    if (e.key === 'Escape') {
      // Escape means discard. Redrawing first would fire blur with the partial
      // value still in the box, and the edit somebody just abandoned gets saved.
      abandoned = true;
      RETURN = true;
      // And it means discard THIS, never the row it is in. The grid answers
      // Escape as well now — it is how a draft is abandoned — and both listeners
      // are on the way up from this box, so without this an Escape meant to undo
      // one mistyped cell would take the whole half-typed row with it. The
      // comment on that handler already says the keys belong to an open editor;
      // this is the line that makes it so rather than leaving it to a test of
      // what an editor looks like from the outside.
      e.stopPropagation();
      draw();
    }
    if (e.key === 'Tab') {
      // Commit and move, the way every grid does. Left to the browser, Tab
      // blurs — which saves — and the redraw the save causes throws the focus
      // away, so the cell to land on is chosen here and `draw()` puts the
      // keyboard on it once the rows exist again.
      e.preventDefault();
      const line = [...cell.parentNode.cells].filter(td => td.hasAttribute('tabindex'));
      const wanted = line.indexOf(cell) + (e.shiftKey ? -1 : 1);
      AT = {id: cell.parentNode.dataset.id,
            col: line[Math.max(0, Math.min(line.length - 1, wanted))].dataset.col};
      RETURN = true;
      input.blur();
    }
  };
}

// ---------------------------------------------------------------------------
// A row you type into
// ---------------------------------------------------------------------------

// Which stored field each column of a new row writes to, per kind, and the
// values a record starts life with. Both are built on the server from the models
// themselves — see `_new_row_fields` — so what a project has no box for here and
// what the create form hides there are one answer to one question.
const NEW_ROW = DATA.new_row || {};
const DEFAULTS = DATA.defaults || {};
const TEMPLATES = DATA.templates || {};
// The check and the cross the draft row's two controls are drawn with, rendered
// on the server. A template variable and not a `.replace` into the finished
// page, which is the rule the whole file is held to; and drawings rather than
// the characters `✓` and `✕`, which is argued at `DRAFT_MARKS`.
const MARK = {{ marks|tojson }};
// What the row being typed answers to in the grid. `+` is not an id and cannot
// become one — an id is a prefix and six hex digits — so nothing that walks the
// rows can confuse the draft with a record.
const DRAFT_ID = '+';

// The row that is not an entity yet: null while there is none, otherwise the
// kind (null until it is chosen), what has been typed so far, and whatever the
// last refusal said.
//
// One variable, and it is the whole of the draft. That is what makes it survive
// a sort — `draw()` rebuilds every row from state, so re-sorting or filtering
// redraws this one with everything in it — and what makes it not survive a
// reload, which is a decision and not an oversight. A half-filled row kept in
// `localStorage` is a record of the plan that is not in git, that nobody can
// review and that no `base_commit` covers; the one draft this app does keep, on
// the detail page, has to carry the commit it was drafted against precisely so
// it can say it has gone stale. That is worth paying for a shaping document
// somebody spent an hour on. It is not worth paying for four short fields with
// Create sitting directly underneath them, and a draft that outlives the page is
// a draft somebody creates twice.
let DRAFT = null;

// What a draft cell shows: exactly what will be committed and nothing that is
// only true of a stored row. `shown()` links the title (there is no page to link
// to yet), turns PR references into links and clamps four columns behind a `+N`
// — none of which applies to a row whose entire content is what was just typed
// into it. The one thing it keeps is the status chip, because a status is a rung
// and reads as one everywhere else on the page.
function draftShown(field) {
  const value = DRAFT.fields[field];
  const text = Array.isArray(value) ? value.join(', ') : (value ?? '');
  if (text === '') return '';
  if (field === 'status') return `<span class="chip ${stClass(text)}">${esc(human(text))}</span>`;
  // `human` only where the value is one of a closed set. A title of `done` is a
  // title, and running every cell through the map would print it as "Done".
  return esc(CHOICES[EDITABLE[field]] ? human(text) : text);
}

function draftRowHtml() {
  const fields = NEW_ROW[DRAFT.kind] || {};
  const cells = keys.map(key => {
    // Where the id will be, and until it exists this is the row's controls
    // instead. The id is the server's to mint — a browser that names an id names
    // a path — so this cell has nothing of its own to show, and what stands in
    // for it is the one decision the id will be made out of plus the two answers
    // to whether it should be made at all.
    //
    // It read `new task`, with the kind picker and two word buttons in a bar
    // under the row. The words said what this cell now IS: the kind belongs in
    // the cell that carries the row's identity, and a bar under a row is a
    // second place to look for controls that belong to it.
    //
    // The sentence stays in the tooltip, because this is the narrowest column on
    // the table and beside the word it took the draft to two lines — a row twice
    // the height of every other row reads as a different kind of thing.
    if (key === 'id')
      return `<td data-col="id" class="draft-id"` +
        ` title="The id and the file are the server's to choose">${draftControls()}</td>`;
    const field = fields[key];
    const named = (FIELD_LABELS[key] || key).toLowerCase();
    if (!field) {
      // Two different reasons a column takes nothing, and the cell says which:
      // some kind can type into it and this one cannot — a project has no
      // appetite of its own — or nobody can, because it is the scheduler's
      // output. Asked of the map rather than listed here, so a column that
      // becomes kind-only later explains itself without this line changing.
      const anyKind = Object.keys(NEW_ROW).some(kind => key in NEW_ROW[kind]);
      const why = anyKind ? `A ${DRAFT.kind} has no ${named}` : WHY[key] || '';
      return `<td data-col="${key}" class="draft-none"` +
        `${why ? ` title="${esc(why)}"` : ''}></td>`;
    }
    return `<td data-col="${key}" class="edit draft-cell" data-field="${esc(field)}"` +
      ` data-hint="${esc(named)}" tabindex="-1"` +
      ` title="${esc('Double-click to edit ' + named)}">${draftShown(field)}</td>`;
  });
  return `<tr class="draft" data-id="${DRAFT_ID}">${cells.join('')}</tr>`;
}

// The last row of the table, in both of its states: the control that starts a
// row, and — once one is started — the kind picker, Create, Cancel and wherever
// the server's refusal lands.
//
// It is one row and not two because it is one thing: the place at the bottom
// where a plan grows. While a move is in the air it is also where a row goes to
// belong to nothing (see `startMoving`), which is the same place said the same
// way — under everything, outside the tree.
function adderHtml() {
  const wide = ` colspan="${keys.length}"`;
  if (!DRAFT) {
    // "New row" and not "New entity", although an entity is what it makes: the
    // control beside the heading is already called that and goes to the form
    // that writes one properly. Two controls with one name on one page is how a
    // person learns to trust neither, and what this one does when you press it
    // is put a row on the table.
    // Both of the last row's jobs are drawn every time, and `sayMoveOut` decides
    // which of them is showing. Emitted empty and filled in afterwards rather
    // than written out here, because the words are the same words `startMoving`
    // needs mid-drag, when the table must not be redrawn at all: one function
    // owns them, and a redraw and a pick-up leave this row saying the same thing.
    return `<tr class="adder"><td${wide}>` +
      `<button type="button" id="add-row" class="add">+ New row</button>` +
      `<button type="button" id="unparent" hidden></button>` +
      `<span class="hint" id="rootless" hidden></span>` +
      `</td></tr>`;
  }
  // The kind first, and it stays: it is the decision that says which fields the
  // row even has, and switching it after typing must not cost the typing — the
  // create form learned that one already. The row itself appears only once the
  // kind is chosen, because until then there is no answer to which columns it
  // has — which is the whole reason the kind is asked first.
  //
  // Which is also why the controls are in this bar until there is a row and in
  // the row's id cell afterwards: they belong to the row, and for one press
  // there is no row for them to belong to. One function draws them either way,
  // so the two places cannot come to offer different things.
  //
  // The sentence that used to be here — "Nothing is written until you press
  // Create" — is gone. It named a button that no longer exists: the controls are
  // a check and a cross now, and a hint that explains a control by the wrong
  // name is worse than no hint. The marks carry their own names in `title` and
  // `aria-label`, which is where a control says what it does.
  return (DRAFT.kind ? draftRowHtml() : '') +
    `<tr class="adder open"><td${wide}>` +
    (DRAFT.kind ? '' : draftControls()) +
    `<ul id="draft-problems" role="status" aria-live="polite" hidden></ul>` +
    `</td></tr>`;
}

// Create it, abandon it, and what it will be — the whole of what a row that does
// not exist yet offers, in one line and in that order.
//
// Marks and not words. `Create` and `Cancel` spelled out are two thirds of the
// id column, and this cell is the row's name rather than a toolbar; the marks
// are drawn rather than typed because `✓` and `✕` are in neither the vendored
// face nor anything else this page ships — see `DRAFT_MARKS`, which is where
// that is argued and where the drawings are.
//
// Which means every one of them is an icon-only control, so each carries the
// name twice: `aria-label` for a reader who cannot see it and `title` for one
// who can see it and cannot tell what it is. Never `title` alone — that is a
// hint, and these are the two controls this row has. The third channel is
// Escape, in the grid's key handler, because somebody who arrived here with Tab
// needs a way out that is not hunting for the ✕.
//
// Create names the kind — "Create this task", not "Create" — because it is the
// press that writes a file, and the row above it is not the only draft-shaped
// thing on the page while a filter is drawn.
function draftControls() {
  const kinds = Object.keys(NEW_ROW).map(kind =>
    `<option value="${esc(kind)}"${kind === DRAFT.kind ? ' selected' : ''}>` +
    `${esc(human(kind))}</option>`).join('');
  const named = DRAFT.kind ? esc(human(DRAFT.kind).toLowerCase()) : '';
  const create = DRAFT.kind
    ? `<button type="button" id="draft-create" class="draft-do primary"` +
      ` aria-label="Create this ${named}" title="Create this ${named}">` +
      `${MARK.create}</button>`
    : '';
  // "choose a kind…" and not "choose…": the word `kind` used to be printed
  // beside the picker and there is no room for it in the id column, so the
  // placeholder carries it instead. It is only ever read in the bar — the row
  // does not exist until a kind is chosen — so the narrow cell never has to
  // draw it.
  //
  // Wrapped, and the wrapper is what does the laying out: a `<td>` cannot be the
  // flex container itself without ceasing to be a table cell, which is the same
  // reason the clamped columns have `.clamped` inside them.
  return `<span class="drafting">` + create +
    `<button type="button" id="draft-cancel" class="draft-do"` +
    ` aria-label="Discard this new row" title="Discard this new row">` +
    `${MARK.cancel}</button>` +
    `<select id="draft-kind" aria-label="Kind"` +
    ` title="Which kind of record this row becomes">` +
    `<option value=""${DRAFT.kind ? '' : ' selected'}>choose a kind…</option>` +
    `${kinds}</select></span>`;
}

// Whatever the last attempt was refused with, put in as text.
//
// `replaceChildren` with text nodes and never `innerHTML`: every one of these
// sentences comes back from the server quoting a field this plan holds, and a
// title is a sentence somebody typed. The list is also why the refusal is drawn
// *in* the bar rather than in `#row-conflict` — a create has no row to sit
// beside, and a refusal with nowhere to land is a refusal that gets swallowed.
function sayDraft() {
  const list = document.getElementById('draft-problems');
  if (!list) return;
  const said = (DRAFT && DRAFT.said) || [];
  list.hidden = !said.length;
  list.replaceChildren(...said.map(text => {
    const item = document.createElement('li');
    item.textContent = text;
    return item;
  }));
}

function refused(lines) {
  if (DRAFT) DRAFT.said = lines;
  draw();
  announce(lines.join(' '));
}

// What the server refused a create with, one sentence per line. The create route
// answers 422 with a `problems` list and everything else with a `detail`, and
// the shell's `refusal` already knows which — this only keeps them apart so that
// three blockers read as three lines instead of one long one. It is not
// `refusals()` from the detail form: that one names the control each problem is
// about, and there are no named controls on a table.
function refusalLines(answer, status) {
  const problems = answer.problems || [];
  return problems.length ? problems.map(problem => problem.message)
                         : [refusal(answer, status)];
}

// The picker, wherever it was just drawn — in the bar while there is no row, in
// the row's id cell once there is one. Asked of the document rather than kept,
// because every redraw replaces it.
function focusDraftKind() {
  const picker = document.getElementById('draft-kind');
  if (picker) picker.focus();
}

function openDraft() {
  DRAFT = {kind: null, fields: {}, said: []};
  draw();
  focusDraftKind();
}

function closeDraft(said) {
  DRAFT = null;
  draw();
  if (said) announce(said);
  const add = document.getElementById('add-row');
  if (add) add.focus();
}

function chooseKind(kind) {
  if (!NEW_ROW[kind]) {
    // Back to "choose a kind…", which takes the row away and the picker with it
    // — `draw()` rebuilds the whole tbody and the picker is drawn in the bar
    // again. Handed back rather than left on `<body>`: the element that had the
    // keyboard no longer exists, and a person who has just changed their mind
    // about the kind is still answering the same question.
    DRAFT.kind = null;
    draw();
    focusDraftKind();
    return;
  }
  DRAFT.kind = kind;
  // What was typed stays. Except a field this kind has not got: a size typed
  // while the row was a task is not a project's to carry, and sending it is a
  // 422 quoting a field that is no longer on the screen.
  const owned = new Set(Object.values(NEW_ROW[kind]));
  for (const name of Object.keys(DRAFT.fields)) if (!owned.has(name)) delete DRAFT.fields[name];
  // The status and the priority a record is created with, shown rather than left
  // blank. A blank cell that turns into `shaping` on save is the row lying about
  // what it is going to write, and these two are the columns somebody scanning
  // the table reads first.
  for (const [name, value] of Object.entries(DEFAULTS))
    if (owned.has(name) && !(name in DRAFT.fields)) DRAFT.fields[name] = value;
  DRAFT.said = [];
  draw();
  // Straight into the one field the row cannot be created without, so the whole
  // flow is: press +, pick the kind, type, press Create.
  const title = tbody.querySelector('tr.draft td[data-field="title"]');
  if (title) openEditor(title);
}

// A typed value into the draft. The same coercion the save path uses, because
// `1, 2` has to mean the same two tags whichever row it was typed into.
function stage(field, value) {
  let coerced;
  try {
    coerced = coerce(EDITABLE[field], value);
  } catch (error) {
    announce(`${field} ${error.message}`);
    draw();
    return;
  }
  if (coerced === null || (Array.isArray(coerced) && !coerced.length)) delete DRAFT.fields[field];
  else DRAFT.fields[field] = coerced;
  draw();
}

async function createDraft() {
  const fields = {kind: DRAFT.kind, ...DRAFT.fields};
  // A title, at minimum. The server refuses a titleless record too, but it
  // refuses it as YAML that will not read back — and the reason a row needs one
  // is not about YAML: an entity with no title is a row nobody can find again,
  // in a table whose first column is a mint-fresh id nobody has seen before.
  // Everything else the status demands is left to `validate_all`, which is the
  // only thing that knows the rules and which of them this record is old enough
  // to be held to.
  if (!String(fields.title || '').trim()) {
    refused(['A row needs a title — it is how anybody finds it again.']);
    const cell = tbody.querySelector('tr.draft td[data-field="title"]');
    if (cell) openEditor(cell);
    return;
  }
  // The banner in the shell has to know a write is in the air before it starts,
  // exactly as a cell save does: the server announces a commit to the event
  // stream before it answers the request that made it.
  dispatchEvent(new Event('openproj:writing'));
  let committed = null;
  try {
    const response = await fetch('/api/entity', {
      method: 'POST', headers: {'content-type': 'application/json'},
      // One way in, and it is the one the create form uses: the id, the path and
      // every rule about what a new record must carry are the server's, and two
      // ways to create an entity is two sets of rules that disagree by Thursday.
      // The body is the kind's own template — the same map `/new` offers — so a
      // pitch made here is the same document as a pitch made there.
      body: JSON.stringify({base_commit: BASE.value, fields,
                            body: TEMPLATES[DRAFT.kind] ?? ''}),
    });
    const answer = await answerOf(response);
    if (!response.ok) { refused(refusalLines(answer, response.status)); return; }
    committed = answer.commit;
    BASE.value = answer.commit;
    DRAFT = null;
    // Re-read rather than invented. A new row's dates, its size, what it blocks
    // and which project it counts against are all the server's arithmetic, and a
    // row drawn from what was posted would be a row missing every column the
    // scheduler fills in.
    const fresh = await refreshRows();
    draw();
    announce(fresh ? `Created ${answer.id}` : `Created ${answer.id} — reload to see it in place`);
    const add = document.getElementById('add-row');
    if (add) add.focus();
  } finally {
    // Announced even when refused, or one rejected create leaves every event
    // after it held back and the banner never appears again.
    dispatchEvent(new CustomEvent('openproj:wrote', {detail: committed}));
  }
}

// ---------------------------------------------------------------------------
// A row you move
// ---------------------------------------------------------------------------

// Which row is being moved, whether it is being dragged or carried by the
// keyboard. One variable for both, because they are one act: what is legal, what
// is drawn and what is written are the same three answers whichever hand is on it.
let MOVING = null;

// Why that row may not hold this one, in words, or '' when it may.
//
// The rule is `PARENT_KINDS`, which is the model's, so this cannot drift from
// what the validator would say about the record afterwards. The sentence is this
// page's own — it is said *before* the write, about a gesture, where the
// validator's is said about a record that already exists.
function refuses(childId, parentId) {
  const child = DATA.rows[childId];
  const parent = DATA.rows[parentId];
  if (!child || !parent) return 'that row is not in this plan';
  // Dropping a row on itself is where it started, not a move, and the kind rule
  // would refuse it anyway — but "a task belongs to a pitch, not to a task" is
  // an odd thing to be told about the row under your own hand.
  if (childId === parentId) return `${childId} cannot hold itself`;
  if (!(PARENT_KINDS[child.kind] || []).includes(parent.kind))
    return `a ${child.kind} belongs to ${holders(child.kind)}, not to a ${parent.kind}`;
  if (child.parent === parentId) return `${childId} is already in ${parentId}`;
  return '';
}

// Why this row may not be dropped on that target, in words, or '' when it may.
// The `+` row is the one target that is not a record: dropping on it means
// belonging to nothing, which is only a move when there is something to leave.
function whyNotOnto(childId, target) {
  if (target.classList.contains('adder'))
    return (DATA.rows[childId] || {}).parent ? '' : `${childId} is not inside anything`;
  return refuses(childId, target.dataset.id);
}

// Every row says whether it would take the one being moved, before the mouse
// gets anywhere near it. This is the whole of "refused while dragging": a row
// that cannot hold it is drawn refusing it from the moment it is picked up, and
// `dragover` never lets go of the drop on one of them, so a move that breaks
// containment is not a request that gets a 422 — it is a request that is never
// made.
function markTargets() {
  for (const tr of tbody.querySelectorAll('tr[data-id]')) {
    tr.classList.remove('can-hold', 'no-hold', 'over');
    if (!MOVING || tr.dataset.id === MOVING || tr.dataset.id === DRAFT_ID) continue;
    tr.classList.add(refuses(MOVING, tr.dataset.id) ? 'no-hold' : 'can-hold');
  }
  // The label goes with the mark, because they are one answer said twice — the
  // ground under the cursor and the words beside it. No row is `over` after this
  // runs, so a label still naming one is a label naming a row that is not lit,
  // and a redraw mid-drag is exactly when that happens.
  sayInto('');
}

// The row a drop would land in, named, next to the cursor.
//
// Not a dialog. A modal on every drag is a toll on a gesture that is already
// deliberate — you have to pick the row up, carry it and let go on the right one
// — and a reparent is one field and one commit that dragging it back undoes. The
// answer belongs where the hand already is, before the drop, rather than as a
// question after it.
//
// The title and not the id, because the ground under the cursor already says
// which row it is and what a person is checking at that moment is that it is the
// *right* row. `textContent`, so a title somebody typed is text here as it is
// everywhere else on this page.
//
// Parked on the body and positioned fixed, like the cells' suggestion popups:
// `.table-scroll` scrolls and clips its contents, and a label that scrolls out
// from under the cursor is worse than no label at all.
let INTO = null;
function sayInto(text, x, y) {
  // Nothing to say and nothing drawn yet is the state every table opens in, so
  // a page nobody drags anything on never grows the element at all.
  if (!INTO && !text) return;
  if (!INTO) {
    INTO = document.createElement('div');
    INTO.id = 'into';
    INTO.hidden = true;
    document.body.append(INTO);
  }
  INTO.hidden = !text;
  INTO.textContent = text || '';
  if (!text) return;
  // Below and right of the pointer, which is where the drag image is not.
  INTO.style.left = Math.round(x + 16) + 'px';
  INTO.style.top = Math.round(y + 18) + 'px';
}

// A row's own word for itself. The id is the fallback and not the label: a row
// with no title is a row nobody can find again, which the create path already
// refuses, but a plan hand-written in git can hold one.
const titleOf = id => (DATA.rows[id] || {}).title || id;

// What the label says over each of the two kinds of target. The `+` row is not a
// parent — it is the way out of the tree — so it says so in the other direction
// rather than naming itself.
function intoWords(target) {
  if (target.classList.contains('adder')) {
    const parent = (DATA.rows[MOVING] || {}).parent;
    return parent ? `→ out of ${titleOf(parent)}` : '';
  }
  return `→ into ${titleOf(target.dataset.id)}`;
}

// What the last row says while a move is in the air, and the whole of it.
//
// It was set imperatively in `startMoving` and nowhere else, which held exactly
// until something redrew the table underneath the move: `draw()` rebuilds the
// whole tbody, `adderHtml` emits the button hidden and wordless, and `moving` is
// still on the table — so `+ New row` stayed hidden, `#unparent:not([hidden])`
// stopped matching, and the sticky bar at the bottom of the plan painted as an
// empty strip while the live region still said "The row at the bottom takes it
// out of pitch-0a0001". Typing one character into the search box did it, as did
// any facet, any sort, and every keyboard move — which is the half of the
// gesture that redraws by design. Empty must not look like broken, and least of
// all while the page is telling somebody the opposite.
//
// So the answer is derived from `MOVING` wherever it is asked for: after every
// redraw, and again when a move starts or ends, which is when a native drag
// forbids a redraw. Both states are drawn, because a row that is already outside
// everything has nothing to be taken out of and the bar has to say so rather
// than go blank — the one control it would otherwise offer is the `+`, and
// pressing that in the middle of a move is not what anybody meant.
function sayMoveOut() {
  const out = document.getElementById('unparent');
  const rootless = document.getElementById('rootless');
  if (!out || !rootless) return;
  const row = MOVING ? DATA.rows[MOVING] : null;
  const parent = row ? row.parent : null;
  out.hidden = !parent;
  out.textContent = parent ? `Take ${MOVING} out of ${parent}` : '';
  rootless.hidden = !row || !!parent;
  rootless.textContent = row && !parent ? `${MOVING} is not inside anything` : '';
}

function startMoving(id) {
  const row = DATA.rows[id];
  if (!row) return;
  MOVING = id;
  // On the table and not on each row: the stylesheet needs one switch to change
  // what the last row offers, and the marks below are per row.
  table.classList.add('moving');
  markTargets();
  sayMoveOut();
  announce(`Moving ${id}. Drop it on ${holders(row.kind)}, or press Enter on one. ` +
           (row.parent ? 'The row at the bottom takes it out of ' + row.parent + '. ' : '') +
           'Escape leaves it where it is.');
}

function stopMoving(said) {
  MOVING = null;
  table.classList.remove('moving');
  markTargets();
  sayMoveOut();
  if (said) announce(said);
}

// The write. A parent is a field like any other, so this is the same PATCH, the
// same base commit, the same 409 and the same announcement as typing into a cell
// — the gesture is new, the save path is not.
async function reparent(childId, parentId) {
  const box = document.getElementById('row-conflict');
  box.hidden = true;
  box.textContent = '';
  dispatchEvent(new Event('openproj:writing'));
  // Said before the request rather than after it. Every write here goes through
  // a fetch from the remote, a commit and a push, and against a repository on
  // GitHub that is seconds — during which the old page said nothing and left the
  // row where it was, which is indistinguishable from a drop that did not take.
  WRITING = childId;
  draw();
  announce(parentId ? `moving ${childId} into ${parentId}…`
                    : `taking ${childId} out…`);
  let committed = null;
  try {
    const response = await fetch(`/api/entity/${encodeURIComponent(childId)}`, {
      method: 'PATCH', headers: {'content-type': 'application/json'},
      body: JSON.stringify({base_commit: BASE.value, fields: {parent: parentId}, body: null}),
    });
    const answer = await answerOf(response);
    if (response.status === 409) {
      box.hidden = false;
      box.textContent = refusal(answer, 409);
      return;
    }
    if (!response.ok) { announce(refusal(answer, response.status)); return; }
    committed = answer.commit;
    BASE.value = answer.commit;
    // The rows, re-read, and not `DATA.rows[childId].parent = parentId`.
    //
    // `parent` is the one field on this page that nothing on this page can work
    // out the consequences of: it moves the row's cycle, its dates, what it
    // waits for and which project it counts against, and every one of those is a
    // column somebody is looking at. The rule one screen up — that a save
    // re-reads the problems and never the forecast — is about not moving dates
    // under somebody who is mid-edit; a drop is a gesture that is over, and a
    // table that does not move after one looks like a drop that did nothing.
    const fresh = await refreshRows();
    draw();
    announce(!fresh ? `${childId} was moved — reload to see where it landed`
             : parentId ? `${childId} is now in ${parentId}`
                        : `${childId} is no longer inside anything`);
  } finally {
    // Whatever happened — committed, refused, or the network gone — the row
    // stops waiting. A row left dimmed after a refusal is a row that looks like
    // it is still going.
    WRITING = null;
    draw();
    dispatchEvent(new CustomEvent('openproj:wrote', {detail: committed}));
  }
}

// The plan as it is now, in the shape this page was built from.
//
// `/api/table.json` and not `/api/index.json`: the second answers with entities
// and spans, and turning those into rows means writing `_row` a second time in
// JavaScript — a progress fraction counted out of a body, a blocker count, a
// project walked up the tree. The route hands back the very payload the page was
// rendered with, so the table after a write is built exactly like the table
// before it.
async function refreshRows() {
  const response = await fetch('/api/table.json');
  if (!response.ok) return false;
  const fresh = await response.json();
  if (!fresh || !fresh.rows) return false;
  DATA.rows = fresh.rows;
  regroup(fresh.problems || []);
  summarise();
  // The shell's banner compares somebody else's commit against what this page is
  // showing. A row created here and left out of that list is a change to a row in
  // front of you that reads as news about somewhere else.
  window.SHOWING = Object.keys(DATA.rows);
  return true;
}

if (EDITABLE) {
  tbody.addEventListener('click', event => {
    const control = event.target.closest('button');
    if (!control) return;
    if (control.id === 'add-row') openDraft();
    else if (control.id === 'draft-cancel') closeDraft('The row was not created');
    else if (control.id === 'draft-create') createDraft();
    else if (control.id === 'unparent' && MOVING) {
      const child = MOVING;
      stopMoving();
      reparent(child, null);
    }
  });

  tbody.addEventListener('change', event => {
    if (event.target.id === 'draft-kind' && DRAFT) chooseKind(event.target.value);
  });

  // Dragging a row lives in `tbody` and resizing a column lives in `thead`, and
  // neither can fire the other: the column grips are `pointerdown` handlers on a
  // `<th>`, this is a native drag that only starts on a handle inside a `<td>`,
  // and there is no element that carries both. The narrower rule — that a row is
  // picked up by its grip rather than anywhere in its body — is the same rule
  // said more strictly, and it is what keeps a cell's text selectable and its
  // editor usable.
  tbody.addEventListener('dragstart', event => {
    const row = event.target.closest('tr[data-id]');
    if (!event.target.closest('.rowgrip') || !row || row.dataset.id === DRAFT_ID) {
      // A selection dragged out of a cell is not a move. Refusing it here is
      // what stops it looking like one.
      event.preventDefault();
      return;
    }
    startMoving(row.dataset.id);
    const carried = event.dataTransfer;
    if (carried) {
      // The id, because a drag that ends outside this table ends in whatever
      // takes text, and the id is the thing worth handing it.
      carried.setData('text/plain', row.dataset.id);
      carried.effectAllowed = 'move';
      if (carried.setDragImage) carried.setDragImage(row, 16, 12);
    }
  });

  tbody.addEventListener('dragover', event => {
    if (!MOVING) return;
    const over = event.target.closest('tr[data-id], tr.adder');
    for (const tr of tbody.querySelectorAll('tr.over')) tr.classList.remove('over');
    // The label goes with the mark, both ways: a row that refuses this one is
    // drawn refusing it and is not named as somewhere it could land.
    if (!over || whyNotOnto(MOVING, over)) { sayInto(''); return; }
    // `preventDefault` is the whole of "you may drop here". Not calling it is
    // how a row refuses: the browser draws its own no-drop cursor over it and
    // `drop` never fires, so the refusal is structural rather than a check
    // somebody has to remember to write at the other end.
    event.preventDefault();
    if (event.dataTransfer) event.dataTransfer.dropEffect = 'move';
    over.classList.add('over');
    sayInto(intoWords(over), event.clientX || 0, event.clientY || 0);
  });

  tbody.addEventListener('drop', event => {
    event.preventDefault();
    const over = event.target.closest('tr[data-id], tr.adder');
    const child = MOVING;
    stopMoving();
    if (!child || !over) return;
    // Asked again here, although `dragover` already refused to let a drop land
    // on a row that cannot take it. What enforces that refusal is the browser,
    // and this file's standing rule is that the browser is assumed to refuse:
    // one implementation that delivers a drop nobody permitted is a blocker
    // committed into the corpus by a hand gesture. `whyNotOnto` is the one
    // answer both handlers ask for, so the two cannot disagree about it.
    const why = whyNotOnto(child, over);
    if (why) { announce(why); return; }
    reparent(child, over.classList.contains('adder') ? null : over.dataset.id);
  });

  // Fires however the drag ended — dropped, cancelled with Escape, let go over
  // the desktop — so it is the one place the marks have to come off.
  tbody.addEventListener('dragend', () => stopMoving());

  tbody.addEventListener('dblclick', event => {
    const cell = event.target.closest('td.edit');
    // The tag reveal is a control inside an editable cell, so a double-click on
    // it would both open the list and open the editor over it.
    if (!cell || event.target.closest('button.more')) return;
    openEditor(cell);
  });

  tbody.addEventListener('keydown', event => {
    // Escape abandons the row nobody has created yet, from anywhere inside it.
    // The two controls it has are marks rather than words, and a person who
    // reached them with Tab should not have to work out which drawing is the way
    // out — this is the key every dismissable thing on this page already answers
    // to, and `closeDraft` says out loud what it did.
    //
    // Two things get it first, both by design. A move in the air owns Escape
    // until it lands, which is why `MOVING` is asked here rather than below. And
    // an open cell editor never reaches this line at all: its own Escape stops
    // the bubble, because discarding one cell and discarding the whole row are
    // different sizes of undo and the smaller one is what was pressed.
    if (event.key === 'Escape' && DRAFT && !MOVING
        && event.target.closest('tr.draft, tr.adder')) {
      event.preventDefault();
      closeDraft('The row was not created');
      return;
    }
    const cell = event.target.closest('td[tabindex]');
    // Only a cell's own keys. Once an editor is open the keys belong to it — its
    // Escape discards and its Tab commits — and the grid must not act as well.
    if (!cell || event.target !== cell) return;
    // A move in the air owns Enter and Escape until it lands. The arrows keep
    // working, because moving to the row you mean is the whole of the gesture —
    // this is the drag, walked instead of dragged, and the same rows are lit and
    // the same rows refuse.
    if (MOVING) {
      if (event.key === 'Escape') {
        event.preventDefault();
        stopMoving(`${MOVING} was left where it was`);
        return;
      }
      if (event.key === 'Enter') {
        event.preventDefault();
        const onto = cell.parentNode.dataset.id;
        const why = refuses(MOVING, onto);
        // The same sentence the drawn refusal is drawn from, said out loud —
        // because the drawn one is the half a keyboard reader does not get.
        if (why) { refuse(cell, why); return; }
        const child = MOVING;
        stopMoving();
        reparent(child, onto);
        return;
      }
    }
    // The id cell is the handle's keyboard equal: it is the cell that is the
    // row's own name, and it is where the grip is drawn.
    if (event.key === 'Enter' && cell.dataset.col === 'id') {
      event.preventDefault();
      const row = DATA.rows[cell.parentNode.dataset.id];
      if (row && movable(row)) startMoving(row.id);
      else if (row) refuse(cell, moveTip(row));
      return;
    }
    if (event.key === 'Enter' || event.key === 'F2') {
      // F2 as well as Enter, because that is the key every spreadsheet uses and
      // Enter is the one everybody tries first.
      event.preventDefault();
      openEditor(cell);
      return;
    }
    const step = {ArrowLeft: [0, -1], ArrowRight: [0, 1],
                  ArrowUp: [-1, 0], ArrowDown: [1, 0]}[event.key];
    if (!step) return;
    event.preventDefault();
    const rows = [...tbody.rows].filter(tr => tr.dataset.id);
    const line = tr => [...tr.cells].filter(td => td.hasAttribute('tabindex'));
    const clamp = (i, n) => Math.max(0, Math.min(n - 1, i));
    // Clamped rather than wrapped: an arrow at the edge of a plan should stop,
    // not jump to the far corner of it.
    const row = rows[clamp(rows.indexOf(cell.parentNode) + step[0], rows.length)];
    const across = line(row);
    rove(across[clamp(line(cell.parentNode).indexOf(cell) + step[1], across.length)], true);
  });
}
{% endif %}
// One `open` class and two controls that set it — the badge in the cell and the
// `+` in the header — so a cell is in one state however it got there, and there
// is no third one to reason about. Both are toggles, and the badge's name is
// swapped here because an icon-only control's name is the whole of what it says.
function setOpen(td, open) {
  td.classList.toggle('open', open);
  const badge = td.querySelector('button.more');
  if (badge) {
    badge.setAttribute('aria-label', open ? badge.dataset.collapse : badge.dataset.expand);
  }
}

// The cells in one column that have anything to open. A list that already fits
// draws no badge, and counting those would leave a column of seventeen cells
// with nothing hidden in it reporting itself as closed forever — a `+` offering
// to do nothing.
function openable(key) {
  return [...tbody.querySelectorAll(`td[data-col="${key}"].clamp`)]
    .filter(td => td.querySelector('button.more'));
}

tbody.addEventListener('click', event => {
  if (event.target.id === 'clear-filters') { clearFilters(); return; }
  const more = event.target.closest('button.more');
  if (!more) return;
  const td = more.closest('td');
  setOpen(td, !td.classList.contains('open'));
  // The column's control offers whatever the column is not already doing, so
  // opening the last closed cell by hand is what turns its `+` into a `−`.
  syncExpanders();
});
// A derived cell that ignores a double-click looks exactly like a cell that is
// broken. It answers instead, in the same place a refused save answers — and
// through `announce`, so the answer reaches a reader who cannot see that place.
// `why` is a parameter and not only the cell's own: a row refusing to hold
// another one is the same event — a cell answering instead of acting — and the
// sentence belongs to the pair rather than to the cell.
function refuse(cell, why) {
  announce(why || cell.dataset.why);
  cell.classList.add('refused');
  setTimeout(() => cell.classList.remove('refused'), 1500);
}
tbody.addEventListener('dblclick', event => {
  const computed = event.target.closest('td[data-why]');
  if (computed) refuse(computed);
});
document.getElementById('blockers').addEventListener('click', event => {
  // A real href, so the count can be copied, shared and opened in a tab. Handled
  // here as well so that following it keeps whatever else was already filtered.
  event.preventDefault();
  update('predicate', 'has_blocker');
});
// The banner in the shell has no id in its URL to compare against on this page,
// because the table shows every entity rather than one. So the table says what
// it is looking at, and "somebody changed the thing in front of you" stays
// distinguishable from "somebody changed something".
window.SHOWING = Object.keys(DATA.rows);
// Column widths, dragged and remembered. The defaults are whatever the browser
// works out from the content, and are only frozen once somebody drags: measuring
// them all at that moment is what keeps the other columns where they were.
// Bumped when the columns changed: widths stored against the old positional
// keys would land on the wrong columns rather than simply being ignored. Bumped
// again when the cells did — id and status grew a chip and tags shrank to one
// line, so a width dragged for the old contents clips the new ones, and a stored
// width is exactly the thing the automatic fit is not allowed to overrule.
// Bumped a third time when the kind chip left the id cell: a width dragged for
// `PITCH pitch-0c0001` is 60px of empty column beside `pitch-0c0001`.
const WIDTH_KEY = 'openproj:widths:4';
const WIDTHS = trustworthy(remembered.map(WIDTH_KEY));

// A remembered width of zero is not a narrow column, it is a corrupt entry — and
// half-trusting one is worse than ignoring the lot. Skipped at apply time the
// column still DREW, so the table was set narrower than the columns it contains
// and every one of them squeezed until the text wrapped; measured instead, it
// measures the squeeze it is already in and stays there. A stored
// `"progress":0` made the header and the first six rows up to five times their
// height, on one machine, at every window width, until that entry was deleted by
// hand. So a map with a nothing in it is thrown away and the fit runs, which
// heals a browser that already holds one without anybody being told to clear it.
function trustworthy(stored) {
  if (!Object.values(stored).some(width => !(width > 0))) return stored;
  // Cleared, not merely ignored: left in place it is re-read and re-rejected on
  // every load forever, and it is the first thing somebody debugging this would
  // find and have to reason about.
  remembered.forget(WIDTH_KEY);
  return {};
}

// Whether the columns are still the fit's to decide. It goes false the moment a
// grip is let go, and never comes back: after that the widths are a decision
// somebody made, and a refit — on a resize, or when the real face lands — would
// be the page quietly undoing it.
let automatic = !Object.keys(WIDTHS).length;
let dragging = false;
const table = document.getElementById('rows');
const headers = [...table.querySelectorAll('th')];
// The box the rows scroll in. It is what the table is fitted to, and what says
// whether the frozen columns are holding anything back yet.
const scroller = table.parentElement;

// The one column that takes whatever is left over. It clamps to a single line
// and hides the rest behind a `+N`, so it is the only column that can be handed
// space, or refused it, without changing what the row says.
const SPARE_COLUMN = 'tags';

// Who pays for an overflow, in order.
//
// The clamped columns pay first. They already show one item and a `+N`, so a
// narrower one hides an item behind a badge that is right there and says how
// many — the cheapest thing on the page to give up. Then the squeezable ones: the
// title, which is a sentence, and the owner, which is one name. Those degrade by
// wrapping, which costs height on every row that holds a long value.
//
// The order is the whole point, and it was wrong the other way round. With `prs`
// exempt, a 1460px window put `title` on its 110px floor — the column you read —
// while `prs` kept all 172px of a reference you can also get by opening the row.
// Every column named in neither keeps exactly what it measured: a date, a count
// and a cycle number have one right width and no graceful way to be narrower.
// The four columns that hold a list, drawn as one item and a `+N`, and the four
// the fit narrows first. One set, because it is one fact: a column may be made
// narrower exactly when its overflow already has somewhere to go.
const CLAMPED = new Set(['tags', 'prs', 'assignees', 'reviewers']);
const SQUEEZABLE = new Set(['title', 'owner']);
// What the table gives up when it runs out of room, in the order it gives them
// up. All four are lookups rather than answers — each is on the detail page and
// each stays filterable in the facets above — so they are what it can lose and
// still answer the question it is open for.
// `progress` goes first: it is counted from a body that may not keep a list at
// all, the entity page draws it in full beside the tasks it is counted from, and
// `?predicate=untracked` finds the rows that have none. `tags` is last because it
// is the column that absorbs whatever is left over: while it is drawn the table
// fills its container exactly, and once it is gone the fit can only leave a gap
// at the right.
const SHED = ['progress', 'reviewers', 'prs', 'tags'];
// One class per column and not one for the set, because they go one at a time.
const shedClass = key => 'shed-' + key;

// A column's identity is the field it stands for. It used to be the column's
// POSITION for the two that do not sort, so inserting a column anywhere to their
// left silently handed prs the width somebody had dragged for blockers — and
// then it was the header's own text, which tied a remembered width to the word
// printed above it rather than to the column.
const keyOf = th => th.dataset.col;
const FLOOR = 110;      // narrower than this and a squeezed column is unreadable
// A clamped column shows one item and a badge, and its header above them. Set to
// 76 — the badge and a short tag — the fit drove all four to that and `REVIEWERS`
// wrapped over two lines above a truncated login, which is a narrower column and
// a taller row: exactly what the clamp was for, undone. A column is only worth
// narrowing while it still says something.
//
// 116 and not the 112 it was, because these four headers now carry the column's
// `+` as well: `.5rem` of padding, then `REVIEWERS` and its sort glyph, then the
// 2rem the control and the grip stand in. Measured in Chrome at each width in
// turn — at 112 and at 115 `ASSIGNEES` and `REVIEWERS` wrap over two lines, and
// at 116 all four fit on one. The floor went up to pay for the control rather
// than the control shrinking to fit under the old one: it is a 17px target in a
// header that already holds a sort button and a drag handle, and the mis-click
// that sorts the table when somebody meant to expand it is what those four
// pixels of column buy.
const CLAMP_FLOOR = 116;

// What each column would need with every cell on one line, so a column ends up
// as wide as its widest value needs and not one character more. Measured from a
// layout that has forgotten the widths already applied, or a column can only
// ever be measured wider than it currently is.
function naturalWidths() {
  const applied = headers.map(th => th.style.width);
  headers.forEach(th => { th.style.width = ''; });
  // Every column, drawn or shed. What a shed column would need is exactly how
  // the fit decides whether there is room to draw it again, and a column that is
  // `display: none` measures zero — so measured with the shedding undone and put
  // back before anything can paint.
  const shedding = SHED.map(shedClass).filter(one => table.classList.contains(one));
  table.classList.remove(...SHED.map(shedClass));
  table.classList.add('measuring');
  table.style.tableLayout = 'auto';
  table.style.width = 'max-content';
  const natural = headers.map(th => Math.ceil(th.getBoundingClientRect().width));
  table.classList.remove('measuring');
  table.classList.add(...shedding);
  headers.forEach((th, i) => { th.style.width = applied[i]; });
  return natural;
}

// The narrowest this set of columns can be drawn: each one on its floor, or at
// what it measured where that is already narrower. It is the same three numbers
// `fitted` works from and the same two floors, so the number below which the
// table starts scrolling and the number that decides which columns are drawn
// cannot disagree.
//
// They did. The shedding was a typed `@media (max-width: 1100px)` while the
// floors put the fourteen-column minimum at 1354px, so every window from 1101 to
// 1393 scrolled sideways with all fourteen columns it had been told it could
// keep — 293px of overflow at the low end. Two numbers that have to agree,
// written in two languages, drifting; now there is one and it is measured.
function minimumWidth(natural, keys) {
  return keys.reduce((total, key, i) => {
    const floor = CLAMPED.has(key) ? CLAMP_FLOOR : SQUEEZABLE.has(key) ? FLOOR : Infinity;
    return total + Math.min(Math.ceil(natural[i]), floor);
  }, 0);
}

// Which columns this much room can hold, as `[key, width]` pairs in the order
// they are drawn — and the whole of the responsive layout, so that it is
// arithmetic a test can run at any window rather than a rule only a browser can
// answer.
//
// One column at a time, and only while what is left over still will not fit: the
// window at which a column goes is the window at which the fit would otherwise
// have to start scrolling, for each of them in turn. All three at once is a cliff
// — at 1354px the table would drop a fifth of what it says to buy 300px it needs
// 112 of.
function drawnColumns(natural, keys, room) {
  let drawn = keys.map((key, i) => [key, natural[i]]);
  const needs = () => minimumWidth(drawn.map(one => one[1]), drawn.map(one => one[0]));
  for (const key of SHED) {
    if (needs() <= room) break;
    drawn = drawn.filter(one => one[0] !== key);
  }
  return drawn;
}

// The fit itself, as arithmetic over three numbers per column and nothing else:
// what the column needs on one line, what it is called, and how much room there
// is. Separate from the measuring because the browser is the only thing that
// knows how wide `Second-order Miura least-squares coefficients` is, and the
// decision made from that number needs no browser at all — which is how it gets
// tested against a window it never has to be opened in.
//
// Every width here is the measured one. It used to be `Math.ceil(w * 1.1)`, a
// 10% cushion on twelve columns that was most of a 1792px table inside a 1460px
// window: the table arrived scrolling sideways, on a plan of seventeen rows.
function fitted(natural, keys, room) {
  const width = natural.map(w => Math.ceil(w));
  let over = width.reduce((a, b) => a + b, 0) - room;

  // Worst-first, by levelling: the widest column in the group comes down to the
  // second widest, then those two come down to the third, and so on until the
  // overflow is paid for or the group is on its floor. A proportional cut instead
  // takes the same 18% off a 300px sentence and a 110px login, so the column that
  // was already the narrowest pays as much as the one that caused the overflow.
  const level = (group, floor) => {
    while (over > 0) {
      const flex = keys.map((_, i) => i)
                       .filter(i => group.has(keys[i]) && width[i] > floor);
      if (!flex.length) return;
      const worst = Math.max(...flex.map(i => width[i]));
      const paying = flex.filter(i => width[i] === worst);
      const next = Math.max(floor, ...flex.filter(i => width[i] < worst).map(i => width[i]));
      const step = Math.min(worst - next, Math.ceil(over / paying.length));
      paying.forEach(i => { width[i] -= step; });
      over -= step * paying.length;
    }
  };

  level(CLAMPED, CLAMP_FLOOR);
  level(SQUEEZABLE, FLOOR);

  // Whatever is left over — a window wider than the plan needs, or the pixel or
  // two the levelling overshot by — goes to the one column that can hold it
  // without changing what any row says.
  const spare = keys.indexOf(SPARE_COLUMN);
  if (over < 0 && spare !== -1 && width[spare] > 0) width[spare] -= over;
  return width;
}

// A collapsed border is drawn between the columns, not inside them, so the table
// renders a pixel or two wider than the sum `applyWidths` sets — and two pixels is
// a horizontal scrollbar across the whole plan just as surely as two hundred are.
// Measured rather than assumed: it depends on the border width, the zoom and how
// the browser rounds, and this table is drawn at whatever zoom somebody left it at.
function chromeOverhead() {
  const set = Number.parseFloat(table.style.width) || 0;
  return set ? Math.max(0, Math.ceil(table.getBoundingClientRect().width - set)) : 0;
}

function fitWidths() {
  const keys = headers.map(keyOf);
  const natural = naturalWidths();
  const fit = room => {
    // Which columns are drawn is this measurement and nothing else — it was a
    // typed breakpoint 254px away from the number it had to agree with.
    const drawn = drawnColumns(natural, keys, room);
    const kept = new Set(drawn.map(one => one[0]));
    SHED.forEach(key => table.classList.toggle(shedClass(key), !kept.has(key)));
    const width = fitted(drawn.map(one => one[1]), drawn.map(one => one[0]), room);
    // Floored, because a fit that squeezes a column to nothing writes a nothing
    // into storage that outlives the window it was measured in.
    drawn.forEach(([key], i) => { WIDTHS[key] = Math.max(1, Math.round(width[i])); });
    applyWidths();
  };
  fit(scroller.clientWidth);
  // Once round to find out what the border costs, and once more to pay for it.
  // Not a loop: the second fit cannot change the overhead, only what is left after
  // it, and a fit that chased its own tail would be a fit that never settled.
  const overhead = chromeOverhead();
  if (overhead) fit(scroller.clientWidth - overhead);
}

function applyWidths() {
  if (!Object.keys(WIDTHS).length) return;
  table.style.tableLayout = 'fixed';
  let total = 0;
  headers.forEach(th => {
    // A column the narrow breakpoint dropped is not part of the total. Counted
    // in, the table is set wider than the columns it actually draws and the last
    // one floats away from the right edge of nothing.
    if (th.offsetParent === null) { th.style.width = ''; return; }
    const key = keyOf(th);
    if (WIDTHS[key]) { th.style.width = WIDTHS[key] + 'px'; total += WIDTHS[key]; }
  });
  // The table stops being 100% wide once the columns are explicit. Left at 100%,
  // a fixed layout divides the space it is given, so widening one column silently
  // squeezes every other — which is precisely what freezing them was meant to
  // prevent. It scrolls sideways in its own container instead.
  table.style.width = total + 'px';
  stickyOffset();
}

// The title column has to begin exactly where the id column ends, and that width
// is dragged, remembered and re-fitted — so it is measured after layout rather
// than written into the stylesheet, where it would be wrong the first time
// somebody moved a grip.
function stickyOffset() {
  table.style.setProperty('--sticky-1', headers[0].getBoundingClientRect().width + 'px');
}

// Expanding a whole column: one click opens every clamped cell in it, one more
// closes them again. Built from `CLAMPED` and not from a second list of column
// names — the set that decides which cells clamp is the set that decides which
// headers can unclamp them, or the two drift and a column grows a control for a
// badge it does not draw.
//
// It lands in a `<th>` that already holds a sort button and a drag grip, and a
// mis-click that sorts the table when somebody meant to expand it is the failure
// this is designed against. Three things answer it:
//
//   * it is a sibling of the sort button, never a child of it: inside, its click
//     would be the button's click and sorting would happen on the way;
//   * the click stops here, because the `<th>` itself is what sorts — the grip
//     already had to do exactly this for the same reason;
//   * the room it stands in is reserved in the header's own padding (`.expands`
//     in the stylesheet), so it is never drawn over the label, and `CLAMP_FLOOR`
//     is the width at which the label, the sort glyph, the control and the grip
//     all still fit. That floor went up to pay for the control. The alternative
//     was a smaller target in a 112px column beside two other things to hit,
//     which is the mis-click written down as a decision.
//
// The two header shapes end up as one control: `assignees` and `reviewers` sort
// and hold a button, `prs` and `tags` are bare text, and in both the label is at
// the left of the cell and the `+` is at the right of it.
const expanders = new Map();
for (const th of headers) {
  const key = keyOf(th);
  if (!CLAMPED.has(key)) continue;
  th.classList.add('expands');
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'expand';
  // Appended before the grip is, below, so the reading order is label, control,
  // grip — the order they are drawn in.
  th.append(button);
  button.onclick = event => {
    event.stopPropagation();
    // What it does is the inverse of what the column is already doing, and the
    // class it reflects that with is set by `syncExpanders` from the cells
    // themselves. Firing blindly, a `−` on a column somebody had closed by hand
    // would close what was already closed and look broken.
    const open = !button.classList.contains('open');
    for (const td of openable(key)) setOpen(td, open);
    syncExpanders();
  };
  expanders.set(key, button);
}

// What each column control offers, read off the column rather than remembered.
// Nothing here is stored: a redraw replaces every cell and takes the state with
// it, and that is the point — this is a way of reading the plan, not a setting.
// A filter can also leave a column with nothing hidden in it, and a control with
// nothing to do goes rather than sitting there lying about what it will do.
function syncExpanders() {
  for (const [key, button] of expanders) {
    const cells = openable(key);
    const open = cells.length > 0 && cells.every(td => td.classList.contains('open'));
    button.hidden = !cells.length;
    button.classList.toggle('open', open);
    // The column's own word, lowercased the way the cells' tooltips say it, so
    // "Show all reviewers" and "Double-click to edit reviewers" name the same
    // column the same way. A `title` as well, because the sighted reader of an
    // icon has the same question — but never a `title` alone: this is a control,
    // not a hint.
    const named = (FIELD_LABELS[key] || key).toLowerCase();
    const name = open ? `Show fewer ${named}` : `Show all ${named}`;
    button.setAttribute('aria-label', name);
    button.title = name;
  }
}

headers.forEach((th, i) => {
  const grip = document.createElement('span');
  grip.className = 'grip';
  th.append(grip);
  grip.onclick = event => event.stopPropagation();
  // Double-click a grip and the column shrinks to what its widest cell needs on
  // one line — the width you would have dragged to, without the dragging.
  grip.ondblclick = event => {
    event.stopPropagation();
    const key = keyOf(th);
    WIDTHS[key] = Math.ceil(naturalWidths()[i]);
    remembered.set(WIDTH_KEY, JSON.stringify(WIDTHS));
    automatic = false;
    applyWidths();
  };
  grip.onpointerdown = event => {
    event.stopPropagation();
    event.preventDefault();
    // The click that follows a drag lands on the header, not the grip, so
    // stopping propagation here is not enough — the sort handler checks this.
    dragging = true;
    grip.classList.add('dragging');
    // Freeze every column first, or resizing one reflows all the others.
    headers.forEach(other => {
      const key = keyOf(other);
      WIDTHS[key] = WIDTHS[key] || Math.round(other.getBoundingClientRect().width);
    });
    table.style.tableLayout = 'fixed';
    const key = keyOf(th);
    const from = event.clientX;
    const was = WIDTHS[key];
    const move = e => {
      WIDTHS[key] = Math.max(40, was + e.clientX - from);
      applyWidths();
    };
    const stop = () => {
      grip.classList.remove('dragging');
      setTimeout(() => { dragging = false; }, 0);   // after the click it caused
      remembered.set(WIDTH_KEY, JSON.stringify(WIDTHS));
      automatic = false;
      removeEventListener('pointermove', move);
      removeEventListener('pointerup', stop);
    };
    addEventListener('pointermove', move);
    addEventListener('pointerup', stop);
  };
});

for (const th of document.querySelectorAll('th[data-sort]')) {
  // On the header, not on the button inside it: a click anywhere in the cell
  // still sorts, and the button's own Enter and Space arrive here by bubbling —
  // which is the whole reason it is a button and not a click handler on a cell
  // nobody can tab to.
  th.addEventListener('click', () => {
    if (dragging) return;
    // Clicking the column you are already sorted by reverses it, which is what
    // every table anybody has used does.
    const already = (params.get('sort') || 'id') === th.dataset.sort;
    params.set('sort', th.dataset.sort);
    update('desc', already && params.get('desc') !== '1' ? '1' : '');
  });
}
regroup(DATA.problems);
summarise();
draw();
// After the first draw, because there is nothing to measure before the rows
// exist. Stored widths win: they were set by hand, on purpose.
if (automatic) fitWidths(); else applyWidths();
// The typeface arrives as a `data:` URI with `font-display: swap`, so the layout
// this was just measured against may still be the fallback's metrics — and then
// a first load fits to widths a reload does not reproduce, which is exactly the
// "broken until I reloaded" it looked like. Measured once more when the real
// face is in, which is the moment the numbers stop moving.
if (document.fonts) document.fonts.ready.then(() => { if (automatic) fitWidths(); });
// The fit drops columns as the window narrows, and the sticky title column
// starts where the id column ends — both are facts about a layout that only
// exists once it has been laid out. An automatic fit is a fit to *this* window,
// so a new window gets a new one; a dragged width is a decision and is only
// re-applied.
// Which is also why a dragged layout keeps all fourteen columns however narrow
// the window gets: shedding exists because the fit would otherwise squeeze every
// column past reading, and a column somebody sized by hand is not being squeezed
// by anything. It scrolls sideways, which is what dragging a column wider than
// the window asks for.
addEventListener('resize', () => {
  if (automatic) fitWidths(); else applyWidths();
  stickyOffset();
});
// The rule down the right of the frozen title column says "what is to the left
// of this is being held still while the rest passes under it". At scrollLeft 0
// nothing is passing under anything and it reads as a stray separator between
// title and priority, which is the first thing anybody asked about it. Set here
// rather than only on the event, because a reload restores scrollLeft before any
// of this runs.
const frozenEdge = () => scroller.classList.toggle('scrolled', scroller.scrollLeft > 0);
scroller.addEventListener('scroll', frozenEdge);
frozenEdge();
</script>
"""

_TABLE_STYLE = """
/* The far end of the edit bar. `margin-left: auto` and not `space-between`,
   because on a rendered file the bar holds nothing else — the count stays at the
   right rather than sliding to the left when the controls beside it are gone. */
.editbar #summary { margin: 0 0 0 auto; text-align: right; }
/* The whole phrase, not the digit: "1 blocking problems" in danger red with the
   count black beside it read as two separate facts. And the colour has to mean
   something — at zero it is muted, because danger nobody can act on is danger
   nobody reads. */
#blockers { color: var(--sev-blocker); text-decoration: none; }
#blockers:hover { text-decoration: underline; }
#blockers.none { color: var(--muted); }
/* The table body scrolls in here rather than in the page. `position: sticky` on
   a header needs a scroll container to hold against, and a container the height
   of its own content gives `top: 0` nothing to do.
   `max-height` and not `height`: three rows are three rows, and a table stretched
   to the window with 400px of nothing under the last one is a table that looks
   like it failed to load the rest. The graph's canvas is the other case — it has
   no size of its own — and it takes the same measurement as a `height`.
   That measurement used to be `100vh - 15rem`, a hand-count of the stack above
   the rows written down as a constant, and it had already been wrong once: the
   page gained a heading and the box ran past the bottom of the window. It is
   measured now, in the shell, and the same number answers the graph and the
   timeline.
   The overflow used to cut off the suggestion popups the cells open, on this
   table and on any table that borrowed the class; `attachSuggest` parks its list
   on the body now, so an ancestor's overflow no longer reaches it. */
.table-scroll { overflow: auto; max-height: var(--room);
                min-height: 9rem; overscroll-behavior: contain; }
table { border-collapse: collapse; width: 100%; font-size: 13px; }
th, td {
  border-bottom: 1px solid var(--line); padding: .3rem .5rem; text-align: left;
  /* Border-box, or a width set from a measured box gains the padding again and
     every column grows by exactly one cell's worth on the first drag. */
  box-sizing: border-box;
  /* A PR reference has no space in it, so at a narrow width it hangs over the
     next column instead of wrapping inside its own. */
  overflow-wrap: anywhere;
}
th { color: var(--muted); font-weight: 400;
     text-transform: uppercase; letter-spacing: .04em; font-size: 11px; }
th[data-sort] { cursor: pointer; user-select: none; }
th.sorted { color: inherit; font-weight: 700; }
th { position: relative; }
/* The button is the header: it takes the cell's type so the column still reads
   as a label, and only the focus ring says it is a control. */
th button { font: inherit; color: inherit; letter-spacing: inherit;
            text-transform: inherit; background: none; border: 0; padding: 0;
            cursor: pointer; }
/* Reserved whether or not this is the sorted column, so sorting does not shove
   every header one glyph to the left. */
th .dir { display: inline-block; width: .8em; color: var(--accent); }
thead th {
  position: sticky; top: 0; z-index: 3; background: var(--surface);
  /* A collapsed border is not painted on a sticky cell — the first row scrolls
     straight over the top of it — so the rule is drawn inside the box instead. */
  box-shadow: inset 0 -1px 0 var(--line);
}
/* The two columns that say which row you are looking at. Scrolled right without
   them, fourteen columns of values belong to nobody. They need a ground of their
   own and a layer above the cells passing underneath.

   One bare attribute selector each, which is (0,1,0) — deliberately the lightest
   rule that can reach these cells, because these two lines state a *default*
   ground and a *default* layer that three rules below exist to correct. Each of
   those adds an element or a class, so each is (0,1,1) and each wins on weight
   alone, whichever order the stylesheet ends up in.

   These were briefly `.table-scroll [data-col=…]` — (0,2,0), written to outrank
   `dd, td.edit { position: relative }` in _SUGGEST_STYLE, which was stealing
   `position: sticky` from the title cell so that it kept the `left` meant for a
   sticky box and shifted 187px right over priority and status. It fixed that and
   silently outranked all three corrections: both frozen headers dropped to
   z-index 1 and were painted over by their own rows, the title header lost its
   bottom rule, and a problem on either column lost its ground. The suggestion
   popup is parked on the body now and that rule is gone, so the weight these
   need is the weight that loses to everything meant to correct them. */
[data-col="id"] { position: sticky; left: 0; z-index: 1; background: var(--surface); }
[data-col="title"] { position: sticky; left: var(--sticky-1, 0px); z-index: 1;
                     background: var(--surface); }
thead [data-col="id"], thead [data-col="title"] { z-index: 4; }
thead [data-col="title"] { box-shadow: inset 0 -1px 0 var(--line); }
/* The edge of the frozen pair, drawn only while there is something passing under
   it. Unconditionally it is a vertical rule between title and priority and
   nothing else — the table has no other column separators, so at scrollLeft 0 it
   reads as one column having been singled out for a border.
   Inset, and that is the whole of it: this shipped as `1px 0 0 var(--line)` and
   painted nothing at all, in either state, because Chrome does not paint an
   *outset* box-shadow on a cell in a `border-collapse: collapse` table. The
   comment two rules up already said so about the header's bottom rule and the
   right edge was written outset anyway, so the resting state was accidentally
   right and the scrolled state had no edge — half-clipped `+N` badges sitting
   hard against the title column, looking like a clipping bug.
   Two rules and not one: the header's own bottom rule is drawn inside its box
   too, so both shadows have to be named together or setting one drops the other.
   `.scrolled td[…]` is (0,2,1) and beats the bare (0,1,0) above it;
   `.scrolled thead th[…]` is (0,2,2) and beats that in turn, whatever order this
   file ends up in. */
.scrolled td[data-col="title"] { box-shadow: inset -1px 0 0 var(--line); }
.scrolled thead th[data-col="title"] {
  box-shadow: inset 0 -1px 0 var(--line), inset -1px 0 0 var(--line);
}
/* The tree.

   The indent is the cell's own padding, which is what puts it into
   `naturalWidths()` — a drawing that overlapped the title would be a column
   measured at a width the words do not fit in. 14px a level and three levels at
   most: `PARENT_KINDS` bounds the real depth at two, a task hanging off a
   project is one, and 42px is what the deepest possible plan costs the one
   column that is a sentence. `tr.dN > td[…]` is (0,2,2) and beats the `th, td`
   padding at (0,0,2) and the frozen column's (0,1,0), which is the whole of what
   it has to beat: nothing else on this page sets padding on a cell.

   The connectors are borders, not characters. `├─` and `└─` line up only in a
   monospace face and this column is proportional — and a screen reader announces
   "box drawings light up and right" before every child's title, which is why the
   wrapper is `aria-hidden` and holds nothing to read.

   Absolute, against the title cell's own `position: sticky`. That is a real
   dependency and it is worth writing down: sticky is a positioned value, so it
   is the containing block for these, and it is set by the rule fifteen lines up
   that freezes the column. If that ever stops being sticky the connectors are
   the second thing to go — they would hang off the scroll container and slide
   away from their rows — and this comment is the note that they go together.
   `top: 0; bottom: 0` is the reason to do it this way at all: the vertical line
   is then exactly the height of the row it is in, whatever that row holds, which
   an inline box guessing at a line height cannot promise. */
tr.d1 > td[data-col="title"] { padding-left: calc(.5rem + 14px); }
tr.d2 > td[data-col="title"] { padding-left: calc(.5rem + 28px); }
tr.d3 > td[data-col="title"] { padding-left: calc(.5rem + 42px); }
.tree { position: absolute; left: .25rem; top: 0; bottom: 0; display: flex; }
.tree .rung { position: relative; width: 14px; }
/* The vertical: full height where the branch carries on past this row, and half
   of it on the last child drawn, which is the whole difference between `├` and
   `└`. `blank` draws neither, and it is a rung rather than a margin so that the
   levels stay in step down the column. */
.tree .line::before, .tree .tee::before, .tree .end::before {
  content: ""; position: absolute; left: 6px; top: 0; width: 1px;
  background: var(--line-strong);
}
.tree .line::before, .tree .tee::before { bottom: 0; }
.tree .end::before { height: 50%; }
/* The stub, stopping short of the title so the word is not touched by a rule. */
.tree .tee::after, .tree .end::after {
  content: ""; position: absolute; left: 6px; top: 50%; width: 6px; height: 1px;
  background: var(--line-strong);
}
/* A row that is not an answer to what was asked, kept because something under it
   is: the pitch over three tasks that matched, so that a filtered table is still
   a plan and not a list of orphans. It is a record like any other — its title
   opens it, its cells still edit, a drop still lands on it — so it is dimmed
   rather than disabled, and `summarise` does not count it.

   `tr.context > td` is (0,1,2), which beats the frozen columns' (0,1,0) and the
   severity grounds' (0,1,1): a dimmed row with a blocker on it loses the fill in
   its cell and keeps both of the other two channels that say so — the stripe,
   which is a border on the `<tr>` and nothing here touches, and the ⚠ in the
   cell, which is text. `table.moving tr.can-hold > td` is (0,2,3) and beats this
   in turn, which is the right way round: for the length of a drag the only thing
   worth knowing about a row is whether it would take the one in your hand.

   The dimming is ink and a ground rather than `opacity` on the row. Opacity
   below 1 makes a stacking context of whatever carries it, and what carries it
   here would be two sticky cells whose whole job is to be opaque while the rest
   of the table passes underneath them — a see-through frozen column is a worse
   defect than the one this is drawing. The chips take theirs on the inside,
   where there is nothing behind them to show through. */
tr.context > td { background: var(--surface-2); color: var(--muted); }
tr.context > td a { color: var(--muted); }
tr.context .chip, tr.context .meter { opacity: .6; }
tr.context .tree .rung::before, tr.context .tree .rung::after { background: var(--line); }
/* One weight heavier than the sticky rules above — an element and a class beats
   a bare attribute selector — so a problem in the id or the title column keeps
   its ground. It is the specificity that does it and not the order: written the
   other way up these would still win, and the comment that said "after the
   sticky rules" was describing a cascade nothing depends on. The `td` is not
   decoration either: the shell already says `.sev-cell-blocker` at (0,1,0) and
   the frozen columns' `background` above would tie it and win on order. */
td.sev-cell-blocker { background: var(--sev-blocker-soft); }
td.sev-cell-warn { background: var(--sev-warn-soft); }
/* Editable and derived cells looked identical, and the only thing that said
   otherwise was a 12px hint at the top of the page. */
td.edit { cursor: cell; }
td.edit:hover { background: var(--surface-2); box-shadow: inset 0 -1px 0 var(--line-strong); }
td.refused { background: var(--surface-2); }
/* A value this record did not name: its reviewers, taken from the work filed
   under it. A ground rather than an italic or a bracket, because the cell is a
   list of logins and every other channel in it is already spoken for — and the
   ground is the one that survives a clamped cell showing one name and a `+2`.
   `--st-ready-soft` and not a colour of its own: the five status tints are the
   palette this table already reads in, and this is a tint from it rather than a
   sixth thing to learn. */
td.inherited { background: var(--st-ready-soft); }
td.clamp { white-space: nowrap; overflow: hidden; }
/* A row, so that what gets cut is the value and never the badge. Laid out
   inline, the `+2` is simply the last thing on an overflowing line: a clamped
   column on its 112px floor cut a third off it, and one sixty-character login
   pushed it 368px past the edge of the cell. The badge is the whole promise the
   clamp makes — it says how many are hidden and it is the control that shows
   them — so it is the one part that cannot be the part that goes.
   Two declarations do the work: `min-width: 0` on the value, because a flex item
   refuses to shrink below its own content without it and we would be back where
   we started, and the ellipsis, so a value that was cut says so.
   `flex: none` on the badge and the glyph is belt and braces. A flex item's
   automatic minimum already keeps them whole — but only while their text has
   nowhere to wrap, and "this one never gives up width" is what they mean rather
   than something the next reader should have to re-derive. */
td.clamp .clamped { display: flex; align-items: baseline; }
td.clamp .clamped > .first { min-width: 0; overflow: hidden; text-overflow: ellipsis; }
td.clamp .clamped > .more, td.clamp .clamped > .sev-mark { flex: none; }
td.clamp .rest { display: none; }
td.clamp .more { font: inherit; font-size: 11px; line-height: 1.2; margin-left: .3rem;
                padding: 0 .25rem; border: 1px solid var(--line-strong); border-radius: 2px;
                background: none; color: var(--muted); cursor: pointer; }
/* The sign, from the class that opens the cell rather than from the script that
   sets it: `+2` and `−2` are one count seen from either side, and drawn this way
   the glyph cannot end up disagreeing with the state it is describing. The badge
   used to be `display: none` while the cell was open, which is what made the
   reveal one-way — there was nothing left to click. */
td.clamp .more::before { content: "+"; }
td.clamp.open .more::before { content: "−"; }
td.clamp.open { white-space: normal; }
/* Opened, the cell is a paragraph again: every item on as many lines as it
   takes, which is what the reveal is for. A flex row here would lay the value
   and the rest of the list side by side and clip the pair. */
td.clamp.open .clamped { display: block; }
td.clamp.open .rest { display: inline; }
td .sev-mark { margin-left: .25rem; }
/* A point smaller than the row it sits in, because a monospace face at the same
   nominal size reads larger than the text beside it: wider glyphs, a taller
   x-height, and no two characters closer together than any other pair. At 13px
   the id was the loudest thing on a row where it is the least interesting — it
   is a token to cite, not a heading — and the mono face is already what marks it
   as one. 12px and not `.9em`: this column is what the frozen title column's
   `left` is measured from, and a relative size compounds if anything above it
   ever changes. */
.eid { font-family: var(--font-mono); font-size: 12px; }
td[data-col="cycle"], td[data-col="size"], td[data-col="start"], td[data-col="end"],
td[data-col="blocked_by"] { font-variant-numeric: tabular-nums; }
/* The column's `+`, in the header of every column that clamps. It is the badge
   in the cells below it wearing the same border and the same 11px, because it
   means the same thing one level up — `+4` in a cell is four you cannot see,
   `+` in the header is every one of them in the column.

   `th .expand` is (0,1,1) and beats `th button` at (0,0,2) whichever order this
   file ends up in, which is the point: that rule strips a header button of its
   border and its background on purpose, so that a sort control reads as a label,
   and this control has to read as a control.

   Absolute, so it sits at the right of the header rather than after a label
   whose width is a different number in each of the four columns — and clear of
   the grip, which owns the last 7px of the cell. The room it stands in is
   reserved below rather than taken from the label. */
th .expand {
  position: absolute; top: 50%; right: 9px; transform: translateY(-50%);
  font: inherit; font-size: 11px; line-height: 1.2; padding: 0 .25rem;
  border: 1px solid var(--line-strong); border-radius: 2px; background: none;
  color: var(--muted); cursor: pointer;
}
th .expand::before { content: "+"; }
th .expand.open::before { content: "−"; }
/* Reserved in the header's own box, because a positioned box is in no
   measurement of its own accord. This is the whole of what puts the control into
   `naturalWidths()`: without it a column whose widest cell is narrower than its
   own header — a plan of two-letter logins — is measured at the label's width,
   handed exactly that, and draws the `+` over the end of the word. On the demo
   corpus every one of the four is sized by a cell instead and nothing overlaps,
   which is precisely why this is not a thing to leave to being noticed.
   `CLAMP_FLOOR` is the other half: the width at which what is left of the header
   still holds the longest of the four labels on one line. */
th.expands { padding-right: 2rem; }
th .grip {
  position: absolute; top: 0; right: 0; width: 7px; height: 100%; cursor: col-resize;
}
th .grip::before {
  content: ""; position: absolute; top: 20%; bottom: 20%; right: 3px; width: 1px;
  background: var(--line-strong);
}
th .grip:hover::before, th .grip.dragging::before { background: var(--accent); width: 2px; }
.measuring th, .measuring td { white-space: nowrap; }
/* One screen is not one width. Below the width the columns need with every
   squeezable one already on its floor, the ones that are lookups rather than
   answers go, one at a time — they are all reachable on the detail page, and the
   filters above still see them.
   Which width that is is not written here. It was, as a media query at a typed
   1100px, and the floors it had to agree with put the real minimum at 1354px:
   every window between them scrolled sideways with all fourteen columns.
   `fitWidths` sets these classes from its own arithmetic now, so there is one
   number and the browser measures it. */
.shed-progress [data-col="progress"],
.shed-reviewers [data-col="reviewers"],
.shed-prs [data-col="prs"],
.shed-tags [data-col="tags"] { display: none; }

/* Where a row is picked up. Two dotted rules and not a `⠿`: that glyph is not in
   the vendored face's latin subset, so on a machine with no webfont it is a tofu
   box — the same argument the status marks settle the other way, because those
   five had to be text inside a 14px bar. Drawn, it follows the theme and cannot
   be the one character a reader's font does not have.
   `cursor: grab` is the only thing on the page that says a row can be picked up
   before somebody tries. */
.rowgrip {
  display: inline-block; width: 6px; height: 11px; margin-right: .4rem;
  vertical-align: -1px; cursor: grab;
  border-left: 2px dotted var(--line-strong); border-right: 2px dotted var(--line-strong);
}
.rowgrip:hover { border-left-color: var(--accent); border-right-color: var(--accent); }
/* While a move is in the air the table answers one question, and it answers it
   in the ground of every cell: this row would take it, this one would not.
   On the cells and not on the `<tr>`, because the two frozen columns paint a
   background of their own — a row-level colour is drawn underneath them and the
   id and the title would be the two cells that did not answer.
   `tr.can-hold > td` is (0,1,2) and beats `[data-col="id"]` at (0,1,0), the
   severity grounds at (0,1,1) and `td.edit:hover` at (0,1,1), whatever order
   this file ends up in. Beating the severity grounds is deliberate and it is
   worth saying so: for the length of one gesture the only thing worth knowing
   about a row is whether it can take the one in your hand, and the problem
   grounds come back the moment it is over. */
table.moving tr.can-hold > td { background: var(--surface-2); }
table.moving tr.no-hold > td { background: var(--surface); color: var(--muted); }
table.moving tr.no-hold > td a, table.moving tr.no-hold > td .chip { color: var(--muted); }
/* The row the drop would land in: the would-be parent, in green, and the only
   green on the page. Every other row a drop could legally land on is on the
   panel tint above, so the two questions a hand is asking — where may this go,
   and where is it going right now — are answered in two different channels
   rather than in two shades of one. A row that cannot be a parent is never
   given it: `dragover` returns before the class is added.
   Inset, and that is not a style choice: Chrome does not paint an *outset*
   box-shadow on a cell in a `border-collapse: collapse` table, which is how the
   frozen column's edge came to be a rule that resolved perfectly and drew
   nothing at all for a whole round. */
table.moving tr.over > td {
  background: var(--drop);
  box-shadow: inset 0 2px 0 var(--ok), inset 0 -2px 0 var(--ok);
}
/* What the drop would do, named, beside the cursor.
   No dialog: a modal on every drag is a toll on a gesture that is already
   deliberate, and a reparent is one field and one commit that dragging back
   undoes. `position: fixed` and parked on the body, because `.table-scroll`
   clips its contents and a label that scrolls out from under the pointer is
   worse than none. z-index 5 clears the whole table — the header is 3, its own
   frozen pair 4 — and `pointer-events: none` keeps it out of the way of the very
   `dragover` that positions it. One line, because it names a title and a title
   is a sentence: two-line labels move under the cursor as they rewrap. */
#into {
  position: fixed; z-index: 5; pointer-events: none;
  font-size: 12px; padding: .1rem .4rem; max-width: 22rem;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  border: 1px solid var(--ok); border-radius: 3px;
  background: var(--drop); color: var(--fg);
}
/* The last row: where a plan grows, and — while a move is in the air — where a
   row goes to belong to nothing.
   Sticky, so that on a plan of two hundred rows the way to add one more is not
   two hundred rows down. z-index 2 puts it over the cells passing under it
   (z-index 1, the frozen columns) and under the header (3, and 4 for its own
   frozen pair), which is the order they are in on screen. */
tr.adder > td {
  position: sticky; bottom: 0; z-index: 2;
  background: var(--surface); border-top: 1px solid var(--line);
  box-shadow: inset 0 1px 0 var(--line);
}
tr.adder button {
  font: inherit; font-size: 12px; padding: .1rem .5rem; margin-right: .5rem;
  border: 1px solid var(--line-strong); border-radius: 3px;
  background: none; color: inherit; cursor: pointer;
}
tr.adder button:hover { border-color: var(--accent); color: var(--accent); }
tr.adder button.primary { border-color: var(--accent); color: var(--accent); font-weight: 600; }
tr.adder .hint { font-size: 12px; color: var(--muted); }
/* The draft row's controls, in whichever of their two places they were drawn:
   the bar while there is no row, the row's id cell once there is one. The
   wrapper lays them out because a `<td>` that is a flex container stops being a
   table cell — the same reason the clamped columns have a `.clamped` inside
   them. Three rules, and each is a thing that went wrong on the page:

   Laid out at all. Without this the marks and the picker were inline boxes in
   the narrowest column on the table and the picker wrapped under them, so the
   draft stood twice the height of every other row — which is the thing
   `draftControls` says the marks are marks in order to avoid.

   `inline-flex` and not `flex`. In the bar this wrapper shares a line with the
   sentence saying nothing is written yet, and a block-level flex box took the
   whole width: the picker stretched to 1400px and the sentence went to a line
   of its own.

   `max-width` is what makes shrink-to-fit shrink. A `<select>` is as wide as
   its widest option, so in the id cell the wrapper sized itself to
   "choose a kind…" — a string only ever read in the bar — and stood 33px past
   the edge of a cell whose width the fit had already decided. */
.drafting { display: inline-flex; align-items: center; gap: .2rem;
            max-width: 100%; vertical-align: middle; margin-right: .5rem; }
/* And the picker is the part that gives, because `min-width` on a flex item is
   `auto`: without this the marks were pushed out of the cell instead. */
.drafting select { font: inherit; font-size: 12px; min-width: 0; flex: 1 1 auto; }
/* An icon-only control. Square and centred rather than padded like a word: the
   mark has no baseline to sit on, and `tr.adder button`'s `.1rem .5rem` is the
   room a word needs on either side of it. */
.draft-do {
  display: inline-flex; align-items: center; justify-content: center;
  flex: none; margin: 0; padding: .2rem;
  font: inherit; font-size: 12px; line-height: 0;
  border: 1px solid var(--line-strong); border-radius: 3px;
  background: none; color: inherit; cursor: pointer;
}
.draft-do:hover { border-color: var(--accent); color: var(--accent); }
/* The one of the two that writes, in the ink this page gives that press
   everywhere else. `.draft-do.primary` is (0,2,0) and its hover (0,3,0), so the
   two do not have to be read in the order they happen to be written in. */
.draft-do.primary { border-color: var(--accent); color: var(--accent); }
.draft-do.primary:hover { background: var(--surface-2); }
/* The `+` and the way out swap places, because at any moment exactly one of them
   is a thing you can do. `:not([hidden])` because `table.moving #unparent` is
   (1,1,1) and the browser's own `[hidden] { display: none }` is (0,1,0): without
   it, the button that has nothing to take a row out of is shown anyway. */
tr.adder #unparent { display: none; }
table.moving tr.adder #add-row { display: none; }
table.moving tr.adder #unparent:not([hidden]) { display: inline-block; }
table.moving tr.adder > td { box-shadow: inset 0 2px 0 var(--accent); }
table.moving tr.adder.over > td { background: var(--surface-2); }
/* A row with a write in the air. Dimmed rather than spinning: the row is still
   readable, still says what it said a second ago, and the one thing that has
   changed is that it is not settled yet. `cursor: progress` on the whole row is
   the second channel, for a reader who has the animation turned off. */
tr.writing > td { opacity: .55; cursor: progress; }
/* The row being typed. It is a form laid out as a row, so an empty cell has to
   look like a box to fill in rather than like a value nobody has written: the
   column's own word, in the muted ink every hint on this page uses.
   `attr()` in `content` and not a text node, because the hint is furniture — a
   screen reader on the cell hears its column header and the editor's own
   `aria-label`, which is the name of the thing, said once. */
tr.draft > td { background: var(--surface-2); }
/* While this cell holds the row's controls instead of an id it is a strip of
   controls and not a value, so it gives back the room either side of a value:
   at the column's own 8px the picker had 56px to say `Project` in and drew
   `Projec`, in the one cell whose whole job is to say what the row will be. */
tr.draft .draft-id { color: var(--muted); padding-left: .3rem; padding-right: .3rem; }
td.draft-cell:empty::after { content: attr(data-hint); color: var(--empty); }
/* A column this kind has not got, or one nothing may type into. Hatched rather
   than merely empty: every other cell in this row carries its column's word in
   the muted ink, so an empty one would read as a box nobody has filled in yet —
   and this is a box nobody can.
   Drawn at `--line-strong` and at full strength, which is not a taste: at
   `--line` under `opacity: .5` the stripes were, on the screen, nothing at all.
   A hatch nobody can see is an empty cell with a comment attached.
   `tr.draft > td.draft-none` is (0,2,2) because it has to beat the row's own
   ground at (0,2,0) two rules up — and that rule uses the `background`
   SHORTHAND, which resets `background-image` to none. Written as `td.draft-none`
   this resolved perfectly and painted nothing, which is this file's
   characteristic failure and was caught by looking at the pixels. What it now
   outranks is exactly that one rule: nothing else in this stylesheet reaches a
   cell of the draft row. */
tr.draft > td.draft-none {
  background-image: repeating-linear-gradient(-45deg, transparent, transparent 3px,
                    var(--line-strong) 3px, var(--line-strong) 4px);
}
/* The one question a status change may ask, over the row it is about. Fixed, so
   it is not clipped by the table's own scroller — the cell it belongs to can be
   in a frozen column with `overflow: hidden` two ancestors up — and z-index 6,
   which clears the header (3), the frozen pair (4) and the drop label (5). */
#askfor {
  position: fixed; z-index: 6; min-width: 14rem;
  display: flex; flex-direction: column; gap: .35rem;
  padding: .5rem .6rem; background: var(--surface); color: var(--fg);
  border: 1px solid var(--line-strong); border-radius: 3px;
  box-shadow: 0 4px 14px rgba(0,0,0,.12);
}
#askfor[hidden] { display: none; }
#askfor .asking { margin: 0; font-size: 12px; color: var(--muted); }
#askfor label { display: flex; flex-direction: column; gap: .15rem;
                font-size: 11px; color: var(--muted); text-transform: uppercase;
                letter-spacing: .04em; }
#askfor input { font: inherit; font-size: 13px; text-transform: none;
                letter-spacing: 0; color: var(--fg); padding: .15rem .3rem;
                border: 1px solid var(--line-strong); border-radius: 3px; }
#askfor .acts { display: flex; gap: .4rem; margin-top: .15rem; }
#askfor button { font: inherit; font-size: 12px; padding: .15rem .6rem;
                 border: 1px solid var(--line-strong); border-radius: 3px;
                 background: none; color: inherit; cursor: pointer; }
#askfor button.primary { border-color: var(--accent); color: var(--accent); font-weight: 600; }
/* The create refusal, beside the row it refused. `#row-conflict` is styled in
   the shell and this is the same kind of news, but a create has no row to sit
   next to — so it lands in the bar, where the button that caused it is. */
#draft-problems { margin: .25rem 0 0; padding-left: 1.1rem; color: var(--sev-blocker);
                  font-size: 12px; }
"""

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
<div class="keyrow">
<ul class="legend" aria-label="What a node's colour and mark mean">
  {% for status in statuses %}
  <li><span class="swatch st-{{ status }}" aria-hidden="true">{{ glyph(status) }}</span
    >{{ status|human }}</li>
  {% endfor %}
</ul>
<div id="summary"><span id="shown" class="num">{{ total }}</span> of {{ total }} shown<span
  id="context"></span></div>
</div>
<div class="canvas">
  {#- `data-fills`: this is the box the shell measures the window into. A canvas
      has no size of its own — whatever it is told, it draws — so it is the one
      box on these three pages that takes a `height` rather than a cap. -#}
  <div id="cy" data-fills></div>
  {#- Written by the script, because which emptiness this is is not known until
      the payload has been parsed and the filter has run. -#}
  <div id="nothing" hidden>
    <p class="headline"></p>
    <p class="hint"></p>
    <button type="button" id="clear-filters" hidden>Clear filters</button>
  </div>
</div>
{% if editable %}
{#- Under the canvas it writes to, like every other page's primary action: Create,
    Edit and Save the setup all moved below their forms and the graph was the
    fourth page with one. Sticky as well as last, because the drawing you are
    committing fills the window and a Save at the far end of it is a Save you go
    looking for while holding an unsaved decision in your head. Sticky is also why
    the canvas above is measured rather than assumed: a bar that is always on
    screen is always in front of something, and for two rounds that something was
    140px of graph. -#}
<div class="commitbar" id="commitbar">
  <button type="button" id="connect">Edit dependencies</button>
  {#- A mode, for the same reason the other one is: a plain drag on this canvas
      means "move the node" and always has, so the gesture that files one record
      inside another has to say which it is. What is new is that the dragging,
      the drop target and the highlighting are the extension's now — the version
      of this written here could not tell the reader where the node would land,
      because the box it would land in moves with the node. -#}
  <button type="button" id="refile">Refile</button>
  <button type="button" id="save" hidden>Save</button>
  <button type="button" id="discard" hidden>Reset</button>
  <span id="state" role="status"></span>
  <input type="hidden" id="base" value="{{ base_commit }}">
</div>
{% endif %}
<script id="elements" type="application/json">{{ elements|tojson }}</script>
{#- `model.PARENT_KINDS`: which kind may hold which. The extension asks before it
    lets go, so a drop the server would refuse is one the canvas never offers. -#}
<script id="parents" type="application/json">{{ parent_kinds|tojson }}</script>
<script>{{ cytoscape }}</script>
{#- ELK rather than dagre, because dagre does not know what a nested node is: it
    lays a plan whose pitches hold tasks out as though it were flat, and the
    result was measured on the real plan at 7% of the canvas with three of six
    dependency edges drawn across a box they are not attached to. ELK's layered
    algorithm is hierarchy-aware and put the same plan on the same canvas with
    none of them crossing. It is the one vendored file that is not permissively
    licensed — EPL-2.0, notice beside it in `static/`, see `VENDOR.md`. -#}
<script>{{ elk }}</script>
<script>{{ cytoscape_elk }}</script>
{#- Filing one thing inside another was written here by hand, shipped, and
    removed the same day: a compound's outline follows the child being dragged,
    so the drop looked like nothing happening until the page reloaded. This
    extension is 14 KB, has no dependencies, and had solved it — see `Look for it
    before you write it` in AGENTS.md, which this is the worked example of.
    Its sibling `cytoscape-edgehandles` was audited and refused in the same pass:
    it wants two lodash modules as globals to replace a gesture that works. -#}
<script>{{ compound_dnd }}</script>
{{ filters }}
<script>
cytoscape.use(cytoscapeElk);
cytoscape.use(cytoscapeCompoundDragAndDrop);

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
const token = name => getComputedStyle(document.documentElement)
  .getPropertyValue(name).trim();
const COLOUR = () => ({
  shaping: token('--st-shaping'), ready: token('--st-ready'),
  in_progress: token('--st-in_progress'), done: token('--st-done'),
  shelved: token('--st-shelved'),
});
// A label's colour belongs to the fill it sits on, not to the page. In dark mode
// these fills are light shapes carrying dark ink, so the text on a node flips
// with its own background rather than with the theme's foreground — white on
// them would be exactly the failure the light theme avoids.
const INK = () => ({
  shaping: token('--st-shaping-ink'), ready: token('--st-ready-ink'),
  in_progress: token('--st-in_progress-ink'), done: token('--st-done-ink'),
  shelved: token('--st-shelved-ink'),
});
// The edge of a status shape, the same token the timeline strokes its bars with
// and the same one the legend below draws round its keys. Read through token()
// and re-read on themechange like the other two: a border resolved once at build
// time is a light theme's border still on the boxes after the toggle.
const LINE = () => ({
  shaping: token('--st-shaping-line'), ready: token('--st-ready-line'),
  in_progress: token('--st-in_progress-line'), done: token('--st-done-line'),
  shelved: token('--st-shelved-line'),
});
// The fill is the only status channel on this canvas, and five fills on a
// luminance ladder are separable without being nameable: you can see that one
// box is darker than the next and still not know which state that is. So a
// node's own title carries the status glyph in front of it — the same glyph the
// timeline draws at a bar's left edge and the legend below shows in its swatch.
// Not a token: a shape, so it survives a screenshot, a projector and deuteranopia.
const GLYPH = {{ glyphs|tojson }};
const labelOf = node =>
  (GLYPH[node.data('status')] || '') + ' ' + (node.data('label') || '');

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
// Measured on the real plan — 31 records, six dependencies — in a 1900x820
// canvas, against the dagre layouts this replaces:
//
//     dagre LR (what shipped)   7% of the canvas   3 of 6 edges across a box
//     dagre TB + packed        57%                 3 of 6
//     elk layered RIGHT        69%                 0 of 6
//
// `hierarchyHandling: INCLUDE_CHILDREN` is the whole reason: dagre lays a nested
// plan out as though it were flat, and a pitch holding four tasks is exactly
// what this plan is made of. ELK lays out the boxes and their contents together.
//
// `RIGHT` and not `DOWN` for the reason `TB` beat `LR` under dagre — the shape of
// this plan, not a preference. Most records depend on nothing, and the direction
// decides whether that pile becomes a column or a row; measured, `DOWN` came out
// at 23% of the canvas against 69%.
//
// An edge here is a dependency and only ever a dependency. What holds what is
// drawn as a box around its contents, which is what `INCLUDE_CHILDREN` lays out
// — the table draws the same relationship as a tree, and neither view turns it
// into an arrow.
const LAYOUT = {
  name: 'elk',
  // ELK's own fitting is off: `packComponents` below moves the pieces afterwards
  // and fits once, and two fits fight over the same viewport.
  fit: false,
  elk: {
    algorithm: 'layered',
    'elk.direction': 'RIGHT',
    'elk.hierarchyHandling': 'INCLUDE_CHILDREN',
    'elk.edgeRouting': 'ORTHOGONAL',
    'elk.spacing.nodeNode': 30,
    'elk.layered.spacing.nodeNodeBetweenLayers': 50,
    // `elk.separateConnectedComponents` and `elk.aspectRatio` were here and are
    // not any more: measured, they changed nothing at all, because
    // `packComponents` runs afterwards and arranges the pieces itself. Two
    // settings that read as though they do something are worse than none.
  },
};

// dagre lays the whole graph out as one drawing, so the pieces that are not
// connected to each other are strung along a single line — which is why even
// `TB` came out 11 times wider than it was tall, and still used a third of the
// canvas. Nothing in the plan says those pieces belong in a row: they are
// separate projects.
//
// So they are arranged afterwards, into rows whose width is chosen to make the
// whole drawing the shape of the canvas it has to fit into. Same layout, same
// edges, and 80% of the canvas instead of 7%, at nearly twice the zoom.
//
// Only the leaves are moved. A compound node's position is derived from its
// children in cytoscape, so shifting a parent as well would move its contents
// twice.
// ELK is asynchronous, which is what makes the handler above enough: it emits
// `layoutstop` after this file has finished being read. dagre was synchronous and
// had already emitted it by then — the pack was written, never called, and the
// graph came out in one long line exactly as before it was written.
function packComponents() {
  const pieces = cy.elements(':visible').components()
    .map(piece => ({piece, box: piece.boundingBox()}))
    .sort((a, b) => b.box.h - a.box.h);
  if (pieces.length < 2) return;
  const gap = 40;
  const area = pieces.reduce((sum, one) => sum + (one.box.w + gap) * (one.box.h + gap), 0);
  // The row width that would make the arrangement as wide-to-tall as the canvas.
  const budget = Math.sqrt(area * (cy.width() / cy.height()));
  let x = 0, y = 0, tallest = 0;
  for (const {piece, box} of pieces) {
    if (x > 0 && x + box.w > budget) { x = 0; y += tallest + gap; tallest = 0; }
    const dx = x - box.x1, dy = y - box.y1;
    piece.nodes().filter(node => node.isChildless())
      .positions(node => ({x: node.position('x') + dx, y: node.position('y') + dy}));
    x += box.w + gap;
    tallest = Math.max(tallest, box.h);
  }
  cy.fit(undefined, 24);
}

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
  layout: LAYOUT,
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
        'text-wrap': 'wrap', 'text-max-width': 136,
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
    { selector: ':parent', style: {
        'background-opacity': .08, 'padding': 20,
        'font-size': GROUP_SIZE, 'font-weight': 600, 'color': token('--fg'),
        // Ellipsis rather than wrap: the offset below is measured on one line,
        // and a label that wrapped would be positioned as if it had not.
        'text-wrap': 'ellipsis', 'text-max-width': GROUP_MAX,
        'text-valign': 'top', 'text-halign': 'left',
        'text-margin-x': e => groupWidth(e) + 12, 'text-margin-y': 17,
        'text-background-color': token('--surface'), 'text-background-opacity': 1,
        'text-background-padding': 3, 'text-background-shape': 'roundrectangle' } },
    // On the canvas only because something that did match points at it. Faded
    // rather than removed, so no arrow leaves for a box you cannot see.
    { selector: 'node.aside', style: { 'opacity': .32 } },
    { selector: 'edge', style: {
        // Orthogonal with rounded corners, not bezier: dagre ranks left to right,
        // so an edge that leaves horizontally and turns once reads as a route
        // between ranks instead of a curve drawn over whatever is in between.
        // taxi-direction is set per edge by route(); this is only the fallback
        // for an edge added before the first routing pass.
        'width': 1.5, 'curve-style': 'round-taxi', 'taxi-direction': 'horizontal',
        'taxi-turn': '50%', 'taxi-turn-min-distance': 12, 'taxi-radius': 8,
        // The default is outside-to-LINE, which trims the ends along the straight
        // line between the two centres — so however cleanly the middle is routed,
        // both stubs come out at an angle. outside-to-node trims towards the next
        // control point instead, which is the whole difference between an
        // orthogonal edge and one that only looks orthogonal in the middle.
        'source-endpoint': 'outside-to-node', 'target-endpoint': 'outside-to-node',
        'target-arrow-shape': 'triangle',
        // --line-strong, not --st-ready. An arrow was drawn in the ready fill
        // back when that fill was a dark blue; the light theme's fills are tints
        // now and #83b8e9 on a white page is 2.10:1 — a dependency you cannot
        // see. An arrow is not a status, it is a drawn boundary, and this is the
        // token that is held at 3:1 against the page in both themes.
        'line-color': token('--line-strong'),
        'target-arrow-color': token('--line-strong') } },
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

// Which way an edge is allowed to turn, decided from where the boxes actually
// are rather than fixed in the stylesheet. Cytoscape computes a taxi turn from
// node CENTRES, so when two boxes overlap in x — which compound containers
// routinely do, being hundreds of pixels wide — the horizontal turn lands inside
// the source box and the trimmed stub comes out at an angle. Up or down is then
// the only right-angled way between them. Recomputed after every layout and
// every drag, so an edge that is orthogonal stays orthogonal when nodes move.
function route() {
  cy.edges().forEach(edge => {
    const from = edge.source().boundingBox(), to = edge.target().boundingBox();
    const overlapsInX = from.x1 < to.x2 && to.x1 < from.x2;
    edge.style('taxi-direction', overlapsInX ? 'vertical' : 'horizontal');
  });
}
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
    .selector('.picked').style({'border-color': token('--danger')})
    .selector(':parent').style({'color': token('--fg'),
                                'text-background-color': token('--surface'),
                                'text-margin-x': e => groupWidth(e) + 12})
    .selector('edge').style({'line-color': token('--line-strong'),
                             'target-arrow-color': token('--line-strong')})
    .selector('edge.pending').style({'line-color': token('--ok'),
                                     'target-arrow-color': token('--ok')})
    .selector('edge.dropping').style({'line-color': token('--sev-blocker'),
                                      'target-arrow-color': token('--sev-blocker')})
    .update();
  route();
}
addEventListener('themechange', paint);
// The face is inlined but still swaps in asynchronously, and a group label
// measured against the fallback stays where the fallback put it.
if (document.fonts) document.fonts.ready.then(paint);

// Packed first and routed after: routing reads where the boxes ended up, and
// the pack moves them.
cy.on('layoutstop', () => { packComponents(); route(); });
cy.on('position', 'node', route);
route();

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
  let headline = 'No entity matches these filters.';
  let detail = 'Every node is filtered out by the controls above.';
  let clearable = true;
  if (!LOADED) {
    headline = 'The plan could not be loaded.';
    detail = 'This page arrived without its data, so there is nothing to draw or filter.';
    clearable = false;
  } else if (!cy.nodes().length) {
    headline = 'This plan has no entities yet.';
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
  cy.elements(':visible').layout({...LAYOUT, fit: true}).run();
}

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
  if (!connecting) location.href = '{{ links.entity }}' + evt.target.id();
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
cy.on('mouseover', 'node', evt => {
  if (connecting) return;
  // `data()` and not a lookup: a node's data IS the row — `_elements` builds it
  // from the same `_row` the table is drawn from — and this page has no `DATA` of
  // its own to look anything up in. The first version of this read `DATA.rows`
  // and drew nothing at all, on the one view the card was added for.
  queueCard(evt.target.data(), evt.originalEvent.clientX, evt.originalEvent.clientY);
});
cy.on('mouseout', 'node', hideCard);
// A node dragged out from under a card, and a canvas panned or zoomed under one:
// the pointer never leaves the node, so `mouseout` does not fire and the card
// stays describing a node that is no longer there.
cy.on('drag pan zoom', hideCardNow);

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

  // One PATCH per dependent, because depends_on lives on the entity that waits.
  // Each write moves HEAD, so the base for the next one is the commit this one
  // returned — reusing the page's base would make every write after the first a
  // conflict against a commit this same button just created.
  SAVE.onclick = async () => {
    SAVE.disabled = true;
    const wanted = new Map();
    // Both halves are grouped by the entity that WAITS, because that is the
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
        const response = await fetch(`/api/entity/${encodeURIComponent(id)}`, {
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
          say(`${id}: ${why}${written ? ` — ${written} already saved` : ''}`);
          SAVE.disabled = false;
          return;
        }
        committed = answer.commit;
        base.value = answer.commit;
        written += 1;
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
// Drag a record onto the box that should hold it. The extension does the part
// this repository got wrong on its own: it knows which box the pointer is over
// while a node is in the air, draws it, and hands back the pair when the drag
// ends. What is left here is the rule about which pairs are allowed and the
// write — the same PATCH the table's own drag sends, because a parent is a field
// like any other.
const REFILE = document.getElementById('refile');
const CAN_HOLD = (() => {
  try { return JSON.parse(document.getElementById('parents').textContent); }
  catch (error) { return {}; }
})();
let refiling = false;
let cdnd = null;

if (REFILE) {
  REFILE.onclick = () => {
    if (connecting) CONNECT.onclick();
    refiling = !refiling;
    REFILE.textContent = refiling ? 'Stop refiling' : 'Refile';
    if (refiling) {
      cdnd = cy.compoundDragAndDrop({
        // Only the records that can be filed under something. A project belongs
        // to nothing, so it is not something to pick up.
        grabbedNode: node => (CAN_HOLD[node.data('kind')] || []).length > 0,
        // And only into a box that may hold it. Asked before the drop rather
        // than after, so the canvas never offers a move the server refuses.
        dropTarget: (target, grabbed) =>
          target.isParent() &&
          (CAN_HOLD[grabbed.data('kind')] || []).includes(target.data('kind')),
        // No new boxes: a project, a pitch and a task are the three kinds this
        // plan has, and dropping one record on another must not invent a fourth
        // thing to hold them.
        dropSibling: () => false,
      });
      say('drag a record onto the box that should hold it, or out of the one it is in');
    } else {
      if (cdnd) { cdnd.destroy(); cdnd = null; }
      say('');
    }
  };

  // Filed. `dropTarget` is the box it landed in.
  cy.on('cdnddrop', (event, dropTarget) => {
    const child = event.target;
    if (!refiling || !dropTarget || !dropTarget.length) return;
    if (dropTarget.id() === (child.data('parent') || null)) return;
    refile(child.id(), dropTarget.id());
  });

  // Taken out. The extension fires this when a node leaves the box it was in,
  // which is the gesture that had no answer at all before: there was no point on
  // the canvas that meant "outside".
  cy.on('cdndout', (event, dropTarget) => {
    const child = event.target;
    if (!refiling || !child.data('parent')) return;
    refile(child.id(), null);
  });
}

// The write. Same PATCH, same base commit, same refusal as everything else this
// page commits; the page reloads afterwards because a parent moves the record's
// cycle, its dates, what it waits for and which project it counts against, and
// not one of those is something this canvas can work out for itself.
async function refile(childId, parentId) {
  const base = document.getElementById('base');
  dispatchEvent(new Event('openproj:writing'));
  let committed = null;
  try {
    say(parentId ? `filing ${childId} into ${parentId}…` : `taking ${childId} out…`);
    const response = await fetch(`/api/entity/${encodeURIComponent(childId)}`, {
      method: 'PATCH', headers: {'content-type': 'application/json'},
      body: JSON.stringify({base_commit: base.value, fields: {parent: parentId}, body: null}),
    });
    const answer = await answerOf(response);
    if (!response.ok) {
      say(refusal(answer, response.status));
      return;
    }
    committed = answer.commit;
    base.value = answer.commit;
  } finally {
    dispatchEvent(new CustomEvent('openproj:wrote', {detail: committed}));
  }
  location.reload();
}

cy.on('tap', 'edge', evt => {
  if (!connecting) return;
  const edge = evt.target;
  if (edge.hasClass('pending')) {
    cy.remove(edge);
    tally('undrawn');
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

  if (from.id() === node.id()) { tally('an entity cannot wait for itself'); return; }
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
    tally('an entity cannot wait for what contains it');
    return;
  }

  cy.add({group: 'edges', classes: 'pending',
          data: {source: from.id(), target: node.id(), kind: 'depends'}});
  route();
  tally();
});
</script>
"""

_GRAPH_STYLE = """
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
"""

# What this chart is showing and how to move through it — at the far end of the
# search box's line, the same slot the graph's pan/zoom sentence sits in. It was a
# row of its own between the window controls and the key, and the timeline stacked
# eight rows before the first bar. What it says is not a control of the view, it
# is a description of it, and a description does not earn a row.
_TIMELINE_HINT = """<p class="hint">{% if windowed %}Showing {{ t.origin }} to {{ t.last }},
  a window of the plan — Reset goes back to all of it.{% endif %}
  Drag sideways or scroll to move through it. Bars reaching past the window are
  clipped to it, never dropped.</p>"""

_TIMELINE = """
{#- Announced, not drawn: the lit nav item says this already. See `.sr-only`. -#}
<h1 class="sr-only">Timeline</h1>
{{ facets }}
<form class="tl-controls" method="get" action="{{ links.timeline }}">
  {#- Prefilled with the window on screen, not the one that was asked for. Two
      empty boxes under a sentence reading "Showing 2026-02-02 to 2026-11-27" ask
      the reader to believe the page over the controls; Reset is what says the
      window is the default one. -#}
  {#- Each label is beside its control rather than wrapped around it, because the
      row is laid out as a grid and the caption, the box and the ISO echo under
      the box are three rows of it. A wrapping `<label>` is one grid item and
      cannot put its own contents in three. `for`/`id` says the same thing to the
      accessibility tree that wrapping said. -#}
  <label class="facet" for="tl-from">from</label>
  <input type="date" id="tl-from" name="from" value="{{ t.origin or '' }}">
  <label class="facet" for="tl-to">to</label>
  <input type="date" id="tl-to" name="to" value="{{ t.last or '' }}">
  <label class="facet" for="tl-zoom">zoom</label>
  <select id="tl-zoom" name="zoom">
    <option value="">fit to window</option>
    {% for px, label in zooms %}
    <option value="{{ px }}"{{ ' selected' if chosen == px else '' }}>{{ label }}</option>
    {% endfor %}
  </select>
  <span class="acts"><button type="submit" class="button primary">Apply</button>
    <a class="button reset" href="{{ links.timeline }}">Reset</a></span>
</form>
{#- Statuses first and marks second, because they are two questions: what state
    is this in, and how much of this bar is a guess. Every swatch is drawn from
    the same token or the same pattern the plot uses — including the glyph, which
    is the half of the status channel that is not colour. -#}
<ul class="legend" aria-label="What a bar's colour and mark mean">
  {% for status in statuses %}
  <li><span class="swatch st-{{ status }}" aria-hidden="true">{{ glyph(status) }}</span
    >{{ status|human }}</li>
  {% endfor %}
</ul>
{#- The second key and the count, on one row — the same arrangement as the graph,
    where there is one key and it carries the count. This is the last row before
    the plot, which is where the count of what is in the plot belongs.
    `bar`, and inset by half a pixel: these two keys are bars, so they carry the
    stroke every bar carries — and an SVG stroke is centred on the edge, so a
    rect filling its own viewBox would have had half of its border clipped
    away. -#}
<div class="keyrow">
<ul class="legend" aria-label="What a bar marking means">
  <li><svg class="swatch" viewBox="0 0 20 11" aria-hidden="true"
      ><rect class="bar st-ready" x=".5" y=".5" width="19" height="10"/><rect
        class="mark mark-estimated st-ready" x=".5" y=".5" width="19"
        height="10"/></svg>appetite assumed</li>
  <li><svg class="swatch" viewBox="0 0 20 11" aria-hidden="true"
      ><rect class="bar st-ready" x=".5" y=".5" width="19" height="10"/><rect
        class="mark mark-unowned st-ready" x=".5" y=".5" width="19"
        height="10"/></svg>nobody on it</li>
  <li><span class="swatch outline late"></span>overruns its cycle</li>
  <li><span class="swatch rule today"></span>today</li>
  <li><span class="swatch rule boundary"></span>a cycle closes</li>
  <li><span class="swatch band"></span>a cycle, build and cooldown</li>
</ul>
<div id="summary"><span id="shown" class="num">{{ t.bars|length }}</span> of {{ t.bars|length }}
  drawn{% if t.offscreen %} · {{ t.offscreen }} with no dates in this
  window{% endif %}</div>
</div>
{#- `data-fills`: the box the shell measures the window into, capped rather than
    filled — a plan with three bars is three bars tall. -#}
<div class="tl" data-fills{% if not t.bars %} hidden{% endif %}>
{#- The column beside the plot is the plot's accessible half, not a caption for
    it: `role="img"` on the SVG prunes everything inside it, which is right —
    seventeen bar links announced twice is worse than none — but only once what
    it prunes exists somewhere else. So every row carries what its bar draws:
    the status the fill means, the dates the width means, the marks the hatching
    means, and the sentence the tooltip holds. -#}
<div class="labels" role="list"
     aria-label="Every bar on the chart, with its status and its dates">
  <div class="spacer" aria-hidden="true" style="height: {{ t.header }}px"></div>
  {#- Indented by containment, so a project's work reads as a block. The clipped
      label is what fits in 250px; the whole title is on the anchor. -#}
  {% for bar in t.bars %}
  <div class="row" role="listitem" data-id="{{ bar.id }}" data-depth="{{ bar.depth }}"
       style="padding-left: {{ 8 + bar.indent }}px">
    <a href="{{ links.entity }}{{ bar.id }}" title="{{ bar.full }}">{{ bar.label }}</a
    ><span class="sr-only">{{ bar.reads }}</span></div>
  {% endfor %}
</div>
<div class="scroll">
<svg width="{{ t.width }}" height="{{ t.height }}"
     viewBox="0 0 {{ t.width }} {{ t.height }}" role="img"
     aria-label="Every scheduled entity as a bar. The same rows are listed beside it.">
  {#- One pair of patterns per status, not one pair in all. A pattern resolves
      its own custom properties against the tree it is declared in, never against
      the shape that references it, so a single --hatch could only ever be right
      for one rung of the ladder — white lines over a near-white "done" bar, or
      near-black ones over a dark "shelved" one. The stroke is the fill's own ink,
      which is the token that already means "what reads on this". -#}
  <defs>
    {% for status in statuses %}
    <pattern id="hatch-estimated-st-{{ status }}" width="6" height="6"
             patternTransform="rotate(45)" patternUnits="userSpaceOnUse">
      <line x1="0" y1="0" x2="0" y2="6" stroke="var(--st-{{ status }}-ink)"
            stroke-opacity=".55" stroke-width="3"/>
    </pattern>
    <pattern id="hatch-unowned-st-{{ status }}" width="8" height="8"
             patternTransform="rotate(-45)" patternUnits="userSpaceOnUse">
      <line x1="0" y1="0" x2="0" y2="8" stroke="var(--st-{{ status }}-ink)"
            stroke-opacity=".7" stroke-width="4"/>
    </pattern>
    {% endfor %}
  </defs>
  {#- A band of its own above the months. A cycle label used to be drawn at y=10
      and a month label at y=18 inside one 26px strip, so a cycle closing near the
      first of a month wrote one word over the other. -#}
  {% for cycle in t.cycles %}
  <rect class="cycle-band" x="{{ cycle.x }}" y="0"
        width="{{ cycle.width }}" height="{{ t.band }}"/>
  {#- The cool-down, shaded inside the band. Nothing is supposed to be built in
      it, so the band cannot show one flat stretch for the whole window. -#}
  {% if cycle.cool_x is not none %}
  <rect class="cycle-cooldown" x="{{ cycle.cool_x }}" y="0"
        width="{{ cycle.cool_width }}" height="{{ t.band }}"/>
  {% endif %}
  <text class="cycle-label" x="{{ cycle.x + 4 }}" y="12">{{ cycle.label }}</text>
  {#- The solid rule is the end of BUILD, because that is the date an overrun is
      measured against. The dashed one is the end of the window. -#}
  {% if cycle.build_x is not none %}
  <line class="build-rule" x1="{{ cycle.build_x }}" y1="0" x2="{{ cycle.build_x }}"
        y2="{{ t.height }}"><title>cycle {{ cycle.number }} stops building here</title></line>
  {% endif %}
  {% if cycle.rule_x is not none %}
  <line class="cycle-rule" x1="{{ cycle.rule_x }}" y1="0" x2="{{ cycle.rule_x }}"
        y2="{{ t.height }}"/>
  {% endif %}
  {% endfor %}
  <line class="band-rule" x1="0" y1="{{ t.band }}" x2="{{ t.width }}" y2="{{ t.band }}"/>
  {% for month in t.months %}
  <line class="month-rule" x1="{{ month.x }}" y1="{{ t.band }}" x2="{{ month.x }}"
        y2="{{ t.height }}"/>
  <text class="month-label" x="{{ month.x + 3 }}" y="{{ t.header - 8 }}">{{ month.label }}</text>
  {% endfor %}
  {#- Drawn over the grid and under today. A bar is the subject of the page; the
      rules behind it are furniture, and the one line that must never be hidden
      by a bar is the one saying where now is. -#}
  {#- The glyph is the bar's second channel, drawn in the fill's own ink at the
      left edge. It is dropped on a bar too narrow to hold it rather than left to
      spill onto the page, where it would be a mark in a status colour sitting on
      no status colour at all. -#}
  {#- tabindex="-1" because the anchor is inside a `role="img"` subtree: Chrome
      does not focus an SVG anchor and Firefox does, so without it the keyboard
      stopped on seventeen links that the accessibility tree had already pruned
      and announced nothing at each one. The mouse keeps the href. -#}
  {% for bar in t.bars %}
  <a href="{{ links.entity }}{{ bar.id }}" tabindex="-1" aria-label="{{ bar.full }}"
     ><rect data-id="{{ bar.id }}" class="{{ bar.classes }} {{ bar.colour }}"
        x="{{ bar.x }}" y="{{ bar.y }}"
        width="{{ bar.width }}" height="{{ bar_px }}"
        ><title>{{ t.rows[bar.id].tip }} — click to open</title></rect>{% for mark in
        bar.marks %}<rect class="mark mark-{{ mark }} {{ bar.colour }}" x="{{ bar.x }}"
        y="{{ bar.y }}" width="{{ bar.width }}" height="{{ bar_px }}"/>{% endfor %}{% if
        bar.glyph %}<text class="bar-glyph {{ bar.colour }}" aria-hidden="true"
        x="{{ bar.x + 3 }}" y="{{ bar.y + glyph_dy }}">{{ bar.glyph }}</text>{% endif %}</a>
  {% endfor %}
  {% if t.today_x is not none %}
  <line class="today" x1="{{ t.today_x }}" y1="0" x2="{{ t.today_x }}" y2="{{ t.height }}"/>
  {#- In the gutter under the last row: the two bands above are full of cycle and
      month labels, and there is exactly one today line to name. -#}
  <text class="today-label" x="{{ t.today_x + 4 }}" y="{{ t.height - 6 }}">today</text>
  {% endif %}
</svg>
</div>
</div>
<div id="nothing"{% if t.bars %} hidden{% endif %}>
  <p class="headline">{{ t.blank.headline }}</p>
  <p class="hint">{{ t.blank.detail }}</p>
  <button type="button" id="clear-filters"{% if not t.bars %} hidden{% endif %}>Clear
    filters</button>
</div>
<script id="bars" type="application/json">{{ bars|tojson }}</script>
{{ filters }}
<script>
const scroller = document.querySelector('.scroll');
const svg = scroller.querySelector('svg');
const plot = document.querySelector('.tl');
const nothing = document.getElementById('nothing');
const ROW_PX = {{ row_px }}, HEADER = {{ t.header }}, WIDTH = {{ t.width }};
const FOOT = {{ foot_px }};
const BAR_TOP = {{ bar_top }}, GLYPH_DY = {{ glyph_dy }};
const RECTS = [...svg.querySelectorAll('rect[data-id]')];
const LABELS = new Map([...document.querySelectorAll('.labels .row')]
  .map(row => [row.dataset.id, row]));
// The bars are drawn by the server, so a payload that will not parse costs the
// filters and not the chart. Everything below asks whether it is there.
let DATA = null;
try { DATA = JSON.parse(document.getElementById('bars').textContent); } catch (e) { DATA = null; }

// Open on today rather than on the oldest finished work. The plan is scrollable
// so history stays reachable, but "now" is what the page is for.
{% if t.today_x is not none %}
scroller.scrollLeft = Math.max(0, {{ t.today_x }} - 320);
{% endif %}

// The window is re-rendered by the server, so zoom keeps its labels upright and
// its corners round. Changing a control just submits; the button stays for
// anybody without JavaScript, and the URL stays shareable either way.
const form = document.querySelector('.tl-controls');
form.addEventListener('submit', event => {
  // The window belongs to the server and the facets to the page, and both live
  // in one query string. A plain submit carries only this form's own fields, so
  // applying a date range used to clear every dropdown above it.
  event.preventDefault();
  for (const control of form.elements) {
    if (!control.name) continue;
    if (control.value) params.set(control.name, control.value);
    else params.delete(control.name);
  }
  location.search = params.toString();
});
form.querySelectorAll('input, select').forEach(control => {
  control.onchange = () => form.requestSubmit();
});
form.querySelector('.reset').onclick = event => {
  // The window, not the filters: a button that undoes two things while naming
  // one is a button nobody presses twice.
  event.preventDefault();
  for (const field of ['from', 'to', 'zoom']) params.delete(field);
  location.search = params.toString();
};

// Drag to pan, which is what everybody tries first on a Gantt.
let panning = null;
scroller.onpointerdown = event => {
  if (event.target.closest('a')) return;      // still let a bar be clicked
  panning = {x: event.clientX, left: scroller.scrollLeft};
  scroller.setPointerCapture(event.pointerId);
  scroller.style.cursor = 'grabbing';
};
scroller.onpointermove = event => {
  if (panning) scroller.scrollLeft = panning.left - (event.clientX - panning.x);
};
scroller.onpointerup = () => { panning = null; scroller.style.cursor = ''; };

const human = value => (DATA && DATA.human[value]) || value;

// A bar carried its dates, its owner and its appetite nowhere: the only thing
// hoverable was a native tooltip holding one sentence about why it starts when
// it does. That sentence is still here, at the bottom of the card, where it reads
// as the answer to a question the rest of the box has just raised — `row.tip`,
// which the shared card draws for whoever puts one on a row.
//
// `showCard` is the shell's, and this is the view it was written for. The graph
// and the table draw the same one now; see the card block in `_SHELL`.
function showTip(id, x, y, now) {
  const row = DATA && DATA.rows[id];
  // `now` for the keyboard: focus is a deliberate act and a delay after one is a
  // page ignoring you. A pointer crossing the plot is not deliberate, so it
  // waits like everywhere else.
  if (row) (now ? showCard : queueCard)(row, x, y);
}

svg.addEventListener('pointerover', event => {
  const rect = event.target.closest('rect[data-id]');
  if (rect) showTip(rect.dataset.id, event.clientX, event.clientY);
});
svg.addEventListener('pointerout', event => {
  if (event.target.closest('rect[data-id]')) hideCard();
});
// The keyboard reaches a row through the label beside it: an SVG anchor is not
// focusable in Chrome, and giving every bar a tabindex would put two stops on
// one row for the sake of the second one. So the label opens the same box.
for (const [id, row] of LABELS) {
  const link = row.querySelector('a');
  link.addEventListener('focus', () => {
    const box = link.getBoundingClientRect();
    showTip(id, box.right, box.bottom, true);
  });
  link.addEventListener('blur', hideCardNow);
}
// The native tooltip holds the same sentence, arrives a second later and lands
// somewhere else. The markup keeps it so a page without script still explains
// itself; the anchor carries the accessible name either way.
if (DATA) for (const title of svg.querySelectorAll('title')) title.remove();

// One filter model, three views: the timeline's answer to it is which rows
// are on the chart. A hidden row leaves no gap: the rows below it move up, the
// drawing shrinks to what is left, and the rules that span the whole plot are
// cut to the new height.
const FULL_HEIGHT = svg.querySelectorAll('.cycle-rule, .build-rule, .month-rule, .today');
const TODAY_LABEL = svg.querySelector('.today-label');

function applyFilter() {
  if (!DATA) return;
  let row = 0;
  for (const rect of RECTS) {
    const on = matches(DATA.rows[rect.dataset.id]);
    rect.parentNode.style.display = on ? '' : 'none';
    LABELS.get(rect.dataset.id).hidden = !on;
    if (!on) continue;
    // The bar, whatever is hatched over it and the glyph naming its status are
    // one row and move together. The glyph is a <text>, so it sits on a baseline
    // rather than at the rect's top edge — moved by the same amount, from the
    // same offset the server drew it at.
    const y = row * ROW_PX + HEADER + BAR_TOP;
    for (const shape of rect.parentNode.querySelectorAll('rect'))
      shape.setAttribute('y', y);
    const glyph = rect.parentNode.querySelector('text.bar-glyph');
    if (glyph) glyph.setAttribute('y', y + GLYPH_DY);
    row++;
  }
  const height = row * ROW_PX + HEADER + FOOT;
  svg.setAttribute('height', height);
  svg.setAttribute('viewBox', `0 0 ${WIDTH} ${height}`);
  for (const line of FULL_HEIGHT) line.setAttribute('y2', height);
  if (TODAY_LABEL) TODAY_LABEL.setAttribute('y', height - 6);
  document.getElementById('shown').textContent = row;
  // A chart with no bars in it is a grid, which reads as an app that failed
  // rather than as a filter that matched nothing.
  plot.hidden = row === 0;
  nothing.hidden = row > 0;
}

addEventListener('openproj:filter', applyFilter);
document.getElementById('clear-filters').onclick = clearFilters;
applyFilter();
</script>
"""

_TIMELINE_STYLE = """
/* FROM, TO, ZOOM, Apply and Reset are one line, and the ISO echo stays under the
   date box it belongs to. A flex row could not do both: the echo makes the two
   date labels a line taller than the zoom label, so `align-items: end` dropped
   ZOOM and both buttons a full line below the boxes and the bar read as two
   rows. Three explicit grid rows — caption, control, echo — say it directly:
   every caption on the first, every control on the second, an echo on the third
   under the box it came from, with the zoom column and the buttons leaving the
   third row empty. `grid-auto-flow: column` fills a column top to bottom before
   starting the next, so the echo the shell inserts after each date input lands
   in that input's own column and nothing here has to know it exists. */
.tl-controls { display: grid; grid-auto-flow: column; grid-auto-columns: max-content;
               align-items: end; column-gap: 1rem; row-gap: .15rem;
               margin: .75rem 0 .25rem; }
.tl-controls > .facet { grid-row: 1; }
.tl-controls > input, .tl-controls > select, .tl-controls > .acts { grid-row: 2; }
.tl-controls > .iso { grid-row: 3; }
.tl-controls .acts { display: flex; gap: .5rem; align-items: baseline; }
.tl-controls input, .tl-controls select {
  display: block; font: inherit; font-size: 13px; text-transform: none; letter-spacing: 0;
  color: inherit;
}
/* Narrower than the row itself, and one line is no longer on offer. The grid goes
   rather than overflowing the page, and the same controls wrap as a flex row —
   the echo beside its box instead of under it, which is the one thing that has
   to give. */
@media (max-width: 620px) {
  .tl-controls { display: flex; flex-wrap: wrap; align-items: baseline; gap: .35rem .75rem; }
}
/* `.button` and `.button.primary` are the shell's. They were written here, in a
   rule scoped to this filter bar, and the table's create action wore the class
   with nothing behind it. */
/* The three markings, drawn the way the plot draws them: a hatch over a real
   status fill, an outline, a rule. A legend that redraws a mark in its own way
   is a legend that can be wrong about the picture beside it — which is how the
   band key came to be a bordered --surface-2 swatch standing in for an unbordered
   --surface-2 band, two wrong answers agreeing with each other. */
.legend .swatch.outline { background: var(--surface-2); }
/* 2.5px, the width the plot draws it at. It was 1.5 while an overrunning bar was
   the only bar with a stroke on it; every bar has one now, and a key drawn at
   the old width would be keying the ordinary border rather than the alarm. */
.legend .swatch.late { border: 2.5px solid var(--danger); }
.legend .swatch.rule { width: 2px; height: 13px; border-radius: 0; }
.legend .swatch.today { background: var(--danger); }
.legend .swatch.boundary { background: none; border-left: 2px dashed var(--line-strong); }
.legend .swatch.band { background: var(--band); }
/* Capped at the room the window has left, and scrolling inside that cap. The same
   measurement the table's rows and the graph's canvas take, for the same reason:
   a plan of two hundred bars used to push the filters, the window controls and
   both keys off the top of the window, so the only way to change what you were
   looking at was to scroll back up past the chart to the controls that change it.
   `max-height` like the table and not `height` like the graph — the plot has a
   height of its own, one row per bar, and stretching seventeen bars over a
   thousand pixels of white is an answer to a question nobody asked. No floor
   either: an empty plan draws `#nothing` outside this box, so there is nothing
   here for a floor to leave room for.
   The scroll is on `.tl` and not on the plot inside it, or the labels would hold
   still while the bars they name scrolled away.
   `flex-start`, and this is the part that is not cosmetic: under `stretch` both
   columns take the *clamped* height of this box and their contents spill out of
   it — visibly clipped, and still counted, so the page grew a scrollbar for rows
   that were already scrollable here. At `flex-start` each column is as tall as
   its own content, the cap has something taller than itself to scroll, and the
   two move together. */
.tl { display: flex; border: 1px solid var(--line); align-items: flex-start;
      max-height: var(--room); overflow: auto; }
.tl[hidden] { display: none; }
/* The plot leaves `_PLOT_FOOT_PX` under the last bar; the label column is a
   separate element and has to leave the same, or its dividing rule stops short of
   the bars it is dividing. Rendered from the constant rather than typed, because
   a fourth copy of that number is a rule that ends 20px early on a chart nobody
   is measuring. */
.labels { flex: 0 0 250px; border-right: 1px solid var(--line);
          padding-bottom: {{ foot_px }}px; }
.labels .row {
  /* Positioned, so that the `.sr-only` sentence inside it is positioned against
     the row. `.sr-only` is `position: absolute`, and with no positioned ancestor
     its containing block is the page itself — which means the plot's scroll
     container does not clip it, seventeen of them landed wherever the rows would
     have been if nothing had been capped, and the page grew a scrollbar for
     content that was already scrollable inside the chart. Nothing moves visually:
     the span is clipped to nothing either way. */
  position: relative;
  /* Fixed, not min: the row carries a clipped title and a clipped-off sentence
     of what the bar draws, and the second one must not add a pixel of height —
     every row here lines up with the bar the scheduler placed beside it. Written
     from `_ROW_PX`, which is the number the plot is laid out with: as a literal
     it was a third copy, and one that would only ever be found by noticing that
     the labels had drifted a row out of step halfway down a long plan. */
  height: {{ row_px }}px; line-height: {{ row_px }}px; font-size: 11px;
  color: var(--muted);
  padding: 0 .5rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.scroll { overflow-x: auto; flex: 1 1 auto; min-width: 0; }
svg { display: block; }
.month-rule { stroke: var(--line); }
.month-label { font-size: 9px; fill: var(--muted); }
/* The band a cycle runs for, start of build to end of cooldown. It carries its
   own number, so the ground only has to say "there is a cycle here"; the dashed
   rule inside it is where one closes. --band and not --surface-2: a panel tint
   behind a panel is a panel, but behind the page it is 1.07:1 and there is no
   band at all. Same token as the legend key, because they are the same band. */
.cycle-band { fill: var(--band); }
.band-rule { stroke: var(--line); }
/* Where a cycle closes — the one rule on this chart that is a fact about the
   plan rather than grid furniture, so it is drawn in the boundary token and not
   the hairline one. The legend already keyed it as --line-strong while the plot
   drew it in --line, which is a legend describing a line nobody could see. */
.cycle-rule { stroke: var(--line-strong); stroke-dasharray: 3 3; }
/* Solid, because it is the deadline the amber flag is measured against; the
   dashed rule beside it is only where the window closes. */
.build-rule { stroke: var(--line-strong); }
.cycle-cooldown { fill: var(--line); fill-opacity: .5; }
.cycle-label { font-size: 10px; fill: var(--accent); font-weight: 600; }
.today { stroke: var(--danger); stroke-width: 1.5; }
.today-label { font-size: 10px; fill: var(--danger); font-weight: 600; }
rect.bar { rx: 3; }
/* An assumed appetite and work nobody is on are hatched, not outlined: the
   outline says "overruns its cycle", and one channel carrying three facts says
   none of them. Drawn as a second rect over the bar so the status colour stays
   underneath, and transparent to the pointer so the bar is still what you hover. */
rect.mark { rx: 3; pointer-events: none; }
/* `rect.late` used to live here. It is written by _status_paint_css() now,
   after the per-status strokes: both selectors are (0,2,1), so document order
   is the only thing left to decide the tie, and the tie decides whether a bar
   that overruns its cycle still says so. */
/* The bar's second channel: which status this is, said as a shape. Drawn in the
   fill's own ink, and transparent to the pointer so the thing under the cursor
   at the left end of a bar is still the bar.
   The face is the inlined one, not the mono stack: the mono stack is whatever
   the reader's machine happens to have, and this glyph is the channel that has
   to survive when the colour does not. */
text.bar-glyph { font-family: var(--font-sans); font-size: 9px; font-weight: 700;
                 pointer-events: none; }
/* Beside the plot rather than over it: the plot is as tall as its rows, and an
   overlay on an empty one has nothing to cover. */
#nothing { border: 1px solid var(--line); padding: 2.5rem 1rem; text-align: center; }
#nothing .headline { margin: 0 0 .25rem; font-size: 15px; }
#nothing .hint { margin: 0 0 .75rem; }
"""


def _timeline_css() -> str:
    """The timeline's whole stylesheet: the written half and the two derived ones.

    Rendered rather than concatenated because two rules in it are geometry the
    server already decided — the label column's row height has to be `_ROW_PX` or
    the names walk out of step with the bars they name, one pixel per row, and its
    foot has to be `_PLOT_FOOT_PX` or the rule between labels and bars stops short
    of the last of them.
    """
    return (
        _ENV.from_string(_TIMELINE_STYLE).render(row_px=_ROW_PX, foot_px=_PLOT_FOOT_PX)
        + _status_paint_css()
    )


def _status_paint_css() -> str:
    """The per-status half of the timeline's stylesheet.

    Twenty-five rules — a fill, a border, a glyph ink and two hatch references
    for each status — so it is written by a loop. Spelled out by hand, the one
    that goes missing is a hatch, and a missing hatch does not look broken: it
    looks like a bar that has stopped being a guess.

    The overrun outline is written here too, at the end, and not with the rest of
    the timeline's rules. It has to beat the per-status stroke below and the two
    selectors weigh the same, so the only thing that decides it is which comes
    last in the sheet.
    """
    rules = [f"rect.st-{s} {{ fill: var(--st-{s}); }}" for s in STATUSES]
    # On the bar, never on the hatch rect stacked over it: the two are the same
    # rectangle, so a stroke on both draws the border twice — and on an
    # overrunning bar the second one would paint the status colour straight down
    # the middle of the danger outline that is the whole point of it.
    rules += [
        f"rect.bar.st-{s} {{ stroke: var(--st-{s}-line); stroke-width: 1; }}" for s in STATUSES
    ]
    # The label on a shape belongs to the fill it sits on, not to the page: on the
    # dark theme's top rungs the fill is nearly white, and --fg on it is nothing.
    rules += [f"text.bar-glyph.st-{s} {{ fill: var(--st-{s}-ink); }}" for s in STATUSES]
    rules += [
        f"rect.mark-{mark}.st-{s} {{ fill: url(#hatch-{mark}-st-{s}); }}"
        for mark in ("estimated", "unowned")
        for s in STATUSES
    ]
    # Overruns its cycle. It was the only stroke on the chart and 1.5px was
    # plenty; now every bar carries one, so this has to be the heavier of the two
    # as well as the redder — 2.5px against 1px on a 14px bar, which reads as a
    # ring round the bar rather than as an edge on it.
    rules.append("rect.bar.late { stroke: var(--danger); stroke-width: 2.5; }")
    return "\n".join(rules) + "\n"


# Raw, because the JS in here contains regex escapes. `\\.` is not a Python escape,
# so it survived as a literal backslash and the widget worked — while emitting a
# SyntaxWarning on every fresh compile, and Python 3.14 turns that into an error.
_COMBOBOX = r"""
<script id="suggest" type="application/json">{{ suggest|tojson }}</script>
<script>
// Every programmatic edit to a textarea goes through here.
//
// `textarea.value = ...` wipes the browser's native undo stack: paste a diagram
// into a four-hundred-line pitch, press ctrl-Z, and the last ten minutes are
// gone with no way back. `execCommand('insertText')` is deprecated and is also
// the only API in any shipping browser that edits a textarea as though a person
// had typed — one undo step, selection handled, `input` fired for free. The
// fallback keeps the feature working if it is ever removed; it loses undo, which
// is the least bad of the things that can be lost.
function replaceRange(area, text) {
  area.focus();
  if (document.execCommand && document.execCommand('insertText', false, text)) return;
  const {selectionStart: from, selectionEnd: to} = area;
  area.value = area.value.slice(0, from) + text + area.value.slice(to);
  area.selectionStart = area.selectionEnd = from + text.length;
  area.dispatchEvent(new Event('input', {bubbles: true}));
}


// A small toolbar, sized to what this team writes rather than to what an editor
// usually offers. Counted across the seed and the migrated HackMD corpus: 485
// lines carry an inline code span, 161 a bullet, 124 a heading, 83 bold — and
// eight carry a markdown link, which is why there is no link button: people write
// `C2SM/icon4py#1364` bare and the renderer already turns it into a link.
//
// The two code buttons are here for a different reason than frequency, and it is
// the better reason. The team types on a mix of US and Swiss-German layouts, and
// on CH a backtick is a dead key — so a fence is three of them in a row, and the
// two fenced blocks in the whole corpus are a measure of how awkward that is
// rather than of how little code people would paste. A button is worth more than
// a count here.
const FORMATS = [
  {key: 'b', label: 'B', title: 'Bold  ⌘B', wrap: '**'},
  {key: 'i', label: 'I', title: 'Italic  ⌘I', wrap: '*', style: 'font-style: italic'},
  {key: 'e', label: '<>', title: 'Code  ⌘E', wrap: '`'},
  {key: 'e', shift: true, label: '{ }', title: 'Code block  ⌘⇧E', fence: true},
  {key: '2', label: 'H', title: 'Heading  ⌘2', prefix: '## '},
  {key: '8', label: '•', title: 'Bullet  ⌘8', prefix: '- '},
  {key: '.', label: '❝', title: 'Quote  ⌘.', prefix: '> '},
];

function lineRange(area) {
  const from = area.value.lastIndexOf('\n', area.selectionStart - 1) + 1;
  let to = area.value.indexOf('\n', area.selectionEnd);
  return [from, to === -1 ? area.value.length : to];
}

function applyMark(area, mark) {
  if (mark.fence) {
    // Whole lines, and on their own lines: a fence only opens a block if nothing
    // shares its line, so wrapping a selection in place would produce three
    // paragraphs of literal backticks.
    const [from, to] = lineRange(area);
    const chosen = area.value.slice(from, to);
    const fenced = /^```/.test(chosen) && /```$/.test(chosen);
    area.setSelectionRange(from, to);
    if (fenced) {
      const inner = chosen.replace(/^```[^\n]*\n?/, '').replace(/\n?```$/, '');
      replaceRange(area, inner);
      area.setSelectionRange(from, from + inner.length);
      return;
    }
    replaceRange(area, '```\n' + chosen + '\n```');
    // The caret lands on the language, which is the one word you type before the
    // code and cannot paste from anywhere.
    area.setSelectionRange(from + 3, from + 3);
    return;
  }
  if (mark.prefix) {
    // Whole lines, and a toggle: pressing bullet twice is how somebody undoes a
    // bullet, and it costs one `startsWith`.
    const [from, to] = lineRange(area);
    const lines = area.value.slice(from, to).split('\n');
    const on = lines.every(line => line.startsWith(mark.prefix));
    const next = lines
      .map(line => (on ? line.slice(mark.prefix.length) : mark.prefix + line))
      .join('\n');
    area.setSelectionRange(from, to);
    replaceRange(area, next);
    area.setSelectionRange(from, from + next.length);
    return;
  }
  const {selectionStart: from, selectionEnd: to} = area;
  const chosen = area.value.slice(from, to);
  const width = mark.wrap.length;
  const wrapped =
    area.value.slice(from - width, from) === mark.wrap &&
    area.value.slice(to, to + width) === mark.wrap;
  if (wrapped) {
    // Already marked: unwrap, taking the marks with it rather than leaving a
    // stray pair behind for somebody to delete by hand.
    area.setSelectionRange(from - width, to + width);
    replaceRange(area, chosen);
    area.setSelectionRange(from - width, to + width - 2 * width);
    return;
  }
  replaceRange(area, mark.wrap + chosen + mark.wrap);
  // An empty selection leaves the caret between the marks, ready to type. A
  // selection stays selected, so a second press undoes it.
  if (chosen) area.setSelectionRange(from + width, to + width);
  else area.setSelectionRange(from + width, from + width);
}

const LIST_ITEM = /^(\s*)([-*+]|\d+\.)(\s+)(\[[ xX]\]\s+)?(.*)$/;

function attachEditing(area, bar) {
  if (bar) {
    for (const mark of FORMATS) {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'mark';
      button.textContent = mark.label;
      button.title = mark.title;
      if (mark.style) button.setAttribute('style', mark.style);
      // mousedown, not click: click runs after the textarea has lost focus and
      // with it the selection the mark is supposed to apply to.
      button.onmousedown = event => { event.preventDefault(); applyMark(area, mark); };
      bar.append(button);
    }
  }

  area.addEventListener('keydown', event => {
    if (event.metaKey || event.ctrlKey) {
      const mark = FORMATS.find(
        m => m.key === event.key.toLowerCase() && !!m.shift === event.shiftKey
      );
      if (mark && !event.altKey) {
        event.preventDefault();
        applyMark(area, mark);
      }
      return;
    }
    if (event.key !== 'Enter' || event.shiftKey) return;
    // Enter continues a list, which is the one thing everybody misses from
    // HackMD within a minute. An empty item ends the list instead of making
    // another empty one, which is how every editor that does this behaves.
    const [from] = lineRange(area);
    const line = area.value.slice(from, area.selectionStart);
    const parts = LIST_ITEM.exec(line);
    if (!parts) return;
    event.preventDefault();
    const [, indent, bullet, gap, box, text] = parts;
    if (!text.trim()) {
      area.setSelectionRange(from, area.selectionEnd);
      replaceRange(area, '');
      return;
    }
    const next = /^\d+\./.test(bullet)
      ? `${parseInt(bullet, 10) + 1}.`
      : bullet;
    replaceRange(area, `\n${indent}${next}${gap}${box ? '[ ] ' : ''}`);
  });
}

// Paste or drop an image and it goes into the plan repository, content-addressed,
// and the markdown that names it is inserted where the cursor is. The path is
// written repository-relative so the same text reads correctly in git, on GitHub
// and here — only the prefix in front of it differs.
function attachUploads(area, status) {
  const insert = markdown => replaceRange(area, markdown);

  async function send(file) {
    if (!file || !file.type.startsWith('image/')) return;
    status.textContent = `uploading ${file.name || 'image'}…`;
    // A placeholder first, so a slow upload does not look like nothing happened
    // and the text cannot be typed over the spot it is going to land in.
    const token = `![uploading ${file.name || 'image'}…]()`;
    insert(token);
    // An upload is a commit like any other, so the shell's banner is told before
    // it starts and told its sha afterwards. Without this the server announced
    // the paste to every tab including this one, and "The plan changed." landed
    // over your own image with nothing left to take it away again.
    dispatchEvent(new Event('openproj:writing'));
    let committed = null;
    try {
      const response = await fetch('/api/asset', {
        method: 'POST', headers: {'content-type': file.type}, body: file,
      });
      const answer = await answerOf(response);
      // Only a fresh upload made a commit. Claiming the sha of one that was
      // already in the plan would swallow a banner about somebody else's write.
      if (response.ok && answer.fresh) committed = answer.commit;
      const alt = (file.name || 'image').replace(/\.[^.]+$/, '').replace(/[\[\]]/g, '');
      const at = area.value.indexOf(token);
      if (at >= 0) {
        area.setSelectionRange(at, at + token.length);
        replaceRange(area, response.ok ? `![${alt}](${answer.path})` : '');
      }
      status.textContent = response.ok
        ? (answer.fresh ? `${answer.path} uploaded` : `${answer.path} — already in the plan`)
        : (answer.detail || 'that upload was refused');
    } finally {
      dispatchEvent(new CustomEvent('openproj:wrote', {detail: committed}));
    }
  }

  area.addEventListener('paste', event => {
    const files = [...(event.clipboardData?.files || [])];
    if (!files.length) return;
    event.preventDefault();
    files.forEach(send);
  });
  area.addEventListener('dragover', event => {
    event.preventDefault();
    area.classList.add('dropping');
  });
  area.addEventListener('dragleave', () => area.classList.remove('dropping'));
  area.addEventListener('drop', event => {
    event.preventDefault();
    area.classList.remove('dropping');
    [...(event.dataTransfer?.files || [])].forEach(send);
  });
}

// Type-to-filter, not a picker beside the field. A datalist only completes a whole
// value, so on a comma-separated field it stops helping after the first name — and
// a separate "add" control is a second place to look for one job.
const SUGGEST = JSON.parse(document.getElementById('suggest').textContent);

// One counter for the whole page, because `aria-controls` and
// `aria-activedescendant` are references by id and a page can carry a dozen of
// these — every fact on the detail form, every cell of the betting table.
let SUGGEST_N = 0;

// Every list currently parked on the body, with the input it belongs to.
//
// A list used to be the input's own next sibling, which meant `overflow` on any
// ancestor cut it off: the table's rows scroll inside `.table-scroll` and nine
// of its fourteen columns carry one of these, so a list opened on a low row was
// clipped against the bottom of the box — the normal case, not an edge. The
// frozen columns made it worse: `position: sticky` with a z-index is a stacking
// context, so a list opened in the title column was also painted under the
// sticky header. The body has neither problem, and nothing has to be given
// `position: relative` to anchor it any more.
//
// The price is that a list is no longer removed with the input it belongs to,
// and the table replaces its whole tbody after every save. An input taken off
// the page while it still holds focus never fires blur, so closing on blur is
// not enough to clean up after it — every list parked here is swept the next
// time one is. The scroll listener goes with it: it is what keeps the list under
// a box that moves, and forty cell edits would otherwise leave forty of them
// measuring inputs that are no longer on the page.
const PARKED = [];

function park(input, list, follow) {
  for (let i = PARKED.length - 1; i >= 0; i--) {
    const stale = PARKED[i];
    if (stale.input.isConnected) continue;
    stale.list.remove();
    removeEventListener('scroll', stale.follow, true);
    removeEventListener('resize', stale.follow);
    PARKED.splice(i, 1);
  }
  PARKED.push({input, list, follow});
  document.body.append(list);
  // Anything that moves the input moves the list: the page scrolling, the table
  // scrolling inside its own box, the window resizing. Capture, because a scroll
  // event on an element does not bubble up to the window.
  addEventListener('scroll', follow, true);
  addEventListener('resize', follow);
}

function attachSuggest(input) {
  const source = SUGGEST[input.dataset.suggest] || [];
  const multi = input.dataset.type === 'list';
  const list = document.createElement('ul');
  const id = 'suggest-' + (++SUGGEST_N);
  list.className = 'suggest';
  list.hidden = true;
  // The combobox contract, none of which this widget had. The keyboard already
  // worked — arrows moved a highlight, Enter picked it — but a highlight drawn
  // with a class is a highlight only a sighted reader can follow, and a popup
  // that is a bare <ul> is a popup nobody is told opened. The four attributes
  // below are the whole of the difference: what this control is, whether its
  // list is open, which list, and which option is current.
  list.id = id;
  list.setAttribute('role', 'listbox');
  input.setAttribute('role', 'combobox');
  input.setAttribute('aria-autocomplete', 'list');
  input.setAttribute('aria-controls', id);
  input.setAttribute('aria-expanded', 'false');

  // Where the input is, in the page's coordinates rather than the viewport's:
  // the list hangs off the body now, so it is positioned against the document.
  // Declared inside `attachSuggest` and not beside it, because the detail page
  // already has a global `place` — the one that puts the width grip against the
  // article — and two classic scripts on a page share one scope.
  function place() {
    const box = input.getBoundingClientRect();
    const under = innerHeight - box.bottom;
    // Above the box when there is no room under it. Parking the list on the body
    // stops it being clipped, but a list hanging off the bottom of the window
    // still has to be scrolled to, and the row somebody is editing is the row
    // they are looking at.
    const over = under < list.offsetHeight && box.top > under;
    list.style.left = (box.left + scrollX) + 'px';
    list.style.top = (over ? box.top + scrollY - list.offsetHeight
                           : box.bottom + scrollY) + 'px';
  }

  park(input, list, () => { if (!list.hidden) place(); });
  let active = -1;

  // `aria-activedescendant` is how a combobox says which option is current
  // without moving focus off the input — which it must not do, because the
  // input is still being typed into.
  function highlight() {
    const items = [...list.children];
    items.forEach((item, i) => {
      item.classList.toggle('on', i === active);
      item.setAttribute('aria-selected', String(i === active));
    });
    if (active >= 0) input.setAttribute('aria-activedescendant', items[active].id);
    else input.removeAttribute('aria-activedescendant');
  }

  const tokens = () => input.value.split(',').map(s => s.trim());
  const typed = () => (multi ? tokens()[tokens().length - 1] : input.value).trim().toLowerCase();

  function choose(value) {
    // `C2SM/icon4py#` is half a reference. Appending the separator after one would
    // end the entry at the point where the number still has to be typed.
    const partial = value.endsWith('#');
    if (multi) {
      const held = tokens();
      held[held.length - 1] = value;
      input.value = held.filter(Boolean).join(', ') + (partial ? '' : ', ');
    } else {
      input.value = value;
    }
    input.dispatchEvent(new Event('input', {bubbles: true}));
    input.focus();
    if (partial) { open(); return; }
    close();
  }

  function close() {
    list.hidden = true;
    list.innerHTML = '';
    active = -1;
    input.setAttribute('aria-expanded', 'false');
    input.removeAttribute('aria-activedescendant');
  }

  function open() {
    const needle = typed();
    const matches = source
      .filter(item => (item.value + ' ' + item.label).toLowerCase().includes(needle))
      .filter(item => !multi || !tokens().slice(0, -1).includes(item.value))
      .slice(0, 8);
    // Everything but the counter is stored text. For the `entities` source the
    // value is an id and the label IS an entity title, so before this, opening
    // the Parent list on the detail page inserted whatever the last person to
    // rename an entity had typed — as markup, into a page that then offers a
    // Save button. `esc` is the shell's, so this widget uses the same one the
    // table and the timeline do rather than being the one script with none.
    list.innerHTML = matches
      .map((m, i) => `<li id="${id}-${i}" role="option" data-value="${esc(m.value)}">` +
        `${esc(m.value)}${m.label ? ` <span class="dim">${esc(m.label)}</span>` : ''}</li>`)
      .join('');
    active = matches.length ? 0 : -1;
    list.hidden = !matches.length;
    // After it is shown and filled, because `place` measures how tall it is to
    // decide whether it fits under the box.
    if (!list.hidden) place();
    input.setAttribute('aria-expanded', String(!list.hidden));
    highlight();
  }

  input.addEventListener('input', open);
  input.addEventListener('focus', () => {
    // A list that already holds a name needs a separator before the next one, or
    // the first thing typed lands inside the previous value and matches nothing.
    if (multi && input.value.trim() && !input.value.trim().endsWith(',')) {
      input.value = input.value.trim() + ', ';
      input.setSelectionRange(input.value.length, input.value.length);
    }
    open();
  });
  input.addEventListener('blur', () => setTimeout(close, 150));
  list.addEventListener('mousedown', event => {
    const item = event.target.closest('li');
    if (item) { event.preventDefault(); choose(item.dataset.value); }
  });
  input.addEventListener('keydown', event => {
    if (list.hidden) return;
    const items = [...list.children];
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      active = (active + (event.key === 'ArrowDown' ? 1 : items.length - 1)) % items.length;
      highlight();
    } else if (event.key === 'Enter' && active >= 0) {
      event.preventDefault();
      choose(items[active].dataset.value);
    } else if (event.key === 'Escape') {
      close();
    }
  });
}

for (const input of document.querySelectorAll('[data-suggest]')) attachSuggest(input);
</script>
"""

_SUGGEST_STYLE = """
/* Absolute against the page, not against the cell it belongs to: `attachSuggest`
   parks the list on the body and writes its `top` and `left` in page
   coordinates. As a child of its own cell it was clipped by `overflow` on any
   ancestor — the table's rows scroll inside `.table-scroll` — and trapped in the
   stacking context of a sticky frozen column. Nothing on the page carries
   `position: relative` for this any more; there was such a rule, `dd, td.edit`,
   and it was also stealing `position: sticky` from the table's title column. */
.suggest { position: absolute; z-index: 20; margin: 0; padding: 0; list-style: none;
           background: var(--surface); border: 1px solid var(--line-strong);
           border-radius: 3px; min-width: 14rem; max-height: 16rem; overflow-y: auto;
           box-shadow: 0 4px 14px rgba(0,0,0,.12); font-size: 13px; }
.suggest li { padding: .25rem .5rem; cursor: pointer; }
.suggest li.on { background: var(--accent); color: var(--on-accent); }
textarea.dropping { outline: 2px dashed var(--accent); outline-offset: -2px; }
.marks { display: inline-flex; gap: .15rem; }
button.mark {
  font: inherit; font-size: 12px; line-height: 1; min-width: 1.9rem; padding: .3rem .35rem;
  border: 1px solid var(--line); border-radius: 3px;
  background: var(--surface); color: var(--muted); cursor: pointer;
}
button.mark:hover { border-color: var(--accent); color: var(--accent); }
.doc img { max-width: 100%; height: auto; }
.suggest .dim { opacity: .6; }
.suggest li.on .dim { opacity: .85; }
"""

# Every branch carries an `id`, and every `<dt>` that renders one of these carries
# a `<label for>` pointing at it. A `<dt>`/`<dd>` pair is a name and a value to a
# reader and nothing at all to the accessibility tree, so before this not one
# control on the detail page or the create page had a name.
_CONTROL = """
{% if f.type in ("status", "priority") %}
<select name="{{ f.name }}" id="{{ f.id }}" data-type="text" class="field"
        {% if f.gates %}data-required-at="{{ f.gates|join(' ') }}"{% endif %}>
  {% for s in (statuses if f.type == "status" else priorities) %}
  <option value="{{ s }}" {% if s == f.value %}selected{% endif %}>{{ s|human }}</option>
  {% endfor %}
</select>
{% elif f.type == "bool" %}
<input type="checkbox" name="{{ f.name }}" id="{{ f.id }}" data-type="bool" class="field"
       {% if f.value %}checked{% endif %}>
{% elif f.type == "date" %}
<input type="date" name="{{ f.name }}" id="{{ f.id }}" data-type="date" value="{{ f.text }}"
       class="field"
       {% if f.gates %}data-required-at="{{ f.gates|join(' ') }}"{% endif %}>
{% else %}
<input name="{{ f.name }}" id="{{ f.id }}" data-type="{{ f.type }}" value="{{ f.text }}"
       class="field" autocomplete="off"
       {% if f.list %}data-suggest="{{ f.list }}"{% endif %}
       {% if f.gates %}data-required-at="{{ f.gates|join(' ') }}"{% endif %}>
{% endif %}
"""

# One script for both forms that carry a status. Written once because the create
# page and the detail page ask the same question of the same controls, and two
# copies of a validation courtesy is one copy that quietly stops matching.
_REQUIRED_JS = Markup("""
// The word printed beside a control, which is the word somebody is looking at.
// The `<dt>` holds the label and then the mark, so its first node is the name.
function labelOf(control) {
  const dt = control.closest('dd')?.previousElementSibling;
  return dt ? dt.childNodes[0].textContent.trim() : control.name;
}

// What the server refused a write with, in the words on this page. A Problem
// carries its field as an identifier because that is what marks the control;
// printing that identifier is how `person_weeks` ended up in a sentence under
// a label reading "Appetite (weeks)". The field is named by the same `labelOf`
// the form's own check uses, so the two refusals cannot drift apart.
function refusals(answer, status) {
  const problems = answer.problems || [];
  // The shell's `refusal`, which is the one place that knows a 409 answers with
  // a report rather than with a `detail` — creating an entity against a moved
  // HEAD is a conflict like any other, and this line printed "refused" for it.
  if (!problems.length) return [refusal(answer, status)];
  return problems.map(problem => {
    // `CSS.escape` because the field arrives over the wire: an unescaped one
    // would be a malformed selector, and a DOMException here would swallow the
    // whole refusal rather than one line of it.
    const control = problem.field
      && document.querySelector(`[data-type][name="${CSS.escape(problem.field)}"]`);
    return control ? `${labelOf(control)}: ${problem.message}` : problem.message;
  });
}

// What the chosen status will make the server refuse this form without. Marked
// on the label rather than announced after a rejected save: which fields a
// status demands is the thing you need before you fill the form in, and the
// rules change under you the moment the status select does.
function markRequired(form) {
  const status = form.querySelector('[name=status]')?.value || 'shaping';
  const waived = form.querySelector('[name=review_waived]')?.checked;
  for (const control of form.querySelectorAll('[data-required-at]')) {
    // review_waived is the escape hatch from the reviewer rule, so honouring it
    // here is the difference between a mark and a nag.
    const demanded = control.dataset.requiredAt.split(' ').includes(status)
      && !(control.name === 'reviewers' && waived);
    if (demanded) control.setAttribute('aria-required', 'true');
    else control.removeAttribute('aria-required');
    const mark = control.closest('dd')?.previousElementSibling?.querySelector('.req');
    if (mark) mark.hidden = !demanded;
  }
}

// `change` and not `input`: the two controls that move the gates are a select
// and a checkbox, and both report on change. It listens on the form so a control
// that appears later — a kind switch unhides three — is covered without rewiring.
function watchRequired(form) {
  form.addEventListener('change', () => markRequired(form));
  markRequired(form);
}
""")


def _control_html(field: dict) -> Markup:
    return _fragment(_CONTROL, f=field, statuses=STATUSES, priorities=PRIORITIES)


# `_FIELDS` and `_fields_html` were the flat list of `<label>field</label>` this
# replaced, and nothing has called them since the create page became the detail
# page with nothing in it. They were the last place a raw field name reached a
# reader, and dead code that still renders is code somebody wires back up.


_NEW = """
<article class="entity editing">
  <p class="back"><a href="{{ links.table }}">← table</a></p>
  {#- The kind sits where the detail page's kind chip sits, above the heading:
      the two are the same document in two modes, and this is the control that
      decides which of the three the reader will be looking at afterwards — the
      first decision on the form, and it was the third thing on a line under the
      title box. -#}
  <p class="eyebrow"><label class="kindpick">kind
      <select id="kind">
        {% for k in kinds %}<option value="{{ k }}"
          {% if k == kind %}selected{% endif %}>{{ k|human }}</option>{% endfor %}
      </select>
    </label></p>
  {#- The heading names the page; the title box below it is a control. It used to
      BE the heading — a heading whose only content was an empty input, which is
      a page with no name at all and a box with no name either. `aria-label`
      rather than a `<label for>` because the visible word is the placeholder,
      and a placeholder disappears the moment anything is typed. -#}
  <h1>New entity</h1>
  <input name="title" data-type="text" form="edit" value="" aria-label="Title"
         class="field title-field" placeholder="Title">
  <p class="meta">the id and the file are the server's to choose</p>
  <form id="edit" onsubmit="return false">
    <input type="hidden" name="base_commit" value="{{ base_commit }}">
    <div class="panes">
      <aside class="facts">
        <dl id="facts">
          {% for row in rows %}
          <dt data-kinds="{{ row.kinds }}"><label for="{{ row.for
            }}">{{ row.label }}</label>{% if row.gates %}
            <span class="req" hidden>required</span>{% endif %}</dt>
          <dd data-kinds="{{ row.kinds }}">{{ row.control }}</dd>
          {% endfor %}
        </dl>
      </aside>
      <div class="main">
        {#- What the form or the server refused this with. Filled by script, so
            it is news arriving on a page that is already open. -#}
        <ul id="problems" class="problems" role="status" aria-live="polite" hidden></ul>
        {#- Two rows, in the order the two kinds of control are reached for. The
            first says what this box will BE — a preview of it, and the template
            it starts from; the second is the typing furniture. One row put a
            seven-character select between `Preview the body` and eight
            single-character buttons, and nothing on the line lined up with
            anything else on it. -#}
        <p class="field bodybar">
          <button type="button" id="preview">Preview the body</button>
          {#- The template is offered, never imposed: it fills an untouched box
              and refuses to overwrite one somebody has typed in. `template` and
              not `start from`: the label names the control, and the sentence it
              was part of ended in the option list. -#}
          <label class="tplpick">template
            <select id="template">
              <option value="pitch">the shaping template</option>
              <option value="task">a task</option>
              <option value="project">a project</option>
              <option value="blank">nothing</option>
            </select>
          </label>
          <span class="hint" id="tplstate" role="status" aria-live="polite"></span>
        </p>
        <p class="field bodybar markbar">
          <span id="marks" class="marks"></span>
          <span class="hint">paste or drop an image to put it in the plan</span>
          <span class="hint" id="upload" role="status" aria-live="polite"></span>
        </p>
        <textarea name="body" class="field body-field" rows="14"
                  aria-label="Shaping document"
                  placeholder="The shaping document."></textarea>
        <div class="doc" hidden></div>
      </div>
    </div>
  </form>
  <div class="commitbar" id="commitbar">
    <span id="unsaved">Nothing is written until you press Create</span>
    <button type="button" id="save">Create</button>
    <span id="state" role="status"></span>
  </div>
</article>
{{ combobox }}
<script>{{ required }}</script>
<script>
const FORM = document.getElementById('edit');
const PROBLEMS = document.getElementById('problems');
const KIND = document.getElementById('kind');

// Every kind's fields are on the page and the ones this kind does not have are
// hidden, rather than each kind being its own round trip. Switching kind after
// typing a title used to mean typing it again.
function showKind() {
  for (const element of FORM.querySelectorAll('[data-kinds]'))
    element.hidden = !element.dataset.kinds.split(' ').includes(KIND.value);
}

showKind();
// The status select is inside the form, so one listener on the form catches both
// it and the review_waived checkbox that lets one of its rules off.
watchRequired(FORM);

function read(control) {
  if (control.dataset.type === 'bool') return control.checked;
  const raw = control.value.trim();
  if (control.dataset.type === 'list')
    return raw ? raw.split(',').map(s => s.trim()).filter(Boolean) : [];
  if (control.dataset.type === 'number') {
    if (raw === '') return null;
    const n = Number(raw);
    if (Number.isNaN(n)) throw new Error(`${control.name} must be a number, not "${raw}"`);
    return n;
  }
  return raw === '' ? null : raw;
}

const PREVIEW = document.getElementById('preview');
const DOC = document.querySelector('.doc');
const BODY = FORM.querySelector('[name=body]');
// The box holding the title, for the preview: the page suppresses the document's
// own leading heading when it repeats the title, and a preview that does not know
// the title cannot suppress it. Found by class rather than through the form,
// because on the create page the title sits outside `<form>` and is bound to it
// by a `form=` attribute — which `querySelector` on the form does not see.
const TITLED = document.querySelector('.title-field');
attachUploads(BODY, document.getElementById('upload'));
attachEditing(BODY, document.getElementById('marks'));

// The body a new entity starts from. Switching kind switches template, because
// picking "pitch" and getting a task's headings is the wrong default in the one
// place the tool can teach the shape of a pitch — but only while the box is
// still one of ours. Once somebody has typed, the box is theirs: the template
// never changes underneath a sentence, and the picker says so rather than
// appearing to do nothing.
const TEMPLATES = {{ templates|tojson }};
const TPL = document.getElementById('template');
const TPLSTATE = document.getElementById('tplstate');

function untouched() {
  return Object.values(TEMPLATES).some(text => text.trim() === BODY.value.trim());
}

function applyTemplate(name) {
  if (!untouched()) {
    TPLSTATE.textContent = 'the body has been edited — clear it to start from a template';
    return false;
  }
  BODY.value = TEMPLATES[name] ?? '';
  TPLSTATE.textContent = '';
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

PREVIEW.onclick = async () => {
  if (!DOC.hidden) {
    DOC.hidden = true;
    BODY.hidden = false;
    PREVIEW.textContent = 'Preview the body';
    return;
  }
  // The title goes with it: the page drops a leading heading that only restates
  // the title, so a preview without one shows a heading the saved page will not.
  // The title in the FORM, not the stored one — this same Save may change it.
  const response = await fetch('/api/preview', {
    method: 'POST', headers: {'content-type': 'application/json'},
    body: JSON.stringify({body: BODY.value, title: TITLED.value}),
  });
  DOC.innerHTML = (await response.json()).html;
  DOC.hidden = false;
  BODY.hidden = true;
  PREVIEW.textContent = 'Back to the source';
};

document.getElementById('save').onclick = async () => {
  const fields = {kind: KIND.value};
  const status = FORM.querySelector('[name=status]')?.value || 'shaping';
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
  const title = document.querySelector('.title-field');
  if (title.value.trim()) fields.title = title.value.trim(); else missing.push('Title');
  if (missing.length) {
    // The words on the page, not the words in the file: `person_weeks` and
    // `in_progress` are what git holds, and a refusal that names them sends
    // somebody looking for a field with that label.
    const chosen = FORM.querySelector('[name=status]');
    PROBLEMS.hidden = false;
    // `replaceChildren` with one line of text, not `innerHTML`: every word in
    // this sentence comes off the page — an option's label, a control's `<dt>` —
    // and the page it comes off is one whose fields hold whatever the plan
    // holds. There is no markup wanted here at all, so none is built.
    const line = document.createElement('li');
    line.textContent = 'still needed at status '
      + `${chosen?.selectedOptions[0]?.textContent.trim() || status}: `
      + missing.join(', ');
    PROBLEMS.replaceChildren(line);
    return;
  }
  // The shell's banner is told before the request goes and told the sha after,
  // because the server announces a commit to the event stream before it answers
  // the request that made it. Creating an entity is a write like any other, and
  // an unannounced one comes back to this tab as somebody else's news.
  dispatchEvent(new Event('openproj:writing'));
  let committed = null;
  try {
    const response = await fetch('/api/entity', {
      method: 'POST', headers: {'content-type': 'application/json'},
      body: JSON.stringify({
        base_commit: FORM.querySelector('[name=base_commit]').value, fields,
        body: BODY.value || '',
      }),
    });
    const answer = await answerOf(response);
    if (!response.ok) {
      // The client check is a courtesy; this is the truth, and swallowing it leaves
      // somebody staring at a form that looks fine. Named by the same `labelOf`
      // the check above uses, so the server's refusal and the form's own name the
      // field identically — and built as text nodes, because `answer.detail`
      // quotes back whatever key was posted.
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
    // Announced even when refused, or one rejected form leaves every later event
    // held back and the banner never appears again.
    dispatchEvent(new CustomEvent('openproj:wrote', {detail: committed}));
  }
};
</script>
"""

_DETAIL = """
{#- The index view is one of the views this page routes between, and it had no
    heading of its own — so with no hash in the URL the page was a list of links
    under nothing. Each `<article>` below carries its own `<h1>`, because each of
    them is a document and exactly one of them is ever displayed. -#}
{% if not single %}<div class="toc">
  <h1>Every entity in this plan except for issues</h1>
  {% for group in groups %}
  <h2 class="tocgroup">{{ group.status|human }}
    <span class="tally">{{ group.entities|length }}</span></h2>
  <ul>
    {% for e in group.entities %}
    {#- The kind first, because it is the thing every row in this list has and
        the thing a reader is scanning for; a chip trailing the title arrived
        after the answer and moved with the title's length. The owner is gone
        from here: this index exists to get you to a record, and the owner is on
        the record, one click away, next to the four other fields you actually
        came for. -#}
    <li><span class="chip kind-{{ e.kind }}">{{ e.kind|human }}</span
      ><a href="{{ links.entity }}{{ e.id }}">{{ e.title }}</a></li>
    {% endfor %}
  </ul>
  {% endfor %}
</div>{% endif %}
{% for e in entities %}
<article id="{{ e.id }}" class="entity">
  {#- Back to the table, which is where you came from and where everything is.
      It pointed at the detail index, which was the same list with none of the
      controls — and that index is no longer in the nav, so a link to it now
      lands somewhere a reader has no other route to. -#}
  <p class="back"><a href="{{ links.table }}">← all entities</a></p>
  {#- Above the title, not under it. What a thing *is* is the first question a
      page answers, and the kind was the third item on a line below the name,
      between an id and a status. It is also the one fact here that never
      changes, which is why it is the one that sits here. -#}
  <p class="eyebrow"><span class="chip kind-{{ e.kind }}">{{ e.kind|human }}</span></p>
  <h1><span class="read">{{ e.title }}</span></h1>
  {#- No status chip. It was here as well as in the facts column forty pixels
      below — the same word, in the same colour, twice, and in edit mode the
      lower one is the select that changes it. A field that can be changed is
      stated where it can be changed: STATUS is the first row of the facts
      column, level with the title, so nothing is further away than it was. -#}
  <p class="meta"><code>{{ e.id }}</code>
     {% if e.parent %}· in {{ e.parent_link }}{% endif %}</p>
  {#- The way in, at the top. It was in the commit bar at the foot of the page,
      under the whole shaping document — so on any record worth reading, the
      button that lets you change it was a scroll away from the thing you had
      just decided to change. Save stays down there, where what is being
      committed ends. -#}
  {% if editable %}
  <p class="editbar"><button type="button" id="toggle">Edit</button></p>
  <form id="edit" data-id="{{ e.id }}" onsubmit="return false">
    <input type="hidden" name="base_commit" value="{{ base_commit }}">
    <input name="title" data-type="text" value="{{ e.title }}" aria-label="Title"
           class="field title-field">
  {% endif %}
  <div class="panes">
    <aside class="facts">
      {#- The id only where there is one of these on the page. This template is
          rendered once per entity, and the static export puts every entity in
          one document — so the export carried seventeen elements with the same
          id, which is invalid, and which makes `getElementById('facts')` answer
          with the first entity's list whatever the hash says. Nothing calls it
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
        <dt class="{% if row.derived %}derived{% endif %}
                   {% if row.editing_only %}editing-only{% endif %}">{% if
          editable and row.control %}<label for="{{ row.for }}">{{ row.label }}</label>{%
          else %}{{ row.label }}{% endif %}{% if
          editable and row.gates %} <span class="req" hidden>required</span>{% endif %}</dt>
        <dd class="{% if row.derived %}derived{% endif %}
                   {% if row.editing_only %}editing-only{% endif %}">
          <span class="read">{{ row.display }}</span>
          {% if editable and row.control %}{{ row.control }}{% endif %}
        </dd>
        {% endfor %}
      </dl>
    </aside>
    <div class="main">
      {% if e.problems %}<ul class="problems">
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
            <a href="{{ links.entity }}{{ item.id }}">{{ item.title }}</a>
            <span class="chip {{ item.status_class }}">{{ item.status|human }}</span>
            <span class="tally">{{ item.size }} wk{% if item.people %}
              · {{ item.people }}{% endif %}</span>
          </li>
          {% endfor %}
        </ul>
      </section>
      {% endif %}
      <div class="doc read">{{ e.body }}</div>
      {% if editable %}
      <p class="field bodybar">
        {#- Who else is in this document, by name. A name is the channel that
            survives every reader; a colour is not, and a caret drawn one line
            off a `<textarea>` through a mirror element is worse than no caret at
            all. Empty when nobody else is here, which is most of the time. -#}
        <span id="together" class="together" role="status" aria-live="polite"></span>
        <button type="button" id="preview">Preview the body</button>
      </p>
      <p class="field bodybar markbar">
        <span id="marks" class="marks"></span>
        <span class="hint">paste or drop an image to put it in the plan</span>
        <span class="hint" id="upload" role="status" aria-live="polite"></span>
      </p>
      {#- The box, and a layer over it for where everybody else is. The layer is
          a sibling rather than a background, because a `<textarea>` cannot hold
          anything but text: the bands are drawn on top, translucent, and take no
          pointer events — the thing under them is the thing being typed in. -#}
      <div class="bodywrap">
        <div id="seats" class="seats" aria-hidden="true"></div>
        <textarea name="body" class="field body-field"
                  aria-label="Shaping document">{{ e.raw_body }}</textarea>
      </div>
      <div id="body-preview" class="field doc" hidden></div>
      <div id="conflict" role="status" aria-live="polite" hidden></div>
      {% endif %}
    </div>
  </div>
  {% if editable %}
  </form>
  {#- Save stays at the bottom, where the thing being committed ends; Edit has
      moved to the top, beside the title, because it is the way IN and a way in
      you have to scroll past a shaping document to find is one nobody finds. -#}
  <div class="commitbar" id="commitbar">
    <span id="unsaved">Nothing to save</span>
    <button type="button" id="save" hidden>Save</button>
    {#- Cancel stays beside Save and never beside Edit. They are the two ways one
        editing session can end and putting them in two places is how somebody
        closes a tab believing the other one was the way out. Edit is a third
        thing — the way IN — which is why it is at the top and this is not. -#}
    <button type="button" id="cancel" hidden>Cancel</button>
    <span id="state" role="status"></span>
  </div>
  {% endif %}
  {#- Deliberately not in the bar above. Save and Cancel are pressed all day and
      the bar is sticky, so it is on screen the whole time; a control that removes
      the record from the plan does not belong within a thumb's width of the one
      that keeps it. It sits at the very end of the record instead, past
      everything there is to read, which is where you are when you have finished
      deciding.

      Classes and not ids, unlike everything else on this page. The static export
      renders every entity into one document and `/detail` serves them all on one
      route, so `id="delete"` would be seventeen elements of that name — and
      `getElementById` answers with the first, which is a Delete button under
      entity nine wired to entity one. The rest of this page has lived with that
      duplication for a year because the worst it can do is edit the wrong thing
      in a box you can see. This one commits. -#}
  {% if editable and may_write %}
  <div class="dangerbar">
    <button type="button" class="delete">Delete this {{ e.kind }}</button>
    <div class="confirming" data-also="{{ (e.deletes + e.frees)|join(" ") }}" hidden>
      {#- The title, spelled out. "Are you sure?" over a record you cannot see
          from the dialog is a question nobody can answer, and this page can be a
          long way from the heading by the time you reach the foot of it. -#}
      <p class="asking">Delete <strong>{{ e.title }}</strong>
        (<code>{{ e.id }}</code>)?<br>
        <span class="hint">The file leaves the plan in a commit. Git keeps every
          version of it, so this can be undone with <code>git revert</code>.</span></p>
      {#- The reach of it, before the press and not after. A record filed under
          this one has nowhere to be once it is gone, so it goes too; a record
          that merely depends on this one is somebody else's work waiting for it,
          and deleting that would be this gesture reaching across the plan. The
          two consequences are drawn as two sentences because they are two
          different things happening to two different sets of files. -#}
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
  </div>
  {% endif %}
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
// per entity: it is a property of the screen it is being read on, not of the plan.
const grip = document.getElementById('grip');
const root = document.documentElement;
const saved = remembered.get('openproj:measure');
if (saved) root.style.setProperty('--measure', saved);

function place() {
  // The visible one. On the index view every article is hidden, and measuring a
  // hidden element gives zero — which parked the handle against the left edge of
  // the page, a rule down the side of a list it has nothing to do with.
  const article = [...document.querySelectorAll('article.entity')]
    .find(candidate => candidate.offsetParent !== null);
  grip.hidden = !article;
  if (article) grip.style.left = article.getBoundingClientRect().right + 'px';
}
place();
addEventListener('resize', place);

grip.onpointerdown = event => {
  grip.setPointerCapture(event.pointerId);
  grip.classList.add('dragging');
  const move = e => {
    // The column is centred, so its right edge is half a width from the middle of
    // the window: dragging that edge out by one pixel is two pixels of column.
    const width = Math.max(320, (e.clientX - innerWidth / 2) * 2);
    root.style.setProperty('--measure', width + 'px');
    place();
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
{% if editable %}{{ combobox }}{% endif %}
{% if editable %}<script>{{ required }}</script>{% endif %}
{% if editable %}<script>
// Only what changed travels. Serialising the whole form would send back every
// field as this tab last saw it, overwriting whatever somebody else changed while
// it sat open — which is exactly what scoped compare-and-swap exists to prevent.
const FORM = document.getElementById('edit');
const ORIGINAL = {};
const CONTROLS = [...FORM.querySelectorAll('[data-type]')];
const BODY = FORM.querySelector('[name=body]');
// The box holding the title, for the preview: the page suppresses the document's
// own leading heading when it repeats the title, and a preview that does not know
// the title cannot suppress it. Found by class rather than through the form,
// because on the create page the title sits outside `<form>` and is bound to it
// by a `form=` attribute — which `querySelector` on the form does not see.
const TITLED = document.querySelector('.title-field');
attachUploads(BODY, document.getElementById('upload'));
attachEditing(BODY, document.getElementById('marks'));
// The commit this page was rendered at, and what every save is compared against.
// Read through this one box rather than looked up at each write, because a
// restored draft moves it back to the commit that draft was written on top of.
const BASE = FORM.querySelector('[name=base_commit]');
// The draft's key, version 2: a draft is now `{base, text}` rather than text.
// Bumped rather than parsed loosely, so a body that happens to be valid JSON
// cannot be mistaken for the new shape.
const DRAFT = `openproj:draft:2:${FORM.dataset.id}`;

function read(control) {
  const type = control.dataset.type;
  if (type === 'bool') return control.checked;
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
let ORIGINAL_BODY = BODY.value;

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
  let fields = {};
  // A number typed as a word throws in `read`; that is Save's message to deliver,
  // not a reason for the counter to stop counting the rest.
  try { fields = changed(); } catch (error) { fields = {}; }
  const count = Object.keys(fields).length + (BODY.value === ORIGINAL_BODY ? 0 : 1);
  const editing = document.querySelector('article.entity').classList.contains('editing');
  BAR.classList.toggle('dirty', count > 0);
  UNSAVED.textContent = count
    ? `${count} unsaved change${count === 1 ? '' : 's'}`
    : (editing ? 'Nothing changed yet' : 'Nothing to save');
}
FORM.addEventListener('input', dirty);
FORM.addEventListener('change', dirty);
// The status select decides which fields the server will refuse this without,
// and the checkbox beside it lets one of those rules off.
watchRequired(FORM);

// `showEditing` and not `show`: the detail page's hash router declares a `show`
// of its own in another `<script>`, and two top-level functions of one name in
// one page are one function. The two blocks are never emitted together today —
// the index is read-only and the single view has no router — so this was a trap
// rather than a defect, and one condition changing anywhere above makes it one.
// (Written without naming the tag: this block is a Jinja template, and a comment
// that mentions one is a comment the template engine reads.)
function showEditing(editing) {
  // One class on the article. Each fact is a single row whose value swaps for its
  // control, so nothing is shown twice and the page does not jump when you start.
  document.querySelector('article.entity').classList.toggle('editing', editing);
  document.getElementById('save').hidden = !editing;
  // Three buttons and never two of them at once: Edit is the way in and lives at
  // the top, beside the record; Save and Cancel are the two ways one editing
  // session ends and live together in the sticky bar at the foot of the thing
  // being committed. The button that used to be here was Edit and Cancel by
  // turns, in one place, which put the way out under the document you were
  // editing.
  document.getElementById('cancel').hidden = !editing;
  document.getElementById('toggle').hidden = editing;
  dirty();
  // The room's bands are measured against a box that has a size. The socket
  // opens on load and the roster arrives while the page is still in read mode,
  // where the textarea is `display: none` and every measurement is zero — so the
  // first thing anybody saw on entering edit mode was no bands at all, on a
  // document somebody else was demonstrably in.
  dispatchEvent(new Event('openproj:editing'));
}

// Both of the buttons that change the mode, through one handler: Edit at the top
// turns it on, Cancel in the bar turns it off, and a second copy of what that
// means is how the two come to disagree about the draft.
function flipEditing() {
  const editing = !document.querySelector('article.entity').classList.contains('editing');
  showEditing(editing);
  // The stored draft goes; the base it brought with it stays. The text is still
  // in the box, so the page is still holding work written against that commit —
  // moving the base forward here is the silent overwrite by another route.
  if (!editing) remembered.forget(DRAFT);
}
document.getElementById('toggle').onclick = flipEditing;
document.getElementById('cancel').onclick = flipEditing;

// Deleting a record. Two presses and a named record between them, and every
// element found through the article the button is in rather than by id — this
// page can hold more than one entity, and a destructive control resolved by
// `getElementById` is one that acts on whichever entity happens to be first.
for (const bar of document.querySelectorAll('.dangerbar')) {
  const article = bar.closest('article.entity');
  const ask = bar.querySelector('.confirming');
  const why = bar.querySelector('.why');
  const open = bar.querySelector('button.delete');

  // Shown and hidden rather than a `confirm()`. A native dialog cannot say which
  // record it is about in the words this page uses, cannot show the server's
  // reason when the delete is refused, and is the one thing on a page that stops
  // every other script until somebody clicks it.
  const asking = state => {
    ask.hidden = !state;
    open.hidden = state;
    why.hidden = true;
    if (state) bar.querySelector('button.keep').focus();
  };
  open.onclick = () => asking(true);
  bar.querySelector('button.keep').onclick = () => asking(false);
  // Escape backs out of the question, the way it backs out of everything else
  // here. Bound on the panel and not on the document, so it cannot swallow the
  // key from the editor when nothing is being confirmed.
  ask.onkeydown = event => { if (event.key === 'Escape') asking(false); };

  bar.querySelector('button.really').onclick = async () => {
    const acts = bar.querySelector('.acts');
    acts.hidden = true;
    // The base commit the page was rendered against, the same one every other
    // write here sends: a delete is a compare-and-swap like the rest, and the
    // server refuses it if somebody has edited the record since this page drew
    // it. Read off the form so there is one answer on the page and not two.
    const base = article.querySelector('input[name=base_commit]').value;
    const also = (ask.dataset.also || '').split(' ').filter(Boolean);
    let answer;
    try {
      answer = await fetch('/api/entity/' + encodeURIComponent(article.id), {
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
      // To the table, because the page you are on is about a record that no
      // longer exists: staying here would show a 404 on the next reload, and
      // reloading it is what the shell does when it hears the commit.
      location.href = {{ links.table|tojson }};
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

document.getElementById('preview').onclick = async () => {
  // Only the body, and without leaving edit mode. It used to swap the whole page
  // back to the read view, which showed the *stored* fields — so adding a reviewer
  // and pressing Preview appeared to lose the change.
  const pane = document.getElementById('body-preview');
  const button = document.getElementById('preview');
  if (!pane.hidden) {
    pane.hidden = true;
    BODY.hidden = false;
    button.textContent = 'Preview the body';
    return;
  }
  // A round trip, not a second markdown implementation: two renderers disagree
  // eventually, and the one people trust would not be the one that gets committed.
  // The title goes with it: the page drops a leading heading that only restates
  // the title, so a preview without one shows a heading the saved page will not.
  // The title in the FORM, not the stored one — this same Save may change it.
  const response = await fetch('/api/preview', {
    method: 'POST', headers: {'content-type': 'application/json'},
    body: JSON.stringify({body: BODY.value, title: TITLED.value}),
  });
  pane.innerHTML = (await response.json()).html;
  pane.hidden = false;
  BODY.hidden = true;
  button.textContent = 'Back to the source';
};

async function save() {
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
  const body = BODY.value === ORIGINAL_BODY ? null : BODY.value;
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
    const response = await fetch(`/api/entity/${encodeURIComponent(FORM.dataset.id)}`, {
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
    remembered.forget(DRAFT);
    location.reload();
  } finally {
    // Announced even when refused, or one 409 leaves every event after it held
    // back and the banner never appears again.
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
BODY.addEventListener('input', () => {
  remembered.set(DRAFT, JSON.stringify({base: BASE.value, text: BODY.value}));
});
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
if (typeof draft.text === 'string' && draft.text !== BODY.value) {
  // The page is at HEAD and this text is not. Saving it is compared against the
  // commit it was drafted against, so the server can tell a merge from an
  // overwrite — and whoever restores it is told the ground moved rather than
  // finding out from a refusal one keystroke later.
  const moved = draft.base && draft.base !== BASE.value;
  if (draft.base) BASE.value = draft.base;
  announce(moved
    ? 'unsaved draft restored — somebody else has changed this since it was written'
    : 'unsaved draft restored');
  BODY.value = draft.text;
  showEditing(true);
}
</script>{% endif %}
{% if editable %}<script>{{ yjs }}</script>
<script>{{ coedit }}</script>{% endif %}
{% if not single %}<script>
// One page, hash-routed: a stable shareable link per entity without a file each.
// With no hash you get an index; with a hash you get exactly one document. Never
// every document at once — that is a wall of text, not a detail view.
function show() {
  const wanted = location.hash.slice(1);
  let found = false;
  for (const article of document.querySelectorAll('article.entity')) {
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
    const now = BODY.value, was = text.toString();
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

  // The document back into the textarea, with the caret left where the reader
  // put it. Setting `.value` collapses the selection to the end, which on a page
  // where somebody else is typing means the caret walks to the bottom of the
  // document once a second.
  function reflect() {
    const want = text.toString(), was = BODY.value;
    if (want === was) return;
    let head = 0;
    while (head < want.length && head < was.length && want[head] === was[head]) head++;
    const shift = want.length - was.length;
    const start = BODY.selectionStart, end = BODY.selectionEnd;
    const moved = at => at <= head ? at : Math.max(head, at + shift);
    BODY.value = want;
    // Only when this box has the caret: `setSelectionRange` on an unfocused
    // textarea also scrolls it, and a page scrolling itself because somebody
    // else typed is the thing nobody asked for.
    if (document.activeElement === BODY) BODY.setSelectionRange(moved(start), moved(end));
    dirty();
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
  text.observe(() => { if (bound) reflect(); });

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

  // Drawn again when the box appears. See `showEditing`.
  addEventListener('openproj:editing', () => { drawSeats(); sit(); });

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

  // The mirror. Built once, kept out of the accessibility tree, and given the
  // textarea's own metrics every time it is measured — a mirror whose font is a
  // fallback measures the fallback's line height, and every band lands somewhere
  // else on the machine that has no webfont yet.
  const ghost = document.createElement('div');
  ghost.className = 'ghost';
  ghost.setAttribute('aria-hidden', 'true');

  function measure(at) {
    const style = getComputedStyle(BODY);
    for (const name of ['fontFamily', 'fontSize', 'fontWeight', 'lineHeight',
                        'letterSpacing', 'padding', 'border', 'whiteSpace',
                        'wordBreak', 'overflowWrap', 'tabSize', 'boxSizing']) {
      ghost.style[name] = style[name];
    }
    ghost.style.width = BODY.clientWidth + 'px';
    ghost.textContent = BODY.value.slice(0, at);
    const mark = document.createElement('span');
    // A zero-width space so the marker has a box on an empty line, and so the
    // line it is on does not get one character wider than the real one.
    mark.textContent = '\u200b';
    ghost.appendChild(mark);
    const top = mark.offsetTop;
    const height = parseFloat(style.lineHeight) || parseFloat(style.fontSize) * 1.4;
    return {top, height};
  }

  function drawSeats() {
    const layer = document.getElementById('seats');
    if (!layer || !BODY) return;
    const others = seats.filter(seat => seat.login !== me);
    if (!others.length) { layer.replaceChildren(); return; }
    document.body.appendChild(ghost);
    const drawn = others.map(seat => {
      const {top, height} = measure(Math.min(seat.at, BODY.value.length));
      const band = document.createElement('div');
      band.className = 'seat';
      band.style.top = (top - BODY.scrollTop) + 'px';
      band.style.height = height + 'px';
      band.style.background = `hsl(${hueOf(seat.login)} 70% 60% / .22)`;
      const who = document.createElement('span');
      who.className = 'seatname';
      who.style.background = `hsl(${hueOf(seat.login)} 70% 60% / .85)`;
      // `textContent`, because this is a login off a socket.
      who.textContent = seat.login;
      band.appendChild(who);
      return band;
    });
    ghost.remove();
    layer.replaceChildren(...drawn);
  }

  // Where this tab's caret is, when it moves to a different place. Sent on the
  // index the two ends already agree on — UTF-16 code units, which is what
  // `selectionStart` counts and what a Yjs text is made of in a browser. The
  // server relays it and never reads it; see `Room.sits`.
  let sentAt = -1;
  function sit() {
    if (!BODY || !bound) return;
    const at = BODY.selectionStart;
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
      const mine = BODY.value !== ORIGINAL_BODY;
      const theirs = text.toString() !== ORIGINAL_BODY;
      if (mine && theirs) {
        // Two edits and no common base — a restored draft against a room that
        // has already moved. Refuse to guess: the room's text is what is in the
        // box, and the draft goes in the conflict report to be pasted back by
        // the person who wrote it.
        const draft = BODY.value;
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
      BODY.addEventListener('input', typed);
      // Where this tab is sitting, and where everybody else's band should be
      // drawn. Four events, because four different things move a band: the
      // caret moving, the text moving under it, the box scrolling, and the
      // window changing the wrap.
      BODY.addEventListener('input', () => { sit(); drawSeats(); });
      BODY.addEventListener('scroll', drawSeats);
      BODY.addEventListener('keyup', sit);
      BODY.addEventListener('click', sit);
      addEventListener('resize', drawSeats);
      sit();
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
      remembered.forget(DRAFT);
      box.hidden = true;
      settle(message.commit);
      dirty();
      announce(message.outcome === 'merged'
        ? 'saved, and somebody else’s change to this file was merged in'
        : (message.pushed === false ? 'saved here, not yet pushed' : 'saved'));
      // Everybody in the room, not only the tab that pressed the button: this
      // commit holds text that is already in every one of these editors, so the
      // shell's "somebody else changed this" banner is wrong about all of them.
      dispatchEvent(new CustomEvent('openproj:ours', {detail: message.commit}));
      // And the tab that pressed Save leaves edit mode, which is what pressing
      // it means. The path without a room reloads the page and lands in read
      // mode by doing so; in a room there is nothing to reload — the document is
      // already what everybody has — so this is the same ending arrived at
      // deliberately. Only the tab that asked: everybody else in the room is
      // still typing, and a commit somebody else made is not a reason to close
      // the box in front of you.
      if (mine && typeof showEditing === 'function') showEditing(false);
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
    if (dead) return;
    const where = (location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host
      + '/api/coedit/' + encodeURIComponent(FORM.dataset.id);
    try {
      socket = new WebSocket(where);
    } catch (error) {
      return stop('');
    }
    socket.onopen = () => {
      arrived = true;
      attempts = 0;
      send({t: 'hello', seed: seed, sv: b64(YJS.encodeStateVector(doc))});
    };
    socket.onmessage = event => {
      let message;
      try { message = JSON.parse(event.data); } catch (error) { return; }
      heard(message);
    };
    // Nothing to say here: a failed handshake fires this and then `onclose`,
    // which is where the one decision lives.
    socket.onerror = () => {};
    socket.onclose = () => {
      settle(null);
      names([]);
      if (dead) return;
      // A socket that has worked once and then closed is the normal case, not a
      // fault: Cloud Run closes every one of them at five minutes. A socket that
      // has never worked is a deployment without websockets, a proxy that drops
      // the upgrade, or a reader who may not write — and asking it again forever
      // is a red line in the console of a page that is working as designed.
      if (!arrived && attempts >= 4) return stop('');
      setTimeout(connect, Math.min(30000, 500 * Math.pow(2, attempts++)));
    };
  }

  connect();
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


_DETAIL_STYLE = """
.tocgroup { font-size: 12px; text-transform: uppercase; letter-spacing: .05em;
            color: var(--muted); font-weight: 600; margin: 1.4rem 0 .3rem; }
.tocgroup .tally { font-weight: 400; letter-spacing: 0; }
.toc ul { margin: 0; }
/* The kind chip leads each row, so the titles have to start at one x — a chip
   is as wide as the word inside it and "Project", "Pitch" and "Task" are three
   widths, which ragged the whole column. A fixed inline-block wide enough for
   the longest of the three, with the gap inside it rather than as a margin, so
   a row that wraps wraps its title and not its marker. */
.toc li .chip.kind-project, .toc li .chip.kind-pitch, .toc li .chip.kind-task {
  display: inline-block; min-width: 5.4rem; text-align: center;
  margin-right: .5rem; vertical-align: baseline;
}
/* Centred, and a container so the panes below can ask how wide the column
   actually is. It sat flush left with a full-height rule down its right edge,
   which on a wide screen is not a document — it is the left half of a two-pane
   layout whose right half failed to load. */
article.entity {
  width: var(--measure, 64rem); max-width: 100%; margin: 0 auto 3rem; position: relative;
  container-type: inline-size;
}
/* The facts beside the document rather than stacked on top of it: the reader
   comes for the shaping doc and glances at the facts, and a screen-and-a-half of
   metadata before the first sentence is the wrong way round. A container query
   and not a media query, because the width that decides this is the column's,
   which the reader sets with the grip — not the window's. */
.panes { display: grid; gap: 0 2.5rem; }
@container (min-width: 56rem) {
  /* 20rem and not less: these are the controls the entity is edited through, and
     a reviewers box too narrow to show three logins is a sidebar that looks
     tidier than the page it replaced and is worse to use. */
  .panes { grid-template-columns: minmax(0, 1fr) 20rem; align-items: start; }
  .panes > .main { grid-column: 1; grid-row: 1; }
  .panes > .facts { grid-column: 2; grid-row: 1; border-left: 1px solid var(--line);
                    padding-left: 1.5rem; }
  /* Half a sidebar is not two columns. Stacked, each fact is a caption over its
     value and reads down the edge of the page. */
  .panes > .facts dl { grid-template-columns: minmax(0, 1fr); gap: 0; }
  .panes > .facts dt { padding-top: .7rem; }
  .panes > .facts dt:first-child { padding-top: 0; }
}
/* A handle, not a border. It was a full-height 2px rule in --line, which is
   exactly how a page draws the edge of a pane; this is a short grip that says
   what it is when you reach for it. */
#grip {
  position: fixed; top: 0; bottom: 0; width: 10px; cursor: col-resize; z-index: 30;
}
#grip::before {
  content: ""; position: absolute; left: 3px; right: 3px; top: 50%; height: 48px;
  transform: translateY(-50%); border-radius: 2px; background: var(--line-strong);
  opacity: .35; transition: opacity .15s, background .15s;
}
#grip:hover::before, #grip.dragging::before { opacity: 1; background: var(--accent); }
article.entity h1 { font-size: 1.5rem; margin: .2rem 0; }
.meta { color: var(--muted); margin-top: 0; display: flex; flex-wrap: wrap;
        gap: .4rem; align-items: baseline; }
.meta code { font-family: var(--font-mono); font-size: 12px; }
/* The line above the title. It carries the one fact that has to be read before
   the name — on the detail page the kind, on the create form the picker that
   decides it — and it is tucked tight against the heading so the two read as one
   header rather than as a paragraph with a heading under it. */
.eyebrow { margin: 0 0 .15rem; color: var(--muted); }
.back { margin: 0 0 .5rem; font-size: 12px; }
/* `.editbar` is the shell's. It was written here, and the table — which wears the
   class on the row holding its only create action — does not load this
   stylesheet. */

dl { display: grid; grid-template-columns: 11rem minmax(0, 1fr); gap: .45rem 1rem; margin: 1rem 0; }
dt { color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .04em;
     padding-top: .35rem; }
dd { margin: 0; }
dt.derived, dd.derived { font-style: italic; }
/* Still italic, because it is still computed and typing over it would change
   nothing. Coloured, because it is the one computed line that is a problem. */
.overrun { color: var(--sev-warn); font-weight: 600; }
/* The same sentence when the tasks still fit: said, but not shouted. A number
   that only appears when something is wrong is a number people learn to fear
   rather than to read. */
.quiet { color: var(--muted); }
/* The marks belong to the form, so they are not on the page when there is no
   form on it — in read mode a row saying REQUIRED beside a filled-in value is
   an instruction with nothing to do. */
article.entity:not(.editing) .req { display: none; }
.problems { color: var(--warn); padding-left: 1.1rem; }
/* Not a problem, and it must not read as one: a note about the shaping document
   sits at the weight of the muted text around it, below anything the validator
   actually refused. */
.hints { color: var(--muted); padding-left: 1.1rem; font-size: 13px; }
/* The tasks a pitch is made of. Its own block above the document, because
   "where has this got to" is the question a pitch page is opened for and the
   answer was a checklist somewhere in the middle of the prose. */
.progress { border-top: 1px solid var(--line); padding-top: .6rem; margin-bottom: 1rem; }
.progress h2 { font-size: 1rem; margin: 0 0 .4rem; display: flex; align-items: center;
               gap: .5rem; }
.progress .tally { color: var(--muted); font-weight: 400; font-size: 12px; }
.progress ul { list-style: none; margin: 0; padding: 0; }
.progress li { display: flex; align-items: baseline; gap: .4rem; padding: .15rem 0;
               font-size: 13px; }
.progress li.ticked a { color: var(--muted); text-decoration: line-through; }
.progress .box { color: var(--muted); }

/* The two modes of the same rows. Controls are hidden until the article is
   editing, and the values they replace are hidden once it is. */
.field { display: none; }
.entity.editing .field { display: block; }
.entity.editing .field[hidden] { display: none; }
/* Where the other people in the room are. One band per person on the line their
   caret is in, translucent so the text keeps its own contrast, with the login on
   the right — a colour on its own is a colour a reader has to be told the
   meaning of, and the two channels together need no legend.
   `pointer-events: none` throughout: the thing under this is the box being typed
   in, and a layer that takes a click is a click that does not reach it. */
.bodywrap { position: relative; }
.seats { position: absolute; inset: 0; overflow: hidden; pointer-events: none;
         border-radius: 3px; }
.seat { position: absolute; left: 0; right: 0; }
.seatname { position: absolute; right: .25rem; top: 0;
            font-size: 10px; line-height: 1.4; padding: 0 .3rem; border-radius: 3px;
            color: var(--bg); font-family: var(--font-sans); }
/* Off the page and measured, never seen. It carries the textarea's own metrics —
   a mirror in a fallback face measures the fallback's line height, and every band
   then lands on the wrong row on the one machine whose webfont has not arrived. */
.ghost { position: absolute; visibility: hidden; top: -9999px; left: -9999px;
         white-space: pre-wrap; word-break: break-word; }
.bodybar { display: none; gap: .6rem; align-items: baseline; margin: 1rem 0 .3rem; }
/* The second row sits under the first rather than a paragraph's worth away: they
   are two halves of one bar, and the box they belong to is below both. */
.bodybar.markbar { margin-top: .25rem; }
.entity.editing .bodybar { display: flex; }
/* Who else is typing in this document, first in the bar because it is the one
   thing here that changes what you are about to do. `:empty` and not a `hidden`
   attribute somebody has to remember to set: the list is written with
   `textContent`, an empty string is the honest spelling of "nobody else", and a
   flex gap around an empty span is .6rem of nothing between two controls. */
.together { color: var(--accent); font-weight: 600; }
.together:empty { display: none; }
.editing-only { display: none; }
.entity.editing .editing-only { display: block; }
.entity.editing .read { display: none; }
.entity.editing dd .field[type=checkbox] { display: inline-block; }
label { display: block; }
/* Except in a fact list, where the label is one word in a line that also carries
   the REQUIRED mark. Block, the mark dropped onto a line of its own beside every
   gated field — an instruction shouting from its own row. */
dt > label { display: inline; }
/* The kind picker sits in the meta line, so it is a word in a sentence rather
   than a block that pushes the rest of the sentence onto its own row. */
.kindpick { display: inline; }
.kindpick select { font: inherit; }
/* In the bodybar beside the preview button, at the weight of the hints around
   it: a template is an offer, not a step. */
.tplpick { display: inline; color: var(--muted); font-size: 12px; }
.tplpick select { font: inherit; }
input.field, select.field, textarea.field {
  width: 100%; box-sizing: border-box; font: inherit; padding: .25rem .4rem;
  border: 1px solid var(--line-strong); border-radius: 3px;
  background: var(--surface); color: inherit;
}
input.title-field { font-size: 1.4rem; font-weight: 600; margin-bottom: .6rem; }
textarea.body-field {
  min-height: 60vh; font-family: var(--font-mono);
  font-size: 13px; line-height: 1.55; resize: vertical;
}
.doc { border-top: 1px solid var(--line); padding-top: 1rem; }
.doc h2 { font-size: 1rem; margin: 1.2rem 0 .3rem; }
.doc code { background: var(--surface-2); padding: 0 .25em; }
/* Where a promoted record says where it came from. It is the first thing in the
   document and it is not part of the problem statement, so it is set apart
   rather than left as an indented paragraph that reads like one. Here as well as
   in `_RECORD_STYLE`: this is the page those lines are mostly read on, and a
   rule in the other file is a rule this page never loads. The two are the same
   declaration on the same selector, so there is no cascade to resolve — no page
   loads both. */
.doc blockquote { margin: 0 0 1rem; padding-left: .8rem; color: var(--muted);
                  border-left: 2px solid var(--line-strong); }
/* `#conflict` is the shell's. It was written here, and the table draws the same
   box — `#row-conflict` — without loading this stylesheet, so the same report
   was a bordered block on one page and unstyled text on the other. */
/* The way out of the plan, at the far end of the record and not in the sticky
   bar. It is deliberately quiet until it is asked: an outline button in the
   danger colour, not a filled red block, because a filled red block at the foot
   of every record is a page that looks like it is warning you about something
   when nothing is wrong. */
.dangerbar { margin: 2.5rem 0 0; padding-top: .75rem;
             border-top: 1px solid var(--line); }
.dangerbar button { font: inherit; font-size: 13px; padding: .25rem .8rem;
        border-radius: 2px; border: 1px solid var(--line-strong);
        background: var(--surface); color: var(--muted); cursor: pointer; }
.dangerbar button.delete:hover, .dangerbar button.really {
        border-color: var(--danger); color: var(--danger); }
.dangerbar .confirming { display: flex; flex-direction: column;
        align-items: flex-start; gap: .5rem; max-width: 46ch;
        padding: .6rem .75rem; border: 1px solid var(--danger);
        border-radius: 3px; background: var(--surface); }
.dangerbar .confirming[hidden] { display: none; }
.dangerbar .asking { margin: 0; font-size: 13px; }
.dangerbar .acts { display: flex; gap: .4rem; }
/* What else this takes with it. The loud one is the deletion of other records —
   that is the sentence somebody has to read before pressing, so it is the danger
   colour and it is bold. The dependency line is quieter on purpose: nothing is
   destroyed there, a field is edited, and drawing the two the same way would
   teach people to skim both. */
.dangerbar .reach { margin: 0; font-size: 13px; font-weight: 600;
                    color: var(--danger); }
.dangerbar .reach.mild { font-weight: 400; color: var(--fg); }
.dangerbar .reach .ids { font-family: var(--font-mono); font-size: 12px;
                         font-weight: 400; }

/* The server's reason, where the question was asked. A refusal that names three
   tasks is the useful half of this feature and it must not go to the console. */
.dangerbar .why { margin: 0; font-size: 12px; color: var(--danger); }
.dangerbar .why[hidden] { display: none; }

"""


# What a person owns, in the order they think about it. Everything not named here
# is either derived (start, end, blocks, any rollup) or authoritative (id), and
# neither belongs in a form: a derived value typed by hand is a lie the next
# reschedule contradicts, and an edited id orphans the file from every reference.
EDITABLE: dict[str, str] = {
    "title": "text",
    "status": "status",
    "owner": "text",
    "assignees": "list",
    "reviewers": "list",
    "review_waived": "bool",
    "assigned_on": "date",
    "priority": "priority",
    "cycle": "number",
    "parent": "text",
    "depends_on": "list",
    "tags": "list",
    "prs": "list",
    "person_weeks": "number",
    "shaped_by": "list",
}
STATUSES = ("shaping", "ready", "in_progress", "done", "shelved")
# Highest first, which is the order a picker is read in and the order the table
# sorts by. Five rungs, because three left the team writing `High+` in the margin.
PRIORITIES = ("very_high", "high", "medium", "low", "very_low")

# The redundant channel. On the graph and the timeline a fill is the only thing
# telling two shapes apart, and a luminance ladder makes five fills *separable*
# without making any one of them *nameable* — you can see that a bar is darker
# than its neighbour and still not know which state that is. So every status also
# owns a mark that is not colour: drawn at a bar's left edge, prefixed to a node's
# title, and shown inside the legend swatch beside the word it stands for.
#
# All five are in the vendored face's latin subset, so a page that falls back to
# no webfont at all still draws five different shapes rather than five boxes.
# Chosen to be different SHAPES, not different weights of one shape: a small dot
# and a large dot are two glyphs a reader has to compare, which is the failure
# the ladder was already meant to fix.
# Five shapes, one per status, and the only place any of them is written.
#
# Text glyphs and not emoji, and that is a constraint rather than a taste: an
# emoji is drawn by the platform's colour font, so it ignores `currentColor` and
# arrives at a different weight on every machine — and these sit inside a 14px
# timeline bar in the bar's own ink. A chequered flag exists only as one (U+1F3C1),
# which is why `ready` is an arrow instead.
STATUS_GLYPH = {
    "shaping": "?",         # still a question
    "ready": "↑",           # queued at the gate, pointing at the off
    "in_progress": "»",     # under way
    "done": "✓",            # finished
    "shelved": "✕",         # struck out, not failed
}
# A person's own mark, drawn beside their name on the People page and nowhere
# else. Inline SVG rather than emoji — which is the same answer STATUS_GLYPH
# above gives, reached by a different argument, because the argument that
# decided the status marks does not apply here.
#
# A status mark is text because it sits inside a 14px timeline bar and has to
# arrive in the bar's own ink: an emoji is drawn by the platform's colour font,
# so it ignores `currentColor` and lands at a different weight on every machine.
# An avatar wants none of that. It is 20px of its own, it is allowed its own
# colour, and being recognisable matters more than matching the ink — so on the
# trade-off that settled the status marks, emoji would win here.
#
# What rules them out is the other promise this codebase makes. Everything a
# page needs is inside the page: the typeface is a `data:` URI, every library is
# inlined, and `test_no_page_reaches_the_network` is what keeps it so — because
# `openproj render` writes a plan that has to be readable off a memory stick
# with no network and nothing installed. An emoji is the one mark that is not in
# the file. It is resolved by whatever colour-emoji font the reader happens to
# have, which on an ordinary Linux workstation is none at all, and a login whose
# icon is a tofu box is worse than a login with no icon: it looks like the tool
# is broken rather than like nobody has chosen. The same file opened on three
# machines would draw three different foxes, and the one thing on this page that
# is a person's own choice is the last thing that should be a property of their
# neighbour's font cache.
#
# So: paths, in the page, in `currentColor`. About 200 bytes each, they follow
# the theme, they scale, and the drawing in the file IS the drawing on screen.
# Stroked outlines at the interface's own weight rather than filled silhouettes,
# and every feature is a whole shape — a head, two ears, two eyes — because at
# 20px a whisker is not a line, it is a grey smudge.
#
# Twenty-four of them, which is a team's worth with room to choose rather than
# one each. The count is not the constraint and never was: being told apart at
# 20px is, and that is what decides how many there can be. Every candidate was
# drawn, rendered at 20px beside the whole set, and looked at, because a shape
# that reads in the source is not evidence about pixels. Seven did not survive
# that and are deliberately absent — a WHALE and a SNAKE, which at that size are
# the fish and the wave this set already has; a SNAIL and a PENGUIN, whose second
# outline inside the first closed into a blot; a BEE, whose stripes did the same;
# a RAINBOW, three concentric arcs that resolve into one thick arc; and a DOG,
# which was a third round face after the cat and the bear. They are named here
# because a shape is rejected for what it collides with rather than for being
# badly drawn, and the next person to add one needs the collisions more than they
# need the survivors.
#
# Three groups, in the order the picker is read: the sky, then the world, then
# the creatures — and inside the creatures, the ones that walk before the ones
# that swim. A list ordered by nothing is a list a reader has to search rather
# than scan. What is stored is the NAME, so these can be redrawn, and this order
# rearranged, without touching anybody's choice — see `model.Person`.
_ICON_ART = {
    "sun": (
        '<circle cx="12" cy="12" r="4.3"/>'
        '<path d="M12 2.4v2.6M12 19v2.6M2.4 12h2.6M19 12h2.6'
        'M5.3 5.3 7.2 7.2M16.8 16.8l1.9 1.9M18.7 5.3 16.8 7.2M7.2 16.8l-1.9 1.9"/>'
    ),
    "moon": '<path d="M20 13.4A8.8 8.8 0 1 1 10.6 4 7 7 0 0 0 20 13.4Z"/>',
    "star": (
        '<path d="M12 3.3 14.2 9.2 20.6 9.5 15.6 13.5 17.3 19.6 12 16.1'
        ' 6.7 19.6 8.4 13.5 3.4 9.5 9.8 9.2Z"/>'
    ),
    "cloud": (
        '<path d="M7.4 18.6h9.8a4.2 4.2 0 0 0 .4-8 5.7 5.7 0 0 0-10.8-1.3'
        'a4.8 4.8 0 0 0 .6 9.3Z"/>'
    ),
    "bolt": '<path d="M13.8 2.6 5.8 13.8h4.8l-.8 7.6 8.4-11.4h-5Z"/>',
    # Six spokes and a chevron at each tip, and nothing along them. The version
    # with branches half way out was a blot at 20px: eighteen strokes inside 20
    # pixels is a grey disc. The sun is the shape it has to stay clear of and
    # does — the sun is a solid centre with detached rays, this is one open
    # asterisk with a hole in the middle.
    "snowflake": (
        '<path d="M12 2.4v19.2M3.7 7.2l16.6 9.6M20.3 7.2 3.7 16.8"/>'
        '<path d="M8.8 4.8 12 8l3.2-3.2M8.8 19.2 12 16l3.2 3.2"/>'
    ),
    # Upright and unmarked, which is the whole of what separates it from the leaf
    # below: that one is tilted and carries a midrib, and a drop that leaned would
    # be the same lens.
    "drop": (
        '<path d="M12 2.6c4.4 5.6 6.6 8.6 6.6 11.2a6.6 6.6 0 0 1-13.2 0'
        'c0-2.6 2.2-5.6 6.6-11.2Z"/>'
    ),
    # The ring passes behind the body as two arcs that stop at its edge, rather
    # than as one ellipse crossing it. An ellipse drawn over the disc lays two
    # chords across the planet, and at 20px a circle with a line through it is a
    # circle with a line through it.
    "planet": (
        '<circle cx="12" cy="12" r="5.6"/>'
        '<path d="M7.1 14.7c-3.5 1.6-6.2 2-6.8.7-.6-1.3 1.2-3.5 4.4-5.5'
        'M16.9 9.3c3.5-1.6 6.2-2 6.8-.7.6 1.3-1.2 3.5-4.4 5.5"/>'
    ),
    "mountain": '<path d="M2.6 19.4 9.4 7.6l4 6.9 2.6-4.3 5.4 9.2Z"/>',
    # Tilted, and fat enough to have two sides. Drawn upright and narrow it was a
    # sliver with a line down it — at 20px indistinguishable from an eye, and the
    # midrib was the whole of what made it a leaf rather than a lens.
    "leaf": (
        '<path d="M4.6 19.4a11.5 11.5 0 0 1 14.8-14.8 11.5 11.5 0 0 1-14.8 14.8Z"/>'
        '<path d="M2.8 21.2 18 6"/>'
    ),
    # The trunk is the whole of what tells this from the mountain at 20px, so it
    # is drawn long enough to see. A bare triangle is a peak, and a triangle with
    # a two-pixel stub under it is a peak somebody smudged.
    "tree": '<path d="M12 2.8 4.4 16.4h15.2Z"/><path d="M12 16.4v4.6"/>',
    # A tulip on a stem, not a rosette. Five petals round a centre is the same
    # radial blob as the sun at this size — and the sun has the better claim to
    # it — so the flower is the shape a flower has from the side instead.
    "flower": (
        '<path d="M6.2 8.2c0 4.2 2.6 7 5.8 7s5.8-2.8 5.8-7c0 0-2.2 1.8-2.9 1.8'
        'S12 5.8 12 5.8s-2.2 4.2-2.9 4.2S6.2 8.2 6.2 8.2Z"/>'
        '<path d="M12 15.2v6.2"/>'
        '<path d="M12 18.4c-1.8-2.2-4-2.4-5.2-1.6-.2 2.4 2.6 3.6 5.2 1.6Z"/>'
    ),
    # Two lines and not three: a third crest closes the gaps between them into a
    # hatched band, and two is already enough to say water rather than a squiggle.
    "wave": (
        '<path d="M2.4 9.8q2.4-3.2 4.8 0t4.8 0 4.8 0 4.8 0"/>'
        '<path d="M2.4 16.2q2.4-3.2 4.8 0t4.8 0 4.8 0 4.8 0"/>'
    ),
    "cat": (
        # One outline for the head and both ears, so no chord is drawn across the
        # face: the arc stops where each ear starts and picks up where it ends.
        '<path d="M8.9 8.8A6.2 6.2 0 0 1 15.1 8.8L19.4 4.8 17.8 12.1'
        'A6.2 6.2 0 1 1 6.2 12.1L4.6 4.8Z"/>'
        '<circle cx="9.8" cy="14" r=".95" fill="currentColor" stroke="none"/>'
        '<circle cx="14.2" cy="14" r=".95" fill="currentColor" stroke="none"/>'
    ),
    "fox": (
        '<path d="M12 20.6 4.4 12.4 3.4 4.6 8.6 7.4h6.8l5.2-2.8-1 7.8Z"/>'
        '<circle cx="8.8" cy="11.9" r=".95" fill="currentColor" stroke="none"/>'
        '<circle cx="15.2" cy="11.9" r=".95" fill="currentColor" stroke="none"/>'
    ),
    "owl": (
        '<path d="M12 3.6c-4.2 0-7 3.2-7 7.6 0 5.4 3.2 9.2 7 9.2s7-3.8 7-9.2'
        'c0-4.4-2.8-7.6-7-7.6Z"/>'
        '<path d="M8.8 4.8 7.2 2.4M15.2 4.8 16.8 2.4"/>'
        '<circle cx="9.5" cy="10.6" r="2.1"/><circle cx="14.5" cy="10.6" r="2.1"/>'
        '<circle cx="9.5" cy="10.6" r=".8" fill="currentColor" stroke="none"/>'
        '<circle cx="14.5" cy="10.6" r=".8" fill="currentColor" stroke="none"/>'
        '<path d="M12 12.4 10.9 14.3 13.1 14.3Z"/>'
    ),
    "rabbit": (
        # The ears are open at the root rather than closed shapes: a closed ear
        # draws its base across the top of the head, and two lines through the
        # face is what a rabbit at 20px turns into.
        '<circle cx="12" cy="16.2" r="4.9"/>'
        '<path d="M9.3 12.6Q6 6.4 8.4 2.8 11.6 5.6 11.4 11.5"/>'
        '<path d="M14.7 12.6Q18 6.4 15.6 2.8 12.4 5.6 12.6 11.5"/>'
        '<circle cx="10.2" cy="15.7" r=".85" fill="currentColor" stroke="none"/>'
        '<circle cx="13.8" cy="15.7" r=".85" fill="currentColor" stroke="none"/>'
    ),
    # Round ears standing outside the head, and a snout inside it. The cat's ears
    # are points on the head's own outline; these break it, and the snout is the
    # second difference — with neither of them this is the cat at 20px, which is
    # what the first attempt was.
    "bear": (
        '<circle cx="6.1" cy="7.5" r="2.7"/><circle cx="17.9" cy="7.5" r="2.7"/>'
        '<circle cx="12" cy="13.6" r="6.5"/>'
        '<circle cx="9.6" cy="12.2" r=".9" fill="currentColor" stroke="none"/>'
        '<circle cx="14.4" cy="12.2" r=".9" fill="currentColor" stroke="none"/>'
        '<circle cx="12" cy="16.4" r="1.9"/>'
    ),
    # Head and body are two circles that touch rather than one silhouette. Drawn
    # as a single outline a small bird is an egg with a beak on it; the notch
    # where the two circles meet is the neck, and it is the only thing at this
    # size that says which end is the front.
    "bird": (
        '<circle cx="14.8" cy="8.2" r="3.4"/>'
        '<path d="M18 7.2 21.8 8.4 18 9.8Z"/>'
        '<circle cx="15.2" cy="7.4" r=".85" fill="currentColor" stroke="none"/>'
        '<circle cx="10.4" cy="15.6" r="5.6"/>'
        '<path d="M5.8 19 1.8 21.8 2.4 17Z"/>'
    ),
    # One closed path per side, each carrying both of that side's wings, so the
    # body is the seam where the two meet rather than a third shape drawn down
    # the middle. Four separate wings put four strokes through the centre, and at
    # 20px the middle filled in.
    "butterfly": (
        '<path d="M12 8.2C8.4 3.6 2.6 4.2 2.6 8.6c0 2.3 1.9 3.5 4.4 3.5'
        '-2.5.6-4.4 2.1-4.4 4.4 0 3.7 5.6 4.4 9.4-.3Z"/>'
        '<path d="M12 8.2c3.6-4.6 9.4-4 9.4.4 0 2.3-1.9 3.5-4.4 3.5'
        '2.5.6 4.4 2.1 4.4 4.4 0 3.7-5.6 4.4-9.4-.3Z"/>'
        '<path d="M12 8.2 9.8 4.2M12 8.2l2.2-4"/>'
    ),
    # The eyes sit on top of the head and break its outline, which is the whole
    # of the difference from the owl — whose eyes are two rings inside a body
    # that closes over them.
    "frog": (
        '<circle cx="8.4" cy="7.6" r="2.6"/><circle cx="15.6" cy="7.6" r="2.6"/>'
        '<circle cx="8.4" cy="7.6" r=".9" fill="currentColor" stroke="none"/>'
        '<circle cx="15.6" cy="7.6" r=".9" fill="currentColor" stroke="none"/>'
        '<path d="M4.4 13.8c0-3 3.4-5.2 7.6-5.2s7.6 2.2 7.6 5.2c0 3.4-3.4 6.2-7.6 6.2'
        's-7.6-2.8-7.6-6.2Z"/>'
        '<path d="M8.6 15.6q3.4 2.4 6.8 0"/>'
    ),
    "fish": (
        '<path d="M4.4 12a9 9 0 0 1 13.6 0 9 9 0 0 1-13.6 0Z"/>'
        '<path d="M18 12 22.4 8.6 22.4 15.4Z"/>'
        '<circle cx="7.9" cy="11.1" r=".9" fill="currentColor" stroke="none"/>'
    ),
    # Claws and eye stalks, both crossing the body's outline. A crab drawn as a
    # shell with legs under it is a face at 20px — the things that stick out are
    # what keep it out of the cat, fox, bear, frog corner of this set.
    "crab": (
        '<path d="M4.8 14.6a7.2 7.2 0 0 1 14.4 0 7.2 7.2 0 0 1-14.4 0Z"/>'
        '<path d="M9.4 9.2V7.2M14.6 9.2V7.2"/>'
        '<circle cx="9.4" cy="6" r="1" fill="currentColor" stroke="none"/>'
        '<circle cx="14.6" cy="6" r="1" fill="currentColor" stroke="none"/>'
        '<path d="M4.9 12.4 2 10.4a2 2 0 1 1 2.8-1.6"/>'
        '<path d="M19.1 12.4 22 10.4a2 2 0 1 0-2.8-1.6"/>'
        '<path d="M6.6 18.6 4.4 21M17.4 18.6l2.2 2.4"/>'
    ),
    "turtle": (
        '<path d="M4.6 15.6a7.4 7.4 0 0 1 14.8 0Z"/>'
        '<circle cx="21" cy="13.6" r="1.7"/>'
        '<path d="M7.6 15.6v2.4M12 15.6v2.6M16.4 15.6v2.4M4.6 15.2 2.4 16.4"/>'
    ),
    # A head in profile, because a whole unicorn at 20px is a horse-shaped smudge
    # with a spike on it. The horn is the entire signal — it is drawn as its own
    # shape rising clear of the skull rather than as a bump on the outline, since
    # a point that shares an edge with the head reads as an ear at this size, and
    # the ear beside it is what it would then be confused with.
    "unicorn": (
        '<path d="M3.4 16.6C3.4 12.2 6.8 8.8 11 8.5L13.2 8.3'
        'C14.6 12.4 15.2 16.7 15.4 21.2H10.2C9.8 18.4 7.2 16.8 3.4 16.6Z"/>'
        '<path d="M11.4 8.1 10.4 1.8 13.4 7.7"/>'
        '<path d="M14.2 8.2 15.4 6.3 16.1 8.7"/>'
        '<path d="M16.6 10.2Q19.6 12.6 18 15.1Q20.3 17.8 18.8 21.2"/>'
        '<circle cx="9.6" cy="12.9" r=".85" fill="currentColor" stroke="none"/>'
    ),
}

# The vocabulary, and the only thing that decides it. `web.py` refuses an icon
# this map does not hold, the picker offers exactly these, and the stored value
# is the key — so adding one is a line here and nothing anywhere else.
ICONS = tuple(_ICON_ART)

# 24 units square and drawn in the current ink, so an icon is the size of the
# text beside it and takes the theme with it. `aria-hidden`, because the name it
# sits next to is the person: a screen reader announcing "fox, jcanton" would be
# reading out a decoration as though it were an identity.
_ICON_SVG = (
    '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
    'stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" '
    'aria-hidden="true" focusable="false">{}</svg>'
)


def icon_svg(name: str) -> Markup:
    """The drawing for a stored icon name, or nothing at all.

    Nothing, and not a placeholder, for a name this version does not draw: an
    icon is a decoration beside a login that is already on screen, so a stored
    `dragon` costs the drawing and nothing else. That is the same bargain
    `_status_class` makes with a status nobody recognises, one rung down — there
    is no rule to fold this onto, because there is nothing underneath a mark.
    """
    art = _ICON_ART.get(name)
    return Markup(_ICON_SVG).format(Markup(art)) if art else Markup("")


# The two marks the table's draft row is created and cancelled with, in the same
# frame as the icons above and for the same reason, one page over.
#
# Drawn and not typed. `✓` (U+2713) and `✕` (U+2715) are not in the vendored
# latin subset — 230 codepoints, and neither is among them — so a page that used
# the characters would be asking the reader's machine for them, which is the one
# thing every other mark on this site is arranged not to do. On a workstation
# without a font that has them, the two controls that create and abandon a record
# are two tofu boxes. `.rowgrip` settles the identical question the identical way
# and says so in the stylesheet: `⠿` is not in the subset either, so the grip is
# two drawn rules instead of a character.
#
# They are not entries in `_ICON_ART`. That map IS the icon vocabulary — `ICONS`
# is `tuple(_ICON_ART)`, the picker offers exactly its keys and `web.py` accepts
# exactly its keys — so a `check` in it is a check somebody can store as their
# face. These are furniture on one control; the frame is what they share.
#
# `aria-hidden` comes with the frame, which is what these need: each sits inside
# a button that carries the name, and a drawing announced beside it would be the
# same control said twice.
DRAFT_MARKS = {
    "create": _ICON_SVG.format('<path d="M5 12.6 9.7 17.3 19 6.9"/>'),
    "cancel": _ICON_SVG.format('<path d="M6.6 6.6 17.4 17.4M17.4 6.6 6.6 17.4"/>'),
}


# Fields only one kind has, so the create form can hide the rest.
# A project is a container and has no size of its own; `shaped_by` is asked of
# the kind that gets shaped. `person_weeks` is on both of the others, so it is
# not kind-only any more.
KIND_ONLY = {"shaped_by": "pitch"}
PREFIX = {"project": "proj", "pitch": "pitch", "task": "task"}
# The validator's own gate, asked rather than copied — and asked through the front
# door. This module used to import `model._status_problems` at import time and run
# the derivation itself, which put the shape of a problem tuple in the renderer's
# hands; the derivation lives with the rule now, and `test_the_gates_are_the_
# validator_s_own_and_not_a_second_copy` is what keeps it honest.
REQUIRED_AT = required_at()

# The reader's name for a field. `appetite_weeks` and `effort_weeks` were two
# storage fields holding one quantity, and calling it Effort here, Appetite on the
# detail page and weeks in the table made it look like three different numbers
# nobody could reconcile. They are one field now — `person_weeks`, named for the
# unit that D1 got wrong — and Appetite is still the word a reader gets, because
# it is the domain's and the team's own template's.
LABELS = {
    "title": "Title", "status": "Status", "owner": "Owner", "assignees": "Assignees",
    "reviewers": "Reviewers", "review_waived": "Review waived", "assigned_on": "Assigned on",
    "priority": "Priority", "cycle": "Cycle", "parent": "Parent", "depends_on": "Blocked by",
    "tags": "Tags", "prs": "PRs", "person_weeks": "Appetite (person-weeks)",
    "shaped_by": "Shaped by",
    # Not stored fields: a facet and a derived column. They are read by the same
    # people in the same control bar, so they take their words from here too.
    "kind": "Kind", "project": "Project", "size": "Appetite", "blocked_by": "Blockers",
    "progress": "Progress",
    "start": "Start", "end": "End", "id": "Id", "predicate": "Flags",
    # The people page's own facet. Which hat somebody is wearing is not stored on
    # an entity at all — it is which field their name is in — but it is read in
    # the same control bar as the rest, so it takes its word from the same map.
    "role": "Role",
}

# The reader's word for a value. `in_progress`, `missing_required_fields` and
# `overruns_cycle` are identifiers: they belong in a `value=`, a class and a
# `data-*` attribute, and nowhere a person reads. One map rather than one per
# page, because five pages inventing their own is how `in_progress` became
# "In progress", "in progress" and "in_progress" on the same screen.
#
# Statuses, priorities, kinds and predicates share it: their identifiers do not
# collide, and a caller rendering an option has no reason to know which family a
# value came from. Anything unknown comes back unchanged, so a value added to the
# model still renders — badly, but it renders.
HUMAN = {
    # statuses
    "shaping": "Shaping",
    "ready": "Ready",
    "in_progress": "In progress",
    "done": "Done",
    "shelved": "Shelved",
    # A note's two, and the third it is only ever given by what it became. They
    # are here rather than left to print as themselves for the reason the map
    # exists: five pages inventing their own capitalisation is how `in_progress`
    # came to be spelled three ways on one screen.
    "thinking": "Thinking",
    "dropped": "Dropped",
    "promoted": "Promoted",
    # priorities
    "very_high": "Very high",
    "high": "High",
    "medium": "Medium",
    "low": "Low",
    "very_low": "Very low",
    # kinds
    "project": "Project",
    "pitch": "Pitch",
    "task": "Task",
    # predicates, as COMPUTED_PREDICATES spells them. `missing_required_fields`
    # is not what it does — it matches any problem of any severity — so it says so.
    "blocked": "Blocked",
    "unblocked": "Not blocked",
    "overruns_cycle": "Overruns its cycle",
    "missing_required_fields": "Has a problem",
    "has_blocker": "Has a blocking problem",
    "review_waived": "Review waived",
    "past_cycle_build": "Still running past its cycle",
    "in_progress_without_prs": "In progress, nothing linked",
    "untracked": "No checklist",
    "for_later": "Has a for-later list",
    # roles, which the people page filters by. Already English, but a dropdown
    # reading "owner, Pitch, Ready" is three labelling conventions in one bar.
    "owner": "Owner",
    "assignee": "Assignee",
    "reviewer": "Reviewer",
    "shaper": "Shaper",
}


def _human(value: object) -> str:
    """The word a reader gets for an identifier the data model uses."""
    if value is None:
        return ""
    return HUMAN.get(str(value), str(value))


# Available to every template as both `human(x)` and `x|human`, so no page has to
# be handed the map, and as `label(field)` for a field name.
_ENV.globals["human"] = _human
_ENV.filters["human"] = _human
# The mark that says the same thing the colour says, for every legend and every
# shape that draws one. Unknown values get nothing rather than a box glyph.
_ENV.globals["glyph"] = lambda status: STATUS_GLYPH.get(str(status), "")
_ENV.globals["label"] = lambda field: LABELS.get(field, field)
# Every chip on every page names its rung through this, so the four templates
# that draw one cannot disagree with the two that build one in Python. They did:
# the detail page's meta line escaped the status into its class and the facts
# list two elements away did not, which is one page holding both answers.
_ENV.globals["status_class"] = _status_class
# Fields that name a person. They get a datalist of everyone already in the corpus,
# so a typo shows up as "not in the list" rather than as a reviewer who does not exist.
PEOPLE_FIELDS = ("owner", "assignees", "reviewers", "shaped_by")
# Which suggestion list each field draws from. A datalist only completes a whole
# value, so the comma-separated ones also get an "add" picker that appends a token
# — otherwise the suggestions are useless the moment there is more than one name.
SUGGESTS = {
    "owner": "people", "assignees": "people", "reviewers": "people", "shaped_by": "people",
    "parent": "entities", "depends_on": "entities", "tags": "tags", "prs": "prs",
    # A cycle number is a reference too. Typed from memory it is off by one as
    # often as it is right, and an entity bet into a cycle nobody has named is
    # weeks that never appear on anybody's capacity.
    "cycle": "cycles",
}


def _editable_for(entity: Entity, prefix: str = "field") -> list[dict]:
    """The fields this kind actually has, with the type a form must coerce back to.

    The prefix is what makes a control's id unique on the page it lands on: the
    static detail export holds every entity in one file, so `owner` alone would
    be the same id sixteen times over and every `<label for>` on the page would
    point at the first of them.
    """
    return [
        {
            "name": name,
            "id": f"{prefix}-{name}",
            "type": kind,
            "value": getattr(entity, name),
            "gates": REQUIRED_AT.get(name, ()),
            "list": SUGGESTS.get(name),
            "text": ", ".join(str(v) for v in getattr(entity, name))
            if kind == "list"
            else ("" if getattr(entity, name) is None else getattr(entity, name)),
        }
        for name, kind in EDITABLE.items()
        if name in type(entity).model_fields
    ]


def _links(ids: list[str], index: Index, links: Links = STATIC) -> Markup:
    """Ids as titles, linked. Every one of the three values in here is free text.

    A title arrives through `PATCH /api/entity`, which does not police it, and an
    id that fails its pattern is a reported problem and not a refusal — so both
    reach this line as whatever somebody typed. Built with an f-string, a title
    holding a `<script>` ran on the parent link of every child of that entity,
    on the page that then offers the reader a Save button. `Markup(...).format`
    escapes each value as it goes in, which is the only version of this that
    stays correct when a fourth value is added to it.
    """
    return Markup(", ").join(
        Markup('<a href="{}{}">{}</a>').format(
            links.entity, i, index.entities[i].title if i in index.entities else i
        )
        for i in ids
    )


def _fact_rows(index: Index, entity: Entity, links: Links) -> list[dict]:
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
    span = index.spans.get(entity.id)
    why = index.explanations.get(entity.id)
    rows = []
    # One mark for "there is nothing here", everywhere. Spelled-out words —
    # `nothing`, `none`, `no` — sit at the same weight as a real value and have
    # to be read before you know the row is empty; a dash is empty at a glance.
    empty = Markup('<span class="empty">—</span>')
    for field in _editable_for(entity, entity.id):
        name = field["name"]
        if name == "title":
            continue
        if name == "depends_on":
            display = _links(index.blocked_by[entity.id], index, links) or empty
        elif name == "parent":
            # By title and linked, the way blockers already read. An id is what
            # the field stores; it is not what anybody is looking for when they
            # ask what this belongs to.
            display = _links([entity.parent], index, links) if entity.parent else empty
        elif name == "prs":
            display = Markup(", ").join(_pr_link(ref) for ref in entity.prs) or empty
        elif name == "review_waived":
            display = Markup("waived") if entity.review_waived else empty
        elif name == "status":
            # The same chip the table, the people page and the bet table wear. A
            # status is the one field on this page every other view colours.
            # Through `_status_class`, so a status nobody has heard of gets the
            # ready ladder rung rather than putting its own text in a class
            # attribute: an unknown status is a *reported problem*, not a
            # refusal, so `status` holds whatever a hand-edited file holds.
            display = Markup('<span class="chip {}">{}</span>').format(
                _status_class(entity.status), _human(entity.status)
            )
        elif name == "priority":
            display = escape(_human(entity.priority))
        elif name == _SIZE_FIELD_NAME and _tasks_add_up_to(index, entity) is not None:
            # The bet, and what its tasks propose to put inside it. Two numbers on
            # one line because they are one question: an appetite read on its own
            # says nothing about whether the work still fits, and the answer was
            # only ever visible by adding the tasks up by hand.
            #
            # Warned about only against a bet somebody actually made. A pitch with
            # no appetite yet is not over it, and `_rollup_problems` says nothing
            # about that case either — a page that shouts where the validator is
            # silent teaches people that one of the two is lying.
            total = _tasks_add_up_to(index, entity)
            stated = field["text"]
            over = bool(stated) and total > float(stated)
            display = Markup('{} · <span class="{}">{} in tasks</span>').format(
                stated or "—", "overrun" if over else "quiet", f"{total:g}"
            )
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
                "for": field["id"],
                "display": display,
                "control": _control_html(field),
                "gates": field["gates"],
                "derived": False,
                # "Review waived: no" is a line that says nothing. The row still
                # exists while editing, because turning the waiver on is the whole
                # point of having it; it just does not clutter the read view.
                "editing_only": name == "review_waived" and not entity.review_waived,
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
        ).format(entity.cycle, f"{span.overruns_cycle_weeks:.1f}")
        if span and span.overruns_cycle_weeks
        else Markup("")
    )
    rows.append(
        {
            "label": "Scheduled",
            "for": "",
            "display": (
                Markup("{} → {}{}").format(span.start, span.end, overrun) if span else empty
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
                # An explanation names the person who is busy and the entity that
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
    rows.append(
        {
            "label": "Blocks",
            "for": "",
            "display": _links(index.blocks[entity.id], index, links) or empty,
            "control": "",
            "gates": (),
            "derived": True,
            "editing_only": False,
        }
    )
    # Derived, never written: from the tasks under it where there are any, and
    # from the body's own checklist where there are none. The full list is a panel
    # of its own beside the document (`_progress_view`); this line is the number,
    # in the column of facts where every other number about this entity is.
    counted = index.progress.get(entity.id)
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
    later = sections(entity.body).get(_FOR_LATER_HEADING, "")
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


_SIZE_FIELD_NAME = "person_weeks"


def _tasks_add_up_to(index: Index, entity: Entity) -> float | None:
    """What the tasks under this one propose to spend, or None if it has none.

    The same number `_rollup_problems` compares against the appetite, read from
    the same place, so the sentence on the page and the sentence in `check`
    cannot disagree about the arithmetic.
    """
    counted = index.progress.get(entity.id)
    return counted.total if counted is not None and counted.unit == "weeks" else None


def _progress_view(index: Index, entity: Entity) -> dict | None:
    """The tasks a pitch is made of, and how much of it they have finished.

    Only where there are tasks. A leaf's checklist is already in its body, drawn
    where its author put it, and lifting it into a panel above would print the
    same list on the page twice — the fact row carries its count instead.

    Every line is derived from the task it names: the tick is that task's
    `status`, so closing one from the table moves this the next time the index is
    built, and there is no checkbox here for the two to disagree about.
    """
    counted = index.progress.get(entity.id)
    if counted is None or not counted.of:
        return None
    config = Config(default_task_effort=index.default_task_effort)
    items = []
    for child_id in counted.of:
        child = index.entities[child_id]
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
        # that draws an entity.
        "tasks": items,
    }


_FOR_LATER_HEADING = "for later"
# The two sections the team's own pitch template asks for and the corpus most
# often leaves empty. Both spellings of each, because both are in use.
_WANTED_SECTIONS = {
    "Rabbit holes": ("rabbit holes", "rabbit hole"),
    "No-gos": ("no-gos", "no-go", "no gos", "no go"),
}


def _shaping_hints(entity: Entity, has_tasks: bool = False) -> list[str]:
    """Sections the pitch template asks for that this body does not have.

    A printed note on one page, deliberately not a `Problem`: it never reaches
    `openproj check`, never fails CI and never blocks a save. The body is prose,
    and a validator with an opinion about prose is a validator people route
    around. This is here to be read by the person already editing the pitch.
    """
    # Only while it is a live bet. An idea nobody has bet on owes nothing yet, and
    # nagging finished work about a section it will never gain is how a note stops
    # being read at all.
    if entity.kind != "pitch" or entity.status not in ("ready", "in_progress"):
        return []
    written = sections(entity.body)
    notes = [
        f"No {label} section. The pitch template asks for one — it is what keeps "
        f"the appetite honest."
        for label, spellings in _WANTED_SECTIONS.items()
        if not any(written.get(spelling) for spelling in spellings)
    ]
    # Said rather than silently resolved. A pitch with tasks is measured by them,
    # so a checklist in its body counts for nothing — and a list somebody is
    # ticking that moves no number on the page is worse than no list at all.
    if has_tasks and checklist(entity.body)[1]:
        notes.append(
            "This pitch keeps a checklist in its body and has tasks under it. The "
            "tasks are what its progress is counted from; the checklist is not."
        )
    return notes


def _detail_rows(index: Index, links: Links = STATIC) -> list[dict]:
    """One entry per entity: what the page's own furniture needs, and nothing else.

    Every fact this page prints comes from `_fact_rows`, which builds each line
    with its value AND its control so the read view and the edit view cannot show
    different things. This carried a second, read-only copy of thirteen of those
    facts — a size, a span, an overrun, a why, blockers, blocks, PRs, tags — that
    reached no template and no test after `_fact_rows` superseded them. A field
    formatted in two places is a field that will be formatted two ways.
    """
    return [
        {
            "id": entity_id,
            "title": entity.title,
            "kind": entity.kind,
            "status": entity.status,
            # `parent` decides whether the meta line says "in" at all; the link is
            # what it says. Both, because an id that is not in this plan still
            # names a parent and `_links` renders it as itself.
            "parent": entity.parent,
            "parent_link": _links([entity.parent], index, links) if entity.parent else "",
            "problems": [p.message for p in index.problems if p.entity_id == entity_id],
            # Not problems: notes about the shaping document, printed here and
            # nowhere else. See `_shaping_hints`.
            "hints": _shaping_hints(entity, bool(index.children.get(entity_id))),
            # The tasks this pitch is made of, ticked from their own statuses.
            "progress": _progress_view(index, entity),
            "body": _body_html(entity, links),
        }
        for entity_id, entity in sorted(index.entities.items())
    ]


# Betting table to review meeting for a plan with nothing to copy from. Four
# weeks is the team's cadence; every cycle written after the first one carries
# its predecessor's length instead.
_DEFAULT_CYCLE_DAYS = 28

KINDS = ("project", "pitch", "task")
# The model behind each of them, once. This was a dict literal inside `_new_rows`
# and is now asked two more questions — which fields a kind has, for the create
# form and for the row a person types straight into the table — and three copies
# of "these are the three kinds" is three places to forget a fourth.
_KIND_MODELS: dict[str, type[Entity]] = {"project": Project, "pitch": Pitch, "task": Task}

# The body a new entity starts from, per kind.
#
# The pitch one is the team's own shaping template, copied from the note they
# already write pitches against, minus its three header lines: `Shaped by`,
# `Appetite` and `Developers` are fields here, and a heading restating a field is
# the two-copies-of-one-fact problem this tool exists to end. The guidance stays
# in HTML comments exactly as it is written there — invisible on the page, see
# `without_comments` — so a pitch drafted in HackMD and one drafted here are the
# same document.
#
# It is also missing that template's `## Progress`, and that is the one real
# departure: a pitch's progress is its TASKS, each one a record with an owner, a
# size and a status of its own. The HackMD list becomes those tasks, its
# sub-items stay as checkboxes inside them — which is what the task template
# below keeps a `## Progress` for — and the pitch page draws the roll-up.
#
# A template is a starting point and nothing else: no heading here is required,
# validated, or read by anything but `_shaping_hints`, which only prints a note.
_PITCH_TEMPLATE = """## Problem
<!-- The raw idea, a use case, or something we have seen that motivates us to
     work on this. -->

## Appetite
<!-- How much time this deserves and how that shapes the solution. The number
     itself is the Appetite field beside the body; this is the reasoning. -->

## Solution
<!-- The core elements, in a form that is easy to understand immediately. -->

## Rabbit holes
<!-- Details worth calling out now to avoid trouble later. -->

## No-gos
<!-- What is deliberately excluded, to fit the appetite or to keep the problem
     tractable. -->

## For later
<!-- Anything cut to fit the appetite, kept where the next shaping will find it. -->
"""

_TASK_TEMPLATE = """## Problem
<!-- What is wrong or missing, concretely. -->

## Solution
<!-- What will be done about it. -->

## Progress

- [ ]
"""

_PROJECT_TEMPLATE = """## Problem
<!-- What this milestone exists to make possible. -->

## Appetite
<!-- Which cycles this is expected to span, and what happens if it does not fit. -->

## Solution
<!-- The pitches that add up to it, and the order they matter in. -->

## No-gos
<!-- What this milestone is not, so its pitches do not grow into it. -->
"""

TEMPLATES = {
    "pitch": _PITCH_TEMPLATE,
    "task": _TASK_TEMPLATE,
    "project": _PROJECT_TEMPLATE,
    "blank": "",
}


def _new_rows() -> list[dict]:
    """One row per field any kind has, each saying which kinds have it.

    The union rather than one kind's worth, because the page carries all three and
    hides what does not apply. Rendering only the chosen kind meant switching kind
    was a fresh page, and a title typed before switching was gone.
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
        # One form on the page, so one prefix. The detail page's is the entity's
        # id, because that page can hold sixteen of them at once.
        for field in _editable_for(blank, "new"):
            if field["name"] == "title":
                continue          # the title is the heading, not a row
            row = rows.setdefault(
                field["name"],
                {"label": LABELS.get(field["name"], field["name"]), "for": field["id"],
                 "control": _control_html(field), "gates": field["gates"], "kinds": []},
            )
            row["kinds"].append(kind)
    return [{**row, "kinds": " ".join(row["kinds"])} for row in rows.values()]


def _new_row_fields() -> dict[str, dict[str, str]]:
    """Per kind, which stored field each column of a new row writes to.

    The table's own answer to the question `_new_rows` answers for the create
    form — what a person may type into a record that does not exist yet — and it
    is asked of the same two places rather than written down a third time:
    `EDITABLE` says which fields a person owns at all, and `model_fields` says
    which of them this kind has. A project has no `person_weeks`, so it gets no
    box under Appetite; a pitch's `shaped_by` would be here if the table had a
    column for it, and the day it does this map grows the entry on its own.

    A column missing from a kind's map is a column that kind cannot be typed into
    — which is three different sentences and all of them true: `id` is the
    server's, `start` is the scheduler's, and Appetite is a thing a project does
    not have. The row draws each of them differently and says which it is.

    `size` is the one column that is not simply its own field. It *shows*
    person_weeks or an assumed default, which is why no stored row lets it be
    typed into (`_TABLE_WHY`) — but a row that does not exist yet has no assumed
    value standing in for a decision, so there is nothing here to commit by
    accident. Typing 3 into it writes `person_weeks: 3`, and the cell goes back
    to being the scheduler's the moment the row is a record.
    """
    per_kind: dict[str, dict[str, str]] = {}
    for kind, model in _KIND_MODELS.items():
        fields = {}
        for column, _ in _TABLE_COLUMNS:
            field = _SIZE_FIELD_NAME if column == "size" else column
            if field in EDITABLE and field in model.model_fields:
                fields[column] = field
        per_kind[kind] = fields
    return per_kind


def render_new(
    kind: str, base_commit: str, links: Links = ROUTES, index: Index | None = None
) -> str:
    """The create page, which is the detail page in edit mode with nothing in it.

    A second, differently-shaped form for creating was the thing that made the
    tool feel like two tools, so this is the same markup, the same controls and
    the same stylesheet — a blank entity rather than a stored one.

    The only page that marks no nav item. `aria-current="page"` claims a page
    within a set of pages and this form is not in that set: pressing Table from it
    abandons the form rather than staying put, so lighting Table would be a claim
    the link does not keep. That is also why `<h1>New entity</h1>` is the one page
    label still on the screen — with nothing lit in the nav, the heading is all
    that says what this page will make.
    """
    body = _ENV.from_string(_NEW).render(
        kind=kind,
        kinds=KINDS,
        rows=_new_rows(),
        base_commit=base_commit,
        links=links,
        combobox=_combobox_html(index),
        required=_REQUIRED_JS,
        templates=TEMPLATES,
    )
    return _page(
        f"openproj — new {kind}",
        body,
        _DETAIL_STYLE + _SUGGEST_STYLE,
        links,
        unreadable=index.unreadable if index else (),
    )


def _pr_sort(ref: str) -> tuple[str, int]:
    """Newest first within a repository. A PR number is a number, and sorting the
    references as text puts #999 above #1400."""
    repo, _, number = ref.partition("#")
    return repo, int(number) if number.isdigit() else 0


def _suggestions(index: Index) -> dict:
    """What already exists, offered rather than remembered.

    A reviewer who is not in this list is a typo far more often than a new
    colleague, and an id typed from memory is a dangling reference the validator
    will reject after the save rather than before it.
    """
    people: set[str] = set()
    tags: set[str] = set()
    for entity in index.entities.values():
        for name in PEOPLE_FIELDS:
            value = getattr(entity, name, None)
            people.update(value if isinstance(value, list) else [value] if value else [])
        tags.update(entity.tags)
    # A login has no comma and no space in it. An early version of the table wrote
    # a whole comma-separated string into a list field, and the picker then offered
    # "jcanton, halungge" as if it were one person — garbage in the corpus became
    # garbage suggested to the next person, which is how it spreads.
    people = {p for p in people if p and "," not in p and " " not in p}
    tags = {g for g in tags if g and "," not in g}
    # {value, label}: the value is what gets written to the file, the label is the
    # human hint beside it. An id typed from memory is a dangling reference the
    # validator rejects after the save; offered, it cannot be mistyped at all.
    # Two kinds of entry for one field. A whole reference completes a PR already
    # cited somewhere in the plan; a bare `org/repo#` completes the half nobody
    # remembers — which org, and whether it is icon4py or icon4pygen — and leaves
    # the number to be typed. Everything here comes from the corpus, so it costs
    # no network and cannot be stale in a way the plan is not already stale.
    refs = {ref for entity in index.entities.values() for ref in entity.prs}
    repos = {ref.split("#")[0] + "#" for ref in refs if "#" in ref}
    return {
        "prs": (
            [{"value": r, "label": "any pull request"} for r in sorted(repos)]
            + [
                {"value": r, "label": ""}
                for r in sorted(refs, key=_pr_sort, reverse=True)
            ]
        ),
        "people": [{"value": p, "label": ""} for p in sorted(people)],
        "entities": [
            {"value": i, "label": e.title} for i, e in sorted(index.entities.items())
        ],
        "tags": [{"value": t, "label": ""} for t in sorted(tags)],
        # Newest first: the cycle being bet into is nearly always the highest
        # number, and the label is the window, because 37 means nothing and
        # "2026-08-24 → 2026-10-04" is the thing being agreed to.
        "cycles": [
            {
                "value": str(number),
                "label": (
                    f"{index.cycles[number][0]} → {index.cycles[number][1]}"
                    if number in index.cycles
                    else "no dates"
                ),
            }
            for number in sorted(_cycle_numbers(index), reverse=True)
        ],
    }


_CYCLE = """
{#- The same header the detail page and the create form wear: a way back, then
    the name, then the meta line. `.back` and not `.editbar` — this is one link
    out, not a row of controls, and it was the only one of the three sized
    differently.

    The eyebrow the other two carry is missing here on purpose. It says what the
    thing is, and this heading is "Cycle 37": the kind is already its first word,
    so a CYCLE chip above it would be the restatement the id column's kind chip
    was. -#}
<p class="back"><a href="{{ links.cycles }}">← all cycles</a></p>
<h1>Cycle {{ c.number }}</h1>
{#- The one link off this page that is not a record: the deck for the review
    meeting, which is the other thing `reviews_on` is a date for. Drawn only where
    `links.deck` is set, which is the server — a static export has no per-cycle
    page and nothing to number a deck with. It is not in the nav: the nav names
    the views of the whole plan, and this is one cycle's handout. -#}
{% if links.deck %}<p class="back"><a href="{{ links.deck }}{{ c.number }}"
  >Review deck →</a></p>{% endif %}
{% if c.recorded %}
<p class="meta">{{ c.starts_on }} → builds until <b>{{ c.builds_until }}</b>
   → cool-down ends {{ c.ends_on }}</p>
{% else %}
<p class="meta">No record yet{% if c.dated %} — config/cycles.yaml puts this cycle at
   {{ c.starts_on }} → {{ c.ends_on }}{% endif %}. Nothing holds these weeks: what is
   below is the record Save would write.</p>
{% endif %}

{#- Three boxes that decide when the cycle runs and how long for, and not one of
    them had a name: the word beside each is a `<dt>`, which is a caption to a
    reader and nothing to the accessibility tree. -#}
<form id="setup" onsubmit="return false">
  <dl id="facts">
    <dt><label for="starts_on">Starts on</label></dt>
    <dd><span class="read">{{ c.starts_on }}</span>
        <input type="date" id="starts_on" name="starts_on" data-type="date"
               value="{{ c.starts_on }}" class="field"></dd>
    <dt><label for="reviews_on">Review meeting</label></dt>
    <dd><span class="read">{{ c.reviews_on }}</span>
        <input type="date" id="reviews_on" name="reviews_on" data-type="date"
               value="{{ c.reviews_on }}" class="field"></dd>
    {#- Both of the above are meetings somebody put in a calendar. Everything
        below is worked out from them and from the holidays, so it is written in
        the derived style and has no box. -#}
    <dt class="derived">Builds until</dt>
    <dd class="derived">{{ c.builds_until }} · {{ c.build_weeks }} working weeks
      {% if c.assumed_review %}<span class="warnish">— assumed: this cycle names
        no review meeting</span>{% endif %}</dd>
    <dt class="derived">Cool-down ends</dt>
    <dd class="derived">{{ c.ends_on }}
      {% if c.assumed_end %}<span class="warnish">— assumed: the next cycle's
        betting table is what ends it, and there is no record after this
        one</span>{% endif %}</dd>
  </dl>
</form>

<h2>Who is in this cycle</h2>
<p class="hint">Availability is a fraction of the {{ c.build_weeks }} working weeks
  this cycle builds for. Only the people named here are in the cycle.
  <span id="stale" class="warnish" hidden>The dates changed — capacity is
    recounted when you save.</span></p>
<table class="load"><thead><tr>
  <th></th><th>person</th><th>available</th><th>capacity</th><th>bet</th><th>load</th>
  <th>scheduled until</th></tr></thead>
<tbody id="roster">
  {% for row in c.people %}
  <tr data-login="{{ row.login }}" data-held="{{ row.held }}"
      class="{{ 'over' if row.over else '' }}">
    {% if editable %}<td class="dropcell"><button type="button" class="drop"
      title="Take {{ row.login }} out of this cycle"
      aria-label="Take {{ row.login }} out of this cycle">&#128465;</button><span
      class="confirm" hidden>out?<button type="button" class="yes">yes</button><button
      type="button" class="no">no</button></span></td>{% else %}<td></td>{% endif %}
    <td>{{ row.login }}</td>
    <td><span class="read">{{ (row.rate * 100)|round|int }}%</span>
        <input class="field rate" data-login="{{ row.login }}" value="{{ row.rate }}"
               aria-label="{{ row.login }} availability" autocomplete="off"></td>
    <td class="derived capacity">{{ '%.1f'|format(row.capacity) }} wk</td>
    <td class="derived">{{ '%.1f'|format(row.held) }} wk</td>
    <td><span class="bar"><span style="width: {{ row.percent }}%"></span></span></td>
    <td class="derived">{{ row.until }}</td>
  </tr>
  {% endfor %}
</tbody></table>
{% if editable %}
<p class="editbar"><label for="joining" class="hint">add somebody</label>
   <input id="joining" placeholder="login" data-suggest="people" autocomplete="off">
   <button type="button" id="add">+ add to the cycle</button>
   <span class="hint">added here, saved with the setup</span></p>
{% endif %}
{% if c.strangers %}
<p class="problems" id="strangers">Bet into this cycle but not in it:
  {{ c.strangers|join(', ') }}. Their work still counts against the plan; add them
  or take the work out.</p>
{% endif %}
<p class="problems" id="over" {{ '' if c.over else 'hidden' }}>Over capacity:
  {{ c.over|join(', ') }}. The room can still bet it — this is a number, not a
  refusal.</p>
{% if c.carried %}
{#- Counted in the bars above, and named here. Work bet in an earlier cycle keeps
    that cycle's number so its overrun keeps accusing, which also means the load
    column cannot show where it came from. -#}
<p class="hint" id="carried">Counted above, and carried in from an earlier cycle:
  {% for row in c.carried %}<a href="{{ links.entity }}{{ row.id }}">{{ row.title
  }}</a> (bet in {{ row.cycle }}){% if not loop.last %}, {% endif %}{% endfor %}.</p>
{% endif %}

{#- The goal above the table, the notes below it, and they are two fields now.
    One box served as both for as long as the goal was the body, which put the
    cycle's whole point wherever the growing half of the document happened to
    leave it — and there is no arrangement of one box that is both above the
    table where the room is looking and below it where the room is writing. -#}
<h2>Goal</h2>
{% if editable %}
<p class="editbar goalbar">
  <textarea id="goal" class="goal" rows="2"
    aria-label="What this cycle is for"
    placeholder="What this cycle is for. Settled at the betting table.">{{ c.goal }}</textarea>
</p>
{% elif c.goal %}
<p class="goal read">{{ c.goal }}</p>
{% endif %}

<h2>The bet</h2>
<p class="hint">Everything ready or in progress. Ticking one stamps it with cycle
  {{ c.number }}; an item already in progress from an earlier cycle keeps the cycle it
  was bet in, so its overrun keeps counting.</p>
{#- No `table-scroll` wrapper. It wore one from the day it was written, against a
    stylesheet that has never carried the rule, so the class did nothing — and
    the rule is the table page's own, sized against a stack of controls this page
    does not have. Eight columns fit a screen; the page scrolls. -#}
<table id="bets" autocomplete="off"><thead><tr>
  <th>in {{ c.number }}</th><th>title</th><th>kind</th><th>status</th>
  <th>appetite</th><th>assignees</th><th>reviewers</th><th>bet in</th>
</tr></thead><tbody>
  {#- Every box in this table is named after the row it is in, not after its
      column. A column header names a cell to somebody reading down the page; to
      a reader who arrives at one control out of four hundred, "appetite" without
      "for what" is not a name. -#}
  {% for row in c.candidates %}
  <tr data-id="{{ row.id }}" class="{{ 'carried' if row.carried else '' }}">
    <td><input type="checkbox" class="bet" autocomplete="off"
               aria-label="Bet {{ row.title }} into cycle {{ c.number }}"
               {{ 'checked' if row.in_cycle else '' }}
               {{ 'disabled' if row.carried else '' }}></td>
    <td><a href="{{ links.entity }}{{ row.id }}">{{ row.title }}</a></td>
    <td><span class="chip kind-{{ row.kind }}">{{ row.kind|human }}</span></td>
    <td><span class="chip {{ status_class(row.status) }}">{{ row.status|human }}</span></td>
    <td><input class="live" data-field="{{ row.size_field }}" data-type="number"
               aria-label="{{ row.title }} appetite in weeks"
               autocomplete="off" value="{{ row.size }}"
               placeholder="{{ row.size_hint }}"></td>
    <td><input class="live wide" data-field="assignees" data-type="list"
               aria-label="{{ row.title }} assignees"
               data-suggest="people" autocomplete="off" value="{{ row.assignees }}"></td>
    <td><input class="live wide" data-field="reviewers" data-type="list"
               aria-label="{{ row.title }} reviewers"
               data-suggest="people" autocomplete="off" value="{{ row.reviewers }}"></td>
    <td class="derived">{{ row.cycle }}</td>
  </tr>
  {% endfor %}
</tbody></table>

<h2>Notes</h2>
{#- Below the table on purpose: this is what the room said while it was ticking
    rows — why a pitch was left out, what would make it a bet next time — and it
    was going into a HackMD note nobody linked. Still the record's markdown body,
    so it renders like every other shaping document here. -#}
{#- Rendered OR editable, never both. The detail page draws prose above the box
    that edits it because the two are far apart there and the rendered copy is
    the thing you came to read. Here they are adjacent, so the page printed the
    notes twice — once as markdown and once as the same text in a box directly
    beneath it — which reads as a bug rather than as a preview.

    The hint that used to sit between them is the box's placeholder now, for the
    same reason: a line under a heading explaining what Notes are for is paid for
    by every reader on every visit; a placeholder is paid for only by the person
    looking at an empty box. -#}
{% if editable %}
<textarea id="notes" class="notes" rows="8" aria-label="Cycle notes"
  placeholder="What came up at the betting table — why a pitch was left out,
what would make it a bet next time. Markdown.">{{ c.raw_body }}</textarea>
{% else %}
<div class="doc read">{{ c.body }}</div>
{% endif %}

{% if editable %}
<div class="commitbar" id="commitbar">
  <span id="unsaved">Nothing to save</span>
  <button type="button" id="save" disabled>Save</button>
  <span id="state" role="status"></span>
  <input type="hidden" id="base" value="{{ base_commit }}">
</div>
{{ combobox }}
<script>
const BASE = document.getElementById('base');
const BAR = document.getElementById('commitbar');
const UNSAVED = document.getElementById('unsaved');
const NUMBER = {{ c.number }};
// Working weeks between the two meetings, holidays taken out — the server's
// answer, shipped rather than recomputed. See the input listener below.
const BUILD_WEEKS = {{ c.build_weeks }};
// What is on this page, so the shell's banner can tell a write that lands here
// from one that lands somewhere else. The cycle record and every entity that can
// be bet into it: those are the ids the server announces.
window.SHOWING = ['cycle-' + NUMBER].concat(
  [...document.querySelectorAll('#bets tbody tr')].map(tr => tr.dataset.id));

// Through the shell's live region, which is what puts it in `#state` as well.
// A receipt that is only drawn is a save nobody is told landed.
function say(message) { announce(message); }

async function put(fields, body = null) {
  dispatchEvent(new Event('openproj:writing'));
  let committed = null;
  try {
    const response = await fetch(`/api/cycle/${NUMBER}`, {
      method: 'PUT', headers: {'content-type': 'application/json'},
      body: JSON.stringify({base_commit: BASE.value, fields, body}),
    });
    // `answerOf` and not `response.json()`: a 500 answers in plain text, and the
    // rejection took `flush()` with it — Save disabled, the bar still claiming
    // unsaved changes, and nothing said. `refusal` because a cycle written
    // against a moved HEAD answers with a report and no `detail` at all.
    const answer = await answerOf(response);
    if (!response.ok) { say(refusal(answer, response.status)); return null; }
    committed = answer.commit;
    BASE.value = answer.commit || BASE.value;
    return answer;
  } finally {
    // Announced even when the write was refused, or one refusal leaves every
    // later event held back and the shell's banner never appears again.
    dispatchEvent(new CustomEvent('openproj:wrote', {detail: committed}));
  }
}

const SAVE = document.getElementById('save');
const NOTES = document.getElementById('notes');
const GOAL = document.getElementById('goal');
let ROSTER_DIRTY = false;
let NOTES_DIRTY = false;
// The goal is a frontmatter field, so it travels with the roster and the dates
// rather than with the body — but it is dirty-tracked like the notes, because an
// untouched box must not be sent: a cycle whose goal nobody edited would
// otherwise be rewritten on every roster save, and `patch_text` only leaves a
// field alone if it is absent from the payload.
let GOAL_DIRTY = false;
const NOTES_WERE = NOTES ? NOTES.value : '';
const GOAL_WAS = GOAL ? GOAL.value : '';

// The receipt has to outlive the reload that proves it. Saving reloads, because
// half the numbers on this page — capacity, load, the scheduled-until column —
// are derived from what was just written; a confirmation that only lived in the
// DOM would be thrown away by the very thing it is confirming.
const RECEIPT = 'openproj:cycle-saved';
let receipt = '';

try {
  const landed = sessionStorage.getItem(RECEIPT);
  if (landed) { say(landed); sessionStorage.removeItem(RECEIPT); }
} catch (e) { /* the save still landed; only the sentence about it is missing */ }

// The whole roster in one write. A name left out means somebody was taken off,
// which per-field merging would silently undo.
async function saveSetup() {
  const setup = document.getElementById('setup');
  const availability = {};
  for (const input of document.querySelectorAll('input.rate')) {
    const typed = input.value.trim();
    const rate = Number(typed);
    // Refused, not skipped. A missing name means somebody was taken out of the
    // cycle with their capacity, so `if (rate > 0)` turned an empty box, a zero
    // or a `50%` into a removal nobody asked for and nothing reported. Taking
    // somebody out is the button beside their name, which asks first. Said the
    // way the bets table one screen away says it: the field, and the value.
    if (!typed || Number.isNaN(rate) || rate <= 0) {
      say(`${input.dataset.login}'s availability must be a number greater than `
          + `zero, not "${input.value}"`);
      input.focus();
      return false;
    }
    availability[input.dataset.login] = rate;
  }
  // The three boxes as they were typed. `Number('six')` is NaN and
  // `JSON.stringify` sends NaN as null, so coercing here threw the typo away and
  // left the server refusing "blank" about a box holding a word. The server is
  // the one place that decides what a cycle field may hold, and it can only name
  // the value if it is given the value.
  const fields = {
    starts_on: setup.querySelector('[name=starts_on]').value,
    reviews_on: setup.querySelector('[name=reviews_on]').value.trim(),
    availability,
  };
  if (GOAL_DIRTY) fields.goal = GOAL.value.trim();
  // `null` and not the unchanged text: the write path merges a body three ways,
  // and sending one nobody edited makes every roster save a body edit too.
  if (!(await put(fields, NOTES_DIRTY ? NOTES.value : null))) return false;
  ROSTER_DIRTY = false;
  NOTES_DIRTY = false;
  GOAL_DIRTY = false;
  return true;
}

if (NOTES) NOTES.oninput = () => {
  NOTES_DIRTY = NOTES.value !== NOTES_WERE;
  mark();
};

if (GOAL) GOAL.oninput = () => {
  GOAL_DIRTY = GOAL.value !== GOAL_WAS;
  mark();
};

// Ticking is a write to the ENTITY, not to the cycle: `cycle` lives on the thing
// being bet, and one row is one commit so a half-finished betting table is still
// a readable history rather than one commit nobody can unpick.
for (const box of document.querySelectorAll('input.bet')) {
  box.onchange = () => {
    const row = box.closest('tr');
    pend(row.dataset.id, 'cycle', box.checked ? NUMBER : null);
    row.querySelector('td:last-child').textContent = box.checked ? NUMBER : '—';
  };
}

// Nothing is written until Save. A betting table is a conversation — a row gets
// staffed, argued about and restaffed inside a minute — and one commit per
// keystroke turns that into a git history nobody can read and a plan that is
// briefly wrong in public between two halves of one decision.
const PENDING = new Map();   // entity id -> {field: value}

function pend(id, field, value) {
  PENDING.set(id, {...(PENDING.get(id) || {}), [field]: value});
  // A new edit makes the last receipt untrue: "saved 3" sitting beside "2
  // unsaved changes" reads as though the three came back.
  say('');
  mark();
}

function mark() {
  // Counted in edits rather than in commits: two fields on one row is two things
  // somebody changed, even though it is one write.
  let edits = (ROSTER_DIRTY ? 1 : 0) + (NOTES_DIRTY ? 1 : 0) + (GOAL_DIRTY ? 1 : 0);
  for (const fields of PENDING.values()) edits += Object.keys(fields).length;
  SAVE.disabled = edits === 0;
  SAVE.textContent = edits ? `Save ${edits} change${edits === 1 ? '' : 's'}` : 'Save';
  // Said in words next to the button rather than only by the button's own
  // label, because the label is what will happen and this is what is true now.
  UNSAVED.textContent = edits
    ? `${edits} unsaved change${edits === 1 ? '' : 's'}` : 'Nothing to save';
  BAR.classList.toggle('dirty', edits > 0);
  for (const tr of document.querySelectorAll('#bets tbody tr'))
    tr.classList.toggle('pending', PENDING.has(tr.dataset.id));
}

// The browser's own warning, which is the only one that can stop a tab closing.
addEventListener('beforeunload', event => {
  if (!PENDING.size && !ROSTER_DIRTY && !NOTES_DIRTY && !GOAL_DIRTY) return;
  event.preventDefault();
  event.returnValue = '';
});

async function flush(quiet) {
  if (!PENDING.size && !ROSTER_DIRTY && !NOTES_DIRTY && !GOAL_DIRTY) return true;
  SAVE.disabled = true;
  // Counted in edits, the unit `mark()` counts, and not in commits. Two fields on
  // one row is one write, so counting writes said "2 unsaved changes" and then
  // "Saved 1 change" about the same two edits — and a save you have to reconcile
  // against its own receipt is a save you do not believe.
  let saved = 0;
  if (ROSTER_DIRTY || NOTES_DIRTY || GOAL_DIRTY) {
    // Counted before the save clears the flags. The roster and the notes go in
    // one PUT and are two edits to `mark()`, so a receipt saying "1" after
    // changing both is the reconciliation problem this counter exists to avoid.
    const edits = (ROSTER_DIRTY ? 1 : 0) + (NOTES_DIRTY ? 1 : 0) + (GOAL_DIRTY ? 1 : 0);
    if (!(await saveSetup())) { mark(); return false; }
    saved += edits;
  }
  // One entity per commit, each against the commit the last one returned: a
  // batch that fails half way is still a readable history rather than one commit
  // nobody can unpick.
  for (const [id, fields] of [...PENDING]) {
    dispatchEvent(new Event('openproj:writing'));
    let committed = null;
    try {
      const response = await fetch(`/api/entity/${encodeURIComponent(id)}`, {
        method: 'PATCH', headers: {'content-type': 'application/json'},
        body: JSON.stringify({base_commit: BASE.value, fields, body: null}),
      });
      const answer = await answerOf(response);
      if (!response.ok) {
        say(`${id}: ${refusal(answer, response.status)}`
            + (saved ? ` — ${saved} already saved` : ''));
        mark();
        return false;
      }
      committed = answer.commit;
      BASE.value = answer.commit || BASE.value;
      PENDING.delete(id);
      saved += Object.keys(fields).length;
    } finally {
      dispatchEvent(new CustomEvent('openproj:wrote', {detail: committed}));
    }
  }
  mark();
  receipt = `${quiet ? 'Autosaved' : 'Saved'} ${saved} change${saved === 1 ? '' : 's'}`;
  say(receipt);
  return true;
}

SAVE.onclick = async () => {
  if (await flush(false)) {
    // Reloaded because capacity, load and the scheduled-until column are all
    // derived from what was just written, and the receipt is handed across the
    // reload so that pressing Save says something rather than blinking.
    try { sessionStorage.setItem(RECEIPT, receipt); } catch (e) { /* still saved */ }
    location.reload();
  }
};

// Every two minutes, so a dropped connection or a closed laptop costs the last
// two minutes rather than the whole meeting. Quiet when there is nothing to say.
setInterval(() => {
  if (PENDING.size || ROSTER_DIRTY || NOTES_DIRTY) flush(true);
}, 120000);

// Every editable cell is an input already: a betting table is filled in, not
// inspected, and a double-click to reach a field somebody is about to type in is
// a step that only exists because the table also had to be readable.
for (const input of document.querySelectorAll('#bets input.live')) {
  if (input.dataset.suggest) attachSuggest(input);
  let was = input.value;
  // Saving on blur alone is not safe when the field is already an input: the
  // browser restores form values across a reload, autofills, and the picker
  // rewrites the field to add a separator — none of which is a person deciding
  // something. A cell is only staged if somebody typed in it or picked from it,
  // which is what an `input` event means.
  let edited = false;
  input.addEventListener('input', () => { edited = true; });
  input.onkeydown = event => {
    if (event.key === 'Escape') { input.value = was; edited = false; input.blur(); }
    if (event.key === 'Enter') input.blur();
  };
  input.onblur = () => {
    const value = input.value.trim();
    if (!edited || value === was.trim()) { edited = false; return; }
    const id = input.closest('tr').dataset.id;
    const field = input.dataset.field;
    let staged;
    if (input.dataset.type === 'list') {
      staged = value ? [...new Set(value.split(',').map(s => s.trim()).filter(Boolean))] : [];
    } else if (value === '') {
      staged = null;
    } else if (Number.isNaN(Number(value))) {
      say(`${field} must be a number, not "${value}"`);
      input.value = was;
      edited = false;
      return;
    } else {
      staged = Number(value);
    }
    was = input.value;
    edited = false;
    pend(id, field, staged);
  };
}

// Capacity is what a rate BUYS, so it has to move while the rate is being typed.
// Left to the next page load, the number somebody is setting is invisible at the
// moment they are setting it — which is most of the moment that matters.
function recount() {
  const build = BUILD_WEEKS;
  const over = [];
  for (const row of document.querySelectorAll('#roster tr')) {
    const rate = Number(row.querySelector('input.rate').value) || 0;
    const held = Number(row.dataset.held) || 0;
    const capacity = rate * build;
    row.querySelector('.capacity').textContent = capacity.toFixed(1) + ' wk';
    row.querySelector('.bar > span').style.width =
      capacity ? Math.min(100, Math.round(100 * held / capacity)) + '%' : '0%';
    row.classList.toggle('over', capacity > 0 && held > capacity);
    if (capacity > 0 && held > capacity) over.push(row.dataset.login);
  }
  const line = document.getElementById('over');
  if (line) {
    line.hidden = !over.length;
    line.textContent = over.length
      ? `Over capacity: ${over.join(', ')}. The room can still bet it — this is a `
        + 'number, not a refusal.'
      : '';
  }
}
document.addEventListener('input', event => {
  if (event.target.matches('input.rate')) recount();
  if (event.target.closest('#setup') || event.target.matches('input.rate')) dirty();
  // A date changes how many working weeks the cycle builds for, and that answer
  // needs the holidays — which this page does not have and should not grow a
  // second copy of. The column says it is out of date rather than showing a
  // number computed by a rule that is only nearly the server's.
  if (event.target.matches('#setup input[type=date]')) {
    const note = document.getElementById('stale');
    if (note) note.hidden = false;
  }
});

function dirty() {
  ROSTER_DIRTY = true;
  mark();
}

// The roster is edited in the page and written by Save, so adding somebody and
// setting their availability is one decision and one commit rather than two.
const HELD = {{ c.held|tojson }};
const JOINING = document.getElementById('joining');
if (JOINING) attachSuggest(JOINING);

// Two clicks, and the second one answers a question rather than repeating the
// gesture that asked it. Taking somebody out of a cycle takes their capacity out
// with them, and the glyph that did it was one unlabelled pixel target away from
// the availability field next to it.
function dropRow(button) {
  const cell = button.closest('td');
  const asking = cell.querySelector('.confirm');
  button.onclick = () => { button.hidden = true; asking.hidden = false; };
  asking.querySelector('.no').onclick = () => { asking.hidden = true; button.hidden = false; };
  asking.querySelector('.yes').onclick = () => {
    const row = button.closest('tr');
    say(`${row.dataset.login} taken out — Save writes it`);
    row.remove();
    recount();
    dirty();
  };
}
document.querySelectorAll('#roster .drop').forEach(dropRow);

// The same cell the roster loop above renders. Kept as one string rather than
// built up, so that the two copies of it can be read against each other; a test
// asserts both carry the name and the question.
function dropCell(login) {
  const who = esc(login);
  return `<td class="dropcell"><button type="button" class="drop"`
    + ` title="Take ${who} out of this cycle"`
    + ` aria-label="Take ${who} out of this cycle">&#128465;</button>`
    + `<span class="confirm" hidden>out?<button type="button" class="yes">yes</button>`
    + `<button type="button" class="no">no</button></span></td>`;
}

document.getElementById('add').onclick = () => {
  const login = JOINING.value.trim().replace(/,$/, '');
  if (!login) return;
  // CSS.escape, the way `refusals()` already does it on the detail page. A login
  // is typed, and a quote or a bracket in one made this a selector that is not a
  // selector: the browser threw inside the handler and the Add button stopped
  // working — for every later click too, with nothing on screen saying why.
  if (document.querySelector(`#roster tr[data-login="${CSS.escape(login)}"]`)) {
    say(`${login} is already in this cycle`);
    return;
  }
  const row = document.createElement('tr');
  row.dataset.login = login;
  // Somebody added to the cycle may already be bet into it — that is exactly why
  // the page named them below the table. Their load comes with them.
  row.dataset.held = (HELD[login] || 0);
  // A login is typed here rather than read out of the plan, which makes this the
  // one injection on these pages that starts as a person doing it to themselves
  // — and ends as everybody's, because Save writes the name into the cycle file
  // and the roster is drawn from that file for every reader afterwards.
  const who = esc(login);
  row.innerHTML = dropCell(login)
    + `<td>${who}</td>`
    + `<td><input class="field rate" data-login="${who}" value="1.0"`
    + ` aria-label="${who} availability" autocomplete="off"></td>`
    + `<td class="derived capacity">—</td>`
    + `<td class="derived">${(HELD[login] || 0).toFixed(1)} wk</td>`
    + `<td><span class="bar"><span style="width: 0%"></span></span></td>`
    + `<td class="derived">—</td>`;
  document.getElementById('roster').append(row);
  dropRow(row.querySelector('.drop'));
  JOINING.value = '';
  recount();
  dirty();
  say(`${login} added — Save writes it`);
};
</script>
{% endif %}
"""

_CYCLE_STYLE = """
/* .commitbar, #unsaved and #save are the shell's: the cycle page was the first
   to need a bar that says whether the page is saved, and then the detail page
   and the create page needed the same one. */
/* A destructive control asks before it acts, and the question replaces the
   glyph rather than appearing beside it, so the row does not jump. */
.confirm { font-size: 12px; color: var(--warn); }
td .confirm { white-space: nowrap; }
.confirm button { font: inherit; font-size: 12px; margin-left: .25rem;
                  padding: 0 .35rem; border-radius: 2px;
                  border: 1px solid var(--line-strong); background: var(--surface);
                  color: var(--fg); cursor: pointer; }
.confirm button.yes { border-color: var(--danger); color: var(--danger); }
/* The notes box, at the width of the prose it holds rather than the width of the
   betting table beside it. */
textarea.notes { display: block; width: 100%; max-width: 52rem; box-sizing: border-box;
                 font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
                 font-size: 13px; line-height: 1.55; padding: .4rem;
                 border: 1px solid var(--line-strong); border-radius: 3px;
                 background: var(--surface); color: inherit; resize: vertical; }
/* The goal box wears the notes' shape and not its typeface: notes are markdown
   and read better in mono, a goal is a sentence somebody says out loud. Wider
   measure than prose wants, because it sits above a table and a goal that wraps
   three times stops being the one line the room agreed on. */
/* No rule above the cycle's prose. `.doc`'s border-top comes from _DETAIL_STYLE,
   where it separates a shaping document from the facts pane above it; here the
   block sits directly under its own `<h2>`, so the same rule drew a stray line
   between a heading and the text it heads. Unscoped and relying on order: this
   sheet is concatenated after _DETAIL_STYLE and is loaded by the two cycle pages
   only, so there is no third page for it to reach. */
.doc { border-top: 0; padding-top: 0; }
textarea.goal { display: block; width: 100%; max-width: 52rem; box-sizing: border-box;
                font: inherit; font-size: 15px; line-height: 1.5; padding: .4rem;
                border: 1px solid var(--line-strong); border-radius: 3px;
                background: var(--surface); color: inherit; resize: vertical; }
p.goal.read { font-size: 15px; max-width: 52rem; margin: 0 0 1rem; }
.goalbar { margin: 0 0 1rem; }
#setup .field, table.load .field { display: inline-block; }
#setup .field { width: 12rem; }
#setup .read, table.load .read { display: none; }
table.load { border-collapse: collapse; font-size: 13px; margin: .5rem 0 1rem; }
table.load th, table.load td {
  border-bottom: 1px solid var(--line); padding: .3rem .6rem; text-align: left;
}
table.load th { color: var(--muted); font-weight: 400; font-size: 11px;
                text-transform: uppercase; letter-spacing: .04em; }
tr.over td { color: var(--danger); }
input.rate { width: 4rem; }
#bets input.live { font: inherit; font-size: 13px; width: 5rem;
                   background: var(--surface); color: inherit;
                   border: 1px solid transparent; border-radius: 3px; padding: .1rem .3rem;
                   /* A box with no border that cuts its value mid-word — "…jcanto"
                      — reads as broken text rather than as a field. An input
                      clips its overflow and says nothing about it; this is the
                      one thing that does. */
                   text-overflow: ellipsis; }
/* As wide as the column it is in, not 11rem regardless. The column is sized by
   the header and the widest name in it and there was room to spare beside every
   one of these boxes, so a fixed width was cutting values the table had already
   made room for. `min-width` keeps the column from collapsing to the width of
   the word above it, and `border-box` keeps the padding inside the cell. */
#bets input.live.wide { width: 100%; min-width: 11rem; box-sizing: border-box; }
#bets input.live:hover { border-color: var(--line); }
/* The border is the hover affordance, not the focus one. Suppressing the outline
   here left the only keyboard-reachable cell on the page with nothing to say it
   had focus; the shell's :focus-visible ring draws it now. */
#bets input.live:focus { border-color: var(--accent); }
/* No `#bets td { position: relative }`. It was here to anchor the suggestion
   popup the assignees and reviewers boxes open, and the popup is parked on the
   body now. Left in, it is a rule with nothing to do and a trap for whoever
   writes the next one: the identical rule on the table's cells is what stole
   `position: sticky` from the frozen title column. */
button.drop { border: none; background: none; cursor: pointer; padding: 0 .2rem;
              color: var(--muted); font-size: 13px; line-height: 1; }
button.drop:hover { color: var(--danger); }
#joining { font: inherit; font-size: 13px; width: 10rem; }
#bets { border-collapse: collapse; width: 100%; font-size: 13px; }
#bets th, #bets td { border-bottom: 1px solid var(--line); padding: .3rem .5rem;
                     text-align: left; }
#bets th { color: var(--muted); font-weight: 400; font-size: 11px;
           text-transform: uppercase; letter-spacing: .04em; }
tr.carried td { color: var(--muted); }
#bets tr.pending td { box-shadow: inset 3px 0 0 -1px var(--accent); }
#bets tr.pending td:first-child { box-shadow: inset 3px 0 0 0 var(--accent); }

/* The cycles index. One card per cycle, and the sentence the method turns on —
   this much bet, that much to bet with — is the largest thing on it. */
.cards { list-style: none; margin: 1rem 0 0; padding: 0; display: grid; gap: .75rem;
         grid-template-columns: repeat(auto-fill, minmax(19rem, 1fr)); }
.card { border: 1px solid var(--line); border-radius: 3px; padding: .6rem .8rem;
        background: var(--surface); }
.card h2 { font-size: 1.05rem; margin: 0; }
.card .window { color: var(--muted); font-size: 12px; margin: .1rem 0 .5rem; }
.card .bet { margin: 0 0 .35rem; font-size: 13px; }
.card .bet b { font-size: 1.15rem; font-variant-numeric: tabular-nums; }
.card span.bar { display: block; width: 100%; height: 10px; }
.card.over .bet b { color: var(--danger); }
.card .note { margin: .35rem 0 0; }
/* The create form is not another cycle in the list, and it writes a record. The
   rule and the heading are what say so before the button does. */
#create { border-top: 1px solid var(--line); margin-top: 2.5rem; padding-top: 1rem; }
#create h2 { font-size: 1.05rem; margin: 0 0 .2rem; }
#start { font: inherit; font-size: 13px; padding: .25rem .8rem; border-radius: 2px;
         border: 1px solid var(--accent); background: var(--surface);
         color: var(--accent); cursor: pointer; }
#confirm { margin: .6rem 0 0; font-size: 13px; }
"""

_CYCLES = """
{#- Announced, not drawn: the lit nav item says this already. See `.sr-only`. -#}
<h1 class="sr-only">Cycles</h1>
<p class="hint">Every cycle the plan names — the ones with a record, the ones
  config/cycles.yaml dates, and the ones something has been bet into. A cycle sets
  the build and cool-down weeks and who is available for it.</p>
{% if cycles %}
<ul class="cards">
  {#- A link only where the page it opens exists. `render_static` writes six
      files and none of them is a cycle, so on a rendered plan every one of these
      headings was an anchor to a fragment that is not on the page — a control
      that does nothing, which is how a reader learns to stop pressing them. -#}
  {% for c in cycles %}
  <li class="card{{ ' over' if c.over else '' }}">
    <h2>{% if per_cycle_page %}<a href="{{ links.cycle }}{{ c.number }}">Cycle {{ c.number
      }}</a>{% else %}Cycle {{ c.number }}{% endif %}</h2>
    <p class="window">{% if c.recorded %}{{ c.starts_on }} → builds until
      {{ c.builds_until }}{% elif c.starts_on %}{{ c.starts_on }} → {{ c.ends_on }}
      {% else %}no dates{% endif %}
      · {{ c.people }} {{ 'person' if c.people == 1 else 'people' }}</p>
    {% if c.recorded %}
    <p class="bet"><b class="num">{{ '%.1f'|format(c.bet) }}</b> of
      <b class="num">{{ '%.1f'|format(c.capacity) }}</b> weeks bet</p>
    <span class="bar"><span style="width: {{ c.percent }}%"></span></span>
    {% else %}
    <p class="bet"><b class="num">{{ '%.1f'|format(c.bet) }}</b> weeks bet against
      no roster</p>
    <p class="hint note">No record yet, so there is no capacity to bet against.</p>
    {% endif %}
  </li>
  {% endfor %}
</ul>
{% else %}
<p class="hint">No cycle has been named yet — not in a record, not in
  config/cycles.yaml, and nothing has been bet into one. Start one below.</p>
{% endif %}
{% if editable %}
<section id="create">
  <h2>Start a cycle</h2>
  <p class="editbar">
    <label class="facet">number
      <input id="number" type="number" value="{{ next.number }}" min="0" max="9999"></label>
    <label class="facet">betting table
      <input id="starts" type="date" value="{{ next.starts_on }}"></label>
    <label class="facet">review meeting
      <input id="reviews" type="date" value="{{ next.reviews_on }}"></label>
    {#- On the same line as the three boxes it acts on. It had a row to itself,
        which reads as a second step and is not one: with the goal box gone this
        form is three fields and the button that commits them, and `.editbar`
        already wraps when the window is too narrow to hold them. -#}
    <button type="button" id="start">Start it</button>
    <span id="state" role="status"></span>
    <input type="hidden" id="base" value="{{ base_commit }}">
  </p>
  {#- No goal box here. It was asked on this form for one round and belongs on
      the cycle's own page instead: this form's whole job is to bring a record
      into existence, and the goal is then edited where it is read, above the
      betting table it is about. Two places to write one field is one place too
      many. -#}
  <p class="confirm" id="confirm" hidden>Start cycle <b id="confirm-number"></b> on
    <b id="confirm-starts"></b>, <b id="confirm-length"></b>, with
    <b id="confirm-people"></b>? This commits a cycle record.
    <button type="button" id="yes">Yes, start it</button>
    <button type="button" id="no">Cancel</button></p>
</section>
<script>
const ROSTER = {{ roster|tojson }};
const START = document.getElementById('start');
const CONFIRM = document.getElementById('confirm');
const field = id => document.getElementById(id);

// Starting a cycle writes a file and moves every date on every page that reads
// it. It was one click on a button beside four inputs somebody had just been
// typing in, with no sentence anywhere saying what the click would do.
START.onclick = () => {
  const people = Object.keys(ROSTER).length;
  field('confirm-number').textContent = field('number').value;
  field('confirm-starts').textContent = field('starts').value;
  // Measured from the two dates in front of you, and not from `#build` and
  // `#cooldown` — two inputs this form stopped having when it started asking for
  // the review date instead. `field()` answered null for both, reading `.value`
  // off null threw, and the throw happened before `CONFIRM.hidden = false`: so
  // "Start it" did nothing at all, silently, and no cycle could be started from
  // the page at all. The confirmation is the only thing between a click and a
  // commit, which is why it is computed from what is on screen.
  const weeks = Math.round(
    (Date.parse(field('reviews').value) - Date.parse(field('starts').value))
    / (7 * 24 * 60 * 60 * 1000));
  field('confirm-length').textContent = Number.isFinite(weeks) && weeks > 0
    ? `${weeks} week${weeks === 1 ? '' : 's'} to the review meeting`
    : 'dates not set';
  field('confirm-people').textContent =
    `${people} ${people === 1 ? 'person' : 'people'} carried over`;
  CONFIRM.hidden = false;
  START.hidden = true;
  announce('');
};

document.getElementById('no').onclick = () => {
  CONFIRM.hidden = true;
  START.hidden = false;
};

// Defaults carried from the last cycle: the length rarely changes, the next one
// starts when the last one ends, and mostly the same people are in it at mostly
// the same rates. All of it is corrected on the cycle's own page afterwards.
document.getElementById('yes').onclick = async () => {
  const number = Number(field('number').value);
  dispatchEvent(new Event('openproj:writing'));
  let committed = null;
  try {
    const response = await fetch(`/api/cycle/${number}`, {
      method: 'PUT', headers: {'content-type': 'application/json'},
      body: JSON.stringify({
        base_commit: field('base').value,
        // As typed, the way the cycle page sends them: a coerced NaN arrives as
        // null and the refusal can only say "blank" about a box with a word in it.
        fields: {
          starts_on: field('starts').value,
          reviews_on: field('reviews').value,
          availability: ROSTER,
        },
        // null, not "": the write path treats a null body as "leave it alone"
        // and an empty string as "set it to empty", and those differ the day
        // somebody starts a cycle whose record already exists.
        body: null,
      }),
    });
    const answer = await answerOf(response);
    if (!response.ok) {
      announce(refusal(answer, response.status));
      CONFIRM.hidden = true;
      START.hidden = false;
      return;
    }
    committed = answer.commit;
    location.href = '/cycle/' + number;
  } finally {
    dispatchEvent(new CustomEvent('openproj:wrote', {detail: committed}));
  }
};
</script>
{% endif %}
"""

_PEOPLE = """
{#- Announced, not drawn: the lit nav item says this already. See `.sr-only`. -#}
<h1 class="sr-only">People</h1>
<p class="hint">Everyone named anywhere in the plan, and what they are on the hook
  for.
  {%- if load.cycle is none %}
  {%- elif load.recorded %} The weeks are cycle {{ load.cycle }}'s: what is bet on
  somebody there, against what they are available for. Weeks bet into another cycle
  are counted beside them, and work bet into no cycle at all is in the rows and in no
  number.
  {%- else %} The weeks are cycle {{ load.cycle }}'s: what is bet on somebody there.
  That cycle has no record, so there is no availability to bet it against.
  {%- endif %}</p>
{{ facets }}
<div id="summary"><span id="shown" class="num">{{ people|length }}</span>
  of {{ people|length }} people</div>
{#- One table for the whole page. Fifteen tables meant fifteen headers, and a
    column of statuses that started at a different x for every person cannot be
    read down. The person is a group row inside it instead of a heading above a
    table of their own. -#}
<table id="roles">
  <thead><tr><th scope="col">role</th><th scope="col">entity</th><th scope="col">kind</th>
    <th scope="col">status</th><th scope="col">scheduled</th></tr></thead>
  {% for person in people %}
  <tbody class="person" data-login="{{ person.login }}">
    <tr class="group{{ ' over' if person.over else '' }}">
      <th colspan="5" scope="colgroup"><div class="groupline">
        {#- The person's own mark. A button for exactly one person on the page —
            whoever is signed in — and a plain span for everybody else, because
            the only icon anybody may set here is their own.

            The button and its list are wrapped together because the list is
            positioned against the wrapper: the group line wraps, so the button
            has no fixed place in it, and a popup anchored to anything else opens
            somewhere the button is not. -#}
        {%- if person.mine %}
        <span class="pickwrap">
        <button type="button" id="pick" class="avatar pick{{ ' unset' if not person.art else '' }}"
                aria-haspopup="listbox" aria-expanded="false" aria-controls="picker"
                aria-label="Your icon" title="Your icon">{{ person.art }}</button>
        {#- A listbox and not a `<select>`: a native option cannot hold an SVG,
            and picking your own mark by reading the word "fox" is not the
            feature. Every row carries the drawing AND the name, because the name
            is what is stored and what a refusal will say back.

            "No icon" first, and not last where the old strip's clear button was:
            it is the way out, and a way out you have to scroll twenty-four rows
            to reach is the hardest row on the list to find.

            `aria-selected` marks the one that is stored, which is a different
            fact from the one the arrow keys are on — that one is named by
            `aria-activedescendant` and drawn by `.on`. The suggestion combobox
            conflates the two, and is right to: it has no stored value to mark. -#}
        <ul id="picker" class="picker" role="listbox" aria-label="Your icon" tabindex="-1" hidden>
          <li id="pick-none" class="option" role="option" data-icon=""
              aria-selected="{{ 'true' if not person.icon else 'false' }}"><span
              class="art"></span>No icon</li>
          {% for one in icons %}
          <li id="pick-{{ one.name }}" class="option" role="option" data-icon="{{ one.name }}"
              aria-selected="{{ 'true' if one.name == person.icon else 'false' }}"><span
              class="art">{{ one.art }}</span>{{ one.name }}</li>
          {%- endfor %}
        </ul>
        </span>
        {%- elif person.art %}
        <span class="avatar">{{ person.art }}</span>
        {%- endif %}
        {%- if person.link %}
        <a class="who" href="{{ links.table }}?{{ person.link.field }}={{ person.login|urlencode }}"
           title="{{ person.link.says }}">{{ person.login }}</a>
        {%- else %}
        <span class="who">{{ person.login }}</span>
        {%- endif %}
        {%- if person.capacity %}
        <span class="load"><b class="num held">{{ '%.1f'|format(person.held) }}</b> of
          <b class="num">{{ '%.1f'|format(person.capacity) }}</b> weeks
          <span class="bar"><span style="width: {{ person.percent }}%"></span></span></span>
        {%- elif person.held and load.recorded %}
        <span class="load stranger"><b class="num held">{{ '%.1f'|format(person.held) }}</b>
          weeks bet, and not on cycle {{ load.cycle }}'s roster</span>
        {%- elif person.held %}
        <span class="load"><b class="num held">{{ '%.1f'|format(person.held) }}</b>
          weeks bet against no roster</span>
        {%- elif load.cycle is not none %}
        <span class="load none">nothing bet in cycle {{ load.cycle }}</span>
        {%- endif %}
        {%- if person.elsewhere %}
        <span class="elsewhere">+<span class="num">{{ '%.1f'|format(person.elsewhere) }}</span>
          weeks in other cycles</span>
        {%- endif %}
        {#- The counts keep their old job and take on the way in: three of the
            four roles are a filter the table has, so a count is a link to the
            rows it counts. -#}
        <span class="tally">
          {%- for t in person.tally -%}
            {%- if t.field %}<a href="{{ links.table }}?{{ t.field }}={{ person.login|urlencode
              }}">{{ t.n }} as {{ t.role }}</a>{% else %}{{ t.n }} as {{ t.role }}{% endif -%}
            {{- ' · ' if not loop.last else '' -}}
          {%- endfor -%}
        </span>
        {%- if person.mine %}
        {#- Where a refusal is read. `announce` writes into `#state` when a page
            has one and into the shell's screen-reader region when it does not,
            and this page had none — so the first version of this feature failed
            silently for everybody who could see: the button did nothing, and the
            only account of why went to a region carrying `.sr-only`, which is
            `position: absolute; clip-path: inset(50%)`.

            A line of its own at the end of the group line, and drawn only where
            the button is. Not at the top of the page: the filter hides a whole
            person's `tbody` at once, so a status line up there would be on screen
            when the control it is about is not, and gone in exactly the case this
            exists for. Anybody who can press the button can see this, because it
            is two centimetres under their hand rather than at the far end of a
            row that is a metre wide on this table. It stays in the flow of the
            group line now that the list floats: a refusal is read after the list
            has closed over it, and a message inside a popup is a message that
            leaves with the popup. -#}
        <span id="state" role="status"></span>
        {%- endif %}
      </div></th>
    </tr>
    {% for row in person.rows %}
    <tr data-role="{{ row.role }}" data-kind="{{ row.kind }}" data-status="{{ row.status }}"
        data-text="{{ row.search }}">
      <td class="role">{{ row.role }}</td>
      <td><a href="{{ links.entity }}{{ row.id }}">{{ row.title }}</a></td>
      <td><span class="chip kind-{{ row.kind }}">{{ row.kind|human }}</span></td>
      <td><span class="chip {{ status_class(row.status) }}">{{ row.status|human }}</span></td>
      <td class="derived">{{ row.span }}</td>
    </tr>
    {% endfor %}
  </tbody>
  {% endfor %}
  {#- Which emptiness this is decides what to do about it, so the page says which
      one it is rather than leaving a header row over a void. -#}
  <tbody id="nothing"{% if people %} hidden{% endif %}>
    <tr class="nothing"><td colspan="5">
      {% if people %}
      <p class="headline">No person matches these filters.</p>
      <p class="hint">Every row is filtered out by the controls above.</p>
      <button type="button" id="clear-filters">Clear filters</button>
      {% else %}
      <p class="headline">Nobody is named in this plan yet.</p>
      <p class="hint">People appear here as soon as they own, are assigned, review or
        shape something.</p>
      {% endif %}
    </td></tr>
  </tbody>
</table>
{{ filters }}
<script>
// A person whose own name matches keeps all their rows: searching for somebody is
// asking what they are on the hook for, not asking to see only the rows that
// happen to repeat their name.
const GROUPS = [...document.querySelectorAll('tbody.person')];
const NOTHING = document.getElementById('nothing');
const COUNT = document.getElementById('shown');

// Hidden, not removed: the rows are rendered once by the server, and rebuilding
// them here to show twelve of fifteen is a second copy of the markup that has to
// keep agreeing with the first.
function apply() {
  const text = (params.get('q') || '').trim().toLowerCase();
  // `getAll` and OR within a field, which is what the bar can now ask and what
  // `matches` and `apply_filters` have always answered. With `get` this page
  // honoured the first value and ignored the rest in silence — a control that
  // sets two and a page that reads one is the same divergence as the search
  // blob, on the same afternoon it was fixed.
  const want = ['role', 'kind', 'status']
    .map(field => [field, params.getAll(field).filter(Boolean)])
    .filter(([, values]) => values.length);
  let visible = 0;
  for (const group of GROUPS) {
    const person = group.dataset.login.toLowerCase();
    let kept = 0;
    for (const row of group.querySelectorAll('tr[data-role]')) {
      const keep = want.every(([field, values]) => values.includes(row.dataset[field]))
        && (!text || person.includes(text) || row.dataset.text.includes(text));
      row.hidden = !keep;
      kept += keep ? 1 : 0;
    }
    group.hidden = kept === 0;
    visible += kept > 0 ? 1 : 0;
  }
  COUNT.textContent = visible;
  NOTHING.hidden = visible > 0;
}

addEventListener('openproj:filter', apply);
// Absent on a plan nobody is named in, where there is no filter to clear.
const CLEAR = document.getElementById('clear-filters');
if (CLEAR) CLEAR.onclick = clearFilters;
apply();
</script>
{#- Only where there is a server to write to. A static export carries no picker,
    so shipping the script that drives one would put a `fetch` for a route that
    does not exist into a file opened over `file://` — dead code in the one copy
    of this plan that has to be readable with nothing else on the machine. -#}
{% if editable %}
<script>
// Picking your own icon. Both are absent for somebody who may write and is named
// nowhere in the plan: this page lists whoever holds work, so there is no row to
// hang a picker off for a person who holds none. Guarded rather than assumed,
// because that reader gets this script like everybody else who may write.
const PICK = document.getElementById('pick');
const PICKER = document.getElementById('picker');

// One region for both sentences a write produces, told apart by colour rather
// than by having two places to look. `announce` picks `#state` on a page that
// has one — this page's is beside the button, and it is drawn only when the
// button is, so the message is where the hand already is.
// `report` and not `say`: two classic scripts on one page share one global
// scope, and `say` is already taken twice in this file.
function report(message, bad) {
  const state = document.getElementById('state');
  if (state) state.classList.toggle('bad', !!bad);
  announce(message);
}

async function chooseIcon(name) {
  // The whole request: one key, and the login is the server's own. There is
  // nothing here to name somebody else with, and nothing to name a file with
  // either — the path is `people/<your login>.md` and it is built on the server
  // from the session. See the endpoint.
  dispatchEvent(new Event('openproj:writing'));
  let committed = null;
  try {
    const response = await fetch('/api/icon', {
      method: 'PUT', headers: {'content-type': 'application/json'},
      body: JSON.stringify({icon: name || null}),
    });
    // `answerOf` and not `.json()`: a refusal that arrives as plain text would
    // otherwise reject here and leave the picker open with nothing said.
    const answer = await answerOf(response);
    if (!response.ok) { report(refusal(answer, response.status), true); return false; }
    committed = answer.commit;
    return true;
  } finally {
    // Announced even when the write was refused, or the shell holds every later
    // event back and its banner never appears again.
    dispatchEvent(new CustomEvent('openproj:wrote', {detail: committed}));
  }
}

// The rows, read once from the markup the server rendered. Not rebuilt here: the
// drawings are already in the page, and a script that assembled twenty-four
// `<svg>` strings would be a second copy of `_ICON_ART` in a template literal —
// an invariant written twice, which this codebase guards once or not at all.
const OPTIONS = PICKER ? [...PICKER.querySelectorAll('[role="option"]')] : [];
// Where the keyboard is, which is NOT which row is stored. `aria-selected` says
// what you have; this says what you are looking at, and the listbox says so with
// `aria-activedescendant` — the same arrangement the suggestion popup in this
// file uses to keep focus on the control while the highlight moves in the list.
// Named like this and not `at`, `highlight`, `choose`: two classic scripts on
// one page share one global scope, which is why `report` is not called `say`.
let AT_ROW = 0;

function highlightRow(next) {
  AT_ROW = (next + OPTIONS.length) % OPTIONS.length;
  OPTIONS.forEach((option, i) => option.classList.toggle('on', i === AT_ROW));
  PICKER.setAttribute('aria-activedescendant', OPTIONS[AT_ROW].id);
  // `block: 'nearest'`, or every move scrolls the list to centre the row and the
  // list appears to jump under a reader who pressed Down once.
  OPTIONS[AT_ROW].scrollIntoView({block: 'nearest'});
}

// `back` is whether closing should hand focus to the button. Escape and a choice
// both should — the button is where that person's hand is. Focus LEAVING the
// list must not, because it left for somewhere the reader chose, and dragging it
// back is the popup arguing with them.
function openPicker(open, back = true) {
  PICKER.hidden = !open;
  PICK.setAttribute('aria-expanded', String(open));
  if (open) {
    // Opened on the row that is already stored, so the first arrow press moves
    // from your own mark rather than from the top of a list of twenty-five.
    highlightRow(Math.max(0, OPTIONS.findIndex(o => o.getAttribute('aria-selected') === 'true')));
    PICKER.focus();
  } else if (back) {
    PICK.focus();
  }
}

async function chooseRow(option) {
  const name = option.dataset.icon;
  // The picker stays open on a refusal, with the reason beside it in `#state`:
  // closing it would leave a page that looks exactly like one where nothing
  // was pressed, which is the state this feature shipped in once already.
  if (!await chooseIcon(name)) return;
  // The drawing is moved, not rebuilt: the chosen row already holds the exact
  // markup the server would send back, so the new mark is a clone of a node this
  // page rendered rather than a string assembled from an answer. Nothing crosses
  // an escaping boundary, and the page does not have to reload to show what it
  // just saved.
  const art = option.querySelector('svg');
  PICK.replaceChildren(...(art ? [art.cloneNode(true)] : []));
  PICK.classList.toggle('unset', !art);
  // The list is open again one press later, and it has to open on what is now
  // stored rather than on what was stored when the page was rendered.
  OPTIONS.forEach(one => one.setAttribute('aria-selected', String(one === option)));
  openPicker(false);
  report(name ? `Your icon is now ${name}.` : 'Your icon is cleared.', false);
}

if (PICK && PICKER) {
  PICK.onclick = () => openPicker(PICKER.hidden);
  PICKER.addEventListener('keydown', event => {
    // The listbox keys, in the order somebody reaches for them. Escape closes,
    // because a popup that only closes by pressing the thing that opened it is a
    // trap for anybody who got here with the keyboard; Home and End because this
    // list is long enough to scroll and "No icon" is at the top of it.
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      highlightRow(AT_ROW + (event.key === 'ArrowDown' ? 1 : -1));
    } else if (event.key === 'Home' || event.key === 'End') {
      event.preventDefault();
      highlightRow(event.key === 'Home' ? 0 : OPTIONS.length - 1);
    } else if (event.key === 'Enter' || event.key === ' ') {
      // Space as well as Enter, and both prevented: Space on a focused element
      // scrolls the page, so a listbox that ignored it would answer the second
      // most obvious key by scrolling the list out from under the reader.
      event.preventDefault();
      chooseRow(OPTIONS[AT_ROW]);
    } else if (event.key === 'Escape') {
      openPicker(false);
    }
  });
  PICKER.addEventListener('click', event => {
    const option = event.target.closest('[role="option"]');
    if (option) chooseRow(option);
  });
  // Clicking anywhere else closes it. `relatedTarget` is the button when the
  // button is what was clicked, and closing here as well would let the click
  // that follows reopen a list the reader was shutting.
  PICKER.addEventListener('focusout', event => {
    if (!PICKER.contains(event.relatedTarget) && event.relatedTarget !== PICK) {
      openPicker(false, false);
    }
  });
}
</script>
{% endif %}
"""

_PEOPLE_STYLE = """
.hint { max-width: 46rem; font-size: 13px; }
#roles { border-collapse: collapse; width: 100%; max-width: 72rem; font-size: 13px; }
#roles th, #roles td { border-bottom: 1px solid var(--line); padding: .3rem .5rem;
                       text-align: left; }
/* The id selector above outranks the shell's centred empty row, which is how the
   message ended up hugging the left edge of a table with nothing in it. */
#roles tr.nothing td { text-align: center; }
/* Sticky against the page rather than a scroll box: five columns fit any screen,
   so the page itself scrolls and the header rides down it. A collapsed border is
   not painted on a sticky cell — the first row scrolls straight over the top of
   it — so the rule is drawn inside the box instead. */
#roles thead th { position: sticky; top: 0; z-index: 2; background: var(--surface);
                  box-shadow: inset 0 -1px 0 var(--line);
                  color: var(--muted); font-weight: 400; font-size: 11px;
                  text-transform: uppercase; letter-spacing: .04em; }
/* A ground, not only a bold name: the group row is the only thing separating one
   person's rows from the next person's now that they share a table, and a run of
   twelve review rows is long enough to lose the boundary in. */
tr.group > th { font-weight: 400; background: var(--surface-2); }
/* Air above each person, so a name does not begin on the line the previous
   person's last row ended on. Space and not a rule: every row here already ends
   in a hairline and the group row already has a ground of its own, and a third
   boundary drawn between two things that are each already bounded is noise. It
   is a thick border in the page's own colour because the table is collapsed —
   a collapsed border resolves to the widest of the two it joins, so this eats
   the row-hairline above it and leaves a clean gap rather than a gap with a line
   in it. The sibling combinator and not `:first-of-type`: the gap belongs
   *between* people, so the first group must not open with one. */
tbody.person + tbody.person > tr.group > th { border-top: .7rem solid var(--bg); }
.groupline { display: flex; flex-wrap: wrap; align-items: baseline; gap: .15rem .75rem; }
.who { font-size: 15px; font-weight: 650; }
.load { color: var(--muted); font-size: 12px; }
.load b { color: var(--fg); font-size: 13px; font-weight: 600; }
/* The number that says the person is over, in the colour that says so. The bar
   beside it turns with the row through the shell's `.over` rule. */
tr.group.over .load b.held { color: var(--danger); }
.load.stranger { color: var(--warn); }
.load.stranger b { color: var(--warn); }
.elsewhere { color: var(--muted); font-size: 12px; }
.tally { color: var(--muted); font-size: 12px; margin-left: auto; }
/* Muted and not accent: the accent is what a link is on every other page, and a
   column of teal words beside a column of teal links reads as twelve dead links. */
td.role { color: var(--muted); font-size: 12px; text-transform: uppercase;
          letter-spacing: .04em; white-space: nowrap; }
/* The person's mark, at the size of the name beside it and in the same ink. Not
   allowed to shrink: the group line wraps, and an icon that collapsed to nothing
   on a narrow window would take the one thing on this page a person chose for
   themselves off the page at exactly the width where the name is all that is
   left. */
.avatar { flex: none; display: inline-flex; align-items: center; justify-content: center;
          width: 1.6rem; height: 1.6rem; color: var(--fg); }
.avatar svg { width: 100%; height: 100%; }
button.avatar {
  font: inherit; background: var(--surface); color: var(--fg); cursor: pointer;
  border: 1px solid transparent; border-radius: 5px; padding: .1rem;
}
button.avatar:hover { border-color: var(--accent); }
/* Nothing chosen yet still has to be a target. An empty button is a control
   nobody can find, and this one is the only way to the picker — so the unset
   state is a dashed ring, which reads as a place something goes. */
button.pick.unset::before { content: ""; width: 1.1rem; height: 1.1rem; border-radius: 50%;
                            border: 1.5px dashed var(--muted); }
/* What the list hangs off. `position: relative` and no z-index on purpose: a
   positioned element with `z-index: auto` does NOT open a stacking context, so
   the list's z-index below is weighed in the page's own context against the
   sticky header's — and 3 beats 2. Given a z-index here the wrapper would become
   the context, the list would be trapped inside it at the wrapper's own level,
   and a list left open while the page scrolls would be painted over by the
   header. `flex: none` for the same reason `.avatar` has it: this is the button's
   place in a line that wraps. */
.pickwrap { position: relative; flex: none; display: inline-flex; }
/* A popup, and no longer a row inside the group line. Twenty-five rows of drawing
   and name cannot be a line in a wrapping flex row: in flow they push every
   person below down by the height of the list, which is an accordion rather than
   a picker, and the reason the old arrangement could get away with a strip of
   bare buttons was that twelve of them fitted on one line.
   So it floats, and everything that arrangement bought — no positioning, no
   z-index, no argument with the sticky header two rows up — is paid for by the
   wrapper above and by the z-index here, both of them argued rather than tried.
   `max-height` and not a row count, so a set that grows again still scrolls
   inside itself rather than off the window. 15rem and not more because this
   opens downward and only downward: a list that flipped above the button on the
   rows near the bottom of the page and below it everywhere else is a list nobody
   can aim at, so the overhang is bounded instead, and the page scrolls to it.
   `.picker[hidden]` is (0,2,0) against `.picker`'s (0,1,0), so the attribute wins
   on specificity and not on source order — which matters because the shell's
   stylesheet is inlined before this one and a rule that relied on order would be
   the loser there. */
.picker { position: absolute; z-index: 3; top: calc(100% + .3rem); left: 0;
          margin: 0; padding: .2rem; list-style: none; min-width: 11rem;
          max-height: 15rem; overflow-y: auto; overscroll-behavior: contain;
          background: var(--surface); color: var(--fg);
          border: 1px solid var(--line-strong); border-radius: 3px;
          box-shadow: 0 4px 14px rgba(0,0,0,.12); font-size: 13px; }
.picker[hidden] { display: none; }
.picker .option { display: flex; align-items: center; gap: .45rem; cursor: pointer;
                  padding: .2rem .35rem; border-radius: 2px; white-space: nowrap; }
/* The drawing keeps its own box, so the names all start at the same x whatever
   width the drawing happens to use. A column of names that stepped in and out
   with the art is a column nobody can scan, which is the whole reason the names
   are here. */
.picker .art { flex: none; display: inline-flex; width: 1.25rem; height: 1.25rem; }
.picker .art svg { width: 100%; height: 100%; }
/* Where the keyboard is, in the colour the suggestion popup already uses for the
   same fact — one language for "this is the row you are on", on the two lists
   this application has. The drawing follows because it is `currentColor`. */
.picker .option.on { background: var(--accent); color: var(--on-accent); }
.picker .option:hover { background: var(--surface-2); }
.picker .option.on:hover { background: var(--accent); }
/* And which row is already yours, which is a different fact from the one above
   and so is drawn in a different channel: weight, not ground. Both at once is the
   ordinary case — you open the list on your own mark — and two grounds would
   have made that one row look like two states of the same thing. */
.picker .option[aria-selected="true"] { font-weight: 650; }
/* What the picker said. A line of its own under the group line, the same way the
   picker used to take one under the name — and not a cell at the end of the row, where
   `.tally`'s `margin-left: auto` had put it a full table's width away from the
   button it is about. Empty it is a zero-height line and costs the row a 2px
   gap; `display: none` on `:empty` would cost more than that, because a live
   region has to be in the accessibility tree BEFORE its text changes or the
   change is announced to nobody.

   Two colours in one region, because it carries two kinds of sentence: a
   receipt, which the mark changing beside it has already confirmed, and a
   refusal, which is the whole reason this element exists and has to be findable
   next to a button that otherwise looks like it did nothing. */
.groupline #state { flex: 0 0 100%; color: var(--muted); font-size: 12px; }
.groupline #state.bad { color: var(--warn); }
"""

_ROLES = (("owner", "owner"), ("assignees", "assignee"), ("reviewers", "reviewer"),
          ("shaped_by", "shaper"))

# Most answerable first. Grouped by entity — which is what building the rows one
# entity at a time gave you — a person with twenty rows had their four ownerships
# scattered through it, and ownership is the thing being on the page is for.
_ROLE_ORDER = ("owner", "assignee", "shaper", "reviewer")

# Which table filter answers "show me this person's <role>", and the words for
# what that link opens. The table facets three of the four fields a person's name
# can sit in; `shaped_by` is not one of them, so a shaper count stays a count
# rather than becoming a link to a filter the table does not have.
_ROLE_FILTER = {
    "owner": ("owner", "owns"),
    "assignee": ("assignees", "is assigned"),
    "reviewer": ("reviewers", "reviews"),
}


def _proposed(index: Index, number: int, window: tuple[date, date] | None) -> Cycle:
    """The record Save would write for a cycle nobody has written one for.

    Every date on it comes from where the rest of the tool already gets that
    cycle's dates: the `config/cycles.yaml` window, and `schedule.build_end`,
    which is what the overrun flag and the timeline's solid rule both read. This
    page must not have arithmetic of its own — it had, briefly, and it took the
    end of the WINDOW for the review meeting. Cool-down is inside a window, so
    cycle 36 offered 7.8 weeks of capacity against a build the scheduler ends
    seven weeks in: three answers about one cycle, and the largest of them was
    the number a betting table would have bet against.

    A cycle nobody has dated at all falls back to the team's cadence, and both
    dates are marked assumed so the page says so.
    """
    config = Config(holidays=index.holidays, cooldown_weeks=index.cooldown_weeks)
    if window is None:
        starts_on = index.today
        builds_until = days_after(starts_on, _DEFAULT_CYCLE_DAYS - 1)
        ends_on = days_after(builds_until, round(index.cooldown_weeks * 7))
    else:
        starts_on = window[0]
        builds_until = build_end(number, window, config)
        ends_on = window[1]
    return Cycle(
        cycle=number,
        starts_on=starts_on,
        # The meeting is the day after the last day of build, and nobody holds one
        # on a Saturday.
        reviews_on=config.next_working_day(builds_until),
        builds_until=builds_until,
        # A window whose cool-down is longer than the window itself would end
        # before its own build. One bad row in a config file, not a broken page.
        ends_on=max(ends_on, builds_until),
        build_weeks=config.working_weeks(starts_on, builds_until),
        # Nobody wrote either of them: the review is inferred from the global
        # cool-down, and the end is only as good as the window it came from.
        assumed_review=True,
        assumed_end=window is None,
    )


def _cycle_view(index: Index, number: int, links: Links = ROUTES) -> dict:
    """Everything the cycle page shows, computed once so the markup only lays out.

    A person's scheduled end date sits beside their capacity bar deliberately: a
    green bar next to a timeline that runs a month past the cycle is the failure
    that stops a room trusting the tool, and the two numbers come from different
    subsystems. Put together, they cannot quietly disagree.
    """
    plan = index.plans.get(number)
    held = index.load(number)
    nominal = index.nominal_availability
    window = index.cycles.get(number)
    # A cycle with no record has a page too, because the index links to every
    # cycle the plan names and not only to the ones somebody wrote down. That
    # page is a form: everything on it is the record Save would write — the
    # model's own default length, the config window's start if there is one, and
    # the team list as a roster to correct. An empty table with an add box next
    # to it is a form nobody can tell is working.
    # A cycle with no record is shown as the record Save would write, resolved
    # the same way a real one is: `with_plans` is what turns two meetings into
    # dates and a length, and doing that arithmetic a second time here is how the
    # form and the page start disagreeing about the same cycle.
    proposed = plan or _proposed(index, number, window)
    listed = list(plan.availability) if plan else list(index.known_people)
    ends_on = proposed.ends_on.isoformat() if proposed.ends_on else ""

    # Exactly who was named. Being on the roster IS being in the cycle, so a name
    # is added deliberately rather than appearing because somebody was assigned
    # something — which would make the roster a report instead of a decision.
    people = []
    for login in sorted(listed, key=str.lower):
        rate = proposed.availability.get(login, nominal)
        # Asked of the cycle rather than multiplied out here. It was
        # `rate * build_weeks`, which is `Cycle.capacity` written a second time —
        # and the cycles index already asks the cycle, so the two pages computed
        # one number two ways.
        capacity = proposed.capacity(login, nominal)
        # `counts_in` and not `cycle == number`, the same question the load column
        # asks. Filtering on the stamp alone hid every carried bet from the date
        # beside the bar — so the bar and the date agreed with each other and both
        # left out the work actually filling the person's weeks.
        mine = [
            index.spans[i].end
            for i, e in index.entities.items()
            if index.counts_in(e, number)
            and login in (e.assignees + ([e.owner] if e.owner else []))
            and i in index.spans
        ]
        people.append(
            {
                "login": login,
                "rate": rate,
                "capacity": capacity,
                "held": held.get(login, 0.0),
                "over": capacity and held.get(login, 0.0) > capacity,
                "percent": min(100, round(100 * held.get(login, 0.0) / capacity))
                if capacity
                else 0,
                "until": max(mine).isoformat() if mine else "—",
            }
        )

    # Bet into this cycle and not on its roster. Dropping them silently would
    # hide load from the one page that exists to add load up.
    strangers = sorted(set(held) - set(listed), key=str.lower)

    # Work bet earlier and still running. It keeps its own cycle number (D-C1), so
    # it is not "in" this cycle by the stamp — but it is being done with this
    # cycle's weeks, and it is counted above. Named here so the number can be
    # argued with rather than wondered about.
    carried = [
        {"id": i, "title": index.entities[i].title, "cycle": index.entities[i].cycle}
        for i in index.carried_into(number)
        # The same two exclusions `load` makes, so this list explains that number
        # and not a different one: a parent is a rollup and charges nothing, and
        # work with nobody on it charges nobody.
        if not index.children.get(i)
        and (index.entities[i].owner or index.entities[i].assignees)
    ]

    candidates = []
    # Ready first, then in progress, and by id inside each: the question at a
    # betting table is what to pick up, and what is already running is context.
    order = ("ready", "in_progress")
    for entity_id, entity in sorted(
        index.entities.items(), key=lambda kv: (order.index(kv[1].status)
                                                if kv[1].status in order else len(order),
                                                kv[0])
    ):
        # A bet is made on a pitch, or on a chore nobody pitched. A task under a
        # pitch is part of that bet and comes with it; a project is a container
        # for bets and is not one. Listing all three put a milestone and eleven
        # of its own tasks on the table beside the five pitches they belong to,
        # and ticking any of them stamped a second cycle onto one decision.
        if entity.status not in order or not is_bettable(entity):
            continue
        size, defaulted = size_weeks(
            entity, Config(default_task_effort=index.default_task_effort)
        )
        candidates.append(
            {
                "id": entity_id,
                "title": entity.title,
                "kind": entity.kind,
                "status": entity.status,
                "size": "" if defaulted else f"{size:g}",
                "size_field": "person_weeks",
                "size_hint": f"{size:g} assumed" if defaulted else "",
                "assignees": ", ".join(entity.assignees),
                "reviewers": ", ".join(entity.reviewers),
                "cycle": entity.cycle if entity.cycle is not None else "—",
                "in_cycle": entity.cycle == number,
                # Bet in an earlier cycle and still running: shown, counted, and
                # not re-stampable. Overwriting its cycle would move the deadline
                # its overrun is measured against and forgive the slip.
                "carried": entity.status == "in_progress"
                and entity.cycle is not None
                and entity.cycle < number,
            }
        )

    return {
        "number": number,
        "recorded": plan is not None,
        "dated": window is not None,
        "starts_on": proposed.starts_on.isoformat(),
        "reviews_on": proposed.reviews_on.isoformat() if proposed.reviews_on else "",
        "builds_until": proposed.builds_until.isoformat() if proposed.builds_until else "",
        "ends_on": ends_on,
        "build_weeks": f"{proposed.build_weeks:g}",
        "assumed_review": proposed.assumed_review,
        "assumed_end": proposed.assumed_end,
        "nominal": nominal,
        "people": people,
        "held": held,
        "strangers": strangers,
        "carried": carried,
        "over": [p["login"] for p in people if p["over"]],
        "candidates": candidates,
        # `_markdown` and not a bare `_MD.render`: a cycle's goal is a shaping
        # document like any other, and rendered its own way it was the one body
        # on the site whose uploaded figures pointed at the wrong prefix and
        # whose remote images still went to the network.
        "body": _markdown(without_comments(plan.body), links) if plan else Markup(""),
        # The source, for the box somebody types in. Rendered above it, edited
        # below it — the same two views of one field the detail page has.
        "raw_body": plan.body if plan else "",
        # The goal is a field and not prose, so it is drawn as text rather than
        # put through the markdown renderer: a sentence the room agreed on does
        # not want a heading level, and running it through `_markdown` would wrap
        # it in a paragraph that the layout above the table has to undo.
        "goal": plan.goal if plan else "",
    }


def render_cycle(
    index: Index, number: int, links: Links = ROUTES, base_commit: str | None = None
) -> str:
    view = _cycle_view(index, number, links)
    body = _ENV.from_string(_CYCLE).render(
        c=view,
        links=links,
        editable=base_commit is not None,
        base_commit=base_commit or "",
        combobox=_combobox_html(index),
    )
    return _page(
        f"openproj — cycle {number}",
        body,
        _DETAIL_STYLE + _CYCLE_STYLE + _SUGGEST_STYLE,
        links,
        # `/cycle/37` is not `/cycles`, and one cycle is what the Cycles listing is
        # a listing of — so the item that got you here is the item that stays lit.
        # The heading below is "Cycle 37", which is the thing you are looking at
        # and not the word in the nav, so it stays on the screen.
        "cycles",
        index.unreadable,
    )


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
    <a class="record" href="{{ links.entity }}{{ s.id }}">{{ s.id }}</a>
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


def _review(entity: Entity, links: Links, assets: dict[str, str]) -> tuple[Markup, str]:
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
    said = without_checklist(without_comments(_drop_repeated_title(entity.body, entity.title)))
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
    if any(text for _, text in checklist_items(entity.body)):
        return Markup(""), ""
    return Markup(""), _NOTHING_SAID


def _slide(index: Index, entity: Entity, links: Links, assets: dict[str, str]) -> dict:
    """One record, as the slide somebody would have typed out of it.

    Every number is read from where the site already keeps it: the tick and the
    percentage from `index.progress`, which counted them once for the table, the
    detail page and this; the links from `_pr_link`, which is what makes a
    reference in a fact row a link somebody can follow.
    """
    counted = index.progress.get(entity.id)
    size, defaulted = size_weeks(entity, Config(default_task_effort=index.default_task_effort))
    bet = bet_of(entity, index.entities)
    body, note = _review(entity, links, assets)
    return {
        "id": entity.id,
        "title": entity.title,
        # The `[GT4Py]` of the real deck. Blank where this record IS the bet —
        # an orphan chore, or a pitch nobody has broken into tasks — because a
        # bracket repeating the heading under it is furniture.
        "under": bet.title if bet is not None and bet.id != entity.id else "",
        "status": entity.status,
        "status_class": _status_class(entity.status),
        "people": ", ".join(_people_on(entity)),
        "size": f"{size:g}" + ("*" if defaulted else ""),
        # `counted.text` and `counted.fraction`, not a division written here: the
        # panel on the detail page and the meter in the table read the same two,
        # and a third arithmetic is a third answer.
        "text": counted.text if counted is not None else "",
        "percent": round(100 * counted.fraction) if counted is not None else 0,
        "points": [
            {"done": done, "text": _markdown_line(said, links, assets)}
            for done, said in checklist_items(entity.body)
        ],
        "prs": [_pr_link(ref) for ref in entity.prs],
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

    def order(pair: tuple[str, Entity]) -> tuple[str, str, str]:
        entity_id, entity = pair
        bet = bet_of(entity, index.entities)
        return (bet.title.casefold(), bet.id, entity_id) if bet else ("", "", entity_id)

    chosen = [
        entity
        for entity_id, entity in sorted(index.entities.items(), key=order)
        if cycle_of(entity, index.entities) == number and not index.children.get(entity_id)
    ]
    # Only the documents this deck actually draws. Reading every asset in the plan
    # would put a screenshot from cycle 30 inside a deck for cycle 37, and a deck
    # is already the heaviest page here.
    bodies = [entity.body for entity in chosen] + ([plan.body] if plan else [])
    assets = _inlined_assets(bodies, asset) if asset else {}
    slides = [_slide(index, entity, links, assets) for entity in chosen]
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
        _ENV.from_string(_DECK).render(d=view, links=links),
        _DETAIL_STYLE + _DECK_STYLE,
        links,
        # A deck is of a cycle, and the Cycles listing is the listing of cycles.
        # Same reasoning as `/cycle/<n>`: the item that got you here stays lit.
        "cycles",
        index.unreadable,
    )


def _cycle_numbers(index: Index) -> set[int]:
    """Every cycle the plan names.

    Three sets that are not the same set: the cycles with a record, the cycles
    config/cycles.yaml dates, and the cycles entities point at. A page that asks
    only one of them loses exactly the cycle somebody is looking for — the one
    holding work with nothing written down behind it.
    """
    return (
        set(index.plans)
        | set(index.cycles)
        | {e.cycle for e in index.entities.values() if e.cycle is not None}
    )


def _current_cycle(index: Index) -> int | None:
    """The cycle the plan is in now, or the nearest thing to one.

    The cycle whose window holds today; failing that the next one to start,
    because between two cycles the live question is the one coming; failing that
    the last one there was, because work bet into a cycle that has ended is still
    work somebody is holding. A cycle with no dates cannot be any of the three.
    """
    dated = sorted(index.cycles.items(), key=lambda pair: pair[1][0])
    for number, (starts, ends) in dated:
        if starts <= index.today <= ends:
            return number
    for number, (starts, _) in dated:
        if starts > index.today:
            return number
    return dated[-1][0] if dated else None


def _cycle_totals(index: Index, number: int) -> dict:
    """One cycle's card: what is bet against what there is to bet with.

    The bet counts every week charged to the cycle, including work belonging to
    somebody the roster does not name. Summing only the roster's rows made a
    cycle look emptier the more of it was bet by people nobody had added — which
    is the direction the number must never be wrong in.
    """
    plan = index.plans.get(number)
    window = index.cycles.get(number)
    bet = sum(index.load(number).values())
    capacity = (
        sum(plan.capacity(who, index.nominal_availability) for who in plan.availability)
        if plan
        else 0.0
    )
    return {
        "number": number,
        "recorded": plan is not None,
        "starts_on": plan.starts_on.isoformat()
        if plan
        else (window[0].isoformat() if window else ""),
        "builds_until": plan.builds_until.isoformat() if plan else "",
        "ends_on": plan.ends_on.isoformat()
        if plan
        else (window[1].isoformat() if window else ""),
        "people": len(plan.availability) if plan else 0,
        "bet": bet,
        "capacity": capacity,
        "percent": min(100, round(100 * bet / capacity)) if capacity else 0,
        "over": bool(capacity) and bet > capacity,
    }


def render_issues(
    index: Index, links: Links = STATIC, base_commit: str | None = None
) -> str:
    """The one page issues live on.

    They are not entities, so they are not on the table, the graph, the people
    page or the timeline — not by an exclusion in each of those, which somebody
    would eventually forget, but because nothing there ever sees one.
    """
    problems: dict[str, list[str]] = {}
    for problem in index.issue_problems:
        problems.setdefault(problem.entity_id, []).append(problem.message)

    rows = []
    for issue in sorted(
        index.issues.values(), key=lambda i: (i.opened_on or date.min, i.id), reverse=True
    ):
        state = issue.state(index.entities)
        rows.append(
            {
                "id": issue.id,
                "title": issue.title,
                "status": issue.status,
                "state": state,
                # An issue whose links decide its state cannot also be set by
                # hand: two ways to say one thing disagree the moment one is used.
                "derived": bool(issue.pitched_into) and issue.status != "shelved",
                "reported_by": issue.reported_by,
                "opened": issue.opened_on.isoformat() if issue.opened_on else "",
                "tags": ", ".join(issue.tags),
                "pitched_into": ", ".join(issue.pitched_into),
                "pitched": _links(issue.pitched_into, index, links),
                "body": issue.body,
                # `_markdown` and not a bare render: an issue body is a shaping
                # note like any other, and it gets the same image and PR handling.
                "rendered": _markdown(issue.body, links) if issue.body else "",
                "problems": problems.get(issue.id, []),
                "search": f"{issue.id} {issue.title} {' '.join(issue.tags)} "
                f"{issue.reported_by or ''} {issue.body}".lower(),
            }
        )

    columns = (
        ("state", "state"), ("title", "title"), ("reported_by", "reported by"),
        ("opened", "opened"), ("pitched", "pitched into"), ("tags", "tags"),
    )
    body = _fragment(
        _ISSUES,
        issues=rows,
        # An issue's state and its status are the same four words, which is why
        # one list serves the filter, the sort rank and the edit control here and
        # the notes page needs two.
        states=list(ISSUE_STATUS),
        closed=["done", "shelved"],
        columns=columns,
        human=_human,
        links=links,
        editable=base_commit is not None,
        record_table=Markup(_RECORD_TABLE),
        nothing=_nothing_rows(
            len(columns),
            empty=not rows,
            headline="No issues are open.",
            hint="An issue is something somebody noticed and nobody has fixed. "
                 "There is nothing here, which on a plan this size is good news.",
            filtered="No issue matches.",
            href=f"{links.issue}new" if base_commit is not None else "",
            button="Open an issue",
        ),
    )
    return _page(
        "Issues", body, _RECORD_STYLE + _SUGGEST_STYLE, links, "issues",
        unreadable=index.unreadable,
    )


def render_issue(
    index: Index,
    issue_id: str | None = None,
    links: Links = ROUTES,
    base_commit: str | None = None,
    signed_in: str = "",
) -> str:
    """One issue, or a blank one. The same page either way.

    A second, differently-shaped form for opening an issue is what made the tool
    feel like two tools the last time, so this is the create view and the edit
    view with one flag between them.
    """
    creating = issue_id is None
    issue = index.issues.get(issue_id or "") if not creating else None
    if not creating and issue is None:
        raise KeyError(issue_id)
    view = _issue_view(issue, index, links) if issue else _blank_issue()
    body = _fragment(
        _ISSUE,
        issue=view,
        creating=creating,
        statuses=list(ISSUE_STATUS),
        human=_human,
        links=links,
        editable=base_commit is not None,
        base_commit=base_commit or "",
        signed_in=signed_in,
        combobox=_combobox_html(index) if base_commit is not None else Markup(""),
        # The same machinery the notes page uses, and now the same shape as well:
        # two kinds and a picker to choose between them. A pitch when the fix is
        # worth a bet somebody argues for, a task when it is only worth doing —
        # which is the judgement the person reading the issue is already making,
        # and the one this control used to make for them by offering one exit.
        promote=(
            _promote_html(
                view["id"],
                PROMOTABLE["issue"],
                "The new record starts in Shaping, carrying this issue\u2019s title, its "
                "tags and its text, and saying in its own document that it came from "
                "here. Nothing else is carried: an issue has no owner and no size to "
                "give it. The issue stays open until what it became is done.",
                base_commit or "",
                links,
            )
            if base_commit is not None and not creating
            else Markup("")
        ),
        original={
            "title": view["title"],
            "status": view["status"],
            "reported_by": view["reported_by"] or "",
            "pitched_into": view["pitched_list"],
            "tags": view["tag_list"],
            "body": view["body"],
        },
    )
    title = "A new issue" if creating else view["title"] or view["id"]
    return _page(
        title, body, _RECORD_STYLE + _SUGGEST_STYLE, links, "issues",
        unreadable=index.unreadable,
    )


def _issue_view(
    issue: Issue, index: Index, links: Links, problems: dict[str, list[str]] | None = None
) -> dict:
    if problems is None:
        problems = {}
        for problem in index.issue_problems:
            problems.setdefault(problem.entity_id, []).append(problem.message)
    return {
        "id": issue.id,
        "title": issue.title,
        "status": issue.status,
        "state": issue.state(index.entities),
        # An issue whose links decide its state cannot also be set by hand: two
        # ways to say one thing disagree the moment one of them is used.
        "derived": bool(issue.pitched_into) and issue.status != "shelved",
        "reported_by": issue.reported_by,
        "opened": issue.opened_on.isoformat() if issue.opened_on else "",
        "tags": ", ".join(issue.tags),
        "tag_list": list(issue.tags),
        "pitched_into": ", ".join(issue.pitched_into),
        "pitched_list": list(issue.pitched_into),
        "pitched": _links(issue.pitched_into, index, links) or Markup("—"),
        "body": issue.body,
        "rendered": _markdown(issue.body, links) if issue.body else Markup(""),
        "problems": problems.get(issue.id, []),
        "search": f"{issue.id} {issue.title} {' '.join(issue.tags)} "
        f"{issue.reported_by or ''} {issue.body}".lower(),
    }


def _blank_issue() -> dict:
    return {
        "id": "", "title": "", "status": "ready", "state": "ready", "derived": False,
        "reported_by": "", "opened": "", "tags": "", "tag_list": [],
        "pitched_into": "", "pitched_list": [], "pitched": Markup(""),
        "body": "", "rendered": Markup(""), "problems": [], "search": "",
    }


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
    the picker's job on both pages. So both say Promote — the word the label above
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
        entity=links.entity,
    )


def render_notes(
    index: Index, links: Links = STATIC, base_commit: str | None = None
) -> str:
    """The one page notes live on.

    Like the issues page, and for the same reason: a note is not an entity, so
    the table, the graph, the timeline and the people page never see one. The
    difference between the two pages is the difference between the two records —
    an issue is something that is broken, a note is something that does not exist
    yet — and the whole of that difference is in the copy and in the columns.
    """
    problems: dict[str, list[str]] = {}
    for problem in index.note_problems:
        problems.setdefault(problem.entity_id, []).append(problem.message)

    # Through `_note_view`, which the note's own page also uses: the issues page
    # builds its row dict and its detail dict separately and they have already
    # gained fields at different times.
    rows = [
        _note_view(note, index, links, problems)
        for note in sorted(
            index.notes.values(), key=lambda n: (n.written_on or date.min, n.id), reverse=True
        )
    ]

    columns = (
        ("state", "state"), ("title", "title"), ("written_by", "written by"),
        ("written", "written"), ("became", "became"), ("tags", "tags"),
    )
    body = _fragment(
        _NOTES,
        notes=rows,
        # Two lists where the issues page needs one: `NOTE_STATUS` is what the
        # edit control may set, and `NOTE_STATES` is what a note may be found in
        # — they differ by `promoted`, which is derived from the link and can
        # therefore be filtered and sorted by but never chosen.
        states=list(NOTE_STATES),
        closed=["promoted", "dropped"],
        columns=columns,
        human=_human,
        links=links,
        editable=base_commit is not None,
        record_table=Markup(_RECORD_TABLE),
        nothing=_nothing_rows(
            len(columns),
            empty=not rows,
            headline="Nothing has been written down yet.",
            hint="A note is where an idea goes before anybody knows what it is: half "
                 "a thought, a name for something, a question nobody has answered. It "
                 "needs no owner, no size and no cycle \u2014 write it down now and find "
                 "out what it is later.",
            filtered="No note matches.",
            href=f"{links.note}new" if base_commit is not None else "",
            button="Write a note",
        ),
    )
    return _page(
        "Notes", body, _RECORD_STYLE + _SUGGEST_STYLE, links, "notes",
        unreadable=index.unreadable,
    )


def render_note(
    index: Index,
    note_id: str | None = None,
    links: Links = ROUTES,
    base_commit: str | None = None,
    signed_in: str = "",
) -> str:
    """One note, or a blank one. The same page either way, for the reason the
    issue page gives: a second, differently-shaped form for writing one down is
    what made the tool feel like two tools."""
    creating = note_id is None
    note = index.notes.get(note_id or "") if not creating else None
    if not creating and note is None:
        raise KeyError(note_id)
    view = _note_view(note, index, links) if note else _blank_note()
    body = _fragment(
        _NOTE,
        note=view,
        creating=creating,
        statuses=list(NOTE_STATUS),
        human=_human,
        links=links,
        editable=base_commit is not None,
        base_commit=base_commit or "",
        signed_in=signed_in,
        combobox=_combobox_html(index) if base_commit is not None else Markup(""),
        promote=(
            _promote_html(
                view["id"],
                PROMOTABLE["note"],
                "The new record starts in Shaping, carrying this note\u2019s title, its "
                "tags and its text, and saying in its own document that it came from "
                "here. Nothing else is carried: a note has no owner and no size to "
                "give it. This note stays, and points at what it became.",
                base_commit or "",
                links,
            )
            if base_commit is not None and not creating
            else Markup("")
        ),
        original={
            "title": view["title"],
            "status": view["status"],
            "written_by": view["written_by"] or "",
            "became": view["became_list"],
            "tags": view["tag_list"],
            "body": view["body"],
        },
    )
    title = "A new note" if creating else view["title"] or view["id"]
    return _page(
        title, body, _RECORD_STYLE + _SUGGEST_STYLE, links, "notes",
        unreadable=index.unreadable,
    )


def _note_view(
    note: Note, index: Index, links: Links, problems: dict[str, list[str]] | None = None
) -> dict:
    if problems is None:
        problems = {}
        for problem in index.note_problems:
            problems.setdefault(problem.entity_id, []).append(problem.message)
    return {
        "id": note.id,
        "title": note.title,
        "status": note.status,
        "state": note.state(index.entities),
        # A note whose link decides its state cannot also be set by hand: two ways
        # to say one thing disagree the moment one of them is used. `dropped` is
        # exempt, because a link does not un-say a decision.
        "derived": bool(note.became) and note.status != "dropped",
        "written_by": note.written_by,
        "written": note.written_on.isoformat() if note.written_on else "",
        "tags": ", ".join(note.tags),
        "tag_list": list(note.tags),
        "became": ", ".join(note.became),
        "became_list": list(note.became),
        "became_links": _links(note.became, index, links) or Markup("\u2014"),
        "body": note.body,
        # `_markdown` and not a bare render: a note is a shaping document in the
        # making, and it gets the same image and PR handling as one.
        "rendered": _markdown(note.body, links) if note.body else Markup(""),
        "problems": problems.get(note.id, []),
        "search": f"{note.id} {note.title} {' '.join(note.tags)} "
        f"{note.written_by or ''} {note.body}".lower(),
    }


def _blank_note() -> dict:
    return {
        "id": "", "title": "", "status": "thinking", "state": "thinking", "derived": False,
        "written_by": "", "written": "", "tags": "", "tag_list": [],
        "became": "", "became_list": [], "became_links": Markup(""),
        "body": "", "rendered": Markup(""), "problems": [], "search": "",
    }


def render_cycles(
    index: Index, links: Links = STATIC, base_commit: str | None = None
) -> str:
    # Every cycle the plan names, not only the ones with a file. A cycle dated in
    # config, or one that entities point at with nothing behind it, is exactly
    # the cycle somebody needs to find: it holds work and holds no record.
    numbers = _cycle_numbers(index)
    rows = [_cycle_totals(index, number) for number in sorted(numbers, reverse=True)]
    last = index.plans[max(index.plans)] if index.plans else None
    # The number to propose comes from the cycles the plan has *decided* — the
    # ones with a record and the ones config/cycles.yaml dates — and not from
    # every number an entity happens to mention. A plan whose cycles live only in
    # config would otherwise be offered cycle 1 while it is running cycle 37; but
    # unioning `entity.cycle` in overshoots the other way, and worse. One bet into
    # a cycle nobody has written down — which the listing above actively invites —
    # made the form propose the number after *that*, with no dates behind it, so
    # the real last cycle's end date was thrown away and the proposal started
    # today. Entity-referenced numbers belong to the listing; they are not a
    # decision about when the next cycle begins.
    decided = set(index.plans) | set(index.cycles)
    top = max(decided) if decided else 0
    ends = index.cycles.get(top)
    body = _ENV.from_string(_CYCLES).render(
        cycles=rows,
        links=links,
        editable=base_commit is not None,
        base_commit=base_commit or "",
        # Whether there is a page per cycle to link a card to. Only the server
        # serves one; `render_static` writes six files and no cycle is among
        # them, so on a rendered plan the card names its cycle and stops there.
        per_cycle_page=links.cycle.startswith("/"),
        # The next cycle's betting table is the day the last one's cool-down
        # ends, and its review meeting is as far from it as the last one's was:
        # both are true far more often than not, and both are corrected on the
        # new cycle's own page.
        next={
            "number": top + 1,
            # `days_after`, because the cycle this reads from may be the one
            # somebody dated at the end of the calendar: a day past that would be
            # `/cycles` gone too.
            "starts_on": days_after(ends[1], 1).isoformat()
            if ends
            else index.today.isoformat(),
            "reviews_on": days_after(
                days_after(ends[1], 1) if ends else index.today,
                _DEFAULT_CYCLE_DAYS
                if last is None or last.reviews_on is None
                else (last.reviews_on - last.starts_on).days,
            ).isoformat(),
            # Which cycle the roster below was taken from, which is the last one
            # with a record and not necessarily the last one that exists.
            "from_cycle": max(index.plans) if index.plans else top,
            # The people who worked the last cycle, at the rates they worked it
            # at. A team changes slowly and availability changes every cycle, so
            # this is a starting point to correct rather than a claim — and it
            # beats retyping fifteen names to change three of them.
            "roster": dict(sorted(last.availability.items(), key=lambda kv: kv[0].lower()))
            if last
            else {},
        },
        roster=last.availability if last else {},
    )
    return _page(
        "openproj — cycles", body, _DETAIL_STYLE + _CYCLE_STYLE, links, "cycles",
        index.unreadable,
    )


def _person_load(index: Index, logins: list[str]) -> dict:
    """What each person is on the hook for in weeks, against what they have.

    Counts were the old answer — "1 as owner, 2 as assignee, 12 as reviewer" adds
    a half-hour review to a six-week build and calls the sum a workload. The
    weeks come from `index.load`, the same function the cycle page bets with, so
    the two pages cannot come to different conclusions about the same person.

    One cycle, named on the page, rather than every cycle summed: availability is
    recorded per cycle, so adding up five cycles of it against a plan that only
    ever bets the current one makes everybody look idle. Weeks bet into any other
    cycle are carried separately instead of dropped — that number is usually the
    reason somebody is busier than this cycle says they are.
    """
    number = _current_cycle(index)
    plan = index.plans.get(number) if number is not None else None
    here = index.load(number) if number is not None else {}
    elsewhere: dict[str, float] = {}
    for other in _cycle_numbers(index) - {number}:
        for login, weeks in index.load(other).items():
            elsewhere[login] = elsewhere.get(login, 0.0) + weeks

    people = {}
    for login in logins:
        held = here.get(login, 0.0)
        # Being on the roster is being in the cycle, which is the cycle page's
        # rule. Falling back to the nominal rate for somebody nobody added would
        # invent availability out of a default and hide the fact that the bet is
        # off the books.
        rostered = plan is not None and login in plan.availability
        capacity = plan.capacity(login, index.nominal_availability) if rostered else 0.0
        people[login] = {
            "held": held,
            "capacity": capacity,
            "over": bool(capacity) and held > capacity,
            "percent": min(100, round(100 * held / capacity)) if capacity else 0,
            "elsewhere": elsewhere.get(login, 0.0),
        }
    return {"cycle": number, "recorded": plan is not None, "people": people}


def render_people(index: Index, links: Links = STATIC, editable: bool = False,
                  me: str = "") -> str:
    """Everyone in the plan, and what they are on the hook for.

    Built from the fields rather than from a roster: a page that reads a separate
    list of members shows people who have nothing to do and misses whoever was
    added this morning. That is also why `me` may be somebody with no row here,
    and why there is then no picker: the only place to put one would be a row for
    a person listed for holding nothing, which is the row this page does not draw.

    `editable` is the server and `me` is who it says may pick an icon. Both are
    needed for a picker and neither is inferred from the other — a static export
    is editable by nobody no matter whose name is in it, and a served page read
    by a stranger is the same. `me` is empty for anybody the write path would
    refuse, decided by the same function the write path asks: a control that can
    only answer 403 is a dead end you find by pressing it.
    """
    held: dict[str, list[dict]] = {}
    for entity_id, entity in sorted(index.entities.items()):
        span = index.spans.get(entity_id)
        for field, role in _ROLES:
            value = getattr(entity, field, None)
            for login in value if isinstance(value, list) else [value] if value else []:
                held.setdefault(login, []).append(
                    {
                        "role": role,
                        "id": entity_id,
                        "title": entity.title,
                        "kind": entity.kind,
                        "status": entity.status,
                        "span": f"{span.start} → {span.end}" if span else "—",
                        "search": f"{entity_id} {entity.title}".lower(),
                    }
                )

    for rows_for_person in held.values():
        rows_for_person.sort(key=lambda r: (_ROLE_ORDER.index(r["role"]), r["title"]))

    load = _person_load(index, list(held))
    people = []
    # Case-folded, or every capitalised login sorts ahead of the lowercase ones and
    # "alphabetical" means ASCII to the page and nothing to the reader.
    for login, rows in sorted(held.items(), key=lambda pair: pair[0].lower()):
        counts = {role: sum(1 for r in rows if r["role"] == role) for _, role in _ROLES}
        tally = [
            {"role": role, "n": counts[role], "field": _ROLE_FILTER.get(role, ("",))[0]}
            for role in _ROLE_ORDER
            if counts[role]
        ]
        # Which filter the name itself opens. The most answerable role they
        # actually hold, because a link to what somebody owns is an empty table
        # for somebody who owns nothing — and a link that lands on an empty table
        # teaches people the link is broken.
        opens = next((t["role"] for t in tally if t["field"]), None)
        # What this person has stored, and only if this version can draw it: a
        # `dragon` nobody has the art for must not mark a row in the picker, and
        # must not stop "No icon" from being the row the list opens on. Same
        # bargain as `icon_svg` one line down, said in the one place that has to
        # agree with it.
        chosen = index.icons.get(login, "")
        people.append(
            {
                "login": login,
                # The drawing, resolved here rather than in the template: an icon
                # name this version no longer draws comes back as nothing at all,
                # so the template asks whether there is a mark and never whether
                # there is a name.
                "art": icon_svg(chosen),
                "icon": chosen if chosen in _ICON_ART else "",
                "mine": editable and login == me,
                "rows": rows,
                "tally": tally,
                "link": {
                    "field": _ROLE_FILTER[opens][0],
                    "says": f"Everything {login} {_ROLE_FILTER[opens][1]}, in the table",
                }
                if opens
                else None,
                **load["people"][login],
            }
        )
    # Only values that are actually on the page: a filter offering a status
    # nobody holds is a dead end that looks like a bug.
    facets = {
        key: sorted({row[key] for rows in held.values() for row in rows})
        for key in ("role", "kind", "status")
    }
    body = _ENV.from_string(_PEOPLE).render(
        people=people,
        links=links,
        # Every icon, drawn once, for the picker. In `ICONS` order, which is the
        # sky, then the world, then the creatures: a list ordered by nothing is a
        # list a reader has to search rather than scan.
        icons=[{"name": name, "art": icon_svg(name)} for name in ICONS],
        editable=editable,
        # The same bar the plan's three views draw, over this page's own three
        # fields. Which hat somebody is wearing is not a field of an entity, so
        # `role` is only ever offered here.
        facets=_facets_html(facets, ("role", "kind", "status"), "Search person, entity, id"),
        load=load,
        filters=_FILTER_JS,
    )
    return _page("openproj — people", body, _PEOPLE_STYLE, links, "people", index.unreadable)


def _by_status(rows: list[dict]) -> list[dict]:
    """The index, in the order work moves through: shaping first, done last.

    A status nobody uses is left out rather than shown empty, and a status the
    validator does not know still gets a heading — the index is a way in, and an
    entity missing from it because its status is misspelt is invisible.
    """
    known = list(STATUSES)
    seen = sorted({row["status"] for row in rows}, key=lambda s: (s not in known, s))
    order = [s for s in known if s in seen] + [s for s in seen if s not in known]
    return [
        {"status": status, "entities": [r for r in rows if r["status"] == status]}
        for status in order
    ]


def render_detail(
    index: Index,
    links: Links = STATIC,
    only: str | None = None,
    base_commit: str | None = None,
    may_write: bool = False,
) -> str:
    """Every entity, or exactly one.

    The server serves one per route; the static build serves them all in a page
    that hides everything but the hash. Same markup, so the two cannot drift.
    """
    rows = _detail_rows(index, links)
    if only is not None:
        rows = [row for row in rows if row["id"] == only]
    # Every entity gets its facts, not only the one being served on its own route:
    # the static export renders them all, and it is the same page.
    for row in rows:
        entity = index.entities[row["id"]]
        row["rows"] = _fact_rows(index, entity, links)
        row["raw_body"] = entity.body
        # What deleting it would take with it, drawn into the confirmation before
        # anybody presses anything. From `cascade_of`, which is what the route
        # itself asks — a panel that listed the consequences from a second
        # derivation of them would be a panel that can be wrong about the commit
        # it is authorising.
        row["deletes"], row["frees"] = cascade_of(index, row["id"])
    body = _ENV.from_string(_DETAIL).render(
        entities=rows,
        groups=_by_status(rows),
        # Every entity this page holds, not the one in the URL: the static export
        # is all of them in one file, and the shell's banner has no other way to
        # tell "somebody changed what you are reading" from "somebody changed
        # something".
        showing=[row["id"] for row in rows],
        single=only is not None,
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
        yjs=_yjs() if base_commit is not None and may_write else Markup(""),
        coedit=_COEDIT if base_commit is not None and may_write else Markup(""),
    )
    return _page(
        "openproj — detail", body, _DETAIL_STYLE + _SUGGEST_STYLE, links, "detail",
        index.unreadable,
    )


_NO_ASIDE = Markup("")


def _titles(index: Index) -> dict[str, str]:
    """What each entity is called, for the menus whose values are ids.

    Only the Project facet has any today. It is the whole index rather than the
    projects alone because a value in a menu is a value in a menu — the day
    something else is filtered by id, this already knows its name.
    """
    return {entity_id: entity.title for entity_id, entity in index.entities.items()}


def _facets_html(
    facets: dict,
    fields: tuple[str, ...] = _PLAN_FACETS,
    search: str = "Search titles, tags, PRs, people",
    aside: Markup = _NO_ASIDE,
    titles: dict[str, str] | None = None,
) -> Markup:
    """The control bar, for any view that filters anything.

    One bar and one `matches()` in `_FILTER_JS`, rather than a copy per page: the
    table's dropdowns and the graph's have to mean the same thing, or a link
    somebody pasted filters differently depending on which view it opens in. The
    people page had written its own, over its own three fields, and had already
    drifted — same markup, a different search box.

    `titles` is what a value is called where the value itself is not a word: the
    Project menu's values are entity ids, because that is what the filter matches
    and what the URL has to carry, and a menu of `proj-370001` asks a reader to
    know the plan by heart. Given per page rather than looked up here, because
    this function is handed facets and not an index — the people page's three
    fields have no titles at all.

    `aside` rides at the far end of the search box's line. It is here rather than
    on each page because the sentence a view writes about itself was a full row on
    every one of them, and a row above the drawing is the most expensive place on
    these pages to put twelve words.
    """
    return _fragment(
        _FACETS, facets=facets, fields=fields, search=search, aside=aside,
        titles=titles or {},
    )


def _combobox_html(index: Index | None) -> Markup:
    """The suggestion data and the widget that filters it, for any page with inputs."""
    data = (
        _suggestions(index)
        if index
        else {"people": [], "entities": [], "tags": [], "prs": [], "cycles": []}
    )
    return _fragment(_COMBOBOX, suggest=data)


# The nav, as the field on `Links` each item points at and the word it wears. One
# list, because the mark for "you are here" has to be decided once: six links
# written out by hand were six places for a seventh page to be added and marked
# nowhere.
_RECORD_TABLE = """
<script>
// The list machinery both inboxes use: search, a state filter, sortable columns
// and columns you can drag by their edge.
//
// One copy, and the argument for sharing it is the same one that says NOT to
// share the entity table's. That table's version is wound through sticky
// columns, a narrow breakpoint and per-column expanders, none of which either
// inbox has — so it was written small a second time on purpose. Between the
// issues table and the notes table there is no such difference: they are one
// table over two kinds of record, and the second copy of a hundred and fifty
// lines is a hundred and fifty lines that drift.
function attachRecordTable(config) {
  const TABLE = config.table;
  // `tr[data-id]`, not every row: the empty-state rows live in the same tbody,
  // and one sorted, hidden and counted among the records is a page that says
  // "1 of 0" over a sentence explaining that there is nothing here.
  const ROWS = [...TABLE.querySelectorAll('tbody tr[data-id]')];
  const BODY_ROWS = TABLE.querySelector('tbody');
  const QUERY = config.search;
  const STATE = config.state;
  const RANK = config.rank;
  const WIDTH_KEY = config.widths;
  const WIDTHS = remembered.map(WIDTH_KEY);

  // Open records are the question these pages exist to answer, so they are what
  // each shows until somebody asks for more.
  function apply() {
    const text = QUERY.value.trim().toLowerCase();
    const wanted = STATE.value;
    let shown = 0;
    for (const row of ROWS) {
      const state = row.dataset.state;
      const open = !config.closed.includes(state);
      const matches =
        (wanted === '*' ? true : wanted ? state === wanted : open) &&
        (!text || row.dataset.text.includes(text));
      row.hidden = !matches;
      shown += matches ? 1 : 0;
    }
    config.shown.textContent = shown;
    // A header row over nothing reads as a broken page whichever emptiness it
    // is. This is the one the controls caused, so it is the one that can offer a
    // way out; the other two — no records at all, and a plan that would not load
    // — are drawn by the server and by the shell, because neither is something
    // pressing a button here could undo.
    if (config.nothing) config.nothing.hidden = shown > 0;
  }
  QUERY.oninput = apply;
  STATE.onchange = apply;
  if (config.clear) {
    config.clear.onclick = () => {
      QUERY.value = '';
      // Both controls, because a Clear that leaves the state select set is a
      // Clear that did not clear — the entity table already learned this one.
      STATE.value = '';
      apply();
    };
  }
  apply();

  // Sorting, the way the table view sorts: click to sort, click again to
  // reverse. `state` is a sequence rather than a word, so it gets a rank.
  let sorted = null;
  let reversed = false;
  const HEADS = [...TABLE.querySelectorAll('th[data-sort]')];

  const keyOf = head => head.dataset.sort;

  function applyWidths() {
    if (!Object.keys(WIDTHS).length) return;
    TABLE.style.tableLayout = 'fixed';
    let total = 0;
    for (const head of HEADS) {
      const width = WIDTHS[keyOf(head)];
      if (width) { head.style.width = width + 'px'; total += width; }
    }
    // A fixed layout divides the space it is given, so at 100% widening one
    // column silently squeezes every other — which is what freezing them was
    // meant to prevent. The table is as wide as its columns and scrolls in its
    // own box.
    TABLE.style.width = total + 'px';
  }

  // What each column needs with every cell on one line. Measured from a layout
  // that has forgotten the widths already applied, or a column can only ever be
  // measured wider than it currently is.
  function naturalWidths() {
    const applied = HEADS.map(head => head.style.width);
    HEADS.forEach(head => { head.style.width = ''; });
    TABLE.classList.add('measuring');
    TABLE.style.tableLayout = 'auto';
    TABLE.style.width = 'max-content';
    const natural = HEADS.map(head => head.getBoundingClientRect().width);
    TABLE.classList.remove('measuring');
    HEADS.forEach((head, i) => { head.style.width = applied[i]; });
    return natural;
  }

  HEADS.forEach((head, i) => {
    const grip = document.createElement('span');
    grip.className = 'grip';
    head.append(grip);
    // Double-click a grip and the column shrinks to what its widest cell needs
    // on one line — the width you would have dragged to, without the dragging.
    grip.ondblclick = event => {
      event.stopPropagation();
      WIDTHS[keyOf(head)] = Math.ceil(naturalWidths()[i]);
      remembered.set(WIDTH_KEY, JSON.stringify(WIDTHS));
      applyWidths();
    };
    grip.onpointerdown = event => {
      event.preventDefault();
      grip.classList.add('dragging');
      // Freeze every column first, or resizing one reflows all the others.
      for (const other of HEADS) {
        const key = keyOf(other);
        WIDTHS[key] = WIDTHS[key] || Math.round(other.getBoundingClientRect().width);
      }
      TABLE.style.tableLayout = 'fixed';
      const key = keyOf(head);
      const from = event.clientX;
      const was = WIDTHS[key];
      const move = e => {
        WIDTHS[key] = Math.max(40, was + e.clientX - from);
        applyWidths();
      };
      const stop = () => {
        grip.classList.remove('dragging');
        remembered.set(WIDTH_KEY, JSON.stringify(WIDTHS));
        removeEventListener('pointermove', move);
        removeEventListener('pointerup', stop);
      };
      addEventListener('pointermove', move);
      addEventListener('pointerup', stop);
    };
  });
  applyWidths();

  function mark() {
    for (const head of HEADS) {
      const here = head.dataset.sort === sorted;
      head.classList.toggle('sorted', here);
      // The direction was invisible, so a column looked the same sorted either
      // way. Announced as well as drawn: aria-sort is all a screen reader has.
      head.setAttribute('aria-sort', here ? (reversed ? 'descending' : 'ascending') : 'none');
      head.querySelector('.dir').textContent = here ? (reversed ? '▾' : '▴') : '';
    }
  }

  for (const head of HEADS) {
    head.querySelector('button').addEventListener('click', () => {
      const key = head.dataset.sort;
      reversed = sorted === key ? !reversed : false;
      sorted = key;
      const value = row => key === 'state'
        ? String(RANK.indexOf(row.dataset.state)).padStart(3, '0')
        : (row.dataset[key] || '');
      const order = [...ROWS].sort((a, b) => value(a).localeCompare(value(b)));
      if (reversed) order.reverse();
      // Inserted before the empty-state row rather than appended past it.
      // Appended, every record ends up BELOW "there is nothing here" the first
      // time somebody sorts a table that has records in it.
      const tail = BODY_ROWS.querySelector('tr.nothing');
      order.forEach(row => BODY_ROWS.insertBefore(row, tail));
      mark();
    });
  }
}
</script>
"""

# The two ways a record table can be empty that a script cannot undo, and the
# one it can. Drawn INSIDE the table body, with the control that gets you out of
# it, because an empty table with the message somewhere else is still a header
# row over a void — finding F1, which keeps coming back through new mechanisms.
_NOTHING = """
{% if empty %}
<tr class="nothing"><td colspan="{{ columns }}">
  <p class="headline">{{ headline }}</p>
  <p class="hint">{{ hint }}</p>
  {% if href %}<a class="button primary" href="{{ href }}">{{ button }}</a>{% endif %}
</td></tr>
{% else %}
<tr class="nothing" id="nomatch" hidden><td colspan="{{ columns }}">
  <p class="headline">{{ filtered }}</p>
  <p class="hint">Every one of them is hidden by the controls above.</p>
  <button type="button" id="clear-search">Clear the search</button>
</td></tr>
{% endif %}
"""


def _nothing_rows(
    columns: int, empty: bool, headline: str, hint: str, filtered: str,
    href: str = "", button: str = "",
) -> Markup:
    """The empty state for one record table, as table rows.

    Both cases are rendered here and only one of them can ever be on a page: with
    no records at all the server draws the sentence about the plan, and with some
    it draws the hidden row the filter reveals. The one that cannot happen is not
    rendered, so there is no chance of a page showing both.
    """
    return _fragment(
        _NOTHING, columns=columns, empty=empty, headline=headline, hint=hint,
        filtered=filtered, href=href, button=button,
    )


_ISSUES = """
<h1 class="sr-only">Issues</h1>
<p class="hint">Something somebody noticed. At the betting table somebody reads what
  is open and writes a pitch for what matters.</p>
{% if editable %}
<p class="editbar"><a class="button" href="{{ links.issue }}new">Open an issue</a></p>
{% endif %}
<div id="controls">
  <input id="q" type="search" placeholder="Search issues" aria-label="Search issues">
  <div class="facets">
    <label class="facet">state
      <select id="state-filter"><option value="">all open</option>
        {% for value in states %}<option value="{{ value }}">{{ human(value) }}</option>
        {% endfor %}
        <option value="*">everything</option>
      </select>
    </label>
  </div>
</div>
<div id="summary"><span id="shown">{{ issues|length }}</span> of {{ issues|length }}</div>
<div class="table-scroll"><table id="issues" class="records"><thead><tr>
  {#- A real button inside every header, the way the entity table does it: there
      is no way to tab to a table cell, so a click handler on the cell alone made
      sorting mouse-only. The direction glyph has its own reserved box so that
      sorting does not shove every header one glyph to the left. -#}
  {% for column, label in columns %}
  <th data-sort="{{ column }}" aria-sort="none"
    ><button type="button">{{ label }}<span class="dir" aria-hidden="true"></span></button></th>
  {%- endfor %}
</tr></thead><tbody>
  {% for issue in issues %}
  <tr data-id="{{ issue.id }}" data-state="{{ issue.state }}" data-text="{{ issue.search }}"
      data-title="{{ issue.title }}" data-reported_by="{{ issue.reported_by or '' }}"
      data-opened="{{ issue.opened }}" data-pitched="{{ issue.pitched_into }}"
      data-tags="{{ issue.tags }}">
    <td><span class="badge state-{{ issue.state }}">{{ human(issue.state) }}</span></td>
    <td><a href="{{ links.issue }}{{ issue.id }}">{{ issue.title }}</a></td>
    <td>{{ issue.reported_by or '—' }}</td>
    <td class="derived">{{ issue.opened or '—' }}</td>
    <td>{{ issue.pitched }}</td>
    <td>{{ issue.tags or '—' }}</td>
  </tr>
  {% endfor %}
  {{ nothing }}
</tbody></table></div>
{{ record_table }}
<script>
attachRecordTable({
  table: document.getElementById('issues'),
  search: document.getElementById('q'),
  state: document.getElementById('state-filter'),
  shown: document.getElementById('shown'),
  nothing: document.getElementById('nomatch'),
  clear: document.getElementById('clear-search'),
  rank: {{ states|tojson }},
  closed: {{ closed|tojson }},
  widths: 'openproj:issue-widths:1',
});
</script>
"""

_ISSUE = """
<p class="back"><a href="{{ links.issues }}">← all issues</a></p>
{% if editable %}
<p class="editbar">
  <button type="button" id="toggle">{{ 'Cancel' if creating else 'Edit' }}</button>
  <button type="button" id="save" {{ '' if creating else 'hidden' }}>
    {{ 'Open it' if creating else 'Save' }}</button>
  <span id="state" role="status" aria-live="polite"></span>
</p>
{% endif %}
<h1>{% if creating %}A new issue{% else %}<span class="read">{{ issue.title }}</span>
{% endif %}</h1>
{% if not creating %}
<p class="meta"><code>{{ issue.id }}</code> ·
  <span class="badge state-{{ issue.state }}">{{ human(issue.state) }}</span>
  {% if issue.opened %}· opened {{ issue.opened }}{% endif %}
  {% if issue.reported_by %}· by {{ issue.reported_by }}{% endif %}</p>
{% endif %}
<form id="edit" data-id="{{ issue.id }}" onsubmit="return false">
  <input type="hidden" name="base_commit" value="{{ base_commit }}">
  <input name="title" class="field title-field" value="{{ issue.title }}"
         placeholder="What did you notice?" autocomplete="off" aria-label="Title">
  <dl id="facts">
    <dt>State</dt>
    <dd><span class="read">{{ human(issue.state) }}</span>
      <select name="status" class="field" {{ 'disabled' if issue.derived else '' }}>
        {% for value in statuses %}<option value="{{ value }}"
          {{ 'selected' if value == issue.status else '' }}>{{ human(value) }}</option>
        {% endfor %}
      </select>
      {% if issue.derived %}<span class="hint">from the work it was pitched into</span>
      {% endif %}</dd>
    <dt>Reported by</dt>
    <dd><span class="read">{{ issue.reported_by or '—' }}</span>
      <input name="reported_by" data-suggest="people" class="field"
             value="{{ issue.reported_by }}" autocomplete="off"
             placeholder="{{ signed_in }}"></dd>
    <dt>Pitched into</dt>
    <dd><span class="read">{{ issue.pitched }}</span>
      <input name="pitched_into" data-type="list" data-suggest="entities" class="field"
             value="{{ issue.pitched_into }}" autocomplete="off"></dd>
    <dt>Tags</dt>
    <dd><span class="read">{{ issue.tags or '—' }}</span>
      <input name="tags" data-type="list" data-suggest="tags" class="field"
             value="{{ issue.tags }}" autocomplete="off"></dd>
  </dl>
  {% if issue.problems %}<ul class="problems">
    {% for problem in issue.problems %}<li>{{ problem }}</li>{% endfor %}</ul>{% endif %}
  <div class="doc read">{{ issue.rendered }}</div>
  {% if editable %}
  <p class="bodybar">
    <span id="marks" class="marks"></span>
    <span class="hint">paste or drop an image to put it in the plan</span>
    <span class="hint" id="upload" role="status" aria-live="polite"></span>
  </p>
  <textarea name="body" class="field body-field" rows="12"
            placeholder="What happened, and how to see it again.">{{ issue.body }}</textarea>
  {% endif %}
</form>
{{ promote }}
{{ combobox }}
{% if editable %}
<script>
const FORM = document.getElementById('edit');
const SAVE = document.getElementById('save');
const SAY = document.getElementById('state');
const BASE = FORM.querySelector('[name=base_commit]');
const BODY = FORM.querySelector('[name=body]');
const CREATING = {{ 'true' if creating else 'false' }};
const ORIGINAL = {{ original|tojson }};

attachUploads(BODY, document.getElementById('upload'));
attachEditing(BODY, document.getElementById('marks'));
for (const control of FORM.querySelectorAll('[data-suggest]')) attachSuggest(control);

function say(message) { SAY.textContent = message; }

function read(name) {
  const control = FORM.querySelector(`[name=${name}]`);
  if (!control) return null;
  const value = control.value.trim();
  if (control.dataset.type === 'list')
    return value ? [...new Set(value.split(',').map(s => s.trim()).filter(Boolean))] : [];
  return value;
}

function changed() {
  // Diffed against what was rendered, never serialised whole: sending every field
  // would overwrite whatever somebody else changed while this tab was open.
  const fields = {};
  for (const name of ['title', 'status', 'reported_by', 'pitched_into', 'tags']) {
    const now = read(name);
    if (now === null) continue;
    if (JSON.stringify(now) !== JSON.stringify(ORIGINAL[name])) fields[name] = now;
  }
  return fields;
}

function dirty() {
  const count = Object.keys(changed()).length + (BODY.value !== ORIGINAL.body ? 1 : 0);
  if (!CREATING) SAVE.hidden = !editing();
  SAVE.disabled = !CREATING && count === 0;
  if (!CREATING) say(count ? `${count} unsaved change${count === 1 ? '' : 's'}` : '');
}

function editing() {
  return CREATING || document.body.classList.contains('editing');
}

function show(on) {
  document.body.classList.toggle('editing', on);
  document.getElementById('toggle').textContent = on ? 'Cancel' : 'Edit';
  dirty();
}

FORM.addEventListener('input', dirty);
FORM.addEventListener('change', dirty);

if (!CREATING) {
  document.getElementById('toggle').onclick = () => {
    const on = !document.body.classList.contains('editing');
    if (!on) {
      // Cancel puts back what was rendered rather than reloading: a reload would
      // also throw away a body somebody is part way through.
      for (const name of ['title', 'status', 'reported_by', 'pitched_into', 'tags']) {
        const control = FORM.querySelector(`[name=${name}]`);
        if (!control) continue;
        const was = ORIGINAL[name];
        control.value = Array.isArray(was) ? was.join(', ') : (was ?? '');
      }
      BODY.value = ORIGINAL.body;
    }
    show(on);
  };
  show(false);
} else {
  // Creating IS editing. Without this the page rendered every control and then
  // hid all of them behind `body.editing`, so a new issue was a heading, a Save
  // button and nothing to type in.
  document.body.classList.add('editing');
  document.getElementById('toggle').onclick = () => { location.href = '{{ links.issues }}'; };
  dirty();
}

SAVE.onclick = async () => {
  SAVE.disabled = true;
  const route = CREATING ? '/api/issue' : `/api/issue/${FORM.dataset.id}`;
  const response = await fetch(route, {
    method: CREATING ? 'POST' : 'PATCH',
    headers: {'content-type': 'application/json'},
    body: JSON.stringify({
      base_commit: BASE.value,
      title: read('title'),
      fields: CREATING
        ? {...changed(), title: read('title')}
        : changed(),
      body: BODY.value,
    }),
  });
  const answer = await response.json();
  if (!response.ok) {
    SAVE.disabled = false;
    say(refusal(answer, response.status));
    return;
  }
  location.href = CREATING ? `{{ links.issue }}${answer.id}` : location.pathname;
};
</script>
{% endif %}
"""

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
    location.href = {{ entity|tojson }} + answer.id;
  };
})();
</script>
"""

_NOTES = """
<h1 class="sr-only">Notes</h1>
<p class="hint">Something somebody is thinking about, before anybody knows what it
  is. A note has no owner, no size and no cycle — when it turns out to be work,
  promote it and it becomes a project, a pitch or a task.</p>
{% if editable %}
<p class="editbar"><a class="button" href="{{ links.note }}new">Write a note</a></p>
{% endif %}
<div id="controls">
  <input id="q" type="search" placeholder="Search notes" aria-label="Search notes">
  <div class="facets">
    <label class="facet">state
      <select id="state-filter"><option value="">still thinking</option>
        {% for value in states %}<option value="{{ value }}">{{ human(value) }}</option>
        {% endfor %}
        <option value="*">everything</option>
      </select>
    </label>
  </div>
</div>
<div id="summary"><span id="shown">{{ notes|length }}</span> of {{ notes|length }}</div>
<div class="table-scroll"><table id="notes" class="records"><thead><tr>
  {% for column, label in columns %}
  <th data-sort="{{ column }}" aria-sort="none"
    ><button type="button">{{ label }}<span class="dir" aria-hidden="true"></span></button></th>
  {%- endfor %}
</tr></thead><tbody>
  {% for note in notes %}
  <tr data-id="{{ note.id }}" data-state="{{ note.state }}" data-text="{{ note.search }}"
      data-title="{{ note.title }}" data-written_by="{{ note.written_by or '' }}"
      data-written="{{ note.written }}" data-became="{{ note.became }}"
      data-tags="{{ note.tags }}">
    <td><span class="badge state-{{ note.state }}">{{ human(note.state) }}</span></td>
    <td><a href="{{ links.note }}{{ note.id }}">{{ note.title }}</a></td>
    <td>{{ note.written_by or '—' }}</td>
    <td class="derived">{{ note.written or '—' }}</td>
    <td>{{ note.became_links }}</td>
    <td>{{ note.tags or '—' }}</td>
  </tr>
  {% endfor %}
  {{ nothing }}
</tbody></table></div>
{{ record_table }}
<script>
attachRecordTable({
  table: document.getElementById('notes'),
  search: document.getElementById('q'),
  state: document.getElementById('state-filter'),
  shown: document.getElementById('shown'),
  nothing: document.getElementById('nomatch'),
  clear: document.getElementById('clear-search'),
  rank: {{ states|tojson }},
  // What "still thinking" hides. A promoted note is answered and a dropped one
  // was decided against; neither is an idea anybody is still turning over, which
  // is the only question this page opens with.
  closed: {{ closed|tojson }},
  widths: 'openproj:note-widths:1',
});
</script>
"""

_NOTE = """
<p class="back"><a href="{{ links.notes }}">← all notes</a></p>
{% if editable %}
<p class="editbar">
  <button type="button" id="toggle">{{ 'Cancel' if creating else 'Edit' }}</button>
  <button type="button" id="save" {{ '' if creating else 'hidden' }}>
    {{ 'Write it down' if creating else 'Save' }}</button>
  <span id="state" role="status" aria-live="polite"></span>
</p>
{% endif %}
<h1>{% if creating %}A new note{% else %}<span class="read">{{ note.title }}</span>
{% endif %}</h1>
{% if not creating %}
<p class="meta"><code>{{ note.id }}</code> ·
  <span class="badge state-{{ note.state }}">{{ human(note.state) }}</span>
  {% if note.written %}· written {{ note.written }}{% endif %}
  {% if note.written_by %}· by {{ note.written_by }}{% endif %}</p>
{% endif %}
<form id="edit" data-id="{{ note.id }}" onsubmit="return false">
  <input type="hidden" name="base_commit" value="{{ base_commit }}">
  <input name="title" class="field title-field" value="{{ note.title }}"
         placeholder="What are you thinking about?" autocomplete="off" aria-label="Title">
  <dl id="facts">
    <dt>State</dt>
    <dd><span class="read">{{ human(note.state) }}</span>
      <select name="status" class="field" {{ 'disabled' if note.derived else '' }}>
        {% for value in statuses %}<option value="{{ value }}"
          {{ 'selected' if value == note.status else '' }}>{{ human(value) }}</option>
        {% endfor %}
      </select>
      {% if note.derived %}<span class="hint">from what it became</span>
      {% endif %}</dd>
    <dt>Written by</dt>
    <dd><span class="read">{{ note.written_by or '—' }}</span>
      <input name="written_by" data-suggest="people" class="field"
             value="{{ note.written_by }}" autocomplete="off"
             placeholder="{{ signed_in }}"></dd>
    <dt>Became</dt>
    <dd><span class="read">{{ note.became_links }}</span>
      <input name="became" data-type="list" data-suggest="entities" class="field"
             value="{{ note.became }}" autocomplete="off"></dd>
    <dt>Tags</dt>
    <dd><span class="read">{{ note.tags or '—' }}</span>
      <input name="tags" data-type="list" data-suggest="tags" class="field"
             value="{{ note.tags }}" autocomplete="off"></dd>
  </dl>
  {% if note.problems %}<ul class="problems">
    {% for problem in note.problems %}<li>{{ problem }}</li>{% endfor %}</ul>{% endif %}
  <div class="doc read">{{ note.rendered }}</div>
  {% if editable %}
  <p class="bodybar">
    <span id="marks" class="marks"></span>
    <span class="hint">paste or drop an image to put it in the plan</span>
    <span class="hint" id="upload" role="status" aria-live="polite"></span>
  </p>
  <textarea name="body" class="field body-field" rows="12"
    placeholder="What is the idea, and what is confusing about it.">{{ note.body }}</textarea>
  {% endif %}
</form>
{{ promote }}
{{ combobox }}
{% if editable %}
<script>
const FORM = document.getElementById('edit');
const SAVE = document.getElementById('save');
const SAY = document.getElementById('state');
const BASE = FORM.querySelector('[name=base_commit]');
const BODY = FORM.querySelector('[name=body]');
const CREATING = {{ 'true' if creating else 'false' }};
const ORIGINAL = {{ original|tojson }};
const FIELDS = ['title', 'status', 'written_by', 'became', 'tags'];

attachUploads(BODY, document.getElementById('upload'));
attachEditing(BODY, document.getElementById('marks'));
for (const control of FORM.querySelectorAll('[data-suggest]')) attachSuggest(control);

function say(message) { SAY.textContent = message; }

function read(name) {
  const control = FORM.querySelector(`[name=${name}]`);
  if (!control) return null;
  const value = control.value.trim();
  if (control.dataset.type === 'list')
    return value ? [...new Set(value.split(',').map(s => s.trim()).filter(Boolean))] : [];
  return value;
}

function changed() {
  // Diffed against what was rendered, never serialised whole: sending every field
  // would overwrite whatever somebody else changed while this tab was open.
  const fields = {};
  for (const name of FIELDS) {
    const now = read(name);
    if (now === null) continue;
    if (JSON.stringify(now) !== JSON.stringify(ORIGINAL[name])) fields[name] = now;
  }
  return fields;
}

function dirty() {
  const count = Object.keys(changed()).length + (BODY.value !== ORIGINAL.body ? 1 : 0);
  if (!CREATING) SAVE.hidden = !editing();
  SAVE.disabled = !CREATING && count === 0;
  if (!CREATING) say(count ? `${count} unsaved change${count === 1 ? '' : 's'}` : '');
}

function editing() {
  return CREATING || document.body.classList.contains('editing');
}

function show(on) {
  document.body.classList.toggle('editing', on);
  document.getElementById('toggle').textContent = on ? 'Cancel' : 'Edit';
  dirty();
}

FORM.addEventListener('input', dirty);
FORM.addEventListener('change', dirty);

if (!CREATING) {
  document.getElementById('toggle').onclick = () => {
    const on = !document.body.classList.contains('editing');
    if (!on) {
      // Cancel puts back what was rendered rather than reloading: a reload would
      // also throw away a body somebody is part way through.
      for (const name of FIELDS) {
        const control = FORM.querySelector(`[name=${name}]`);
        if (!control) continue;
        const was = ORIGINAL[name];
        control.value = Array.isArray(was) ? was.join(', ') : (was ?? '');
      }
      BODY.value = ORIGINAL.body;
    }
    show(on);
  };
  show(false);
} else {
  // Creating IS editing. Without this the page rendered every control and then
  // hid all of them behind `body.editing`, so a new note was a heading, a Save
  // button and nothing to type in.
  document.body.classList.add('editing');
  document.getElementById('toggle').onclick = () => { location.href = '{{ links.notes }}'; };
  dirty();
}

SAVE.onclick = async () => {
  SAVE.disabled = true;
  const route = CREATING ? '/api/note' : `/api/note/${FORM.dataset.id}`;
  const response = await fetch(route, {
    method: CREATING ? 'POST' : 'PATCH',
    headers: {'content-type': 'application/json'},
    body: JSON.stringify({
      base_commit: BASE.value,
      title: read('title'),
      fields: CREATING
        ? {...changed(), title: read('title')}
        : changed(),
      body: BODY.value,
    }),
  });
  const answer = await response.json();
  if (!response.ok) {
    SAVE.disabled = false;
    say(refusal(answer, response.status));
    return;
  }
  location.href = CREATING ? `{{ links.note }}${answer.id}` : location.pathname;
};
</script>
{% endif %}
"""

# One stylesheet for both inboxes, for the reason `attachRecordTable` is one
# script: the issues table and the notes table are the same table over two kinds
# of record. `.records` and not `#issues, #notes`, so a third one costs a class
# on a `<table>` rather than an edit to fourteen selectors — which is how a rule
# comes to be right for two tables and missing on the third.
_RECORD_STYLE = """
.records { border-collapse: collapse; width: 100%; font-size: 13px; }
.records th, .records td {
  border-bottom: 1px solid var(--line); padding: .35rem .6rem; text-align: left;
  vertical-align: top;
  /* Border-box, or a width set from a measured box gains the padding again and
     every column grows by exactly one cell's worth on the first drag. The entity
     table carries this rule in its own stylesheet, which these pages do not
     get — and dragging one column here moved all six until it did. */
  box-sizing: border-box;
  /* A PR reference has no space in it, so at a narrow width it hangs over the
     next column instead of wrapping inside its own. */
  overflow-wrap: anywhere;
}
.records th { color: var(--muted); font-weight: 400; font-size: 11px;
              text-transform: uppercase; letter-spacing: .04em; user-select: none;
              position: sticky; top: 0; z-index: 3; background: var(--surface);
              /* A collapsed border is not painted on a sticky cell — the first row
                 scrolls straight over the top of it — so the rule is drawn inside
                 the box instead. */
              box-shadow: inset 0 -1px 0 var(--line); }
/* The grip is positioned against this. */
.records th { position: relative; }
/* And the grip itself, which the entity table carries in ITS stylesheet — so
   the span was rendered here with no width, no cursor and nothing to see: a
   control that existed, worked when a script poked it, and could not be reached
   by a hand. */
.records th .grip {
  position: absolute; top: 0; right: 0; width: 7px; height: 100%; cursor: col-resize;
}
.records th .grip::before {
  content: ""; position: absolute; top: 20%; bottom: 20%; right: 3px; width: 1px;
  background: var(--line-strong);
}
.records th .grip:hover::before,
.records th .grip.dragging::before { background: var(--accent); width: 2px; }
.records th button { font: inherit; color: inherit; letter-spacing: inherit;
                     text-transform: inherit; background: none; border: 0; padding: 0;
                     cursor: pointer; }
/* Reserved whether or not this is the sorted column, so sorting does not shove
   every header one glyph to the left. */
.records th .dir { display: inline-block; width: .8em; color: var(--accent); }
.records th.sorted { color: inherit; font-weight: 700; }
.records td:nth-child(2) { font-weight: 600; }
/* Except on the row that says there is nothing here, whose cell is the second
   one only by accident of spanning from it. */
.records tr.nothing td { font-weight: 400; }
.badge { font-size: 11px; text-transform: uppercase; letter-spacing: .04em;
         white-space: nowrap; }
/* Live above the page's ground, over for everything that is finished with. The
   word is in the element, so this is the second channel and not the only one —
   which is the whole reason these are text and not four dots. */
.state-ready { color: var(--accent); }
.state-in_progress { color: var(--accent); }
.state-thinking { color: var(--accent); }
.state-done { color: var(--muted); }
.state-shelved { color: var(--muted); }
.state-promoted { color: var(--muted); }
.state-dropped { color: var(--muted); }
/* The few rules these pages share with the detail page, copied rather than
   inherited. `_DETAIL_STYLE` carries the width grip and its transition, which is
   a control these pages do not have — and the motion inventory is right that a
   page should not ship animation for an element it never renders. */
.problems { color: var(--warn); padding-left: 1.1rem; }
.doc { border-top: 1px solid var(--line); padding-top: 1rem; }
.doc h2 { font-size: 1rem; margin: 1.2rem 0 .3rem; }
.doc code { background: var(--surface-2); padding: 0 .25em; }
.doc blockquote { margin: 0 0 1rem; padding-left: .8rem; color: var(--muted);
                  border-left: 2px solid var(--line-strong); }
/* `display: flex` and not `inline-block`, and NOT carrying `.field`: with that
   class on it, `body.editing .field` won on specificity and the bar went
   inline — putting the textarea on the same line as the buttons. */
.bodybar { display: none; gap: .6rem; align-items: baseline; margin: .8rem 0 .3rem; }
/* The second row sits under the first rather than a paragraph's worth away: they
   are two halves of one bar, and the box they belong to is below both. */
.bodybar.markbar { margin-top: .25rem; }
body.editing .bodybar { display: flex; }
#facts { display: grid; grid-template-columns: 10rem 1fr; gap: .35rem .9rem;
         margin: 1rem 0; align-items: baseline; }
#facts dt { color: var(--muted); font-size: 11px; text-transform: uppercase;
            letter-spacing: .04em; }
.field { display: none; }
body.editing .field { display: inline-block; }
body.editing .read { display: none; }
.title-field { font-size: 1.4rem; font-weight: 700; width: 100%; max-width: 44rem; }
.body-field { width: 100%; max-width: 44rem; font-family: ui-monospace, monospace;
              font-size: 13px; }
#facts .field { width: 100%; max-width: 28rem; font: inherit; font-size: 13px; }
/* The promotion bar. Hidden while the record is being edited: promoting carries
   the STORED body across, so offering it over a textarea somebody is halfway
   through is offering to promote a document they cannot see. */
#promote { display: flex; gap: .5rem; align-items: baseline; flex-wrap: wrap;
           border-top: 1px solid var(--line); margin-top: 1.5rem; padding-top: 1rem; }
body.editing #promote { display: none; }
#promote select { font: inherit; font-size: 13px; }
#promote .hint { margin: 0; }
"""


_NAV = (
    ("table", "Table"), ("graph", "Graph"), ("timeline", "Timeline"),
    ("cycles", "Cycles"), ("people", "People"), ("issues", "Issues"),
    ("notes", "Notes"),
)
_NAV_KEYS = frozenset(key for key, _ in _NAV)
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
) -> str:
    """Autoescaping protects entity titles inside the inner templates; the already
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
    return _ENV.from_string(_SHELL).render(
        title=title,
        content=Markup(content),
        style=Markup(style),
        csp=Markup(CSP),
        font=_font_uri(),
        icon=_icon_uri(),
        links=links,
        # The word map, on every page rather than in the three payloads that
        # happened to carry it. The hover card is drawn by three views and the
        # graph's payload is cytoscape elements — no `DATA` at all — so the card
        # read `in_progress` off a node and drew it as itself. `HUMAN` exists
        # because five pages inventing their own capitalisation is how one status
        # came to be spelled three ways on one screen; a card is the fourth page.
        words=HUMAN,
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
        # The shell writes the chip and legend rules for every status, so a
        # status added to the model cannot arrive with three of its four tokens
        # wired up and the fourth still spelled out on a line nobody edited.
        statuses=STATUSES,
        # Only the server has an event stream to listen to. A static page opening a
        # connection to nothing would retry forever in the console.
        live=links.table.startswith("/"),
    )


def preview_html(body: str, links: Links = ROUTES, title: str = "") -> str:
    """Markdown rendered for the preview pane, exactly as the page will render it.

    `_MD` and not a second MarkdownIt: the one built here had tables switched off,
    so a shaping doc's table previewed as a wall of pipes and then rendered as a
    table once saved — the preview disagreeing with the page about the one thing
    somebody opens a preview to check. HTML stays disabled in both, because the
    body is written by signed-in members and rendered back to every reader, and
    markdown-it-py leaves raw HTML alone by default.

    The title is what the page drops from the top of the document when the doc
    opens by restating it. Passed in rather than looked up, because a preview is
    of the box in front of somebody, which is not what is committed yet — and
    empty by default, which drops nothing.

    Routes by default: the only thing that asks for a preview is the server.
    """
    return _markdown(without_comments(_drop_repeated_title(body, title)), links)


def render_table(index: Index, links: Links = STATIC, base_commit: str | None = None) -> str:
    payload = _payload(index)
    blocking = [p for p in index.problems if p.severity == "blocker"]
    body = _ENV.from_string(_TABLE).render(
        payload=payload,
        blockers=len(blocking),
        # The population `?predicate=has_blocker` matches. One entity can carry
        # three problems, so the count and the filter it links to were counting
        # different things and the table opened shorter than the number promised.
        blocked=len({p.entity_id for p in blocking}),
        editable=base_commit is not None,
        base_commit=base_commit or "",
        links=links,
        columns=_columns_for(index),
        # The drawings the draft row's two controls are made of. Sent as values
        # and read by the script, rather than written out as two `<svg>` strings
        # in a template literal: this is the same argument the icon picker makes
        # against rebuilding its own art in JavaScript, one drawing per mark and
        # in the language the rest of this file's drawings are written in.
        marks=DRAFT_MARKS,
        why=_TABLE_WHY,
        facets=_facets_html(index.facets, titles=_titles(index)),
        filters=_FILTER_JS,
        combobox=_combobox_html(index),
    )
    return _page(
        "openproj — table", body, _TABLE_STYLE + _SUGGEST_STYLE, links, "table",
        index.unreadable,
    )


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
    body = _ENV.from_string(_GRAPH).render(
        editable=base_commit is not None,
        base_commit=base_commit or "",
        facets=_facets_html(index.facets, aside=_GRAPH_HINT, titles=_titles(index)),
        filters=_FILTER_JS,
        statuses=STATUSES,
        glyphs=STATUS_GLYPH,
        total=len(index.entities),
        links=links,
        elements=_elements(index),
        parent_kinds={kind: list(kinds) for kind, kinds in PARENT_KINDS.items()},
        cytoscape=_library("cytoscape.min.js"),
        elk=_library("elk.bundled.js"),
        cytoscape_elk=_library("cytoscape-elk.js"),
        compound_dnd=_library("cytoscape-compound-drag-and-drop.js"),
    )
    return _page("openproj — graph", body, _GRAPH_STYLE, links, "graph", index.unreadable)


_ZOOMS = (("2", "months"), ("6", "weeks"), ("14", "days"), ("30", "close"))


def render_timeline(
    index: Index,
    links: Links = STATIC,
    window: tuple[date | None, date | None] = (None, None),
    zoom: float | None = None,
) -> str:
    timeline = _timeline(index, window, zoom)
    body = _ENV.from_string(_TIMELINE).render(
        t=timeline,
        links=links,
        zooms=_ZOOMS,
        chosen=f"{zoom:g}" if zoom else "",
        # Whether this is a window or the whole plan. The date boxes echo what is
        # on screen either way — they used to echo the request, so the default view
        # showed two empty boxes under a sentence naming the dates it was drawing,
        # and the controls disagreed with the picture. What is lost by filling them
        # in is the answer to "am I looking at everything", and that is a sentence,
        # not two empty boxes.
        windowed=bool(window[0] or window[1]),
        statuses=STATUSES,
        row_px=_ROW_PX,
        bar_px=_BAR_PX,
        bar_top=_BAR_TOP,
        foot_px=_PLOT_FOOT_PX,
        glyph_dy=_GLYPH_DY,
        facets=_facets_html(
            index.facets,
            aside=_fragment(
                _TIMELINE_HINT, t=timeline, windowed=bool(window[0] or window[1])
            ),
            titles=_titles(index),
        ),
        filters=_FILTER_JS,
        # The rows the shared `matches()` reads, for the bars that were drawn. Not
        # the whole plan: a bar that is not on this window cannot be filtered onto it.
        bars={"rows": timeline["rows"], "human": HUMAN},
    )
    return _page(
        "openproj — timeline", body, _timeline_css(), links, "timeline", index.unreadable
    )


def render_static(index: Index, out_dir: Path, repo: Path | None = None) -> tuple[str, ...]:
    """The pages, and the images they name. Returns what it wrote, in order.

    Without the copy an exported plan renders every uploaded figure as a broken
    image — the markdown points at `assets/…` relative to the page, which is
    exactly right and exactly useless if the directory is not there.

    The names come back rather than being restated by the caller, because they
    already were: the export grew from three pages to six and the CLI went on
    announcing "index.html, graph.html and timeline.html" to somebody who had
    just been handed six files.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    assets = (repo / "assets") if repo else None
    if assets and assets.is_dir():
        shutil.copytree(assets, out_dir / "assets", dirs_exist_ok=True)
    written: list[str] = []
    for name, html in (
        ("index.html", render_table(index)),
        ("detail.html", render_detail(index)),
        ("people.html", render_people(index)),
        ("cycles.html", render_cycles(index)),
        ("issues.html", render_issues(index)),
        ("notes.html", render_notes(index)),
        ("graph.html", render_graph(index)),
        ("timeline.html", render_timeline(index)),
    ):
        (out_dir / name).write_text(html, encoding="utf-8")
        written.append(name)
    return tuple(written)
