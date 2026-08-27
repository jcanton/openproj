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

import re
from html import unescape

from openproj.render import ROUTES
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
