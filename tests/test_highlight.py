"""Syntax highlighting in a code fence, done on the server.

Three claims, and none of them answers another.

The renderer's half is a parse: which fences get coloured, which are deliberately
left as ink, and whether the attributes markdown-it put on the tag are still
there afterwards — that last one is the regression this feature nearly shipped,
because a hand-built `<pre><code>` looks perfect on the Help page and silently
desyncs the record page's preview.

The stylesheet's half is a lookup: every class the highlighter can emit is either
coloured by `_code_css` or is one of the two this file knows it leaves as ink.
Pygments adds token types between releases, and a class nobody styled is not a
visible bug — it is one word drawn in the body ink, which is what an
unhighlighted fence looks like anyway.

The palette's half is arithmetic, and it lives in `test_themes.py` beside the
other contrast measurements: the eight hues are derived rather than taken, and
the reason is that taking them put 95 of 144 combinations below AA.
"""

from __future__ import annotations

import json
import re
from datetime import date
from html import unescape
from pathlib import Path

import pytest
from browser import chrome, measured_in

# `one_pitch` and `HEAD` from the card's own file, because the page under test
# here is the card's: a record with a document on it, and the commit the table
# is rendered at. Two spellings of "a pitch with a body" is how the two files
# end up asking about different rows.
from test_card import HEAD, one_pitch

from openproj.index import Index, build_index
from openproj.model import load_repo
from openproj.render import ROUTES, render_graph, render_table, render_timeline
from openproj.render.markdown import _lexer_for, _markdown
from openproj.render.styles import _CODE_COLOURS, _code_css

# What `_code_css` deliberately does not colour, and why each is on the list
# rather than an oversight. Both are extremely common — a run of spaces and a
# bare identifier — and both are the code's own ink by design.
UNCOLOURED = {"hl-w", "hl-n"}


def classes_in(html: str) -> set[str]:
    return set(re.findall(r'class="(hl-[a-z0-9]+)"', html))


def text_of(html: str) -> str:
    return re.sub(r"<[^>]+>", "", html)


def test_a_fence_that_names_its_language_is_coloured():
    drawn = str(_markdown('```python\nx = "one"  # note\n```\n', ROUTES))
    found = classes_in(drawn)
    assert "hl-s2" in found, f"the string is not coloured: {drawn}"
    assert "hl-c1" in found, f"the comment is not coloured: {drawn}"
    assert 'class="language-python"' in drawn


def test_a_fence_that_does_not_is_left_as_ink():
    """No guessing, and this is the whole of that rule.

    Pygments will analyse an unlabelled block and hand back its best guess. A
    shell session mis-guessed as Perl is a fence coloured confidently and wrongly,
    which is worse than the plain one it replaced: the colours read as
    information. A fence says what it is or it stays ink.
    """
    for info in ("", "nosuchlanguage"):
        drawn = str(_markdown(f"```{info}\nx = 1  # note\n```\n", ROUTES))
        assert not classes_in(drawn), f"{info!r} was highlighted anyway: {drawn}"


def test_the_text_survives_being_coloured():
    """Every character of the fence is still on the page, in order.

    Highlighting splits a line into spans, so nothing that reads the rendered
    page for a raw sentence will find one — but a reader must still see exactly
    what was typed, and `<` and `&` must still arrive escaped.
    """
    source = 'if a < b and c: print("hi")  # <not a tag>'
    drawn = str(_markdown(f"```python\n{source}\n```\n", ROUTES))
    assert "<not a tag>" not in drawn, "a fence's text reached the page as markup"
    # Unescaped rather than escaped by hand: which characters a renderer chooses
    # to escape is its business, and an expectation written as a chain of
    # `.replace` calls is a second, worse escaper that fails on the day the first
    # one starts escaping `>` as well.
    assert unescape(text_of(drawn)).strip() == source, text_of(drawn)


def test_a_hostile_language_name_does_not_reach_the_page_as_markup():
    """The info string is a thing a person types into a plan file.

    An unknown language is left alone by `_highlighted`, which means the name
    goes on to `class="language-…"` through markdown-it's own escaping. This is
    the fifth escaping bug this repository has been asked about; it is asked here
    too.
    """
    drawn = str(_markdown('```"><script>alert(1)</script>\nx\n```\n', ROUTES))
    assert "<script>" not in drawn, drawn


def test_the_attributes_on_the_tag_survive_the_highlighter():
    """**The regression this nearly shipped.**

    The first shape of this feature was a render rule that built its own
    `<pre><code class="language-x">`, and it looked right everywhere a person
    would have looked. What it dropped was `data-startline`, which `_source_lines`
    stamps on every block and which the record page reads to scroll the preview to
    the line being written (`detail.py`, `[data-startline]`). A shaping document
    with a code block in it would have scrolled to the wrong place, with nothing
    on any page to say why.

    Highlighting is markdown-it's `highlight` option now, so the tag stays theirs.
    """
    drawn = str(_markdown('# One\n\n```python\nx = "one"\n```\n', ROUTES))
    assert 'data-startline="3"' in drawn, drawn
    assert classes_in(drawn), "the fence lost its highlighting instead"


def test_every_class_the_highlighter_emits_is_either_coloured_or_known_ink():
    """The stylesheet is generated from Pygments' own table, and this is the
    check that the generation still reaches everything a real document produces.

    Written against rendered samples rather than against `STANDARD_TYPES`, because
    `_code_css` reads that table too and the two would agree by construction. What
    is asked here is what a page actually carries.
    """
    styled = set(re.findall(r"\.(hl-[a-z0-9]+)", _code_css()))
    samples = {
        "python": 'from x import y\n\n\n@dec\nclass A(B):\n    """d"""\n    n = 1.5e3\n',
        "bash": 'set -eu\nfor f in *.md; do echo "${f}"; done  # loop\n',
        "yaml": "key: value\nlist:\n  - one\n  - 2\n",
        "diff": "--- a\n+++ b\n-gone\n+here\n",
        "json": '{"a": [1, null, true], "b": "two"}\n',
    }
    for language, source in samples.items():
        drawn = str(_markdown(f"```{language}\n{source}```\n", ROUTES))
        loose = classes_in(drawn) - styled - UNCOLOURED
        assert not loose, f"{language}: emitted and never coloured: {sorted(loose)}"


def test_the_colour_table_covers_every_role_the_stylesheet_names():
    """`_CODE_COLOURS` maps token branches onto roles and `_code_css` writes the
    rules; a role in one and not the other is a `var(--code-…)` nothing defines,
    which paints as nothing at all rather than as a wrong colour.
    """
    named = set(re.findall(r"var\(--code-([a-z]+)\)", _code_css()))
    assert named == set(_CODE_COLOURS.values())


def test_an_unknown_language_is_asked_for_once():
    """`_lexer_for` is cached, and the cache has to survive a miss as well as a
    hit: `get_lexer_by_name` walks Pygments' whole alias registry before raising,
    and a shaping document is re-rendered on every keystroke of the preview.
    """
    _lexer_for.cache_clear()
    for _ in range(5):
        assert _lexer_for("nosuchlanguage") is None
        assert _lexer_for("python") is not None
    info = _lexer_for.cache_info()
    assert info.misses == 2, info


# --------------------------------------------------------------------------- #
# Where the rules are, which is every page — because the hover card is
# --------------------------------------------------------------------------- #


@pytest.fixture
def index(demo_root: Path) -> Index:
    records, config, _ = load_repo(demo_root)
    return build_index(records, config, date(2026, 8, 17))


def test_every_page_carries_the_highlighters_rules_exactly_once(index: Index):
    """jcanton, 2026-09-18: *"the little hover card body doesn't colour code
    blocks syntax (while the /detail page in preview and side-by-side does), can
    this be added?"*.

    Nothing was wrong with the markup. `/api/card/<id>` renders a record's body
    through the same function the record page uses, so the card has been drawing
    `<span class="hl-k">` for as long as it has drawn documents at all. The
    RULES were in `_DETAIL_STYLE`, which the table, the graph and the timeline do
    not load — a deliberate saving, made when the argument "those pages have no
    fence on them" was still true. The card is what made it false: every row on
    all three opens a shaping document, and a shaping document about code has
    fences in it.

    So the sheet is the shell's now. **Exactly once** is the other half: leaving
    the old copy in `_DETAIL_STYLE` would have been the cheap fix and would put
    eighty rules twice into the record page, the cycle pages, the deck and Help.
    """
    sheet = _code_css()
    pages = {
        "table": render_table(index, ROUTES, base_commit=HEAD, may_write=True),
        "graph": render_graph(index, ROUTES, base_commit=HEAD, may_write=True),
        "timeline": render_timeline(index, ROUTES),
    }
    for name, page in pages.items():
        assert page.count(sheet) == 1, (
            f"the {name} draws hover cards and carries the highlighter's rules "
            f"{page.count(sheet)} times"
        )


# The card's document, answered by the page itself: a `file://` page reaches no
# server, and what is being asked is what the card DOES with a fence rather than
# whether one arrives. `test_card.py` opens a card the same way and says why.
_A_FENCE_IN_A_CARD = """
<script>
window.fetch = async () => ({ok: true, json: async () => ({html: %s})});
showCard(DATA.rows[%s], 100, 100);
</script>
"""

_WHAT_COLOUR_THE_KEYWORD_IS = """
const body = CARD.querySelector('.card-body');
// `hl-kn` and not `hl-k`: Pygments draws `import` as Keyword.Namespace, which
// takes its own short name. Both walk up to the `keyword` role in
// `_CODE_COLOURS` — the branch is what is coloured, not the leaf — so the class
// a fence actually carries is the one to ask about.
const word = body ? body.querySelector('.hl-kn') : null;
return {
  drawn: !!word,
  word: word ? word.textContent : '',
  ink: getComputedStyle(body).color,
  colour: word ? getComputedStyle(word).color : '',
};
"""


def test_a_fence_in_a_card_is_coloured_on_a_page_that_draws_no_fence_itself(
    index: Index, tmp_path: Path
):
    """The claim a substring cannot make. A page can carry every rule in the sheet
    and still draw the keyword in the body ink — an `@media` block nobody matches,
    a `--code-keyword` that resolves to nothing, a selector one specificity step
    under `.card-body pre`. This asks Chrome what colour the word actually is.

    On the table, which has no fence of its own anywhere on it. That is the page
    the rules were missing from, and asking it of the record page would be asking
    the one page that always had them.
    """
    record_id = one_pitch(index)
    drawn = str(_markdown("```python\nimport kiln4py\n```\n", ROUTES))
    page = render_table(index, ROUTES, base_commit=HEAD, may_write=True).replace(
        "</body>", _A_FENCE_IN_A_CARD % (json.dumps(drawn), json.dumps(record_id)) + "</body>"
    )
    got = measured_in(
        chrome(), page, tmp_path / "cardfence.html", 1200, _WHAT_COLOUR_THE_KEYWORD_IS,
        height=800,
    )

    assert got["drawn"], "the card drew no highlighted span at all"
    assert got["word"] == "import", got["word"]
    assert got["colour"] and got["colour"] != got["ink"], (
        f"the keyword is drawn in the body's own ink ({got['ink']}), so the rules "
        "reached the page and nothing painted them"
    )
