# Architecture

## The pages

`index.html` is **Records**, the landing page — every record in the plan, one line each, sorted by
last edited where there is git history to ask and by id in an export of a plain directory, with the
search box above it. `table.html` is the filterable, searchable table and the page PM work lives
in. `graph.html` is the dependency DAG, grouped by project and pitch. `timeline.html` is the
derived Gantt. `cycles.html` and `people.html` are the cycle records with their betting tables, and
who is on what and who is full. A capacity number and a date are drawn beside each other or neither
is trusted, so each person's row carries their scheduled end date next to the capacity bar: a green
bar against a timeline running into November is what stops a room trusting the tool. `detail.html`
is one record on its own page — any of the six kinds — and under the server it is also where a
record is edited.

Issues and notes are records whose rung says `planned=False`: they are on Records and on their own
pages, and never in the plan views. The exclusion is not a filter on each page — `Index.plan`
holds planned kinds only, a validator on `Index` refuses anything else, and each name states its
population, so a timeline function that reaches for `records` announces the widened view on the
line that takes it. `POST /api/promote` is the door out of both inboxes: it writes the record and
marks the source in one commit.

They render from one in-memory index, share one filter model, and keep their state in the query
string — so every view is a shareable URL, the back button works, and there are no saved views to
manage. The index is rebuilt whole from a commit and never incrementally — measured 2026-08-12 at
~50 ms over 300 records and ~250 ms over 2,000, which buys the deletion of the entire class of
incremental-invalidation bugs. It is an immutable snapshot swapped in atomically, so a reader holds
a reference and is never blocked by a write.

`/deck/<n>` is the odd one out and is a route only. It is the deck for one cycle's review meeting —
a title slide, then one slide per piece of work bet into that cycle, each with its ticked points,
its percentage, its pull requests and what the record says about what happened, and it prints one
slide to a page. That last part is a floor and not a filter: the shaping argument stays off the
sheet because the room argued it at the betting table, but a slide that has nothing else falls back
to the record's Solution, because a heading over blank paper is nothing to present from. The
fallback is bounded — 120 words, measured against Chrome's own pagination — since a quotation of the
plan has no business pushing the presenter's slide onto a second sheet; and where it was cut, or
where the record turned out to have nothing written on it at all, the slide says so in a line of its
own. A sheet that silently dropped half a section cannot be told from a finished one, and the person
holding it is the one person who cannot go and check. It takes a cycle number, so
it has no place in a static export that writes one file per view of the whole plan; it is reached
from that cycle's own page, and it is deliberately not a seventh tab. It is also the one page that
carries its images inside itself as `data:` URIs, because it is the one page meant to be handed to
somebody who was not in the room.

## Two repositories

The tool and the plan are separate repositories, and stay separate in production.

```
C2SM/openproj        this repo — code, tests, and fixtures. No real plan data.
C2SM/<name>-plan     the data — markdown records and config. No code.
```

`seed/` and `tests/fixtures/corpus/` live here only because they are a demo and a
test fixture. Neither is anybody's plan.

Three reasons the split is load-bearing:

- **A plan commit must not run the tool's CI.** Someone changing a status should not
  queue a test suite, and a red suite should not block someone changing a status.
- **The write credential must be structurally incapable of touching source.** The
  server commits to the plan repo continuously. Scoped to one repository with
  `contents: write`, a leaked token costs you a revertable plan; scoped wider it is a
  supply-chain foothold in a scientific codebase.
- **Their histories have nothing to say to each other.** `git log` on the plan is a
  record of decisions; on the tool it is a record of code. Interleaving them makes
  both harder to read, and `git blame` on an appetite field stops being useful.

The seam is the `--repo` argument. The server holds a bare clone of the plan repo and
knows nothing else about it, so pointing a deployment at a different plan is a flag,
not a fork.

```bash
git clone --bare https://github.com/jcanton/icon4py-plan.git plan.git
uv run openproj serve --repo plan.git --auth dev
```

That is the recipe for a **real** plan. For a look at the tool with nothing to point it at,
`openproj demo` does the same five steps against the bundled `seed/` corpus in a temporary
directory — it is the same server behind the same seam, with the clone replaced by a repository it
builds for itself.

A **bare** clone, and not a directory of files: there is no working copy to contend for and no index
to lock, which is what makes one writer behind an `flock` a workable design. `--auth dev` skips
sign-in and is for a local run only; the deployment runs `--auth github`, which refuses to start
without a signing secret and an OAuth client. `deploy/RUNBOOK.md` has the rest.

On Cloud Run the container clones the plan repo on boot and pushes on write, which is
also why the running service is close to stateless — the durable data is the git remote,
not the disk.

## Layout

```
src/openproj/model.py      schemas, parse, round-trip serialise, validate_all
src/openproj/schedule.py   the scheduler — a pure function, the product
src/openproj/index.py      the snapshot every view renders from
src/openproj/render.py     the pages
src/openproj/store.py      the git write layer — bare repo, one writer, scoped CAS
src/openproj/coedit.py     the co-editing rooms — one Y.Text per record, in memory
src/openproj/web.py        the server: routes, auth, the write endpoints
src/openproj/cli.py        check / render / schedule / serve / demo
src/openproj/themes.py     the colour schemes — sixteen numbers a row, nothing else
seed/                      the demo corpus
tests/fixtures/corpus/     the frozen golden corpus the scheduler goldens pin
static/                    vendored, pinned JS — see static/VENDOR.md
```

`store.py` is a bare repository with no index to contend for, one writer behind an `flock`, and
compare-and-swap scoped to the path being written — so an edit to a different file retries invisibly
and only a genuine overlap is refused.

**No npm, no build step, no CDN.** A Node toolchain that rots is the most common way a small
internal tool becomes unbuildable in two years. `tests/test_render.py` asserts no rendered page
reaches the network.

**`node` is not needed to build or run it, and is needed to test it fully.** Thirty-four tests run
the shipped page scripts against a minimal DOM — the table's rows, the timeline's tooltip, the
combobox and the cycle roster exist only after a script has run, so nothing in a rendered file
shows what they build. Without `node` on PATH those tests skip, and a suite missing them is green
for the wrong reason. `pytest` names every skip; a machine that is meant to gate a merge should
have `node` installed.

## Colour

Two controls in the corner, and they do different jobs. The light/dark switch is the
polarity. The picker beside it is the palette: nine base16 families, each a light and a
dark, plus the app's own colours — which are the absence of a choice rather than a
family called "default", so every page nobody has chosen for is drawn by the stylesheet
as written.

A scheme is sixteen colours and the app draws with fifty-five, so the other thirty-nine
are derived — once, in `_scheme_css`, for every scheme. `themes.py` is a table with a row
per palette and nothing else in it; adding a family is a row. The derivation leans on
`color-mix` in oklab, because a chip's soft ground and a node's readable fill are the hue
and the background in some proportion, and neither exists in a palette written for a
terminal.

Three values are chosen per palette rather than taken from the slot the format names: the
ink, the secondary ink and the link colour, each picked by contrast (`_chosen`). base05
is nominally the foreground and a terminal scheme is free to make it something no
paragraph has been set in. `tests/test_themes.py` measures the result twice — the palette
in Python, and what the page paints in Chrome, at AA for every chip and every fill of
every family in both polarities.

## Co-editing one document

Several people can type in one shaping document at once. `src/openproj/coedit.py` holds the rooms —
one `Y.Text` of the markdown body per record, and nothing else; the frontmatter stays on the form,
where the fields are typed and `validate_all` decides requiredness in one place. `WSS
/api/coedit/<id>` carries it, which `connect-src 'self'` already permits.

A room is a way of arriving at a commit, not a replacement for one. Every room ends in exactly one
`store.write` against its own base — on Save, on the last participant leaving, or after twenty
seconds of quiet — so a person editing in git, in a second tab or through the API is still handled
by the same three-way merge, and a genuine overlap is still the same refusal. The author is computed
rather than declared: whoever inserted the most characters since the last commit, with a
`Co-authored-by:` for everybody else in the diff, and characters are credited to the socket they
arrived on rather than to the client id inside the update.

Nothing is persisted: git holds the text. The room is in memory on one process, which
`--max-instances 1` makes safe, and losing it costs the twenty-second window and nothing that was
committed. Why Yjs and not Automerge is in `static/VENDOR.md`, beside the bytes: Automerge's wasm
is 3,571,259 bytes and running it needs `script-src 'wasm-unsafe-eval'`, and weakening a policy
that says `default-src 'none'` to run a merge algorithm is the wrong trade.

## Deliberately not built

Each of these was excluded, and the reason is here so that it is not re-opened. **Notification
infrastructure** is its own project, and Slack exists. **User-defined custom fields** mean editing
the model and running a migration — the honest cost of a field every page has to know about. **A
PR-based editing workflow** is what git already is, and the premise of this tool is that a pull
request is the wrong default for a plan. **Time tracking, burndown charts and per-project
permissions** were asked for by nobody here, and each needs a second source of truth to answer.
**Inline comments and resolved threads on a record** would be the first piece of plan state that is
not a file — a second store, a second permission model and a second notification path — while the
review channel this team already uses is the pull request, which every pitch names in `prs:`.

Real-time co-editing was on this list until the design above, excluded on the grounds that
compare-and-swap *is* the design, and that argument still holds for everything except the body of one
document that two people are writing at the same time.

Nothing may make the CI bot write record frontmatter. The bot owns `derived/` and nothing else;
if it starts patching frontmatter, bot and humans fight over the same files forever.

🤖 Written by an agent on behalf of @jcanton
