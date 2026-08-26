# Rebuilding `static/excalidraw.js`

This is the only build step in the repository. Everything else here is either
plain Python, run through `uv`, or a file vendored verbatim under `static/` and
checked in as bytes somebody else published. `static/excalidraw.js` cannot be
that: upstream ships Excalidraw ESM-only, with roughly thirty externalised bare
dependencies and no self-contained `<script>`-tag build at all, so there is no
single file to drop in and checksum. Making that file is a build, and the
build has to live somewhere — this directory, rather than inside `static/`
itself, so nobody mistakes a `.mjs` for something that runs at request time.

## Running it

```
node tools/build-excalidraw.mjs
```

Run from the repository root (or anywhere — the script locates itself and the
repository from its own path, not from the working directory). It prints the
temporary directory it built in, the byte count, and the sha256 of the file it
wrote to `static/excalidraw.js`. Compare that hash against `static/SHA256SUMS`.
Needs Node and a working `npm` with network access to the registry; nothing
else.

After it runs, refresh the checksum file the way `static/VENDOR.md` says to,
from the `static/` directory:

```
cd static && shasum -a 256 *.js *.mjs *.woff2 > SHA256SUMS
```

## Why it never touches `node_modules` in this checkout

"Never run npm inside the repository" is not a rule this build gets to skip
just because it is the one thing here that needs npm. `npm ci` against
`excalidraw-package-lock.json` installs 263 packages — a tree nobody wants
tracked, ignored, or accidentally committed. So `tools/build-excalidraw.mjs`
never installs where it sits. It re-executes itself inside a fresh directory
under the OS temp path, stages `excalidraw-entry.js` and the pinned
`excalidraw-package.json` / `excalidraw-package-lock.json` there as `entry.js`
and `package.json` / `package-lock.json`, runs `npm ci` in that directory, and
only then bundles — and only the one finished file, `excalidraw.trim.js`,
crosses back into this checkout, as `static/excalidraw.js`. The temporary
directory is left on disk afterward (the script prints where) so its contents
can be inspected before it is deleted; nothing about the build depends on it
surviving.

## What the build script actually does, and why the flags are load-bearing

Read `build-excalidraw.mjs`'s own comments for the mechanics. The two facts
worth stating here, because a simpler-looking rebuild attempt will hit both:

- `--loader:.woff2=dataurl` alone inlines nothing. The fonts are reached as
  plain string literals inside the package's own compiled chunks, not as
  `import`s esbuild's loader machinery ever sees, so an `onLoad` plugin has to
  rewrite those literals — and the matching `url(...)` references in the
  package's CSS — by hand.
- `--format=iife` folds every dynamic `import()` into the one output file
  regardless of what is reachable at runtime, so "English locale only" and
  "no mermaid" are not things a bundler flag gets for free here; the plugin
  stubs them before esbuild ever sees them, or all 56 locale chunks and the
  mermaid-to-excalidraw import dialog (mermaid, cytoscape, katex — roughly
  2.8 MiB) would ship regardless of whether the page ever asks for them.

## Two families were cut, for two different reasons

`dataUri()` in the build script returns a `local:` sentinel instead of a
`data:` URI for two font families, and `ExcalidrawFontFace.createUrls()`
treats that sentinel as "fall back to whatever the browser already has
installed under this name" — no fetch, no console error, confirmed by the
spike this build followed. The two cuts are not the same kind of cut:

- **Xiaolai** is cut for size: 209 files, 12,667,492 B, for a CJK fallback
  face this tool's English-only UI never reaches.
- **Liberation Sans** is cut for licence, and that one is not a size call —
  see `static/VENDOR.md` for the full reasoning. Short version: the copy this
  npm package ships is not the OFL-1.1 release Red Hat has published since
  2012, it is the older GPLv2-plus-font-exception build, and that exception's
  own text covers documents that embed the font rather than software that
  bundles it — with no separate file here, unlike ELK, for a notice to travel
  beside. It is an internal fallback face Excalidraw itself never offers in
  its font picker, so nothing a person chooses is affected by the cut.

If a re-vendoring ever needs Liberation back, that means Excalidraw's own
`dist/prod` has picked up the 2012-or-later OFL release under its own name —
check the family's licence again from scratch rather than assuming the cut
above still applies to whatever ships next.
