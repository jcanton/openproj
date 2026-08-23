"""The vendored files under `static/`, read off the disk and inlined."""

from __future__ import annotations

import base64
import os
from functools import cache, lru_cache
from pathlib import Path

from markupsafe import Markup


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


def _inline(name: str) -> str:
    return (_static_dir() / name).read_text(encoding="utf-8")


@cache
def _library(name: str) -> Markup:
    """A vendored library, read once, as the markup it is.

    The three graph libraries used to arrive as `@@name@@` markers substituted
    into the *finished* page, which is a substitution over text that by then held
    every title, tag and login in the plan — so a record titled
    `@@cytoscape.min.js@@` re-inlined 796 KB into the graph's data block and the
    page loaded with no plan at all. A template variable cannot do that: Jinja
    renders a value, it does not rescan it.

    `Markup` because this genuinely is trusted script text — a file shipped in
    `static/`, pinned by `SHA256SUMS`, containing no `</script` (which
    `test_injection` holds it to, because a re-vendoring could change it). Cached
    because every graph page carries 670 KB of it and the read is not free.
    """
    return Markup(_inline(name))


@cache
def _ace() -> Markup:
    """Ace and its vim keymap, as the two classic scripts they already are.

    594,306 B, inlined only when the address asked for them, and every part of
    that sentence is load-bearing.

    **Why they are here at all.** Ask 6 of the seven is a vim keymap, and it is
    the one a `<textarea>` cannot have: modal editing over `selectionStart`, with
    motions, operators, registers, counts, text objects, macros and an ex line,
    over an undo stack you do not own. `static/VENDOR.md` records the search that
    ended here and records that this is a HUMAN OVERRIDE of a written refusal
    rather than a re-derivation of it: the condition that file set for revisiting
    was "when somebody is actually slowed down by the textarea", and nobody has
    produced that measurement. Somebody asked for vim. That is a legitimate
    reason and it is a different one.

    **Why the markdown mode is not here.** `mode-markdown.js` is another
    75,276 B for syntax highlighting, which is on nobody's list; it is the only
    one of the three files that fails `test_no_page_asks_the_network_for_a_font`,
    twice, on a tokeniser regex and a completion template that fetch nothing; and
    it inlines four dormant worker-spawning sub-modes, so a later
    `setMode('ace/mode/javascript')` for a fenced-code sub-editor would build a
    `blob:` Worker this policy blocks IN SILENCE — an `error` event with an empty
    message, no exception, and Ace's own "Could not load worker" warning never
    firing because the constructor does not throw. Measured here, in Chrome,
    under this exact `CSP`, with `window.Worker` hooked before Ace parsed: the
    two files below construct 0 Workers, take 0 CSP violations, inject 0 scripts
    and leave `session.$worker` null, and the same probe with the markdown mode
    added and `ace/mode/javascript` set constructs a `blob:` Worker and logs
    `worker-src <- blob` — which is what makes the zero evidence rather than a
    check that could only pass.

    **Why the two are one block.** `keybinding-vim.js` registers
    `ace/keyboard/vim` against the `ace.define` registry `ace.js` created, so it
    is not a library beside Ace, it is the rest of Ace. They are concatenated
    with a newline between them because a minified file may end in a line comment
    and the next byte after it would be inside it.

    Verbatim, both of them, byte for byte from the `ace-builds` 1.44.0 npm
    tarball's `src-min-noconflict/` — not a CDN-generated derivative — and
    checksummed in `static/SHA256SUMS`. BSD-3-Clause, this repository's own
    licence; the minified files carry no notice at all, so `ace-LICENSE.txt`
    ships beside them and the notice goes in the page, on the precedent Inter
    already set here: every rendered page is a copy, and a copy is a
    redistribution.
    """
    # The notice travels with the bytes, and this is the only way it can: all
    # three minified files contain zero occurrences of `Copyright`, `BSD` and
    # `Ajax.org` — upstream strips the block when it minifies — so a page that
    # inlines them and says nothing has redistributed the software without the
    # notice BSD-3 clause 2 asks for. Read from the file rather than typed here,
    # so a re-vendoring that changes the licence changes this too.
    notice = _inline("ace-LICENSE.txt")
    # `*/` cannot appear in it and does not, but a licence is exactly the kind of
    # file somebody edits, and a stray one would end the comment and leave the
    # rest of the text as code.
    if "*/" in notice:
        raise ValueError("static/ace-LICENSE.txt would end the comment it is written into")
    return Markup(
        f"/* Ace 1.44.0 (ace.js and keybinding-vim.js), BSD-3-Clause.\n\n{notice}*/\n"
        + _inline("ace.js") + "\n" + _inline("keybinding-vim.js")
    )


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
