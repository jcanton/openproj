"""The Help page: the repository's own documentation, drawn inside the app.

The page has no plan behind it, so almost nothing here is about records. What it
is about is the seam between this code and a handful of files on a disk — which is
where every way this can break lives: a file renamed, a container built without
them, a heading that collides with another document's, a contents entry pointing
at an id nothing draws.

Nothing here counts the documents. `DOCS` is the list, every assertion is written
against it, and a count in a docstring is the thing AGENTS.md says has been wrong
every time it was written down.

Parsed rather than searched, for `pages.py`'s reason: the shell's stylesheet is
inlined into every page, so `"Quickstart" in page` is answered by a CSS comment as
readily as by a heading.
"""

from __future__ import annotations

import re
from datetime import date
from html.parser import HTMLParser
from pathlib import Path

import pytest

from openproj.index import Index, build_index
from openproj.model import Unreadable, load_repo
from openproj.render import ROUTES, STATIC, render_help
from openproj.render.help import DOCS, _read_doc, _without_title
from openproj.vendor import _docs_root


class _Page(HTMLParser):
    """Every id the page draws, every in-page link, and every heading with the
    document it is inside.

    One parser and not three passes with a regex, because two of the three
    questions are about *duplicates* — `ids` is a list rather than a set on
    purpose, so a heading drawn twice is visible here instead of collapsing into
    the answer that says everything is fine.

    Whether a heading is a document's is decided by the `<section>` it is in and
    never by counting depth. The first version of this counted every start tag
    inside `.helpdocs` and decremented on every end tag, which drifts upwards for
    ever the first time a document contains an `<hr>` or an `<img>`: a void
    element opens and never closes, so the counter never comes back to zero and
    the parser thinks it is still inside the documents for the rest of the page.
    Sections do not nest here, so a flag set on one and cleared on its end tag is
    both simpler and right.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.ids: list[str] = []
        self.fragments: list[str] = []
        # (tag, text, the section id it is inside, or "" for the page's own).
        self.headings: list[tuple[str, str, str]] = []
        self.sections: list[str] = []
        self._section = ""
        self._heading: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        found = dict(attrs)
        classes = set((found.get("class") or "").split())
        if found.get("id"):
            self.ids.append(found["id"])
        if tag == "a" and (found.get("href") or "").startswith("#"):
            self.fragments.append(found["href"][1:])
        if tag == "section" and "helpdoc" in classes:
            self._section = found.get("id") or ""
            self.sections.append(self._section)
        if re.fullmatch(r"h[1-6]", tag):
            self._heading, self._text = tag, []

    def handle_endtag(self, tag: str) -> None:
        if tag == self._heading:
            self.headings.append(
                (tag, " ".join("".join(self._text).split()), self._section)
            )
            self._heading = None
        if tag == "section":
            self._section = ""

    def handle_data(self, data: str) -> None:
        if self._heading:
            self._text.append(data)

    def in_documents(self) -> list[tuple[str, str]]:
        return [(tag, text) for tag, text, section in self.headings if section]


def parsed(page: str) -> _Page:
    found = _Page()
    found.feed(page)
    return found


@pytest.fixture
def index(seed_root: Path) -> Index:
    """The corpus, only so the shell has an `Index` to draw its banner from.

    Nothing on this page comes from a plan, and every assertion below would be
    the same against an empty one — the index is here because `render_help` takes
    one, and it takes one because the unreadable-files banner is on every page.
    """
    records, config, unreadable = load_repo(seed_root)
    return build_index(records, config, date(2026, 8, 17), unreadable)


@pytest.fixture
def page(index: Index) -> str:
    return render_help(index, ROUTES)


def test_every_document_the_page_names_is_a_file_in_this_repository():
    """`DOCS` is a list of paths and nothing checks them at import time.

    Renaming `docs/EDITOR.md` is a normal thing to do, and without this the only
    symptom is a section on a page nobody opens saying it could not be read. The
    root comes from `_docs_root`, so this also fails if the resolution itself
    stops working in a checkout.
    """
    root = _docs_root()
    missing = [doc.path for doc in DOCS if not (root / doc.path).is_file()]
    assert not missing, f"named in DOCS and not in the repository: {missing}"


def test_the_page_draws_one_section_per_document_and_no_failures(page: str):
    found = parsed(page)
    assert found.sections == [f"doc-{doc.key}" for doc in DOCS]
    assert 'class="unread"' not in page, "a document could not be read"


def test_a_document_that_cannot_be_read_costs_that_document_and_nothing_else(
    tmp_path: Path,
):
    """The failure mode the container has and a checkout does not.

    `Dockerfile` has to copy `docs/` and `README.md` in; the day it does not, this
    is what the page must do — name the file and go on drawing the rest, rather
    than raise out of `render_help` and take the route with it.

    Asked of `_read_doc` with a root that has nothing in it, which is exactly the
    shape of an image built without the COPY.
    """
    text, why = _read_doc(tmp_path, DOCS[0])
    assert text == ""
    assert why, "a document that could not be read has to say why"
    # And with no root at all — `_docs_root` raising — which is the other half.
    assert _read_doc(None, DOCS[0])[1]


def test_no_id_is_drawn_twice(page: str):
    """The documents share one fragment space, and a heading is not unique across
    them — `## The pages` and `## The body` are each in more than one file over the
    corpus's life. Unprefixed, the second draws an id nothing can reach and both
    contents entries lead to the first, which looks exactly like a working page.
    """
    found = parsed(page)
    twice = sorted({i for i in found.ids if found.ids.count(i) > 1})
    assert not twice, f"drawn more than once: {twice}"


def test_every_contents_entry_points_at_something_on_the_page(page: str):
    found = parsed(page)
    dangling = sorted(set(found.fragments) - set(found.ids))
    assert not dangling, f"contents entries with no target: {dangling}"
    # And the other direction, which is the one that goes wrong silently: a
    # document whose headings were not collected draws a title in the contents
    # and nothing under it.
    for doc in DOCS:
        assert any(f.startswith(f"{doc.key}-") for f in found.fragments), \
            f"{doc.path} contributed no headings to the contents"


def test_a_document_is_demoted_under_the_heading_that_names_it(page: str):
    """The section's own `<h2>` is the document's name, so the document's `##`
    has to be an `<h3>`. Left alone they are siblings of the heading they sit
    under, and a heading list — which is how the reader this app's floor is
    written for navigates — shows a flat row of documents with no contents.
    """
    found = parsed(page)
    levels = [tag for tag, _ in found.in_documents()]
    assert "h1" not in levels, "a document kept a top-level heading"
    assert levels.count("h2") == len(DOCS), "one h2 per document, and no more"
    assert "h3" in levels, "no document contributed a section heading"


def test_the_documents_own_title_line_is_not_drawn_twice(page: str):
    """Every one of them opens by naming itself, because in git that heading is
    the only thing naming the file. Under an `<h2>` saying nearly the same words
    it reads as a rendering fault.
    """
    assert _without_title("# Quickstart\n\nBody\n") == "Body\n"
    assert _without_title("Body\n") == "Body\n", "a file with no heading keeps its first line"
    labels = [text for tag, text in parsed(page).in_documents() if tag == "h2"]
    assert labels == [doc.label for doc in DOCS]


def test_the_page_is_the_same_in_both_modes(page: str, index: Index):
    """The one view that renders identically served and exported: it is about the
    tool and not about a plan, which is why it can be a nav item at all — a nav
    link into a file nobody wrote is a dead link on every other exported page.
    """
    exported = render_help(index, STATIC)
    assert parsed(exported).sections == parsed(page).sections
    assert 'class="unread"' not in exported


def test_the_container_carries_the_documents():
    """The Dockerfile is the one place this breaks where no other test looks.

    The image copies `src/`, `static/` and `boot.py` and nothing else, so a Help
    page that reads files off a disk is a Help page that draws six failures in
    production while every test here passes in a checkout.
    """
    root = Path(__file__).resolve().parents[1]
    text = (root / "Dockerfile").read_text(encoding="utf-8")
    assert "docs/" in text and "/app/docs/" in text, "docs/ is not copied into the image"
    assert "README.md" in text, "README.md is not copied into the image"
    assert "OPENPROJ_DOCS" in text, "the image does not say where its documentation is"

    # And the other half, which is the half that actually broke. `COPY docs/`
    # was in the Dockerfile and the build still failed — `.gcloudignore` decides
    # what is uploaded as the build context, `docs/` was listed there under "not
    # part of the running service", and it stopped being true the moment the Help
    # page started reading those files. Nothing in CI builds an image, so a green
    # suite said nothing about it; this line is what a green suite now says.
    ignored = [
        line.strip()
        for line in (root / ".gcloudignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    for wanted in ("docs/", "docs", "README.md", "*.md", "**/*.md"):
        assert wanted not in ignored, (
            f".gcloudignore excludes {wanted!r}, so the documentation never reaches "
            "the build context and `COPY docs/` fails"
        )


def test_the_separator_in_the_build_row_is_a_character_and_not_an_escape(page: str):
    """`content: "\\00B7"` in a Python triple-quoted string is an OCTAL escape, and
    the page shipped a NUL byte followed by the text `B7` — which CSS replaces
    with U+FFFD, so the footer read `openproj 0.37.0 <?>B7 plan 1234abc` on every
    page of the app. It resolved, it parsed, and it drew the wrong glyph.
    """
    assert "\x00" not in page, "a NUL byte reached the page"
    assert "�" not in page, "a replacement character reached the page"
    assert '#build > * + *::before { content: "·"' in page


def test_the_build_row_hides_a_fact_that_has_not_arrived(page: str):
    """`#planhead` is filled by the health poll and is empty until it answers. The
    dot before it has to go with it, or the row reads `openproj 0.37.0 · ·
    Report issue` for the second before the poll lands and for ever on a page
    where it never does.
    """
    assert "#planhead:empty { display: none; }" in page
    assert "Report issue" in page
    row = re.search(r"<footer id=\"build\">.*?</footer>", page, re.S)
    assert row and " · " not in row.group(0), "a separator was written into the markup"


def test_the_banner_is_on_this_page_like_every_other(seed_root: Path):
    """`render_help` takes an `Index` for this and for nothing else.

    The shell draws the unreadable-files banner on every page, and
    `test_every_page_the_renderer_can_draw_carries_the_banner` derives the entry
    points from this package's namespace rather than from a list, precisely so the
    next page cannot be the one that forgets. A reader who is on Help while three
    plan files will not parse is a reader who should be told.
    """
    from pages import unreadable_in

    records, config, _ = load_repo(seed_root)
    broken = [Unreadable(path="tasks/task-a00002.md", why="no frontmatter")]
    index = build_index(records, config, date(2026, 8, 17), broken)
    named = unreadable_in(render_help(index, ROUTES))
    assert any("tasks/task-a00002.md" in line for line in named), named


def test_the_page_does_not_scroll_sideways_on_a_phone(page: str, tmp_path: Path):
    """These documents are full of the one thing that makes a page scroll
    sideways: an identifier with no space in it, in running prose. Measured, the
    offender was a single inline `<code>` 530px wide in a 460px column, and
    nothing in a parsed document could have said so.
    """
    from browser import chrome, measured_in

    found = measured_in(
        chrome(),
        page,
        tmp_path / "help.html",
        390,
        """
        const clipped = (e) => { let n = e.parentElement;
          while (n && n !== document.documentElement) {
            if (getComputedStyle(n).overflowX !== 'visible') return true;
            n = n.parentElement; } return false; };
        const wide = [];
        for (const e of document.querySelectorAll('body *')) {
          const r = e.getBoundingClientRect();
          if (r.right > innerWidth + 1 && !clipped(e))
            wide.push(e.tagName + ': ' + (e.textContent || '').trim().slice(0, 40));
        }
        return {scrollWidth: document.documentElement.scrollWidth,
                windowWidth: innerWidth, wide: wide.slice(0, 4)};
        """,
        780,
    )
    assert found["wide"] == []
    assert found["scrollWidth"] <= found["windowWidth"]


def test_the_contents_folds_on_a_narrow_screen_and_sticks_on_a_wide_one(
    page: str, tmp_path: Path
):
    """Two claims a parsed document cannot answer, and both were wrong first time.

    A contents entry per heading in every document, stacked above the first word
    of documentation, is what the one-column layout produces unfolded. And the
    sticky box did not stick at all: Chrome slots a
    `<details>`'s children into a `::details-content` box that is its own
    containing block, so a sticky element inside one is constrained to a rectangle
    exactly its own height. Scrolled to 4000 it read -3940, which is the page
    carrying it along.
    """
    from browser import chrome, measured_in

    script = """
    const fold = document.querySelector('.tocfold');
    const summary = fold.querySelector('summary');
    scrollTo(0, 0);
    const before = Math.round(fold.getBoundingClientRect().top);
    scrollTo(0, 4000);
    const after = Math.round(fold.getBoundingClientRect().top);
    return {open: fold.open, summary: getComputedStyle(summary).display,
            top: [before, after],
            scrollable: fold.scrollHeight > fold.clientHeight};
    """
    browser = chrome()
    wide = measured_in(browser, page, tmp_path / "wide.html", 1280, script, 900)
    assert wide["open"] is True
    assert wide["summary"] == "none", "nothing to fold beside a column of its own"
    assert wide["top"][1] <= 16, f"the contents did not stick: {wide['top']}"
    assert wide["scrollable"], "the contents is taller than the window and must scroll"

    narrow = measured_in(browser, page, tmp_path / "narrow.html", 390, script, 780)
    assert narrow["open"] is False, "the contents did not fold"
    assert narrow["summary"] != "none", "folded with no handle to open it"
