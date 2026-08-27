"""Markdown to HTML, with this app's PR references, assets and task lists."""

from __future__ import annotations

import base64
import re
from collections.abc import Callable, Iterable, Sequence
from functools import lru_cache

from markdown_it import MarkdownIt
from markdown_it.renderer import RendererHTML
from markdown_it.rules_core import StateCore
from markdown_it.token import Token
from markupsafe import Markup
from mdit_py_plugins.attrs import attrs_plugin
from mdit_py_plugins.tasklists import tasklists_plugin
from pygments import highlight
from pygments.lexer import Lexer
from pygments.lexers import get_lexer_by_name
from pygments.util import ClassNotFound

from ..model import ID_PATTERN, Record, without_comments
from .shell import ROUTES, STATIC, Links
from .styles import CODE_FORMATTER

# Commonmark, plus the two things people were already typing and getting back as
# punctuation. `~~dropped~~` rendered as four literal tildes and `- [ ] a task`
# as the literal text `[ ]`, because commonmark has neither — so a struck-out
# line read as emphasis nobody could see, and a checklist, which is what the
# Progress section of a pitch is made of, read as a bullet with a box drawn in
# ASCII. Both are GitHub's spelling and HackMD's, which is where these documents
# were written before they were migrated here.
#
# The plugin is a dependency and not a hand-rolled rule for the reason
# `AGENTS.md` gives: `mdit-py-plugins` is markdown-it-py's own companion package,
# it costs the browser nothing at all, and a second implementation of the one
# checkbox syntax is a second thing to keep in step with the parser under it.
# The two attributes a figure may carry, and the only shapes their values may
# take. An allowlist twice over: the name has to be in this map and the value has
# to match this pattern, or the attribute is dropped.
#
# Written as a size rather than as free CSS. `{width=60%}` becomes
# `style="width: 60%"`, and because the value is bounded to digits and one of
# three units it cannot carry a `;`, a quote or a second declaration — so this is
# an allowlist and not an escape, which is the rule this repository keeps: there
# is no denylist of CSS spellings that is ever finished.
#
# Three digits, because a figure wider than 999 of anything is not a figure.
_ATTR_SAFE = re.compile(r"\A[0-9]{1,3}(?:%|px|rem)?\Z")
_ATTR_KEEP = ("width", "height")


def _with_unit(value: str) -> str:
    """A bare number means per cent, which is what a figure on a slide wants.

    `{width=60}` is what somebody types, and it is the only spelling that works
    UNQUOTED: the plugin's inline attribute syntax ends a bare value at the first
    character that is not word-ish, so `{width=60%}` parses as no attribute at
    all and prints as literal text. `{width="60%"}` works and is two more
    keystrokes for the thing people will write most often.

    Per cent and not pixels, because a slide is scaled: everything on it is laid
    out in one 1280x720 space and then multiplied to fit a thumbnail, a preview
    pane or a wall, so a width relative to the sheet is the only one that means
    the same thing at all four sizes. `px` and `rem` are still accepted for
    somebody who wants a figure at a fixed size, and they scale with the rest.
    """
    return value + "%" if value.isdigit() else value


@lru_cache(maxsize=64)
def _lexer_for(language: str) -> Lexer | None:
    """The lexer for an info string's first word, or None if there is not one.

    **No guessing.** Pygments will happily analyse an unlabelled block and return
    its best guess, and a shell session mis-guessed as Perl is a fence coloured
    confidently and wrongly — worse than the plain one it replaced, because the
    colours read as information. A fence says what it is or it stays ink.

    Cached because the alternative is a lexer built per fence per render, and the
    Help page alone draws a dozen; `get_lexer_by_name` walks Pygments' whole
    registry of aliases on a miss.
    """
    try:
        return get_lexer_by_name(language, stripnl=False)
    except ClassNotFound:
        return None


def _highlighted(code: str, language: str, attrs: str) -> str:
    """A fence's contents as Pygments spans, or "" to leave it as plain text.

    **Wired as markdown-it's `highlight` option and not as another render rule**,
    which was the first shape and was wrong in a way nothing on the Help page
    would have shown: a rule that builds its own `<pre><code>` drops the token's
    attributes, and `data-startline` is one of them. That attribute is how the
    record page scrolls the preview to the line you are writing (`detail.py`,
    `[data-startline]`), so hand-building the tag would have silently desynced
    the preview at every code block in a shaping document. Returning the inner
    HTML and letting markdown-it write the tag keeps the attributes, the language
    class and the escaping rules all in one place — theirs.

    **Highlighted on the server, and this is the trade the mermaid bundle lost.**
    A highlighter in the browser is another megabyte fetched onto a page held to
    `default-src 'none'`; Pygments runs here and what reaches the reader is spans
    and a stylesheet. Unlike the diagram above it therefore works identically in
    the static export, which has no server to ask.

    **No guessing**, which is why an unlabelled fence returns "". Pygments will
    analyse an unlabelled block and return its best guess, and a shell session
    mis-guessed as Perl is a fence coloured confidently and wrongly — worse than
    the plain one it replaced, because the colours read as information.

    The empty string and not the escaped code: markdown-it falls back to its own
    escaping when `highlight` gives it nothing, so declining here is one branch
    and not a second copy of an escaper.
    """
    lexer = _lexer_for(language) if language else None
    return highlight(code, lexer, CODE_FORMATTER) if lexer is not None else ""


_MD = (
    MarkdownIt("commonmark", {"html": False, "highlight": _highlighted})
    .enable(["table", "strikethrough"])
    .use(tasklists_plugin)
    # `![The driver](assets/0123….png){width=60%}` — jcanton, 2026-08-25, asking
    # for figures that can be sized and stood side by side, on a slide and in a
    # record body alike. The pandoc/kramdown spelling rather than one invented
    # here, because it is what somebody who writes markdown elsewhere already
    # types and what GitHub's own renderer is closest to.
    #
    # **This plugin sets ARBITRARY attributes**, which on a page in a repository
    # anybody can push to is `{onload=…}`, `{style=…}` and `{class=…}` written
    # into the plan by hand. `html: False` above stops raw tags and says nothing
    # about this. So the allowlist is in `_image`, on the token, before the tag
    # exists — the same place and the same reasoning as the `assets/` check that
    # is already there. Nothing else in this file consumes an attribute, and
    # `_ATTR_SAFE` is what makes that a rule rather than an accident.
    # Narrowed on BOTH of the plugin's own axes as well: `after=("image",)` so a
    # `{…}` following a link or a code span is text rather than markup — those
    # are the plugin's other three sites and this file overrides the renderer for
    # none of them — and `allowed` so the plugin itself drops a name before the
    # token exists. `_image`'s check below is the third fence and stays: two of
    # these three are the library's, and the one that is ours is the one that
    # cannot be changed by a version bump.
    .use(attrs_plugin, after=("image",), allowed=_ATTR_KEEP)
)


_PR = re.compile(r"\b([\w.-]+/[\w.-]+)#(\d+)\b")


def _pr_link(ref: str) -> Markup:
    """A dead PR reference teaches people the field is decorative.

    `Markup(...).format` and not an f-string. Called from `_after_markdown` the
    reference has already been through the markdown escaper and is harmless;
    called from the facts list it is `record.prs`, which is free text a member
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
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}
# Written as a repository-relative path so the markdown reads the same in git, on
# GitHub and in the tool; only the prefix in front of it changes.
#
# Group 1 carries the DIRECTORY as well as the name, which it did not when there
# was one directory and every reader could re-add `assets/` by hand. With two
# there is no prefix to re-add, and a caller that guessed would guess wrong for
# half the embeds. The drawings arm is pinned to `.png` rather than sharing
# `_ASSET_MEDIA`'s alternation, so that map stays the single source for the
# *asset* format list — which is what the comment above it asks for.
_EMBED_SRC = re.compile(
    r"((?:assets/[0-9a-f]{16}(?:"
    + "|".join(re.escape(s) for s in _ASSET_MEDIA)
    + r")|drawings/draw-[0-9a-f]{6}\.png))"
)


def _source_lines(state: StateCore) -> None:
    """Every top-level block, stamped with the lines of source it came from.

    The box and the rendered document are two views of one text, and nothing in
    the browser can line them up unless the rendered half says where each piece
    was written. `token.map` is markdown-it's own answer to that and is already
    computed by the time this runs — nothing here re-parses, and no line is
    counted a second time in JavaScript, which is how the two would come to
    disagree.

    A core rule and not a `RendererHTML` override per tag: this belongs on a
    heading exactly as much as on a paragraph, a list, a table, a fence and a
    rule, and a method per tag is a method per tag plus one more the day a plugin
    adds a block. Written as an attribute on the token rather than into a string,
    so it leaves through the same escaper as every other attribute.

    `token.level == 0`, so only the blocks a reader scrolls past are marked. Every
    paragraph inside every list item would be stamped too, which is bytes on every
    page for a resolution nothing wants: what a scroll position interpolates
    between is top-level blocks.

    `map` is [start, end) and zero-based; both numbers here are one-based and
    inclusive, because that is what the editing surface counts in and a second
    convention is a second place to be off by one.
    """
    for token in state.tokens:
        if token.level == 0 and token.nesting >= 0 and token.map:
            token.attrSet("data-startline", str(token.map[0] + 1))
            token.attrSet("data-endline", str(token.map[1]))


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
    # **The attribute allowlist, applied before anything renders.** `attrs_plugin`
    # puts whatever was inside `{…}` on this token, and a plan is a repository
    # anybody can push to — so `{onerror=alert(1)}` and `{style=position:fixed;…}`
    # are one line of markdown away from every page that draws this record. Both
    # halves are allowlists: the NAME must be one of two, and the VALUE must be
    # digits and one of three units.
    #
    # Read off and rebuilt rather than deleted in place: `token.attrs` is the
    # dict the renderer will use, and removing keys while walking it is the kind
    # of thing that half-works. Everything not named here is simply not carried
    # forward, which is the same shape as the `assets/` question below — asked as
    # "is this one of the things we allow" and never as "is this one of the
    # things we know to be bad".
    size = "; ".join(
        f"{name}: {_with_unit(str(value))}"
        for name in _ATTR_KEEP
        if (value := token.attrGet(name)) and _ATTR_SAFE.match(str(value))
    )
    token.attrs = {"src": source, "alt": token.attrGet("alt") or ""}
    if size:
        # A `style` and not the HTML `width` attribute, because that one is
        # defined in pixels and a percentage there is non-conforming — browsers
        # honour it, which is worse than refusing it: it works until one does
        # not. The value reaching here has already been through `_ATTR_SAFE`, so
        # it cannot carry a semicolon, a quote or a second declaration.
        token.attrSet("style", size)
    embed = _EMBED_SRC.fullmatch(source)
    if not embed:
        alt = self.renderInlineAsText(token.children, options, env) if token.children else ""
        return str(Markup('<a href="{}">{} (external image)</a>').format(source, alt or "image"))
    # `or` and not an `if`: an embed the reader could not fetch falls back to the
    # path, which is what every other page draws. Missing bytes must cost the
    # picture and not the page.
    inlined = env.get("assets", {}).get(embed.group(1))
    token.attrSet("src", inlined or links.repo + embed.group(1))
    return RendererHTML.image(self, tokens, idx, options, env)


def _fence(
    self: RendererHTML, tokens: Sequence[Token], idx: int, options: object, env: dict
) -> str:
    """A ```mermaid fence is a diagram where there is a server, and source where
    there is not.

    jcanton, 2026-08-27: "please vendor mermaid and let's include it and render
    the block nicely". `docs/data-model.md` has carried a promotion flowchart
    since it was written and the Help page drew it as five lines of ASCII-ish
    source.

    **The prefix decides, exactly as it does for `_image` and `_link`.** The
    bundle is 3.5 MB and is fetched from `/static/mermaid.min.js` rather than
    inlined (see `static/VENDOR.md`), so a diagram needs a server to ask. The
    static export has none — its pages are opened over `file://` — and a `<pre>`
    that sits there empty for ever, or a console full of failed fetches, is worse
    than the source it replaced. So an exported page keeps the ordinary code
    block it has always had, and `openproj render` writes the same bytes it did
    before this rule existed.

    **The content is escaped by `Markup(...).format`, exactly as it would be in a
    code block.** A mermaid fence in a shaping document is text a member typed,
    and what reaches the page is text: mermaid parses it in the browser at
    `securityLevel: 'strict'`, which is the shell's business (see `_MERMAID_JS`)
    and not this function's. Nothing here builds markup out of it.
    """
    token = tokens[idx]
    # The first word of the info string, which is where a language goes:
    # ` ```mermaid ` and ` ```mermaid something ` are both mermaid, and
    # ` ```mermaidish ` is not.
    language = token.info.strip().split(maxsplit=1)[:1]
    served = env.get("links", STATIC).table.startswith("/")
    if language == ["mermaid"] and served:
        # `<pre>` and not `<div>`: until mermaid has run — and for ever if the
        # bundle never arrives — this element is showing source, and source in a
        # `<div>` loses its line breaks. Mermaid replaces the content with an
        # `<svg>` and stamps `data-processed`, which is what the stylesheet reads
        # to stop drawing it as a code block.
        return str(Markup('<pre class="mermaid">{}</pre>\n').format(token.content))
    # Everything else, highlighted or not, is markdown-it's own fence renderer —
    # which is what calls `_highlighted` below through the `highlight` option, and
    # what keeps the `data-startline` on the tag.
    return RendererHTML.fence(self, tokens, idx, options, env)


def _link(self: RendererHTML, tokens: Sequence[Token], idx: int, options: object, env: dict) -> str:
    """A link whose target is a record id points at that record's page.

    jcanton, 2026-08-25: "I'd like to have links to other records in the body of
    a record". `[Port the transport](pitch-000001)` is what a person types, and
    it is what the same characters mean in git and on GitHub — a relative link to
    nothing there, and a link to the record here. Written that way round on
    purpose: the alternative spellings all put this tool's URL shape inside the
    plan's own files, and the plan outlives the tool.

    **The prefix comes from `env`, exactly as `_image`'s does.** A served page
    links to `/detail/<id>` and a rendered file to `detail.html#<id>`; one
    renderer draws both, and the prefix is the only thing that differs.

    **An allowlist, and the same one the validator uses.** `ID_PATTERN` is
    public and is the single copy — it is what an id must match to be written and
    what closes `<directory>/<id>.md` as a path — so this widens the day a rung
    is added and never otherwise. Anything else is left exactly as it was
    written: `https://…`, a mailto, `#anchor`, `./notes.md`, and a record id with
    a fragment glued on are all somebody meaning something other than this.

    **Whether the record EXISTS is deliberately not asked.** This renderer is
    handed a body and a link prefix and never an index — the preview route has
    one and `_markdown_line` on a deck slide does not — so the question could
    only be answered on some of the pages that draw the same document. A link to
    a record that has been deleted answers 404, which is the same thing
    `_pr_link` does with a pull request nobody opened, and it is a broken link
    rather than a page that renders differently depending on which view you are
    in.
    """
    token = tokens[idx]
    href = token.attrGet("href") or ""
    if ID_PATTERN.match(href):
        token.attrSet("href", env.get("links", STATIC).record + href)
    return self.renderToken(tokens, idx, options, env)


def _slug(text: str) -> str:
    """A heading, folded to what a fragment may hold.

    An allowlist rather than a list of characters to strip. A doc heading is
    prose — `## Two populations: `Index.records` and `Index.plan`` is a real
    one — and the punctuation that has to leave a fragment is not a set anybody
    finishes enumerating. So the rule is the other way round: ASCII letters and
    digits survive, every run of anything else becomes one hyphen.

    Written as a loop and not as `re.sub`, which is what it obviously wants to
    be. `test_no_page_is_assembled_by_substitution` parses this package as syntax
    and refuses `.replace`, `.sub` and `.subn` anywhere in it — because a page was
    once assembled by substituting into finished markup, and a rule with an
    exception is a rule somebody argues their way past. This call is safe and the
    check is blunt on purpose; the loop costs six lines and keeps the check blunt.
    """
    folded: list[str] = []
    for character in text.lower():
        if character.isascii() and character.isalnum():
            folded.append(character)
        elif folded and folded[-1] != "-":
            folded.append("-")
    return "".join(folded).strip("-")


def _heading_text(inline: Token) -> str:
    """A heading's words, with its markup taken off.

    `token.content` is the raw markdown — backticks, emphasis and all — and a
    table of contents entry reading `` `Index.plan` `` with the backticks in it
    is a fragment somebody has to mentally strip. The children are already
    tokenised by the time a core rule runs, so the text is there to be read
    rather than re-parsed: `text` for prose and `code_inline` for a span, which
    between them are every leaf a heading in these documents has.
    """
    return "".join(
        child.content for child in (inline.children or []) if child.type in ("text", "code_inline")
    ).strip()


def _heading_ids(state: StateCore) -> None:
    """Ids and one level of demotion, for a document drawn inside another page.

    Off unless `env["anchor"]` says which document this is, so a record body — the
    other million calls through `_MD` — is parsed by exactly the chain it was
    before. It is one rule and not a second parser for the reason `_markdown_line`
    gives: a doc has to render the way every other document here renders, with
    the same PR rule, the same image allowlist and the same `html: false`.

    **The id is prefixed by the document.** Six documents on one page share one
    fragment space, and `## The pages` is a heading in two of them; unprefixed,
    the second one draws an id nothing can reach and the table of contents sends
    both entries to the first. The counter below covers the rest — a document
    that repeats a heading within itself, which `EDITOR.md` does.

    **Demoted by one.** The page draws each document under an `<h2>` carrying its
    name, so the document's own `##` sections belong at `<h3>`; left alone they
    would be siblings of the heading they sit under, and a heading list — which
    is how the reader this app's floor is written for navigates — would show six
    flat documents instead of six with contents. The document's leading `# ` is
    already gone (`_drop_repeated_title`), so nothing here is demoted out of `h6`
    in practice; the `min` is there because a `######` in a file somebody writes
    tomorrow must not produce an `<h7>`, which is not an element.
    """
    anchor = state.env.get("anchor")
    if not anchor:
        return
    found = state.env.setdefault("headings", [])
    seen: dict[str, int] = {}
    tokens = state.tokens
    for at, token in enumerate(tokens):
        if token.type != "heading_open":
            continue
        text = _heading_text(tokens[at + 1])
        level = min(int(token.tag[1:]) + 1, 6)
        token.tag = tokens[at + 2].tag = f"h{level}"
        # `or anchor` and not a bare fallback id: a heading of nothing but
        # punctuation slugs to the empty string, and `anchor + "-"` is a
        # fragment that reads as a bug in the page rather than as a link.
        base = f"{anchor}-{_slug(text)}" if _slug(text) else anchor
        seen[base] = repeats = seen.get(base, 0) + 1
        identifier = base if repeats == 1 else f"{base}-{repeats}"
        token.attrSet("id", identifier)
        found.append({"level": level, "id": identifier, "text": text})


_MD.core.ruler.push("openproj_source_lines", _source_lines)
_MD.core.ruler.push("openproj_pr_refs", _pr_refs)
_MD.core.ruler.push("openproj_heading_ids", _heading_ids)
_MD.add_render_rule("image", _image)
_MD.add_render_rule("link_open", _link)
_MD.add_render_rule("fence", _fence)


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


def document_html(text: str, links: Links, anchor: str) -> tuple[Markup, tuple[dict, ...]]:
    """A whole document, and the headings it turned out to have.

    The Help page's entry point, and `_markdown`'s sibling rather than its
    replacement: same parser, same rules, same `html: false`, with `anchor`
    switching on the one core rule a document inside another page needs. Two
    functions and not a flag on `_markdown` because the return types differ — a
    caller that wants a table of contents wants the headings, and every other
    caller in this package would then be unpacking a tuple to throw half of it
    away.

    The headings come back as the rule found them, in document order, each with
    the level it was DEMOTED to — so the caller nests the list without knowing
    that a `##` in the file is an `<h3>` on the page. Written that way after the
    first version returned the source level and the page built a table of
    contents one rung out of step with the document it was for.
    """
    env: dict = {"links": links, "assets": {}, "anchor": anchor}
    html = Markup(_MD.render(text, env))
    return html, tuple(env.get("headings", ()))


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


def _body_html(record: Record, links: Links = STATIC) -> Markup:
    return _markdown(without_comments(_drop_repeated_title(record.body, record.title)), links)


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
        # A path now, not a bare name — group(1) carries the directory, and a
        # reader who forgot that would build `assets/assets/…` and read nothing.
        for path in _EMBED_SRC.findall(body):
            if path in found:
                continue
            data = read(path)
            if data is None:
                continue
            media = _ASSET_MEDIA["." + path.rsplit(".", 1)[1]]
            found[path] = f"data:{media};base64,{base64.b64encode(data).decode('ascii')}"
    return found


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
