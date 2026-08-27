# A save that does not wait for GitHub

Designed 2026-08-24 with jcanton and **built since**: `src/openproj/pusher.py` is the thread
this document argues for. What follows is the expensive half — the reasoning and the measurements —
kept where the next person can read it, and read it as the design it was rather than as a
description of what shipped.

## The number this is about

`POST /api/record` measured 1.45s, 1.55s, 1.93s and 2.04s on the deployed service on
2026-08-24; `PATCH /api/record/{id}` 1.46s to 2.02s; `DELETE` 1.60s. Read routes on the
same instance answer in 7 to 60ms.

Measured against the local server with no remote, the whole of this application's work on
a create is **8 to 12 ms**: `validate_all` over the whole plan 0.55ms, `_records_at`
0.025ms warm behind the blob-keyed parse cache, `_config_at` 2.05ms, the entire pygit2
commit 2.4ms. Everything else is `_send`'s push to GitHub — a fresh TLS connection per
push, an unauthenticated `GET info/refs` that GitHub answers 401, the authenticated
retry, and then `git-receive-pack`, whose server-side time is the ~0.9-1.5s that
dominates.

None of that is ours to make faster. libgit2 opens a new connection per push and pygit2
exposes no way to pool it or to pre-send credentials; both were checked. So the only
thing left to change is **who waits for it**.

## What changes, in one sentence

The request stops waiting for the push. A commit is made under the lock exactly as
today, the answer goes back at once, and a single background pusher lands
`refs/heads/main` on its own.

## What does not change, and this is the important half

- The compare-and-swap and `_commit` stay inside `_writing`, byte for byte. Two people
  saving the same record still resolve through the same per-path three-way merge and
  still get the same 409 in the same words.
- No commit is ever reported as having reached the remote before it has.
  `WriteResult.pushed` keeps meaning exactly what it means today.
- History stays linear. Every commit the remote receives has one parent, keeps the
  original author signature — the person, with the bot as committer — and keeps its
  message. `git log --format='%an'` stays a per-person audit trail.
- `/api/health` still reads two local refs, takes no lock and touches no network.

## Why not batch on a timer

The first shape offered was a 5-minute sync interval. It was rejected, and the reason is
worth keeping because it is not obvious.

Cloud Run allocates CPU **only while a request is in flight** (the live revision carries
no `cpu-throttling: false` annotation, and the runbook explains why it must not: two to
three orders of magnitude more expensive). A five-minute `asyncio` timer therefore cannot
be relied on to fire at all. Worse, the instance is torn down when it goes *quiet* — which
is precisely when the last person has stopped working, which is precisely when their
newest commits are the unpushed ones. The rare event is perfectly aligned with the
expensive one.

And batching buys nothing the cheap version does not. The speed comes from not making the
person wait, not from grouping the pushes. Deferring by ~2 seconds gets the same answer
with a hundred and fiftieth of the exposure, keeps `unpushed: 0` meaningful, and keeps a
hand-push colliding with one commit instead of five minutes of them.

## The open problem, and the three answers weighed

Today `_attempt` can recover from a rejected push because it holds `_writing` across
*both* the commit and the push. On `_Rejected` it rewinds `refs/heads/main` to `before` —
the head captured immediately before its own `_commit` — absorbs the remote and re-runs
the compare-and-swap. That is sound only because nothing else can have committed in
between.

Move the push out of the lock and `before` is wrong: HEAD may carry commits other people
made after the one being retried, and the rewind discards them silently. The trigger is
somebody pushing to the plan by hand, which the README makes a first-class workflow.

Three shapes were designed independently and each was attacked by an adversary told to
find the interleaving that loses somebody's work.

**Reconcile-by-merge** — one bot-authored merge commit per hand-push, parents `[local, remote]`, tree built per path. Rejected. It dissolves `write_all`'s atomicity: that
function's own comment says *"A conflict on ANY path writes nothing at all — a partial
commit is exactly the half-done state above, arriving through the other door"*, and a
per-path merge over a flattened tip tree has no commit boundaries to honour. A promotion
would land its new pitch and lose the note that says what it became. It also braids the
plan's history permanently and forecloses linear-history protection.

**A fence and a replay queue** — bound how far local may run ahead by keeping each
pending write's full payload in memory, so a rewind can always re-drive them. Rejected,
though its central insight is kept: safety is not a *count* of unpushed commits, it is
that everything above the last remote-confirmed sha can be re-driven. Its fatal problem
is that it still rewinds, so a crash mid-recovery leaves acknowledged commits reachable
from no ref a restart looks at. At a queue depth of one it also degrades to today's
blocking under concurrent saves, which is the case this whole change exists to fix.

**Rebase-by-recommit** — chosen. Described below.

## Rebase-by-recommit

### The write path

`_finish` stops calling `_send`. It returns `WriteResult(commit, outcome, pushed=False)`
and sets a `threading.Event` that pokes the pusher. `_attempt` loses its `_Rejected` arm
entirely — the `before` capture, both rewinds, `_absorb_remote` and the `tries`
parameter all go, because `_Rejected` can no longer reach it. The compare-and-swap keeps
handling browser-side staleness (a `base_commit` older than HEAD) exactly as today;
remote staleness stops being its problem.

`put_asset` loses its opening `_absorb_remote()`. That fetch existed because nothing else
ever reconciled an unpushed asset commit; the pusher now reconciles everything. After
this change **nothing inside `_writing` touches the network at all**, anywhere in the
file.

The per-path decision ladder is extracted out of `_attempt` into one function, so that
write-time and replay-time conflict semantics cannot drift. This is the file's own rule:
an invariant written twice will be guarded once.

### The pusher

One thread. It waits on the poke, calls a new `Store.sync()`, and hands the outcome back
to the event loop through `call_soon_threadsafe`. It works on a **fresh
`pygit2.Repository` handle**, never the shared one, which is the pattern the file already
uses for every cross-thread read — pygit2 objects are not safe to share between threads,
and this file has no working copy and no index precisely because eight concurrent writers
once lost 87.5% of their commits to `index.lock`.

On the quiet day `sync()` pushes and stops. **No fetch, and the original commits go up
with their original shas** — a client's answered sha is the sha that lands. Sha
instability exists only on the recovery path.

### Recovery, when the push is rejected

All of this runs *without* `_writing`, except the last swap.

1. Fetch. Unreachable is not a rejection: the backlog stays intact and the pusher backs
   off, which is today's behaviour for a commit the remote missed.
2. **Force-push guard.** The store keeps a private ref meaning "the newest commit this
   process has positively confirmed the remote holds as part of our lineage". If the
   fetched remote does not contain it, the remote *lost* a commit we saw it hold: that is
   a genuine fork, and it parks. No replay, no rewind, ever. This replaces
   `_absorb_remote`'s two-arm shape, whose diverged arm would otherwise catch every
   ordinary hand-push once local-only commits are routine.
3. Walk the local-only commits, oldest first.
4. For each, take its per-path blob-id diff against its own parent, and re-drive it
   through the shared ladder onto the growing tip: identical blob id means a convergent
   edit and is skipped; unchanged-since-base takes ours; delete-versus-edit refuses; and
   anything else decodes and merges the way a save does. Winners are folded in with the
   existing `_insert`/`_drop` loop. A replay that produces an identical tree mints
   nothing — no empty commits on the decision log.
5. Mint each replayed commit with `ref=None`, so no branch moves: **the original author
   signature verbatim**, the bot as committer, the message unchanged.
6. Push the rebased tip and every parked branch in one call, **before** local main moves.
   The person's content is durable on GitHub before anything claims otherwise.
7. Only now take `_writing`, replay any commits made during the recovery — pure local
   tree work, milliseconds — and move the branch ref. Then push again if that added
   anything.

A rejection during recovery simply restarts it, and it converges: replaying an
already-applied delta is a no-op, and hand-pushes arrive at human rate.

### The one flaw the adversary found, and its answer

Commits made *during* a recovery are replayed at step 7 under the lock, and that replay
had no conflict arm — a straggler that conflicts would be silently dropped. It gets the
same treatment as the main loop: park it, push its branch, continue. Nothing may be
dropped merely because it arrived late.

### Parked conflicts

A conflict discovered at replay time has **no user attached**. The 200 went out long ago.
So the commit is not dropped and not retried forever; it is pushed to
`openproj/stranded-<sha>` on the plan repository, which cannot be rejected because the
ref does not exist yet — verified against two real repositories: a `main` push refused as
non-fast-forward, the identical commits accepted on a side ref, and the work reachable on
the remote afterwards.

A pull request is opened from that branch. The App's installation was granted
`pull_requests: write` on 2026-08-24 for this, and remains `repository_selection: selected` — it can create a ref and a PR on the plan and nothing else, so the rule that
the push credential is structurally incapable of touching source still holds. The branch
is the durability and the PR is the visibility: **a 403 or an outage on the PR is logged
and never fatal**, because the branch has already landed by then.

**A parked commit does not stall the ones behind it.** Later commits replay against a tip
that lacks it, which for non-overlapping edits merges cleanly and for overlapping edits
parks in turn — never silent reintroduction. The cost is real and is accepted: a
multi-commit intent can be split, so a record can end up pointing at a parent that is
only on a branch. That is a *reported blocker*, not a broken page, because this
application parses permissively and validates strictly; the plan says so beside the
record. Stalling everybody behind one person's conflict is the worse answer.

`write_all` stays atomic. A promotion is one decision and one commit, so if any of its
paths conflicts the whole commit parks — the half-done state does not come back through
this door either.

## Saying it on the page

Three states, escalating, chosen by jcanton:

- **Normally** — a quiet per-row mark on `/table` meaning "saved here, not on GitHub
  yet", clearing when the commit is confirmed landed. The table and the shell banner are
  the whole surface; the graph, timeline, cycles and record page rely on the banner.
- **When the pile grows or the pusher is failing** — a loud banner in the shell naming
  the problem and how many commits are stranded.
- **Past a threshold** — writes are refused with the 503 the wedged path already uses,
  so nobody adds to a pile that cannot land. The threshold is **fifty unpushed commits or
  ten minutes since the last successful push**, whichever comes first. Both numbers are
  arbitrary and are written down so they can be argued with rather than discovered in an
  incident: ten minutes is long enough to ride out a GitHub outage and short enough that
  a wedged pusher is caught inside one working session, and fifty commits is more than a
  betting table generates in that window.

### Confirmation cannot be "my sha is on main"

Recovery mints new shas. A page that waits to see its own answered sha on the branch
would wait forever after any rejection. So the pusher announces, per sync, the tip it
landed and an **old-to-new map** of every sha it re-minted, plus every sha it parked and
where. A mark clears when its sha is named as landed, as re-minted-and-landed, or as
converged; it turns into a problem when its sha is named as parked.

Three consequences to build for rather than discover:

- **The SSE stream has no replay.** A tab that reconnects — and Cloud Run recycles every
  stream at 300s — misses the frame and its mark never clears. Clearing needs
  "everything up to X has landed" semantics and a poll fallback, not a per-commit event.
- **`render/editor.py` says "saved here, not yet pushed" whenever `pushed === false`.**
  Under this design that fires on every save and becomes wallpaper. It needs a third
  state: in flight, landed, stranded — not a boolean.
- **`POST /api/record`'s 201 body carries no `pushed` key at all** today, so the create
  path has nothing to hang a mark on until it does.

## Health

`unpushed` stops meaning "at risk" — it will be non-zero for a second or two after every
save. The alarm has to be re-scoped to *nonzero and not draining*: the age of the oldest
unpushed commit, and when the last push succeeded. `diverged` changes from
neither-contains-the-other to "the remote no longer contains what we confirmed it held",
because both-sides-moved is now the ordinary recoverable case rather than a wedge.

`/api/health` must never be wired as a Cloud Run liveness probe. It never could be, but
it matters more now: answering a red check by replacing the container would "clear" the
condition by destroying exactly the commits the check is complaining about.

## Two prerequisites, and they are bugs today

Neither is optional and both ship first.

**`deploy/boot.py` never receives SIGTERM.** The Dockerfile's `CMD` makes `boot.py` PID
1; it installs no signal handler and starts the server with `subprocess.call` rather than
`exec`. Python leaves SIGTERM at `SIG_DFL`, and a default-disposition signal to PID 1 is
discarded by the kernel. So `Server.handle_exit` never runs on Cloud Run,
`app.state.closing` never sets, and teardown is ten silent seconds and then SIGKILL. The
careful comment in `cli.py` explaining why that hook exists describes something that has
never happened in production — and the co-editing room's shutdown flush, which commits
pending room text, has never run there either. That is a live way to lose somebody's
writing, independent of this design, and every flush-on-shutdown here depends on fixing
it.

**`_merge_body`'s equal-replacement hole.** The guard requires `replacement != other_replacement` before the one-span assembly, so two differently-shaped edits with
identical replacement text merge silently wrong. Every design here leans on `_merge`, and
the replay leans on it without a person watching. It is a hard gate, not an open
question.

## Four pieces, in this order

This is more than one implementation plan and should not be attempted as one:

1. `deploy/boot.py`'s signal handling — small, and a bug on its own merits.
2. `_merge_body`'s equal-replacement hole — small, and a gate on everything below.
3. The pusher: `sync()`, the recovery, the parked branches and the PR. The large piece.
4. The per-row mark, the escalating banner, the landed protocol and the health rescope.

Each earns its own plan. Only the third is big.

## Testing

The claims are about threads, a real remote and a real browser, so the tests are asked in
those media, which is what this repository already does.

- Rejection and recovery against a **real second repository**, not a mock: a hand-push
  landing between the commit and the push, and the local backlog replayed onto it with
  authors, messages and order intact. `file://` and HTTPS answer a refused push in
  different words, which is why the store asks git rather than reading the message; the
  tests keep doing the same.
- The interleavings the adversary found, each as a named test: a straggler conflicting
  during the swap; a conflict in the middle of a batch; the process dying between the
  fetch and the push, and between the push and the swap; a force-push met by the guard.
- **Concurrency asked of real threads.** Several writers saving at once while the pusher
  runs, asserting every answered sha ends up landed, re-minted-and-landed, or parked on a
  branch that exists — and never merely gone.
- The per-row mark driven in Chrome with trusted input, the way the table's other press
  claims are asked.
- Every fix mutation-tested: delete it, watch the test fail, put it back.

## What this does not solve

An instance killed **ungracefully** — OOM, hardware, anything that skips SIGTERM — still
loses whatever has not been pushed. The window is roughly a push, not five minutes, and
the escalating banner makes a stuck pusher visible rather than silent, but the exposure
is real and is the price of the change.

`--min-instances 1` would remove the "the instance died with commits on it" half at the
cost of a warm instance. It is a separate decision and is deliberately not bundled here.
