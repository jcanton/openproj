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


class _Unreadable(HTMLParser):
    """The shell's "not a record" banner: its headline, and each file it lists."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.found: list[str] = []
        self.headline = ""
        self._depth = 0
        self._text: list[str] | None = None
        self._kind = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        found = dict(attrs)
        if found.get("id") == "unreadable":
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
    """"<path> — <why>" for each plan file the page says is not a record.

    Read out of the parsed document and not searched for in the served bytes.
    The shell inlines its own stylesheet into every page and the comments in it
    name files, quote sentences and spell out `.unreadable` — a substring test
    for a path finds its answer in a CSS comment as happily as in a banner, which
    is exactly how two earlier assertions in this suite passed over nothing.
    """
    parser = _Unreadable()
    parser.feed(page)
    return parser.found


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
    """Every `<select>` on the page, as the list of options inside it."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.found: list[list[tuple[str, str]]] = []
        self._options: list[tuple[str, str]] | None = None
        self._value: str | None = None
        self._text = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "select":
            self._options = []
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
    return parser.found

