"""A rendered page, read the way a browser reads it rather than as a string.

A substring cannot tell markup from text, and it cannot tell either of them from
prose: the shell's stylesheet is inlined into every page, so a comment that
mentions a heading or names a control puts those exact characters into the served
bytes, and two assertions written as `"New entity" not in body` found their answer
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


def lit(page: str) -> list[str]:
    """The label of every nav item carrying `aria-current="page"`.

    A list and not a string, because "exactly one" is half of what a caller has to
    be able to say: a page that marks two items is as wrong as one that marks
    none, and a helper answering `str | None` cannot tell them apart.
    """
    return [label for label, _, marked in nav_of(page) if marked]
