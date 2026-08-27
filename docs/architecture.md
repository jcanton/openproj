# Architecture

## The pages

`index.html` is **Records**, the landing page — every record in the plan, one
line each, newest edit first, with the search box above it. `table.html` is the
filterable, searchable table and the page PM work lives in. `graph.html` is the
dependency DAG, grouped by project and pitch. `timeline.html` is the derived
Gantt. `cycles.html` and `people.html` are the cycle records with their betting
tables, and who is on what and who is full — and on a cycle's roster each
person's row carries their scheduled end date beside their capacity bar, so a
green capacity bar can never sit next to a timeline running into November
without saying so. `detail.html` is one record on its own page — any of the six
kinds — and under the server it is also where a record is edited. `help.html`
is this documentation.

Issues and notes are records whose rung says `planned=False`: they are on
Records and on their own pages, and never in the plan views.

The pages render from one in-memory index, share one filter model, and keep
their state in the query string — so every view is a shareable URL, and there
are no saved views to manage. The index is rebuilt whole from a commit and
never incrementally — measured at ~50 ms over 300 records and ~250 ms over
2,000, which buys the deletion of the entire class of incremental-invalidation
bugs. It is an immutable snapshot swapped in atomically, so a reader holds a
reference and is never blocked by a write.

`/deck/<n>` is a route only: the deck for one cycle's review meeting — a title
slide, then one slide per piece of work bet into that cycle It takes a cycle
number, so it has no place in a static export; it is reached from that cycle's
own page.

## Two repositories

The tool and the plan are separate repositories, and stay separate in production.

```
jcanton/openproj      this repo — code, tests, and fixtures. No real plan data.
jcanton/icon4py-plan  the data — markdown records and config. No code.
```

Three reasons the split is load-bearing:

- **A plan commit must not run the tool's CI.** Someone changing a status should not queue a test
  suite, and a red suite should not block someone changing a status.
- **The write credential must be structurally incapable of touching source.** Scoped to one
  repository with `contents: write`, a leaked token costs you a revertable plan; scoped wider it is a
  supply-chain foothold in a scientific codebase.
- **Their histories have nothing to say to each other.** `git log` on the plan is a record of
  decisions; on the tool it is a record of code.

The seam is the `--repo` argument. The server holds a bare clone of the plan repo and knows nothing
else about it, so pointing a deployment at a different plan is a flag, not a fork.

```bash
git clone --bare https://github.com/jcanton/icon4py-plan.git plan.git
uv run openproj serve --repo plan.git --auth dev
```

For a look at the tool with nothing to point it at, `openproj demo` does the same against the bundled
`seed/` corpus in a temporary directory. `--auth dev` is for a local run only; the
deployment runs `--auth github`, which refuses to start without a signing secret and an OAuth
client. `deploy/RUNBOOK.md` has the rest.

On Cloud Run the container clones the plan repo on boot and pushes on write, which is also why the
running service is close to stateless — the durable data is the git remote, not the disk.

## Layout

```
src/openproj/model.py      schemas, parse, round-trip serialise, validate_all
src/openproj/schedule.py   the scheduler — a pure function, the product
src/openproj/index.py      the snapshot every view renders from
src/openproj/query.py      the search language, shared by the server and the browser
src/openproj/render/       the pages — a package behind a re-exporting facade
src/openproj/store.py      the git write layer — bare repo, one writer, scoped CAS
src/openproj/pusher.py     the deferred push: a commit lands locally, then goes out
src/openproj/coedit.py     the co-editing rooms — one Y.Text per record, in memory
src/openproj/web.py        the server: routes, auth, the write endpoints
src/openproj/auth.py       sign-in: the OAuth dance, the session, who may write
src/openproj/github.py     what the server asks GitHub — the App token, open PRs
src/openproj/vendor.py     static/ and docs/ on disk, read once and inlined
src/openproj/cli.py        check / render / schedule / serve / demo
src/openproj/themes.py     the colour schemes — sixteen numbers a row, nothing else
seed/                      the demo corpus
tests/fixtures/corpus/     the frozen golden corpus the scheduler goldens pin
static/                    vendored, pinned JS — see static/VENDOR.md
docs/                      this documentation, and what the app's Help page reads
```

`store.py` is a bare repository with no index to contend for, one writer behind an `flock`, and
compare-and-swap scoped to the path being written — so an edit to a different file retries invisibly
and only a genuine overlap is refused.

**No npm, no build step, no CDN**, and `tests/test_render.py` asserts no rendered page reaches the
network. Two vendored libraries are fetched rather than carried, both megabytes: the drawing editor
on the first press of the drawing button, and mermaid on a page that has a fence for it. `GET
/static/<name>` answers for an allowlist of exactly those two; `static/VENDOR.md` has the
arithmetic. A diagram in a document is a diagram where there is a server and its source where there
is not — `openproj render` writes files opened over `file://`, which have nothing to fetch from.

**`node` is not needed to build or run it, and is needed to test it fully.** A set of tests runs the
shipped page scripts against a minimal DOM; without `node` on PATH they skip, and a suite missing
them is green for the wrong reason.

## Colour

Two controls in the corner, beside the identity. The light/dark switch is the polarity; the picker
beside it is the palette — nine base16 families, each a light and a dark, plus the app's own colours,
which are the absence of a choice rather than a family called "default".

A scheme is sixteen colours and the app draws with fifty-five, so the other thirty-nine are derived
once, for every scheme. `themes.py` is a table with a row per palette; adding a family is a row.
`tests/test_themes.py` measures the result twice — the palette in Python, and what the page paints
in Chrome, at AA for every chip and every fill of every family in both polarities.

## Co-editing one document

Several people can type in one shaping document at once. `coedit.py` holds the rooms — one `Y.Text`
of the markdown body per record, and nothing else; the frontmatter stays on the form, where the
fields are typed and `validate_all` decides requiredness in one place.

A room is a way of arriving at a commit, not a replacement for one. Every room ends in exactly one
`store.write` against its own base — on Save, on the last participant leaving, or after twenty
seconds of quiet — so a person editing in git, in a second tab or through the API is still handled by
the same three-way merge, and a genuine overlap is still the same refusal. The author is whoever
inserted the most characters since the last commit, with a `Co-authored-by:` for everybody else.

Nothing is persisted: git holds the text. The room is in memory on one process, which
`--max-instances 1` makes safe, and losing it costs the twenty-second window and nothing committed.
`AGENTS.md` lists what was deliberately not built, and why, so that it is not re-opened.
