"""A rendered page, read the way a browser reads it rather than as a string.

A substring cannot tell markup from text, and it cannot tell either of them from
prose: the shell's stylesheet is inlined into every page, so a comment that
mentions a heading or names a control puts those exact characters into the served
bytes, and two assertions written as `"New record" not in body` found their answer
in a CSS comment rather than in a button. Five escaping bugs had already shipped
under tests that asserted on substrings of a page.

Both parsers here answer questions the nav-and-headings round asked and could not
ask any other way: *which* heading is clipped, and *which* nav item is marked. A
regex for `<h1>` was correct until the heading gained a class, which is the same
week it gained one.

`browser.py` is for the questions a parser cannot answer either — whether
anything was painted. This is the layer below that: the document, parsed.
"""

from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
from typing import NamedTuple


class _Headings(HTMLParser):
    """Every top-level heading, as (classes, text)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.found: list[tuple[frozenset[str], str]] = []
        self._open = False
        self._classes: frozenset[str] = frozenset()
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        # No nesting to track: an `<h1>` inside an `<h1>` is not markup this app
        # can produce, and the one heading with a child — the detail page's title,
        # wrapped in a `<span class="read">` — closes on its own end tag.
        if tag == "h1":
            self._open, self._text = True, []
            self._classes = frozenset((dict(attrs).get("class") or "").split())

    def handle_endtag(self, tag: str) -> None:
        if tag == "h1" and self._open:
            self.found.append((self._classes, " ".join("".join(self._text).split())))
            self._open = False

    def handle_data(self, data: str) -> None:
        if self._open:
            self._text.append(data)


def headings(page: str) -> list[tuple[frozenset[str], str]]:
    """(classes, text) for each `<h1>`, in document order."""
    parser = _Headings()
    parser.feed(page)
    return parser.found


class _Nav(HTMLParser):
    """The nav's links, as (label, href, marked-as-current)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.found: list[tuple[str, str, bool]] = []
        self._in_nav = False
        self._link: tuple[str, bool] | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "nav":
            self._in_nav = True
        elif tag == "a" and self._in_nav:
            found = dict(attrs)
            self._link = (found.get("href") or "", found.get("aria-current") == "page")
            self._text = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._link is not None:
            href, marked = self._link
            self.found.append(("".join(self._text).strip(), href, marked))
            self._link = None
        elif tag == "nav":
            self._in_nav = False

    def handle_data(self, data: str) -> None:
        if self._link is not None:
            self._text.append(data)


def nav_of(page: str) -> list[tuple[str, str, bool]]:
    """(label, href, marked) for every link in the nav, in document order."""
    parser = _Nav()
    parser.feed(page)
    return parser.found


class _Unreadable(HTMLParser):
    """One of the shell's two file banners: its headline, and each file it lists.

    `which` is the section id — `unreadable` for the plan files that are not
    records, `unusable` for the config and cycle files that read and hold a
    number nothing can compute with. One parser for both because the two sections
    have the same shape on purpose and a second copy of this would be a second
    thing to keep in step; the id is the only thing that differs, and it is the
    only thing that tells a reader them apart.
    """

    def __init__(self, which: str = "unreadable") -> None:
        super().__init__(convert_charrefs=True)
        self._which = which
        self.found: list[str] = []
        self.headline = ""
        self._depth = 0
        self._text: list[str] | None = None
        self._kind = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        found = dict(attrs)
        if found.get("id") == self._which:
            self._depth = 1
            # A banner that exists says at least this much, so an empty one is
            # still distinguishable from no banner at all.
            self.headline = self.headline or "(no headline)"
            return
        if not self._depth:
            return
        # Every element inside counts, so the `<code>` wrapping the path does not
        # close the section on its own end tag.
        self._depth += 1
        if tag == "li" or "headline" in (found.get("class") or "").split():
            self._text, self._kind = [], tag
            self._kind = "item" if tag == "li" else "headline"

    def handle_endtag(self, tag: str) -> None:
        if not self._depth:
            return
        if self._text is not None and (
            (self._kind == "item" and tag == "li") or (self._kind == "headline" and tag == "p")
        ):
            said = " ".join("".join(self._text).split())
            if self._kind == "item":
                self.found.append(said)
            else:
                self.headline = said
            self._text = None
        self._depth -= 1

    def handle_data(self, data: str) -> None:
        if self._text is not None:
            self._text.append(data)


def unreadable_in(page: str) -> list[str]:
    """ "<path> — <why>" for each plan file the page says is not a record.

    Read out of the parsed document and not searched for in the served bytes.
    The shell inlines its own stylesheet into every page and the comments in it
    name files, quote sentences and spell out `.unreadable` — a substring test
    for a path finds its answer in a CSS comment as happily as in a banner, which
    is exactly how two earlier assertions in this suite passed over nothing.
    """
    parser = _Unreadable()
    parser.feed(page)
    return parser.found


def unusable_in(page: str) -> list[str]:
    """ "<path> — <why>" for each file the page says holds a number that is not one.

    `unreadable_in`'s sibling, and parsed rather than searched for the reason
    that one gives — with a second one here: the two banners are drawn with the
    same `class="unreadable"`, because they are the same weight and a second
    colour would be a channel carrying nothing. A substring test cannot tell them
    apart at all; the section id can.
    """
    parser = _Unreadable("unusable")
    parser.feed(page)
    return parser.found


def unusable_banner_says(page: str) -> str:
    """The headline of that banner, or "" when the page draws none."""
    parser = _Unreadable("unusable")
    parser.feed(page)
    return parser.headline


def banner_says(page: str) -> str:
    """The headline of that banner, or "" when the page draws no banner.

    Separate from the list, and not derived from it, because an empty list is the
    answer to two different questions: "there is no banner" and "there is a
    banner with nothing in it". A test written only against the list stayed green
    with the `{% if %}` around the section deleted — an empty red box announcing
    "0 files in the plan are not records" on every page in the app, which is the
    negative case it was written to hold and could not see.
    """
    parser = _Unreadable()
    parser.feed(page)
    return parser.headline


def lit(page: str) -> list[str]:
    """The label of every nav item carrying `aria-current="page"`.

    A list and not a string, because "exactly one" is half of what a caller has to
    be able to say: a page that marks two items is as wrong as one that marks
    none, and a helper answering `str | None` cannot tell them apart.
    """
    return [label for label, _, marked in nav_of(page) if marked]


class _Selects(HTMLParser):
    """Every `<select>` on the page, as the list of options inside it, and the id
    it carries — because not every dropdown on these pages is a filter. The
    colour-scheme picker in the corner is a preference, and "all" is not one of
    the things a palette can be."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.found: list[list[tuple[str, str]]] = []
        self.ids: list[str] = []
        self._options: list[tuple[str, str]] | None = None
        self._id = ""
        self._value: str | None = None
        self._text = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "select":
            self._options = []
            self._id = dict(attrs).get("id") or ""
        elif tag == "option" and self._options is not None:
            self._value = dict(attrs).get("value") or ""
            self._text = ""

    def handle_data(self, data: str) -> None:
        if self._value is not None:
            self._text += data

    def handle_endtag(self, tag: str) -> None:
        if tag == "option" and self._options is not None and self._value is not None:
            self._options.append((self._value, self._text.strip()))
            self._value = None
        elif tag == "select" and self._options is not None:
            self.found.append(self._options)
            self.ids.append(self._id)
            self._options = None


def selects(page: str) -> list[list[tuple[str, str]]]:
    """Every dropdown, and what each offers.

    The reason this is a parser and not a regex is the one in the docstring
    above, caught a second time: a stylesheet comment that names a `<select>`
    puts the characters of an opening tag into the served page, and a regex for
    `<select[^>]*>(.*?)</select>` matched the comment and read the next real
    dropdown's options as its contents. `HTMLParser` treats the body of a
    `<style>` as the text it is.
    """
    parser = _Selects()
    parser.feed(page)
    # The scheme picker is not a filter and has no "all". Dropped here rather
    # than in each caller, because every caller is asking about filters.
    return [
        options
        for options, which in zip(parser.found, parser.ids, strict=True)
        if which != "scheme"
    ]


class Element(NamedTuple):
    """One element: what it is, what it carries, and what it says."""

    tag: str
    attrs: dict[str, str]
    text: str


class _Elements(HTMLParser):
    """Every element in document order, each with the text it contains.

    The parsers above each answer one page's question. This one answers the
    question a rendered *document* raises, which is a different shape: markdown
    output is not a fixed set of controls but whatever the writer typed, so what
    a test needs is "which elements are these, and what is inside them" rather
    than "where is the nav".

    Text is closed on the end tag and stored back over the placeholder pushed on
    the start tag, so an element's text is everything inside it — `<li>` reports
    the checkbox's line and `<s>` reports the words that were struck out. Void
    elements have no end tag and no text, and are reported as they are seen.
    """

    # `<input>` is the one that matters here — a task list is an input inside a
    # list item — and the rest are named so that an unclosed `<br>` or `<img>`
    # cannot swallow the elements after it.
    VOID = frozenset("area base br col embed hr img input link meta param source track wbr".split())

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.found: list[Element] = []
        self._open: list[tuple[str, int, list[str]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.found.append(Element(tag, {k: v or "" for k, v in attrs}, ""))
        if tag not in self.VOID:
            self._open.append((tag, len(self.found) - 1, []))

    def handle_endtag(self, tag: str) -> None:
        # From the inside out, and everything inside an unclosed element is
        # closed with it: markdown-it emits well-formed markup, and a test that
        # silently dropped half a document because one tag was misspelt would be
        # a test that says nothing about the half it did read.
        for depth in range(len(self._open) - 1, -1, -1):
            if self._open[depth][0] != tag:
                continue
            for name, at, text in self._open[depth:]:
                said = " ".join("".join(text).split())
                self.found[at] = Element(name, self.found[at].attrs, said)
            del self._open[depth:]
            return

    def handle_data(self, data: str) -> None:
        for _, _, text in self._open:
            text.append(data)


def elements(page: str) -> list[Element]:
    """Every element of a rendered document, parsed rather than searched for.

    `"<h2>" in html` stopped being true the day a heading gained an attribute,
    which is what it should never have been asserting: the claim is that the
    document contains a level-two heading saying a particular thing, and that is
    a question about an element and not about a string of characters.
    """
    parser = _Elements()
    parser.feed(page)
    return parser.found


def tags(page: str) -> set[str]:
    """Every element name a rendered document actually contains.

    For the assertion whose whole content is "there is no `<img>` here" — which
    is the shape that kept being written as `"<img" not in page`, and which that
    string cannot answer for two reasons at once.

    **A page carries its own stylesheet and its own scripts.** Everything is
    inlined, so a `<style>` or `<script>` block is part of the text of every
    page this app renders, and a comment inside one that names the element it is
    describing satisfies the search. That is not a hypothetical: a comment added
    to `styles.py` saying that a `<code>` inside a `<pre>` is inline failed a
    deck test asserting `"<pre>" not in page` — a test about what a review slide
    carries, red because of prose about a selector. `html.parser` reads the
    contents of `<style>` and `<script>` as text, so nothing in either reaches
    this set.

    **And a substring cannot tell markup from text.** `&lt;script&gt;` in a
    rendered fence contains no `<script`, but `<script` appears in plenty of
    things that are not an element. Five escaping bugs shipped here under tests
    that asserted on substrings of a page; the claim in every one of them was
    about an element.
    """
    return {one.tag for one in elements(page)}


# The renderer's own source, as one text. It was one file until render.py became
# a package, and four tests read it off disk rather than restating what it
# contains: the `|safe` sweep, the one-escaper count, the marker corpus, and the
# `answer.detail` sweep. Each is asking "is this true of everything the renderer
# ships", so each has to see all of it — and a new module in the package must be
# swept the day it lands, not the day somebody remembers to add it to a list.
#
# `vendor.py` is in here although it sits outside the package: it holds the
# inlining that reads `static/` off the disk, it emits into the same pages, and
# leaving it out would be a hole in exactly the sweeps this exists for.
def render_paths() -> list[Path]:
    """Every file of Python the renderer is made of, in a stable order.

    The sweeps that read the renderer as SYNTAX need the files rather than the
    text: `from __future__ import annotations` has to be the first statement in
    a module, so a concatenation of modules is not parseable Python.
    """
    root = Path(__file__).resolve().parents[1] / "src" / "openproj"
    return sorted((root / "render").glob("*.py")) + [root / "vendor.py"]


def render_source() -> str:
    """The same files as one text, for the sweeps that read it as text."""
    return "\n".join(p.read_text(encoding="utf-8") for p in render_paths())
