# Drawings

Designed and built 2026-08-26 with jcanton. Excalidraw, vendored, opens in a
popup over the editor; a drawing is a PNG that carries its own editable scene, and
it lives at a stable path under one top-level directory. Nothing here was speculative
about the product — every fork below was decided in conversation. A feasibility spike
ran first against the questions the CSP raised, and settled all but two of them; both
are resolved where the spike's own answers are, in "The spike, which came first"
below, rather than restated here.

## What it is

A button above the editor opens a menu: **+ drawing**, and under it the drawings
this body already embeds, listed by id in the order they appear. Press one and
Excalidraw opens over the editor with that drawing in it. Save, and the file is
rewritten in place; the body is not touched at all.

An embed is ordinary image markdown:

```
![sync flow](drawings/draw-a1b2c3.png){width=60}
```

No bespoke syntax, and the reason is that a bespoke syntax buys nothing and costs
everything outside this app. The file genuinely is a PNG genuinely at that path, so
GitHub renders it, `git show` renders it, and any markdown viewer renders it. This is
the argument already written at `render/markdown.py:118-119`: a repository-relative
path so the markdown reads the same in git, on GitHub and in the tool, with only the
prefix in front of it changing.

The caption is the alt text. There is no naming mechanic and no rename mechanic,
because there is nothing for one to do: the id is the name, and the caption is text
somebody types.

## The format: a PNG that is also its own source

`exportToBlob({elements, appState: {exportEmbedScene: true}, mimeType: 'image/png'})`
produces a PNG whose `tEXt` chunk holds the deflated scene. Reopening is
`loadFromBlob` on the bytes the server just served. One file, no sidecar, no second
source of truth that can drift from the first.

Not SVG. `web.py:613-614` refuses SVG on purpose — "it is a document that can carry
script" — and a drawing is not the reason to reverse that. The drawing door accepts
`image/png` and nothing else, so `IMAGE_TYPES` is not widened either.

## Where the bytes live

One flat top-level directory, one file per drawing, the name is the id:

```
drawings/draw-a1b2c3.png
```

**Not `assets/`.** `Store.put_asset`'s docstring (`store.py:1659-1663`) is a guarantee
about the whole tree it writes into — an asset is never edited, so there is no base to
compare against, nothing to merge, and no conflict that can exist, which is why it
needs none of `write_all`'s compare-and-swap. A mutable file in `assets/` makes that
sentence false about a directory whose `immutable, max-age=31536000` caching
(`web.py:3269-3271`) and whose replay fast path (`_replay_one`, `store.py:1397`) both
rest on it being true. A separate directory keeps the two guarantees visibly separate,
and no existing asset test changes.

**Why not content-addressed, which would have been nearly free.** `put_asset` already
works; `assets/<sha16>.png` already matches every pattern, already exports, already
inlines into the deck. The whole feature would have been a save button and a body
rewrite. But that body rewrite is the problem: content-addressing mints a new path on
every save, so every save must find the old path in the body and splice the new one
in — a body write racing the record editor's own save, on the same file, through the
merge ladder. A stable path makes that race not exist. That is what the extra day
buys, and it carries the decision on its own. Two smaller things come with it: a menu
a human can read, and a URL that survives an edit, so the picture in a deck, in an
export, on GitHub and in a link somebody pasted stays pointed at the same drawing.

What is *not* a difference, against the obvious argument: repository growth. Both
schemes keep every version of the bytes for ever. Content-addressing keeps old blobs
at old paths in the tree; a rewritten path keeps them in history. Git holds both.

## A PNG must never touch the merge ladder

This is the part that corrupts, so it is written down before the code that avoids it.

Three lines, read and verified:

1. `store.py:1941` — `_commit` does `create_blob(content.encode("utf-8"))`. `bytes` has
   no `.encode`, so a PNG through `Store.write` is an `AttributeError`, which is not in
   `WRITE_FAILURES` (`web.py:131-138`) and so is an unhandled 500 rather than a refusal.
2. `store.py:895` — `read` decodes UTF-8, so `_attempt`'s stale-base branch
   (`store.py:1894`) raises `UnicodeDecodeError` on a stored PNG. Also not in
   `WRITE_FAILURES`. Also a traceback.
3. And the reason those two crashes are the *good* outcome: if anyone ever makes them
   go away by decoding latin-1 first, `_split` (`store.py:321-324`) sees no `---` and
   hands the entire binary to `_merge_body`'s line merge, which splits on
   `str.splitlines(True)` boundaries — for binary that includes `\r`, `\x0b`, `\x0c`,
   `\x1c`-`\x1e` and `\x85` — and `_merge` (`store.py:557`) returns
   `f"---\n{front}---\n{body}"`. Eleven bytes in front of the PNG magic number, on a
   clean merge, committed, answered 200 with a real sha, on a branch that cannot be
   force-pushed. A file no decoder will open.

So drawings get their own store method, and it never decodes anything.

## `Store.put_drawing`

```python
def put_drawing(
    self, path: str, data: bytes, base_blob: str | None, author: str, message: str
) -> tuple[WriteResult, str]:   # (result, the new blob oid, which is the new ETag)
```

Assembled almost entirely from parts that already exist:

- `with self._writing:` then `_refuse_forked()` and `_refuse_swamped()`, copied verbatim
  from `put_asset` (`store.py:1677-1684`) and for its stated reason: while the plan is
  forked, no route may answer as though this service can take work.
- `stored = _blob_at(self._repo, self.head(), path)` — `store.py:307`, which is
  `Store.read` without the decode. Blob-id compare-and-swap, never a decode.
- `base_blob is None` (a create) and `stored is not None` → refuse. This is the `O_EXCL`
  the store has nowhere today, and it costs one line because check and write are inside
  the same lock.
- `base_blob is not None` and `str(stored) != base_blob` → refuse, with the sentence in
  "Two people, one drawing" below.
- `blob = create_blob(data)`, and `if blob == stored:` return without minting. Required,
  not optional: `store.py:1778-1784` and `store.py:1406-1407` record the same bug being
  fixed twice — an empty commit on the decision log says a decision was made when none
  was.
- otherwise `_insert` → `create_commit(_BRANCH, ...)` → `_finish(head, "committed")`,
  exactly as `put_asset` does at `store.py:1689-1697`.

**Not a flag on `write_all`.** It would touch five sites — the `dict[str, str | None]`
signature, `_commit` and its `.encode`, `_attempt`'s already-gone probe and its
base/current read pair, and `_verdict` — and `_verdict`'s own docstring
(`store.py:571-574`) says it was extracted so write-time and replay-time conflict
semantics cannot drift. Widening it *is* the drift. The decision is also per-path, not
per-call: a flag cannot express one commit holding a `.md` and a `.png`.

Two comments became false the day this shipped, and were corrected in the same commit:
`put_asset`'s docstring (`store.py:1659-1665`) was scoped to the
content-addressed half, and `_replay_one`'s `UnicodeDecodeError` arm
(`store.py:1434-1446`) stopped saying that reaching it means a hand-committed
binary. A concurrently-edited drawing is now a routine way in, and the consequence is
the whole commit parking to `refs/openproj/stranded-<sha>` (`store.py:1482`) after a
200 already went out.

## The id

```python
drawing_id = f"draw-{secrets.token_hex(3)}"
```

Same alphabet, same width, same CSPRNG and the same never-from-the-client rule as the
record mint at `web.py:3402`, and for the reason `POST /api/record` gives at
`web.py:3400-3401`: an id supplied by a browser is a path supplied by a browser, once
it becomes `drawings/<id>.png`. `draw` collides with no rung prefix in `KINDS`
(`model.py:1233-1264`), so the `record_id.split("-")[0]` idiom at `web.py:1266`,
`web.py:2036` and `model.py:1394` cannot mis-route a drawing into a record directory.

**With a uniqueness check, which the record mint does not have.** Nothing between
`web.py:3402` and `web.py:3440` queries the index or the tree; records survive on an
incidental guard falling out of `_identity_problems` (`model.py:2858-2872`). A drawing
never reaches `validate_all`, so it would inherit no guard at all — and `_attempt`
short-circuits to an unconditional overwrite whenever `current == base_commit`
(`store.py:1890-1893`), so no guard means silent data loss. A drawing can afford the
check records cannot, because the path *is* the id and there is no `<id>--<slug>`
ambiguity: the route mints, `put_drawing` refuses over an occupied path under the lock,
the route re-mints, up to eight times, then 500s. Not theatre — `token_hex(3)` is
16,777,216 values, and by the birthday bound a corpus of 1,000 drawings already carries
roughly a 3% chance that some pair collides. `docs/data-model.md:32`'s "never collide"
is true of a simultaneous pair and not of a growing corpus.

**No slug half, ever**, and the argument is not YAGNI. Records need `_path_for`
(`web.py:1275-1307`) because humans rename record files in git and the slug drifts.
That is survivable only because bodies reference records *by id*, through `_link`. A
drawing embed references it *by path*. So a real rename would have to rewrite every
body that names the drawing — a body-rewriting feature, which a path finder does not
make cheaper — and a slugged filename would break GitHub's own rendering of
`![](drawings/draw-a1b2c3.png)`, which is the whole reason the path is repository-relative.

## Serving

A new route beside `/assets/{name}`, which is left exactly as it is:

```python
@app.get("/drawings/{name}")
```

Guarded by `DRAWING_PATTERN` on the stem and a literal `.png` suffix. Answers
`image/png` with `ETag: "<blob oid>"`, `cache-control: no-cache`, and a 304 on a
matching `If-None-Match`.

**Not `immutable`.** `web.py:3269-3271` justifies that header with "the name IS the hash
of the contents, so this bytes-for-bytes cannot change under a cache", which is exactly
what stops being true here. `no-cache` means revalidate every time, not do not store;
the ETag turns the revalidation into a 304 whenever the drawing has not moved.

This is also the trap most likely to ship silently. Widening `ASSET_PATTERN`
(`web.py:621`) instead of adding a sibling drags `immutable, max-age=31536000` onto a
mutable file, and every reader's browser holds an edited drawing for a year.
`tests/test_web.py:2953` asserts only that `"immutable" in cache-control`, so it keeps
passing while the behaviour becomes wrong. The shortcut is one grep away; this
paragraph is the guard.

The ETag is load-bearing twice for the price of once: it is also the `base_blob` the
editor hands back on save. The browser's cache token and the compare-and-swap token are
the same string.

## Writing

```
POST /api/drawing            raw image/png body, no id.  Mints, refuses over an
                             occupied path, retries.  -> {id, path, etag, commit}
PUT  /api/drawing/{id}       raw image/png body, If-Match: "<etag>".  Same shape.
```

Both check the eight-byte PNG signature and the byte ceiling, and both end in exactly
one `await _write_or_refuse(store.put_drawing, ...)` with the method as the **bare first
positional argument** — `tests/test_web.py:5083-5090` collects `id(call.args[0])`, so a
lambda wrapper or a keyword argument escapes the guard in silence.

`tests/test_web.py:5064`'s `WRITERS` set gained `"put_drawing"`. Without that line the
AST guard would have silently stopped covering the new routes: the test keeps passing,
and a forked plan answers a drawing save with a traceback — the exact outage
`test_no_write_route_escapes_the_refusal` was written for.

`web.py:19-22`'s module docstring enumerates the closed writable surface, and now
names `drawings/<drawing id>.png` by `DRAWING_PATTERN` alongside the rest, because it
is the file's stated invariant and reviewers check against it.

## Two people, one drawing

The loser is refused, in one sentence, and their strokes are gone:

> `drawings/draw-a1b2c3.png` — somebody changed this drawing while you had it open, and
> a drawing has no merge. Reopen it.

There is no third drawing that is both people's intent. This is the argument
`_merge_body`'s own docstring makes at `store.py:412-416` about CRDTs, and pretending
otherwise for a PNG would be worse than saying it plainly. Saving the loser's work as a
*new* drawing was considered and deferred: it mints a second id and splices a second
embed into the body, which puts back exactly the body-write race the stable path was
chosen to remove.

## The read side, and the one risky edit

Before this shipped, `_ASSET_SRC` matched only `assets/[0-9a-f]{16}.<ext>`, so a
drawing path fell through `markdown.py:294-296` and rendered as
`<a href="…">sync flow (external image)</a>` — a text link, on the detail page, in
the preview, in the deck and in the export alike.

It became `_EMBED_SRC` (`render/markdown.py:127-131`), with two arms, and
**group(1) widened to carry the directory**:

```python
_EMBED_SRC = re.compile(
    r"((?:assets/[0-9a-f]{16}(?:" + "|".join(re.escape(s) for s in _ASSET_MEDIA) + ")"
    r"|drawings/draw-[0-9a-f]{6}\.png))"
)
```

Group(1) used to exclude the directory, and every consumer re-added `assets/` by hand.
With two directories that was no longer possible, so the prefix moved into the group,
`Links.asset` (`render/shell.py:54`, `:100`) became `Links.repo` (`""` static, `"/"`
served), and the three byte-identical
`lambda name: store.read_asset(commit, f"assets/{name}")` calls, at `web.py:2200`,
`:2287` and `:2369`, collapsed to `lambda path: store.read_asset(commit, path)`.

The drawings arm is pinned to `\.png` rather than sharing `_ASSET_MEDIA`'s alternation,
so `_ASSET_MEDIA` stays the single source for the *asset* format list, which is what its
comment at `markdown.py:110-114` asks for. Keys stay consistent by construction, because
`_image`'s lookup and `_inlined_assets`' map are both built from group(1), and the
suffix-driven media lookup at `markdown.py:439` still works on a full path.

**This was the riskiest edit in the change.** Four call sites had to move together or
the deck would have silently stopped inlining pictures and started emailing broken
images; `tests/test_deck.py:543` would have caught it only if the fixture path moved in
the same commit — it did, and stayed green.

`render/export.py:41-47` used to copy only `assets/`; it is now a loop over
`("assets", "drawings")`. Without it every exported page would show a broken drawing,
for exactly the reason its docstring at `export.py:26-29` already gives about assets.

## What does not change

`model.py` — nothing, anywhere. `record_paths_in` (`model.py:244-295`) drops `drawings/`
at its `below in wanted` test, `_plan_files` (`model.py:1611`) rglobs only named record
directories, and `SEARCH_FIELDS` (`index.py:484-487`) reads record fields and never
touches a blob. A new top-level directory is invisible to the record model by
construction.

`cli.py:174` — nothing. `_seed_files`' `found.suffix in (".md", ".yaml")` filter drops a
`seed/drawings/*.png` before `read_text` can raise on it, which is what that filter was
added to prevent (`cli.py:163-167`). The consequence is that **the demo corpus ships no
drawings**, or `openproj demo` renders a body naming a file that is not there.

`docs/data-model.md:79-84` — the paragraph headed "A plan directory is flat" enumerates
eight directories, and `drawings/` is named beside them as a ninth, also flat, for a
reason of its own.

## The editor side

Excalidraw is vendored: a single-file, non-splitting IIFE built offline with esbuild,
`en` locale only, mermaid and TTDDialog cut, fonts inlined as `data:` URIs, committed to
`static/` with the build script and its lockfile beside it, checksummed in
`static/SHA256SUMS` and named in `static/VENDOR.md`. Upstream publishes no such file —
it is ESM-only with thirty externalised bare dependencies and deleted its UMD build in
v0.18.0 — so this is our build artifact and the override goes in writing, the way Ace's
did.

It is **not** on the editor page. `detail.html` stays at 1,110,377 B with Ace, unchanged,
because the bundle is fetched on the first press of the drawing button rather than carried
on the page, and mounted in a popup over the editor. `openproj` had no route that served a
static file at all before this — every other vendored library is read off disk and inlined
into a rendered page rather than fetched by the browser on its own. `GET /static/{name}` was
added for exactly this one file, an explicit allowlist of vendored names rather than a
`StaticFiles` mount, because a mount's whole feature is taking a path from the request and
everything else in this server takes an id and derives the path itself. The fetch is
`connect-src 'self'`, which the policy grants; the injection that follows it is an inline
script and not a `<script src>`, because `script-src` is `'unsafe-inline'` and grants no
`'self'` for a fetched script to match — a `src` attribute pointing at the same file is
refused outright, so fetch-and-inject is the one door that opens. An iframe is not an option
either: `render/shell.py:79-90` is `default-src 'none'` with no `frame-src`.

The spike's own build — mermaid and all 55 locales already stubbed out, `en` the only one
that ships — measured **5,603,202 B raw, 2,025,230 B gzip** against `@excalidraw/excalidraw`
**0.18.1** and React **18.3.1** (not React 19: the peer range permits it, but 19 is not the
version that was on the scale, so this does not claim it is). The bundle that actually
shipped came in smaller: **5,508,971 B raw, 1,963,903 B gzip**. The difference is not slack
in the build; it is one font family removed once this vendoring looked at its actual
licence, and a second dropped for size — see "The font licences," below. jcanton approved
vendoring it on 2026-08-26 with the consequence spelled out rather than glossed over:
`static/` went from 2.7 MB to roughly 8.0 MB the day this landed. `detail.html`'s own byte
count did not move, because none of those bytes are on it until somebody presses the button.

The generic network probe used to flag only an injected script that carried a `src`
(`tests/test_editor.py:5297-5325`), so fetch-and-inject would have passed the letter of that
probe while breaking its spirit. It was widened in the same commit to also catch a marked
inline injection, so the zero violations it asserts is evidence the probe could have failed
rather than an assertion that could only ever pass.

The control goes in the `.editbar` beside `{{ slidebar }}` (`detail.py:1024`,
`slides.py:152`), not as a seventeenth entry in `FORMATS`. A menu is page chrome, not a
formatting mark, and it keeps `tests/test_editor.py:1566-1571` and `:2236` and the 40rem
wrap query calibrated to "sixteen buttons needing 561px" (`styles.py:222-229`) out of the
change.

The button carries the Excalidraw icon — jcanton, 2026-08-26 — inline SVG like every other
mark in this bar, because `test_no_page_reaches_the_network` (`tests/test_render.py:177`)
forbids fetching one, the same rule every other icon here already obeys.

The menu is `_EMBED_SRC.finditer(surface.text())`, drawings arm only, deduped keeping the
first occurrence, in match order — which over the raw markdown *is* embed order. Label is
the bare id. Recomputed in JS when the menu opens: no server round trip, no stored state,
nothing to keep in sync. It is the same scan `_inlined_assets` already does at
`markdown.py:433`.

`attachDrawing` sits beside `attachUploads` and is wired at both its call sites,
`detail.py:1592` and `slides.py:815`. It inherited a hole doing so: `slides.py` used to
build `const SURFACE = window.aceSurface && MAY_WRITE ? aceSurface(...) : null` rather
than call `bodySurface`, so on `/detail/<id>?view=slide&editor=plain` `SURFACE` was `null`
and none of the `attach*` calls ran at all — no toolbar, no upload wiring, no gutter, no
status strip, and the new drawing button would have inherited exactly that silence.
`render_slide_editor` had no test at all. Both are fixed in the same commit as this
work rather than left as a follow-up: `slides.py:523` now calls `bodySurface(PROSE)`
behind the same `MAY_WRITE` guard, and `tests/test_editor.py` covers the plain slide
editor's toolbar and status strip, and separately confirms a reader (`MAY_WRITE` false)
still gets no surface and none of the five `attach*` calls.

## Closing over unsaved strokes

`teardown()` was the popup's only close path — reached from Close, from Escape,
and from every error branch — and for as long as this feature had no guard on
it, all three unmounted immediately. Draw for ten minutes, press Escape by
reflex, and the strokes were gone: the drawing was never posted, so there was
no blob and no history to recover it from. jcanton asked for a guard on being
shown the gap, 2026-08-26.

Not `window.confirm()`, for the same reasons `detail.py`'s delete flow already
gives at `detail.py:1947-1950`: a native dialog cannot say which drawing this
is, cannot show a server's reason (there is none here to show, but the point
generalises), and stops every other script on the page until somebody answers
it. A fourth reason is specific to this feature: the browser tests drive real
Chrome over CDP, and a native dialog blocks every subsequent DevTools command
— the harness would hang rather than fail. So the question is in-page chrome,
`.drawask`, shown in place of Save and Close rather than beside them, the same
shape `.confirming` uses for a delete.

**What counts as dirty was decided, not inferred from `onChange` firing.**
Excalidraw's `onChange` runs on mount, on pointer-move, on selection and on
scroll, so a flag set by onChange firing at all would have asked on a popup
nobody touched as readily as on a real drawing — and a guard that cries wolf
gets dismissed on reflex, which is worse than no guard at all. So `openDrawing`
carries no running flag. A close attempt instead compares the scene as it
stands, `api.getSceneElements()`, against the array Excalidraw was mounted
with — by count first, then element by element on the fields an actual
stroke, drag, resize, restyle or reorder moves (position, size, angle, the
point list a line or freedraw carries, its text, and the handful of style
fields), deliberately not on `version`/`versionNonce`/`updated`, which
Excalidraw bumps on more than a content change.

Two things had to stay silent for the guard to be worth having: opening an
existing drawing and closing it untouched, and drawing, saving, then closing.
The first holds because the comparison's baseline is `initial.elements` — what
was actually handed to Excalidraw to mount, not a second read taken back off
it — so a fresh, untouched mount reads as identical to itself. The second
holds structurally: a successful save calls the raw `teardown()` directly
rather than the close-attempt path that asks, because there is nothing left
in the popup for the person to lose once their strokes are already on the
server. Escape is two levels, matching the delete flow's own
(`detail.py:1959-1962`): with the question up it backs out of the question,
and only with no question up does it close the popup — bound as one branch of
the same `document`-level `keydown` listener the popup already had, rather
than a second listener, so Excalidraw's own reading of Escape (to drop a
selection) is unaffected.

## The spike, which came first

No openproj code was written until a throwaway spike answered the questions the CSP
asks. The bundle was built, mounted under `default-src 'none'`, and measured:

1. **Does it run at all** with no worker, no `blob:`, no wasm and no `<script src>`?
   Assert zero `securitypolicyviolation` events, with a deliberately-broken control
   beside it so the probe can fail — the shape already used for Ace at
   `tests/test_editor.py:5358`.
2. **Does the PNG export path avoid wasm?** Yes, and the wasm question is CLOSED,
   negatively: Excalidraw made **zero** wasm calls anywhere on the PNG path, and with
   wasm hard-blocked the exported PNGs came out correct and the same size. Nothing in
   `render/shell.py`'s policy needs to change for mount, PNG export or the PNG round
   trip. The chunk this question was really asked about — `chunk-EIO257PC.js`,
   1,824,966 B, the single largest input in the bundle — is real, but the guess about
   it was wrong on both counts: it is not the harfbuzz subsetter, it is
   **fonteditor-core**'s emscripten woff2 encoder, its wasm already base64-inlined as
   `Module.wasmBinary`; and it is not "pulled for SVG export" in any sense that saves a
   byte on the PNG path — `--format=iife` inlines it unconditionally, so 1,782 KiB of
   every shipped bundle is an encoder the PNG path never calls.
3. **How big is the real bundle?** The earlier guess measured the wrong build: that
   figure was for `--splitting --format=esm`, and splitting was never going to be
   available here, since chunk fetches need `script-src 'self'`. The `en`-only,
   mermaid-free IIFE that actually ships came in at **5,603,202 B raw, 2,025,230 B
   gzip** — heavy rather than impossible, and approved on those terms (see "The editor
   side," above).
4. **How big is a real drawing?** Measured: a 3-element drawing exports to ~15.8 kB and
   a 30-element one with ten text labels to ~116.5 kB — **5.6% of `MAX_ASSET_BYTES`, 18x
   headroom**. `MAX_ASSET_BYTES` is 2 MB (`web.py:612`), and it is not the constraint
   the spec feared for vector scenes. The scene itself rides in one `tEXt` chunk keyed
   `application/vnd.excalidraw+json` — 1,344 B for the 3-element scene, verified by
   parsing the PNG outside the browser — and the round trip was verified end to end: 3
   elements in, 3 out, types in order, with `loadFromBlob(blob, null, null)` the working
   call. Two exports of the same scene do not land on the same byte count, which matters
   for how a test may assert against this — see "Five helpers, not one," below.
5. **Does the unconditional `esm.sh` font fallback stay quiet?** Yes, and the guess
   about it was wrong twice over. There IS an effective disable:
   `ExcalidrawFontFace.createUrls()` short-circuits with `if (t.startsWith("data"))
   return [t]`, so rewriting the font literals to `data:` URIs means the esm.sh
   fallback is never even consulted — verified with DNS blackholed, zero external
   requests. And `font-src data:` does not refuse a `data:` `@font-face` the way it was
   assumed to: those URIs load fine under the existing policy,
   `document.fonts.check('20px Excalifont')` comes back true, and the exported PNG
   carries the real handwriting rather than a system-font substitute.
6. **Does it touch `localStorage` bare?** The shell wraps every browser-store access
   because bare access *throws on the property* in private windows and under enterprise
   policy — nine of twelve bare calls once killed the table before the first row drew.
7. **Does it mount under `--virtual-time-budget`?** Measured, and answered badly — see
   "Five helpers, not one," below, for the numbers. There is no forced-synchronous-paint
   hook the way Ace's `renderer.updateFull(true)` is one, and what a probe has to do
   instead, racing `requestAnimationFrame` against a `setTimeout`, is there too.

Green on every question above, so the openproj side proceeded as designed rather than
falling back to the export-and-drop handshake against excalidraw.com that was the plan if
wasm or fonts had come back red. Two things stayed unmeasured by the spike itself, and both
were closed once the rest was built:

- **The fetch-and-inject delivery this design specifies was never itself exercised by the
  spike.** The probe had inlined all 9.1 MB into one `file://` page rather than fetching it.
  `connect-src 'self'` allows the fetch and `script-src 'unsafe-inline'` allows the
  injection, and `'self'` is absent from `script-src` so a `<script src>` is refused and
  fetch-and-inject is the only door that opens — and the pair was then driven together, over
  a real origin, in `test_the_fetch_and_inject_delivery_is_clean_under_the_real_policy`
  (`tests/test_editor.py:7988`): zero `securitypolicyviolation` events, with a real
  `<script src>` as the forced-failure control beside it, so the zero is evidence the probe
  could have failed and did not, rather than an assertion that could only ever pass.
- **Inserting a raster image into a drawing is blocked, and stays blocked.** pica and
  image-blob-reduce construct a `data:text/javascript;base64` Worker for a
  `createImageBitmap` probe and a `blob:` Worker for resizing, and the policy is
  `default-src 'none'` with no `worker-src` and no `blob:`. jcanton accepted this on
  2026-08-26. The mounted editor hides the image tool (`UIOptions.tools.image = false`,
  `render/controls.py:2536`) — a control that is not offered, rather than one that lies.

## Five helpers, not one

`tests/browser.py` has five, not the single `file://` + `--dump-dom` channel this page
used to assume. `measured_in` (`tests/browser.py:105`) is that one: it writes the page
to disk and opens `where.as_uri()`, with the DOM as the only channel out. `_devtools`
(`tests/browser.py:181`), `in_a_live_page` (`tests/browser.py:328`) and `pressed_in`
(`tests/browser.py:280`) all drive real Chrome over the DevTools protocol instead,
against a real socket. And `screenshot()` (`tests/browser.py:48`) is a working pixel
channel: it rendered a correct full editor at its existing 5000 ms default.

The `live_server` fixture (`tests/test_web.py:2043`) runs the real app under uvicorn on
`127.0.0.1`, and `tests/test_web.py:2100` plus three uses of `in_a_live_page` in
`tests/test_coedit.py` already drive real journeys against it. **The
open-an-existing-drawing round trip is testable today**, over a real origin, through
`in_a_live_page` or `pressed_in` against `live_server` — exactly the way the co-editing
tests already do it. It is not a manual check, and the claim that it was one is gone
along with this sentence.

What is genuinely hard, and worth writing down instead of a blanket "cannot test":
`measured_in` cannot drive this page. At its usual ~5000 ms budget, 0 of 6 runs
completed; at 60000 ms, 3 of 6; only at 600000 ms did all 6 complete, and not cleanly
monotonically along the way — a longer budget is not simply a safer one here.
`requestAnimationFrame` is unreliable under it too: in the same scene, 1 fired and 2
timed out under `--dump-dom`, against 3 fired and 0 timed out over the DevTools
protocol, and a nested double-rAF never resolved at all either way. So any probe
against this page has to race `requestAnimationFrame` against a `setTimeout` rather
than trust the frame to arrive.

And no assertion here may use an exact byte size. Excalidraw's roughness draws its
wobble from a random seed, so the same scene exported twice does not land on the same
byte count: 15.1k–18.3k bytes at 3 elements, 113.2k–117.9k at 30, measured across
repeats of the identical drawing. A test that asserted a literal size would be
asserting the seed, not the feature.

The coverage this ships with: `put_drawing`'s refusals and its same-bytes convergence,
at the store level; the two routes and their `_write_or_refuse` wrapping, at the web
level; `_EMBED_SRC` against both arms and the negative cases (`drawings/notadrawing.png`,
`drawings/draw-a1b2c3.svg`, and three more) in
`test_a_drawing_is_drawn_and_a_lookalike_is_not` (`tests/test_render.py:3782`); the
export copying both directories; the deck inlining a drawing; the menu's scan as a pure
function over body text; and now, over a real origin, the round trip itself.

## Ceilings to respect

- `PILE_CEILING_COMMITS = 50` (`store.py:193`), sized because fifty commits is more than
  a betting table generates in that window. **One commit per Save press, never per
  stroke** — otherwise a drawing session refuses every save in the plan with a 503, not
  just drawing saves. The same-bytes convergence check kills the no-op re-save. Neither is
  enforced by anything; both are discipline.
- PNG is already zlib-compressed, so git cannot delta it and every save is a full new
  blob. `store.py:186-187`: on Cloud Run the filesystem is memory, so a 200 there is data
  loss with a receipt.
- `Store.last_edited` puts every path at head into the settle-set (`store.py:943`), and
  `_PARSED`'s prune threshold (`web.py:835`) counts total blobs. Drawings arrive in bulk
  and inflate both for no benefit.

## Things that are true and unpleasant

- **`drawings/` is invisible to every reporting surface.** A mistyped drawing path in a
  body is a silent broken image: no banner, no `openproj check` line, nothing. One level
  up from the hole `record_paths_in`'s nested-file branch exists to close.
- **The name `drawings` becomes spoken for.** `_RECORD_DIRS` is derived from `KINDS`
  (`model.py:1315`), so a future seventh rung named `drawing` would retroactively make
  `drawings/` a record directory and every file in it a claimed record, with no migration.
- **The font licences were checked family by family, and one did not clear the bar the
  other seven did.** The Latin build ships **24 woff2 across 7 families**: Assistant (4
  files, 81,144 B), Excalifont (7, 64,768 B), Cascadia (1, 65,732 B), Virgil (1, 56,156 B),
  ComicShanns (4, 31,452 B), Nunito (5, 57,564 B), Lilita (2, 12,092 B). The package itself
  is MIT and the repo LICENSE is MIT, but every one of those 24 files is third-party with
  no per-font LICENSE file in the npm package, so each family was checked against its own
  shipped `name` table rather than assumed from a web page. The generated Excalifont's
  embedded string still reads "Copyright (c) 2024 by Excalidraw. All rights reserved." —
  no licence grant of its own anywhere in the file — resolved on Excalidraw's own public word
  that it is OFL-1.1, since Excalidraw holds the copyright. **Liberation Sans (1 file,
  70,668 B) was dropped**, and not for size: its shipped binary turned out to be the
  pre-2012 Ascender/Red Hat build, GPLv2 with the standard font-embedding exception — and
  that exception is scoped to a document that embeds a font, not to software that bundles
  one as a resource inside its own distributed binary. `dataUri()` returns it the same
  `local:` sentinel it returns for Xiaolai, below, and Excalidraw's own font metadata marks
  Liberation Sans `private:` true, an internal metrics-fallback face never offered in the
  font picker, so the cut changes nothing a person using this tool can choose. The full
  texts, one per family, are in `static/excalidraw-fonts-LICENSE.txt`; the per-file licence
  requirement `static/VENDOR.md` states applies to all 24.
- **CJK is out.** Confirmed almost exactly: Xiaolai, 209 files, 12,667,492 B, under
  every option. Dropping it is clean rather than merely necessary, though: replacing the
  literals with a `local:` sentinel makes `createUrls()` return `[]` — no fetch, no
  console error. The canvas just falls back to whatever that leaves it drawing with, and
  what that fallback actually renders was not inspected, so non-Latin text in a drawing
  stays a quiet correctness gap.
- **`exportToBlob` may not honour `appState.exportScale`.** Read from master: the public
  wrapper appears to override the `createCanvas` that would have applied it, so a 2x
  export may silently come back 1x unless `getDimensions` is passed. No corroborating bug
  report found. It decides whether drawings look right on a retina screen, and it needs a
  smoke test rather than a citation.
- **A conflict's shape on the wire needed its own refusal line, not the editor's existing
  conflict box.** The drawing popup has no textarea and no diff to show, so `_result`'s 409
  is caught before it reaches any shared machinery: the status line prints the server's
  sentence verbatim and the popup stays open with the strokes still in it, rather than
  closing on the refusal it just showed (`render/controls.py:2579-2587`). Verified against a
  real conflict — an `httpx` client changes the same drawing from outside the browser
  between reopen and Save — in `test_a_stale_save_is_refused_and_the_popup_keeps_the_work`
  (`tests/test_editor.py:8138`).
