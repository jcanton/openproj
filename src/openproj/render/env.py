"""The Jinja environment, its filters and globals, and the JSON that reaches a page."""

from __future__ import annotations

import json
from functools import cache

from jinja2 import Environment, Template
from markupsafe import Markup

from ..model import what_json_can_carry
from .tokens import LABELS, PRIORITY_GLYPH, STATUS_GLYPH, _human, _read_date, _status_class

# The three characters that can end a `<script>` block, spelled as JSON escapes.
# A translation table rather than a chain of `str.replace`: same result, and this
# file no longer substitutes anything into text a person could have typed.
_JSON_ESCAPES = str.maketrans({"<": "\\u003c", ">": "\\u003e", "&": "\\u0026"})


def _json(data: object) -> str:
    """JSON for a `<script>` block, with the characters that can end one escaped.

    Every page ships its data inlined, and `json.dumps` leaves `<` alone — so a
    record titled `</script>...` closed the block it was sitting in and everything
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


_ENV = Environment(autoescape=True)
# Jinja ships a `tojson`, and it is nearly this: `htmlsafe_json_dumps` spells out
# `<`, `>`, `&` and `\'` for the same reason `_json` does. Replaced rather than
# added beside, because two JSON filters on one environment is two guarantees to
# keep in step — and every `{{ x|tojson }}` already written on these pages is a
# data block in a `<script>`, which is exactly what `_json` is for.
_ENV.filters["tojson"] = _script_json


@cache
def _compiled(source: str) -> Template:
    """This template, lexed, parsed and compiled to Python exactly once.

    `Environment.from_string` compiles every time it is called — Jinja's own
    cache hangs off a loader and `get_template`, and there is no loader here
    because the templates are string constants in this module. So the fourteen
    of them were being recompiled per call, and the calls are per record: the
    hill is a fragment, the promote menu is a fragment, and a plan with 479
    records rendered its pages through 6,739 separate `compile()` calls.
    Measured on that corpus, one export took 43.6 seconds and 21 of them were
    inside `jinja2.visitor`; with this cache it takes 0.74. The frozen golden
    corpus went 0.66s to 0.026s, and one served `/detail` 60ms to 5ms.

    Keyed on the source rather than on a name because that is what the call
    sites have, and it costs nothing: the keys are the module constants
    themselves, already resident, and there are fourteen distinct ones. Nothing
    here builds a template string at run time, so the cache cannot grow.

    A compiled `Template` is stateless and re-renderable by design, and filters
    are resolved against the environment at render time rather than baked in at
    compile time — so `_ENV.filters["tojson"]` above still applies. Checked
    rather than assumed: every page of both corpora, static and served, is
    byte-identical with the cache and without it.
    """
    return _ENV.from_string(source)


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
    return Markup(_compiled(template).render(**values))


# Available to every template as both `human(x)` and `x|human`, so no page has to
# be handed the map, and as `label(field)` for a field name.
_ENV.globals["human"] = _human
_ENV.filters["human"] = _human
# The mark that says the same thing the colour says, for every legend and every
# shape that draws one. Unknown values get nothing rather than a box glyph.
_ENV.globals["glyph"] = lambda status: STATUS_GLYPH.get(str(status), "")
# The five slots, of which `level` are lit. A macro rather than a string built in
# each template, so the markup the browser writes and the markup Jinja writes are
# the same markup.
# The mark that goes in front of a word where only a string will do. One function
# for both ladders, so a template asks for "the mark for this value" rather than
# knowing which map to reach into.
_ENV.globals["mark"] = lambda kind, value: (
    f"{STATUS_GLYPH.get(str(value), '')} " if kind == "status"
    else f"{PRIORITY_GLYPH.get(str(value), '')} "
)
_ENV.globals["pri"] = lambda value: PRIORITY_GLYPH.get(str(value), "")


_ENV.globals["on"] = _read_date
_ENV.globals["label"] = lambda field: LABELS.get(field, field)
# Every chip on every page names its rung through this, so the templates that
# call it (grep `{{ status_class(`: the cycle page's betting table, the people
# page) cannot disagree with the Python callers (grep `_status_class(`: the
# timeline's bars, `_progress_view`, the deck's `_slide`). They did:
# the detail page's meta line escaped the status into its class and the facts
# list two elements away did not, which is one page holding both answers.
_ENV.globals["status_class"] = _status_class
