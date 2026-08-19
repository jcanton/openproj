# Co-editing one shaping document — design

**Status:** proposed, 2026-08-18. Nothing implemented. Every size below was measured today.

## 1. Yjs, and what vendoring it costs

Automerge is out on one measurement: `@automerge/automerge` 3.4.1's `dist/automerge.wasm` is
**3,571,259 bytes**, and the entrypoint that avoids a second fetch inlines it as base64 at
**4,761,717 bytes** — thirteen cytoscapes in every detail page, and it needs
`script-src 'wasm-unsafe-eval'`. Weakening the CSP to run a merge algorithm is the wrong trade.

Yjs 13.6.32 (MIT) has no wasm and no self-contained bundle either. `dist/yjs.mjs` (299,797 B)
carries twenty bare `lib0/*` imports; jsDelivr's `+esm` (79,709 B) rewrites those to CDN paths,
which `test_no_page_reaches_the_network` would catch and should; y-protocols' bundle (6,711 B)
externalises Yjs and drags a second lib0. One artifact bundles lib0 in:

| commit as | from | bytes | sha256 |
|---|---|---|---|
| `static/yjs.bundle.mjs` | `esm.sh/yjs@13.6.32/es2020/yjs.bundle.mjs` | 93,496 | `2ac30c83…` |
| `static/yjs-process-shim.mjs` | `esm.sh/node/process.mjs` | 7,861 | `79e7646e…` |
| `static/yjs-LICENSE.txt` | yjs v13.6.32 `LICENSE`, MIT | 1,211 | — |

101,357 bytes, a quarter of the cytoscape already vendored. The honest cost: they cannot be inlined
*verbatim*. The bundle opens with one `import` of the shim and closes with `export{…}`, and the page
has no module graph to hand that to. The bytes in git stay upstream's and stay checksummed;
`render.py` joins them and rewrites those two lines at inline time, and a test asserts the result
holds no `import` or `export` at all. Minified code carries no notice, so the MIT text ships beside
it the way Inter's OFL does.

y-protocols is not vendored. Awareness is a per-client last-write-wins map with a timeout — a
hundred lines over a socket we own, against a second lib0 and an import map the CSP forbids.

## 2. Transport

`WSS /api/coedit/<entity_id>`. CSP 3 makes `'self'` match the `ws`/`wss` variant of the document's
origin, so `connect-src 'self'` already permits it and must not be touched — a claim about browsers,
so `tests/browser.py` checks it rather than a comment asserting it.

Two facts the deploy fixes. `pyproject.toml` pins plain `uvicorn`, and `uv.lock` has neither
`websockets` nor `wsproto`, so uvicorn refuses every upgrade with 403 today; add `wsproto`, pure
Python, no wheel to rot. And Cloud Run runs `--timeout 300`, so **every socket dies after five
minutes**. Reconnection is the normal case, which is most of the argument for a CRDT over OT.

Refusal is the floor, not the edge case: `file://` has an opaque origin and no server, a proxy may
drop the upgrade, and a five-minute teardown looks like both. One flag — no socket, and the page is
exactly today's textarea, draft, `base_commit`, Save, 409.

## 3. What is shared: the body, and nothing else

A `Y.Text` of the markdown body; the frontmatter stays on the form. The fields are typed,
`validate_all` decides requiredness in one place, the `parse_text` gate stands over the write path,
and `_merge_frontmatter` merges them per key — they set the status while I set the priority has not
been a disagreement for months. A `Y.Map` would make the CRDT the authority on values whose
invariant lives elsewhere, and it would converge happily on `title: 5`. The body is the half with no
structure, no validator, and a line merge that refuses honestly rather than merging well.

Awareness carries login, colour and a `Y.RelativePosition` caret, and is never persisted: presence
is not authorship.

## 4. The commit, and who authors it

Every Yjs item records the `clientID` that inserted it, and the server binds clientID to login from
the session cookie at connect — never from the client. So the people in a commit are computed:

- **author** — whoever inserted the most characters since the last commit. Deterministic, and right
  in the ordinary case of one person writing and another fixing a sentence.
- **`Co-authored-by:`** for everyone else in that diff. `git log --format='%an'` keeps the
  per-person trail it has today; `git shortlog` sees both halves.
- **committer** stays `openproj-bot`. That split is untouched.

A commit fires on Save, on the last participant leaving, or after twenty seconds of quiet — one
`store.write` against the room's base. If somebody edited in git or through the API meanwhile,
`_merge` runs exactly as now, and when it folds in their change the server applies the difference
back into the `Y.Doc`, so the room sees their paragraph arrive as text. A genuine overlap still
returns the conflict report, shown to the room and retried on the next quiet window — never pasted
into the editing surface.

## 5. Restart

The room is in memory on one process, which `--max-instances 1` makes safe and a redeploy makes
temporary. It is a cache: every client holds the same `Y.Doc`, so a restart with anybody connected
loses nothing — they reconnect, exchange state vectors, rebuild it. The floor is the twenty-second
window, and below that the draft already in `localStorage`.

The trap is seeding. Two docs built independently from the same text share no history and merge into
that text *twice*. So a room is seeded once from HEAD's body with a fixed clientID, making the seed
a function of the commit; a client carries the commit it was seeded at, and a mismatch is answered
with "reload" rather than a merge. Somebody typing through a restart sees the socket drop, their
text stay, and either a silent reconnect or the reload a 409 would have given them.

## 6. Not this round

No CRDT for frontmatter. No Yjs state persisted anywhere — git holds text, and a binary the tool
cannot read back is not a source of truth. No y-protocols, no Automerge, no wasm, no CSP change, no
second instance. No editor library: VENDOR.md's refusal of CodeMirror stands, which leaves remote
carets to be drawn over a `<textarea>` through a mirror element — the one piece of real pixel work
here, and why `tests/browser.py` gates this. Ship convergence and a named presence list first; a
caret one line off is worse than no caret.

🤖 Written by an agent on behalf of @jcanton
