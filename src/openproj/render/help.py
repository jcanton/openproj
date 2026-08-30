"""The documentation, in the app: one page, every document, a contents beside it.

jcanton, 2026-08-27: "let's put the openproj documentation in the app. currently
it sits only in the repo as .md files" — one landing page, with an internal table
of contents on the left pointing at the other docs.

**One page and not one route per document**, which is what was asked for and is
also the right shape: a route each would be a nav item each or a second level of
navigation to build, and the thing somebody does with documentation is search it.
One page means the browser's own find works across the whole of it, and a link to
any heading in any document is a fragment on one URL.

**The files are read off the disk rather than baked into the module.** They are
the same bytes git holds and GitHub renders, so there is exactly one copy of every
sentence and no build step that could let the two drift — which is the rule the
rest of this repository is built on. What it costs is that the container has to
carry them: `Dockerfile` copies `README.md` and `docs/` in, and `_docs_root`
(`vendor.py`) is what finds them in either layout.
"""

from __future__ import annotations

from pathlib import Path
from typing import NamedTuple

from markupsafe import Markup

from ..index import Index
from ..vendor import _docs_root
from .env import _compiled
from .markdown import _LEADING_HEADING, document_html
from .shell import STATIC, Links, _page
from .styles import _DETAIL_STYLE, _SUGGEST_STYLE


class Doc(NamedTuple):
    """One document on the page: its fragment, its name, and where it is read from.

    `key` is the fragment and the prefix every heading inside the document is
    given, so `#quickstart-the-three-things` names one heading in one document on
    a page carrying several. `label` is what the contents calls it and is written
    here rather than taken from the file's own `# ` heading, because a file is free
    to name itself after the thing it describes rather than after what reading it
    gets you, and an entry in a list of documents about openproj that says
    "openproj" says nothing at all.
    """

    key: str
    label: str
    path: str


# Reading order, and it is the order somebody new should meet them in: how to use
# it, then the practice it encodes, then the model, then how it is built.
#
# **`README.md` was on this page and was taken off**, 2026-08-27, and not because
# it was wrong: it is the repository's front door, and half of it — what the thing
# is for, how to install it, what the licence is — is addressed to somebody who
# has just found the code and has no plan in front of them. A reader who is
# already signed into the app has answered every one of those questions by
# arriving. It stays the first thing on GitHub and stays copied into the image,
# because `_docs_root` finds the documentation BY it (`vendor.py`); it is simply
# not drawn.
#
# `AGENTS.md` is deliberately absent. It is written for whoever is changing this
# code and its whole content is invariants, failure modes and how to find the bug
# that is already here — a document for a contributor with a checkout, not for a
# reader of a plan. The same goes for `design/QUEUE.md` (a work queue),
# `design/deferred-push.md` and `design/drawings.md` (design records for one
# subsystem each) and `design/hackmd-observed.md` (research notes taken before the
# tool existed). They stay in the repository, where a contributor already is.
#
# **`design/EDITOR.md` was asked for here and is not, and the reason is not that it
# is long.** It is a document ABOUT this code — a library audit and a dated
# decision log — and the two rules that hold every page of this app to
# `default-src 'none'` are substring scans over the whole served page:
# `fetches_nothing` fails a page containing `cdn.`, and `asks_for_no_font` fails
# one containing a `url(` token that is not `data:` or `#`. That document argues
# about a bundle on `uicdn.toast.com` and quotes the `url(` tokens inside
# `mode-markdown.js`, so drawing it here would have meant nine `cdn.` hits and
# five `url(` hits on a page that fetches nothing at all — and the only way to
# make it pass is to loosen the two tripwires that would notice a real CDN link.
# Prose about the rule tripping the rule is not a reason to weaken the rule.
DOCS: tuple[Doc, ...] = (
    Doc("quickstart", "Quickstart", "docs/quickstart.md"),
    Doc("shape-up", "Shape Up, as this tool practises it", "docs/shape-up.md"),
    Doc("data-model", "The data model", "docs/data-model.md"),
    Doc("architecture", "Architecture", "docs/architecture.md"),
)


def _read_doc(root: Path | None, doc: Doc) -> tuple[str, str]:
    """The document's text, or an empty text and one line saying why not.

    **A document that cannot be read costs that document and nothing else**, which
    is `readable`'s rule in `model.py` applied to the one other place this
    application reads files off a disk. A container built without `COPY docs/`, a
    wheel installed with no `OPENPROJ_DOCS`, a file renamed in the repository and
    not here — each of those is a missing section, and a Help page that answers
    500 for any of them is worse than one that names the file it wanted.

    `Exception` and not a tuple of the ones seen so far, for the same reason
    `readable` catches it: `FileNotFoundError`, `IsADirectoryError`,
    `PermissionError` and `UnicodeDecodeError` are four already, and the denylist
    this repository refuses to write everywhere else is exactly as unfinishable
    here. Nothing below this call does anything but render text.
    """
    if root is None:
        return "", "the documentation directory was not found"
    try:
        return (root / doc.path).read_text(encoding="utf-8"), ""
    except Exception as error:  # noqa: BLE001 — see the docstring
        return "", f"{type(error).__name__}: {error}"


def _without_title(text: str) -> str:
    """The document, with its own opening `# ` heading taken off.

    The page draws `doc.label` as the section's heading, so the file's first line
    would land directly under an `<h2>` saying nearly the same words — the
    rendering fault `_drop_repeated_title` exists to prevent on a record page.
    Unconditional here where that one compares, because the files in `DOCS` are
    known and every one of them opens by naming itself; a file that does not simply
    keeps its first section, which is what the regex not matching already means.
    """
    match = _LEADING_HEADING.match(text)
    return text[match.end() :].lstrip("\n") if match else text


_HELP = """
{#- Announced, not drawn: the lit nav item already says which view this is. -#}
<h1 class="sr-only">Help</h1>
<div class="helppanes">
{#- A navigation landmark with a name on it, because this is the second set of
    links on the page and a reader moving by landmark needs to tell it from the
    one at the top — and `role="navigation"` on a `<div>` rather than the `<nav>`
    element that would say the same thing, which is the whole of the difference
    and is deliberate.

    **The shell's stylesheet is on every page and its `nav` rules are bare.**
    `nav { display: flex; flex-wrap: wrap; gap: .35rem 1rem }` is written for the
    one row of links at the top of the app, and a second `<nav>` element on this
    page took every word of it: the contents laid itself out as a wrapped ROW,
    each document's heading list beside its title instead of under it, measured
    at x=96/y=62 for a list whose own heading was at x=20/y=95. `nav a` (0,1,1)
    beat `.tocdoc { color }` (0,1,0) in the same pass, so the titles were drawn in
    the muted ink meant for links you are not on.

    Both were fixable with overrides, and overrides are the wrong answer here:
    they would have to be re-checked against every future line added to a block
    that is about a different component. The landmark is identical in the
    accessibility tree either way, so the element is the thing to give up.
    `tests/cascade.py` is what says which rule wins, and it is what this was
    resolved with rather than by guessing. -#}
<div class="helptoc"><details class="tocfold" open><summary>Contents</summary>
<div class="helptocbox" role="navigation" aria-label="Documentation contents">
  {%- for doc in docs %}
  <a class="tocdoc" href="#doc-{{ doc.key }}">{{ doc.label }}</a>
  {%- if doc.headings %}
  <ul class="tocin">
    {%- for heading in doc.headings %}
    <li class="lv{{ heading.level }}"><a href="#{{ heading.id }}">{{ heading.text }}</a></li>
    {%- endfor %}
  </ul>
  {%- endif %}
  {%- endfor %}
</div></details></div>
<div class="helpdocs">
  {%- for doc in docs %}
  <section class="doc helpdoc" id="doc-{{ doc.key }}">
    <h2>{{ doc.label }}</h2>
    {%- if doc.why %}
    {#- Empty must not look like broken. A section that drew nothing at all is a
        page that has quietly lost one of its documents and looks completely
        normal — the same failure `Unreadable` was written for, so it says the
        same two things: which file, and why. -#}
    <p class="unread"><code>{{ doc.path }}</code> could not be read: {{ doc.why }}</p>
    {%- else %}
    {{ doc.html }}
    {%- endif %}
  </section>
  {%- endfor %}
</div>
</div>
<script>
// A contents entry per heading in every document, stacked above the first word of
// documentation, is what the one-column layout below 60rem produced: measured at
// 390px, a reader scrolled past the whole of it to reach the README's first
// sentence. A count is not written down here on purpose — it moves with the
// documents. So the contents folds, and
// it folds the way everything else in this app folds on a small screen — a
// `<details>` shipped `open` and closed from here, with the handle drawn only at
// the width that closes it. `_FILTER_JS` does exactly this for the filter bar,
// the timeline's key and its window controls; this is the fourth box and it costs
// no new idea.
//
// It cannot USE `_FILTER_JS`, which is the facets script and is loaded by the
// three filtering views: this page has no facets, and the fold is nine lines
// against fifteen hundred.
//
// `STACKED` and not `PHONE` or `NARROW`, which are `_FILTER_JS`'s and the shell's
// own names for two other queries — every script on a page shares one global
// scope, and a page carrying two of them redeclares a const and loses the rest of
// the block. It is also a different WIDTH from both: this layout gives up its
// second column at 60rem, where the app gives up its nav row at 40, so a fold
// pinned to 40rem would leave the contents full height in the one-column band
// between them.
const STACKED = matchMedia('(max-width: 60rem)');
const TOCFOLD = document.querySelector('.tocfold');
function foldContents(stacked) { if (TOCFOLD) TOCFOLD.open = !stacked; }
foldContents(STACKED.matches);
// Both ways and on every change, for `foldOnAPhone`'s reason: turned to landscape
// with the box still closed, the handle that reopens it is gone with the media
// query that drew it, and the contents is unreachable on a page whose whole job
// is to be navigated.
STACKED.addEventListener('change', event => foldContents(event.matches));
</script>
"""


_HELP_STYLE = """
/* Two columns, and the contents is the narrow one. `minmax(0, …)` on BOTH,
   because a grid track's default `min-width: auto` is its content's minimum —
   and the documents carry code fences and tables that do not wrap, so without it
   the second track grows past the viewport and the whole page scrolls sideways
   instead of the one block that is too wide. */
.helppanes { display: grid; grid-template-columns: minmax(0, 16rem) minmax(0, 1fr);
             gap: 0 2rem; }
/* A measure, and it is the one place in this app that wants one. Every other
   page is a table, a graph or a form — dense, and read by scanning — and this one
   is documents of prose read line by line. At 1280px the second track came
   out 952px wide, which is about 150 characters a line and roughly twice what
   anybody reads comfortably; a record's own shaping document has never been
   wider than the record page's column. `max-width` on the inner block and not a
   fixed second track, so a fence or a table wider than the measure still has the
   whole column to scroll inside. */
.helpdocs { max-width: 52rem; }
/* The sticky element is the `<details>` and NOT the box inside it, and that is a
   measurement rather than a preference. A grid item stretches to the row's
   height, which is what gives a sticky box something to travel through — so the
   first version put `position: sticky` on `.helptocbox` inside the fold, and it
   did not stick at all: scrolled to y=4000 the box's top read -3940, which is
   the page carrying it along. Chrome slots a `<details>`'s non-summary children
   into a `::details-content` box that is its own containing block, so the sticky
   box was constrained to a rectangle exactly its own height and had nowhere to
   go. Unwrapping the same DOM in the same window put it at 8px, which is what
   named the cause.

   Sticking the `<details>` itself skips that box entirely: its containing block
   is `.helptoc`, an ordinary grid item stretched to the row. And it must NOT
   also carry `height: 100%` — a sticky element as tall as its containing block
   has no travel either, which is the same defect wearing the other hat. */
.tocfold { position: sticky; top: .5rem; max-height: calc(100dvh - 2rem);
           overflow-y: auto; padding-right: .5rem; }
/* Nothing to fold while the contents is a column of its own — the same rule and
   the same reasoning as `.keyfold > summary, .windowfold > summary` in the
   shell, at this page's own breakpoint. */
.tocfold > summary { display: none; }
.helptoc a { display: block; text-decoration: none; padding: .1rem 0; }
.helptoc a:hover { text-decoration: underline; }
.tocdoc { font-weight: 600; color: var(--fg); margin-top: .9rem; }
.helptoc .tocdoc:first-child { margin-top: 0; }
.tocin { list-style: none; margin: .1rem 0 0; padding: 0; font-size: 13px; }
/* The document's `##` renders as an `<h3>` (see `_heading_ids`), so `lv3` is a
   top-level section of a document and every deeper level indents from it. Written
   as a step per level rather than one rule per level: the documents use three
   between them today and a fourth must not be an unindented row. */
.tocin li { padding-left: calc((var(--lv, 3) - 3) * .7rem); }
.tocin li.lv3 { --lv: 3; }
.tocin li.lv4 { --lv: 4; }
.tocin li.lv5 { --lv: 5; }
.tocin li.lv6 { --lv: 6; }
.tocin a { color: var(--muted); }
/* `scroll-margin-top` and not a spacer: a fragment link lands the target at the
   very top of the viewport, and a heading flush against the window edge reads as
   a page that scrolled too far. */
.helpdoc h2, .helpdoc h3, .helpdoc h4, .helpdoc h5, .helpdoc h6 { scroll-margin-top: .8rem; }
.helpdoc { scroll-margin-top: .8rem; }
.helpdoc h2 { font-size: 1.15rem; margin: 0 0 .8rem; }
/* `.doc h2` in `_DETAIL_STYLE` sizes a record body's own headings, and the
   demotion means these documents have none — so `h3` and `h4` are what a reader
   of this page actually sees, and they had nothing but the browser's defaults,
   which put an `<h3>` at 1.17em of a 14px page and an `<h4>` BELOW body size. */
.helpdoc h3 { font-size: 1rem; margin: 1.6rem 0 .3rem; }
.helpdoc h4 { font-size: .9rem; margin: 1.2rem 0 .3rem; text-transform: uppercase;
              letter-spacing: .04em; color: var(--muted); }
.helpdoc + .helpdoc { margin-top: 2.5rem; }
/* A fence in one of these documents is a shell session or a block of YAML, and
   several are wider than the column. It scrolls inside its own box, because the
   alternative is the page scrolling sideways — the rule the whole app is held
   to. */
.helpdoc pre { overflow-x: auto; background: var(--surface-2); padding: .6rem .7rem;
               border-radius: 3px; }
.helpdoc pre code { background: none; padding: 0; }
/* A table in these documents is a real table of six columns, not the two-column
   list a shaping document tends to carry, so it gets the same treatment a wide
   fence does. `display: block` on the wrapper would collapse the table's own
   layout; there is no wrapper here because the markdown renderer emits the
   `<table>` directly, so the scroll goes on a container the stylesheet makes. */
.helpdoc table { display: block; overflow-x: auto; max-width: 100%; }
.helpdoc .unread { color: var(--warn); }
/* **The page must not scroll sideways**, and these documents are full of the one
   thing that makes it: an identifier with no space in it, in running prose.
   Measured at 390px (Chrome floors a window at 500, so the content column is
   460), the offender was a single inline `<code>` reading
   `test_a_seat_band_lands_on_the_right_line_at_a_width…` — 530px of unbreakable
   text in a 460px column, and `documentElement.scrollWidth` came out 554 against
   a 500px window. It is one rule and not a `<wbr>` policy for whoever writes the
   next paragraph.

   `break-word` and not `anywhere`: the difference is whether the word counts
   toward min-content width, and a table cell holding one of these must still ask
   for the room it needs. Inside a `<pre>` this does nothing at all — `white-space:
   pre` means no wrapping happens for it to govern — so the fences above keep
   their own horizontal scroll and their lines stay as written. */
.helpdoc { overflow-wrap: break-word; }
@media (max-width: 60rem) {
  /* One column, contents first. It stops being sticky at the same moment it
     stops being beside anything: a box pinned to the top of the window with the
     document scrolling under it is a box eating a third of a short screen. */
  .helppanes { grid-template-columns: minmax(0, 1fr); }
  .tocfold { position: static; max-height: none; overflow: visible; padding-right: 0; }
  .helptoc { margin-bottom: 1.5rem; }
  /* The handle, drawn as the filter bar's and the timeline's are, so the third
     place this app folds something away costs no learning. Copied in effect and
     not by selector: those rules are `#controls .facetbox > summary` and
     `.keyfold > summary`, and widening either to reach a box on another page is
     how a rule meant for one page ends up deciding the geometry of another. */
  .tocfold > summary {
    display: list-item; list-style-position: inside;
    padding: .45rem .1rem; cursor: pointer;
    font-size: 11px; color: var(--muted);
    text-transform: uppercase; letter-spacing: .04em;
  }
}
"""


def render_help(index: Index, links: Links = STATIC) -> str:
    """Every document this tool ships, on one page, with a contents beside it.

    Nothing on this page comes from the plan — it is about the tool, which is why
    it renders the same in the static export as on the server and why an exported
    plan that has outlived the service still carries its own instructions. The
    `Index` is here for one thing: the shell draws the unreadable-files banner on
    EVERY page, and `test_every_page_the_renderer_can_draw_carries_the_banner`
    reads this package's namespace rather than a list of entry points, precisely
    so the ninth page cannot be the one that forgets. A reader who is on Help
    while three plan files will not parse is a reader who should be told.
    """
    try:
        root: Path | None = _docs_root()
    except RuntimeError:
        # Not a re-raise and not a log line: `_read_doc` turns this into one
        # section per document, each naming the file it wanted, which is the same
        # page a single missing document produces. One failure mode drawn one way.
        root = None
    drawn = []
    for doc in DOCS:
        text, why = _read_doc(root, doc)
        html, headings = (
            document_html(_without_title(text), links, doc.key)
            if text
            else (
                Markup(""),
                (),
            )
        )
        drawn.append(
            {
                "key": doc.key,
                "label": doc.label,
                "path": doc.path,
                "html": html,
                "headings": headings,
                "why": why,
            }
        )
    body = _compiled(_HELP).render(docs=drawn)
    return _page(
        "openproj — help",
        body,
        _SUGGEST_STYLE + _DETAIL_STYLE + _HELP_STYLE,
        links,
        "help",
        index.unreadable,
    )
