# Twenty people on openproj

What happens when ten to twenty colleagues use this tool at once — on the same record, on
different records, in the same shaping document — and what it costs them in speed and in risk to
the plan repository.

Six bounded load scenarios and about two dozen standalone probes, all under `tests/load/`, all
committed, all reproducible. **Nothing under `src/openproj/` was changed to take any of these
numbers.** The only instrument inside the process is `tests/load/server.py:shim`, which charges
`pygit2.Remote.push`/`.fetch` a `sleep` so a `file://` remote on the same SSD can stand in for
GitHub over HTTPS.

Three things to know before reading a number here:

* **Every measurement is from one laptop core.** An Apple M4-class core, and the server used
  0.91–1.03 of one core in every phase that saturated it — one uvicorn process, sync routes on
  anyio worker threads, one GIL. So these already *are* single-core numbers. The only correction
  from here to Cloud Run is how fast one core is, and that correction is the softest number in the
  document: **2–3×, estimated, never measured**. It is applied below to CPU work and deliberately
  not to network waits, which do not get slower on a throttled vCPU.
* **No push in this audit went to real GitHub.** `--rtt-ms` charges a constant sleep. That models
  latency and not TLS, packfile negotiation, token refresh, variance, or a rate limit. 600 ms is
  `store.py`'s own price for a GitHub round trip.
* **The audited tree is one rename behind `main`.** This branch was cut at `5a09f6d`; `main` has
  since landed Entity→Record. The honest check that `src/` is untouched is
  `git diff $(git merge-base main HEAD)..HEAD -- src/`, which is empty. The delta from `main` is
  cosmetic (`entity_id`→`record_id`, docstring wording) and invalidates nothing here, but line
  numbers cited below are this tree's.

---

## 0. Re-measured after the template cache landed (2026-08-23, later the same day)

Everything below was taken on a tree cut at `5a09f6d`. `main` has since landed a one-line fix in
`render.py`: `Environment.from_string` was compiling the same fourteen Jinja templates on every
call, because Jinja's own cache hangs off a loader and there is no loader here — the templates are
module constants. So the read numbers below were inflated, and the honest thing is to say by how
much rather than to caveat them.

`readload.py --readers 20 --seconds 25` re-run on the fixed tree, same corpus, same machine,
p50 in the warm-1 phase:

| route | as measured below | after the fix | |
|---|---:|---:|---:|
| `GET /` | 1142.7 ms | 350.9 ms | **3.3x** |
| `GET /table` | 1196.1 ms | 386.6 ms | 3.1x |
| `GET /graph` | 1204.9 ms | 387.7 ms | 3.1x |
| `GET /issues` | 1112.4 ms | 334.6 ms | 3.3x |
| `GET /timeline` | 1034.5 ms | 341.9 ms | 3.0x |
| `PATCH` | 978.6 ms | 226.0 ms | 4.3x |
| **`GET /detail/<id>`** | **4112.0 ms** | **3885.6 ms** | **1.06x** |

**Every route got about three times faster except the one this document is about.** That is the
result, and it makes section 6's first item more urgent rather than less: `/detail` did not move
because its cost is not template compilation, it is `_detail_rows` building a full `markdown_it`
render for every record in the plan and then keeping one. After the fix `/detail` is roughly EIGHT
times slower than every other page, where before it was three.

The server still ran at 0.94-1.05 cores throughout, so the ceiling is still one core and still CPU.
What changed is how much of that core is spent on work somebody asked for.

Two numbers below are therefore stale in the reader's favour and are left as they were taken:
the per-route latencies in section 3, and the 63% share of CPU attributed to discarded `/detail`
work — that share is now HIGHER, because everything it was competing with got three times cheaper.

The write-path findings, the three data-loss mechanisms and every integrity result are unaffected:
they are about the store, the merge and the socket, and none of them renders a page.

---

## 1. The answer in five lines

**The plan repository is safe, and that is measured rather than assumed.** About 1,800 accepted
writes across six scenarios produced no conflict marker in any commit walked, no fork, no file
that stopped parsing, and `local == origin` with zero unpushed commits at the end of every run.

**People's writing has three exposures**, each found by a probe built to find it. Two lose text
outright: a save answered `200` for a commit that never left the instance, and a three-way merge
that silently drops one of two edits beginning on the same line — reverting a colleague's committed
line while answering `merged`. The third, a co-editing room refused once and then refused for ever,
announces itself to everybody every time and still ends in loss unless somebody copies the text out.

**Twenty people's time hurts in bursts, not at human speed.** Twenty people clicking every 30 s is
0.67 requests/s and the instance is mostly idle. The failure is fifteen people opening one link at
once — 7–10 s a page on a throttled core, and 21–31 s on an instance idle since lunch. Twenty
readers alone saturate the one core the deployment has, and the write ceiling for the whole service
is one GitHub round trip: `1000 / (20 + rtt_ms)` saves per second, 1.4/s at 600 ms.

**It breaks first on CPU, on the read path, not on locks.** `GET /detail/<id>` costs 236 ms warm
on a 561-record plan and grows 0.32 ms per record in the plan, because `render_detail` renders the
markdown body of *every* record and then keeps one; under load that is ~63% of everything the
server does, thrown away.

**The single most important change is to move the `only` filter above `_detail_rows`**
(`render.py:19651-19653`) — one line, no concurrency semantics touched, and it is the difference
between "twenty people is slow" and "twenty people is unusable on a plan twice this size".

---

## 2. What works

An audit that finds only faults is not credible, and this one found a system whose hard parts hold
up under measurement. Each claim below is a thing that was *tried* to break and did not.

**A serialised writer with the push inside the lock keeps the instance strictly ahead of the
remote, never beside it.** Sampling local HEAD against origin HEAD every 200 ms through 20 writers
at 600 ms push latency: `max_commits_ahead` is **1**, everywhere, in every run. The instance is
either level with the remote or exactly one commit ahead of it. That is the direct payoff of
committing and pushing under the same mutex, and it is why no run in this audit ever forked the
repository by itself.

**Per-path compare-and-swap means twenty people on twenty records never contend.** Twenty writers,
twenty records, 60 s, three push latencies: **318 of 383 saves (83%) came back `retried`** —
somebody else committed, but not to your file, so retry silently — and **zero 409s** across all
five runs. Nobody was told about a collision that was not theirs.

**Per-key frontmatter merge is right for the shape people actually produce.** Twelve people each
moving a different key on one record: **119 of 138 merged, zero refusals**. File-level locking
would have refused all 119. "They set the status while I set the priority" is not a disagreement,
and the store measurably does not treat it as one — including when the other party is a live
co-editing room, where a field-only `PATCH` landed twice on a record three people were typing into
and the room's next commit came back `merged` with the body untouched.

**Per-hunk body merge is right for the shape a shaping document produces.** Twelve people each
inserting a line under a *different* heading of one document: **116 merges, zero conflicts, all
139 inserted lines present, and every one under the heading its author aimed at.** Not one landed
in a neighbour's paragraph.

**A refusal writes nothing and never emits a marker.** Across every run of this audit — 97 commits
walked in the adversarial run, 54 in its tail, 13 in the read run, and every commit of every other
— **no blob anywhere in any history carries `<<<<<<<`**. A 409 leaves no partial file, no
half-merged frontmatter, and names the field and both values. Modify-versus-delete is refused in
*both* directions, and `DELETE` additionally compare-and-swaps on the shape of the cascade, so a
task filed under a pitch while the confirm panel was open blocks the delete instead of being
removed unnamed.

**`_absorb_remote` handles a colleague with a terminal, and handles it fast.** Four real `git
push`es from a real clone into the record set a run was actively writing: **all four reconciled on
the first attempt**, visible in the instance's own ref after 0.11–3.33 s and on the page after
1.04–4.40 s, all four markers in the final tree, nobody's concurrent write lost, and **no
divergence at any of 600 samples**. The rewind-fetch-retry path re-runs the three-way merge against
what actually landed, exactly as written.

**The CRDT loses nothing and the wire is cheap.** Fifteen people typing into one room for 90 s:
**8,103 of 8,103 code points in the committed file**, all fifteen anchors present, every document
converged to one identical string. 64.7 client updates/s in, 908.6 frames/s out — N−1
amplification exactly — for 0.058–0.102 core-seconds per wall second and 90 MB RSS. Keystroke to
another person's screen: **p50 2.5 ms, p99 8.7 ms**, zero arrivals missing out of 3,990.

**`byte_offset` holds under concurrency, including astral text.** One typist wrote 👍 🤖 🇮🇹 (two
regional indicators) 👨‍👩‍👧 (five code points, two ZWJs), `e`+U+0301, `n`+U+0303 and an em dash while
fourteen others typed around them. The committed blob decodes as strict UTF-8 with **0 U+FFFD, 0
lone surrogates, and ZWJ count exactly 2× the family count (78/78)**. In the adversarial run two
people spliced 506 and 513 characters either side of one 👍 for two minutes while a terminal push
forced the room to absorb across that character: exactly one 👍 in the file, both runs intact, both
anchors exact.

**Reconnection is a non-event, and `LINGER_SECONDS = 420 > 300` is load-bearing.** Three walls of
20 simultaneous socket closures — half polite, half `SO_LINGER 0` resets — produced **60 welcomes
and 0 "reload"**, nobody holding fewer characters afterwards, and **556 keystrokes typed while a
socket was down (3.9% of all typing) all reached git**. Presence bookkeeping let go of 15 of 15
abrupt drops within 10 ms, and an end-of-run census found five rooms with no ghost seats.

**A stale-body save from a dropped tab cannot remove committed text.** This is structural, not
lucky: the wholesale-write path requires `was == stored`, the tab's base is the room's last landed
commit, so the body it holds is necessarily a *superset* of the file's. It can only add. When the
file has moved, `_merge` runs instead and refuses — measured: a socket RST'd 30 s earlier, its two
colleagues 280 characters ahead, saving with a fresh base and a stale body, answered **409 in
45.7 ms** with the file and the lines named.

**Attribution survives everything.** Across every run: **zero commits authored by `unsigned`**. Every
cookie verified; twenty simulated people are twenty people in the log, and eight reconnections in
one session did not turn anybody into somebody else.

**Reads never take the store lock, and `PATCH` never blocks the event loop.** Seven
`asyncio.to_thread` sites cover every HTTP write route; `_commit_room` is the sole writer that is
not one of them, and it says why. The consequence is visible in the numbers: as push latency rises
from 0 to 600 ms, `GET /api/health` gets *faster* (739 ms → 18 ms p50 at 20 writers), because
writers blocked in a push release the GIL.

**Under saturation the failure mode is queueing, not shedding.** 1,191 page requests, 12 PATCHes
and 13 health checks in the read run: every one answered 200 except a single dropped read on
`/api/health` (1 of 13). 820 requests in the adversarial run: every one a 200 or a 409, zero
timeouts. That is the correct thing for a Python web app to do under 20× overload and it is not
what most of them do.

---

## 3. Speed

### What one action costs, warm, with nobody else on the machine

561-record corpus, one laptop core, index memo hot.

| action | cost | note |
|---|---|---|
| `GET /api/health` | **0.7 ms** | one `store.head()`; the only genuinely cheap route |
| `GET /api/index.json` | 5.7 ms | |
| `GET /issues` | 16.0 ms | the filtered view is the cheapest page in the app |
| `GET /` | 27–31 ms | |
| `GET /graph` | 29.7 ms | **2.69 MB of HTML** |
| `GET /timeline` | 41.8 ms | |
| `GET /table` | 40.9 ms | |
| **`GET /detail/<id>`** | **236 ms** | 1.23 MB; **55 ms fixed + 0.32 ms × records in the plan** |
| `PATCH /api/entity/<id>`, free push | 14.9 ms | 7 `head()`, 5 whole-tree walks, ~6 blob reads |
| `PATCH /api/entity/<id>`, 600 ms push | 636.5 ms | the difference is one round trip, inside the mutex |
| one keystroke → another person's screen | 2.5 ms p50 | loopback; add the network |
| first index build in a fresh process | **581 ms** | |
| every index build after that | **29 ms** | including after a commit — see below |

Two of those rows correct claims made earlier in this audit and are worth stating flatly, because
both are the kind of number that gets quoted forward:

* **The 600 ms index build is a cost per *process*, not per commit.** `web._read_records`'s
  `_PARSED` cache is keyed on `(blob id, path)` and deliberately not on commit, so a rebuild after
  a write re-parses one file and reuses 560. Measured in one process: 581 ms, then 29.5, 29.4,
  29.2, and 30.7 / 38.7 / 30.6 after writes. Every "≈600 ms" in the scenario reports is the first
  build in a fresh server, which is the only build you see if you start a server and send one
  request. **A write costs the readers ~30 ms of index, not ~600.**
* **`/detail`'s 236 ms is not the inlined Ace bundle.** `?editor=plain` (612 KB, half the page) is
  238.1 ms and a read-only render with no editor at all (441 KB) is 238.8 ms. Removing Ace saves
  *zero* CPU. `/graph` is 2.69 MB in 29.7 ms; bytes are nearly free here. The 236 ms is
  `markdown_it`, 561 times, for one row that survives the next line.

### What it costs with people on it

The sweep is not uniform — different scenarios put people in different places, deliberately — so
this table says what was actually run rather than pretending to a clean 1/5/10/20 ladder.

| load | `GET /detail` p50 | `GET /` p50 | `PATCH` p50 | `/api/health` p50 | throughput |
|---|---|---|---|---|---|
| 1 client, warm | 251 ms | 31 ms | 15 ms | 0.7 ms | — |
| 2 readers | — | 103 ms | — | — | — |
| 12 writers, 1 record, rtt 0 | 1935–2113 ms | — | 284–304 ms | 199 ms | 2.69 saves/s |
| 12 writers, 1 record, rtt 600 | ~400 ms | — | **6200 ms** | — | 1.31 saves/s |
| 15 co-editors, 1 room | — | — | — | — | 2.5 ms propagation p50 |
| 20 writers, 20 records, rtt 0 | 1635 ms | — | 696 ms | 739 ms | 2.14 saves/s |
| 20 writers, 20 records, rtt 600 | 496 ms | — | **7247 ms** (p99 12819) | 18 ms | 1.29 saves/s |
| 20 readers, warm | 3453 ms | 1262 ms | — | — | 6.89 pages/s |
| 19 readers + 1 writer / 5 s | 4087 ms | 821 ms | 979 ms | 1232 ms | 6.38 pages/s |
| 20 mixed (8 read, 6 write, 6 type) | 2076 ms | 387 ms | 81 ms | 11 ms (p99 2068) | 5.93 pages/s, 0.91 cores |

**5 and 10 users were not swept, and interpolating them is arithmetic rather than guesswork.** Two
independent runs confirmed the service behaves as an ordinary single-server queue: Little's law
agreed with the measured in-flight depth to 1.3% in one (L 7.61 vs 7.71 predicted) and to two
decimals in the other. So N people at cadence T is predictable from the service time, and the
service time is what the two ceilings below set.

### The two ceilings, and what sets them

**Writes: one push round trip, for the whole service.** `Store._writing` is a `threading.Lock`,
and `Remote.push` happens inside it. Measured with one `Store`, eight threads, eight files, no
HTTP and no rendering — the mutex alone:

| push rtt | 0 | 25 ms | 50 ms | 150 ms | 300 ms | 600 ms |
|---|---|---|---|---|---|---|
| saves/s | 49.6 | 13.8 | 9.3 | 4.34 | 2.55 | **1.44** |

Above ~150 ms this is a straight line: **`ceiling(rtt) ≈ 1000 / (20 + rtt_ms)` saves per second
for the entire service.** The 20 ms is the local git work and will be larger on a slower core, so
the formula's floor moves; the round trip does not.

**Reads: one core, and one route on it.** Twenty readers used 1.03 / 0.98 / 0.98 cores across three
phases. This is the audit's most valuable measured fact, because it means the laptop's other nine
cores bought the server nothing and every number here is already a single-core number. Of the
113.4 CPU-seconds the adversarial run spent, **~92.6 s were 369 `/detail` renders**, and ~77% of
each of those was `_detail_rows` over records the page discards. **About 63% of the server's whole
CPU under mixed load is work thrown away**, and it grows 0.32 ms per record added to the plan.

`gcloud_deploy.sh` says, in the paragraph arguing `--concurrency 200`, that "the scarce thing is
the slot, not the CPU". The reasoning for the flag is right and should not change. That sentence is
wrong: at twenty people the scarce thing is measurably the CPU, and the connection budget was never
approached.

### On one throttled vCPU

Applying 2–3× to CPU work only, and leaving network waits alone:

| | measured, 1 laptop core | estimated, 1 Cloud Run vCPU |
|---|---|---|
| `GET /detail`, warm, uncontended | 236 ms | 0.5–0.7 s |
| first index build (cold start) | 581 ms | 1.2–1.8 s |
| read throughput ceiling | 6.9 pages/s | 2.3–3.5 pages/s |
| `GET /detail` p50 at 20 concurrent readers | 3.5 s | 7–10 s |
| cold-cache herd, 20 simultaneous first requests | 10.4 s | 21–31 s |
| save at 600 ms push, uncontended | 0.64 s | 0.7–0.75 s (mostly network) |
| write ceiling at 600 ms push | 1.44 saves/s | ~1.4 saves/s (unchanged) |

**The honest reading of that table is not "too slow". It is "fine at human speed, bad in bursts".**
Twenty people each loading a page every 30 s is 0.67 requests/s, which this instance serves in
~200 ms with most of a core idle. Twenty people each saving every minute is 0.33 saves/s against a
1.4/s ceiling — 23% utilisation, and a Save that feels like one round trip because it is one. The
saturated rows above come from cadences 10–20× real use, and they were run to find the ceiling, not
to forecast a Tuesday.

What is *not* rare is the burst: a link goes into the team channel and fifteen people click within
a second. On a warm instance that is 15 × 236 ms of strictly serialised CPU, 3.5 s on this laptop
and 7–10 s throttled. On a **cold** instance — and `--min-instances 0` means idle since lunch is
cold — it is the herd: twenty first requests all completing within 5 ms of each other **at
10.35 s**, because `index_now()` takes no lock and twenty threads each parse the same 561 records
into the same empty cache. That is 21–31 s throttled, and it is the single worst first impression
this system can make.

The co-editing room adds a third to a half of the throttled core underneath all of that — 15
people with carets cost 0.102 core-s per wall second here, and the fan-out scales as N² in frames
and N³ in bytes, because every `at` frame is answered with the whole roster (787 bytes against
47 for an update). The room is the cheap tenant of an expensive building.

One stall is worth naming separately because it is not CPU. `_commit_room` is the only writer not
handed to `asyncio.to_thread`, deliberately, so a room's commit — push included — runs on the event
loop. Measured directly: at 600 ms push, one person's Save silenced **all fifteen sockets in the
room for 665–699 ms**, with 42–45 of other people's keystrokes on the wire during the silence;
propagation p99 went 5.9 ms → 158.8 ms. At eight rooms saving every 3 s, `GET /api/health` — a
route that costs 0.7 ms — reached **p95 5738 ms, max 15300 ms**. Its partial mitigation is another
defect: a busy room never goes quiet, so it never commits, so it never freezes the loop either.

---

## 4. Data loss risk

The definition used throughout: **a write was accepted, reported as success, and is not there
afterwards.** By that definition, and this is the most valuable sentence in the document:

**Across roughly 1,800 accepted writes in six load scenarios, nothing that was accepted went
missing.** Every marker present, `form_writes.lost 0` in every verification block, `local ==
origin` with 0 unpushed commits at the end of every run, `git fsck` clean on plan and origin, 561
records still parsing with the same 41 blockers the generated corpus arrived with.

Three mechanisms can nevertheless lose text. All three were found by probes built to find them, and
they differ in kind: the first needs the environment to fail, the second needs nothing at all to go
wrong, and the third announces itself and then loses the text anyway.

### Loss 1 — a save answered `200` for a commit that reached nowhere durable

The application is behaving correctly and the environment is what failed. `Store._finish` sets
`WriteResult.pushed` correctly, and it is right to commit anyway — refusing would mean the tracker
stops working whenever GitHub does. But `pushed` reaches **exactly one caller in the whole
application**: the co-editing socket's `saved` frame. `web.py:1801`'s `_result` builds `{outcome, commit, conflict,
head}` and drops it, so every HTTP write route is blind to it, and every `pushed` field in every
run's JSON reads `unknown` for `PATCH`.

Measured: with the remote made unwritable for 8 s, **10 saves were answered 200 with a commit sha
and all 10 markers are on the instance and on no origin**. On Cloud Run the filesystem is in
memory and `--min-instances 0` tears the instance down after a few minutes of quiet, so those
commits are what somebody finds missing on Monday, having watched the page say "saved" ten times.

Scope, stated honestly: the unwritable remote was manufactured. A GitHub outage, an expired
installation token or a secondary rate limit produces the same shape, and `store.py`'s own comment
predicts it — but this has never been observed against real GitHub. **CONFIRMED as measured,
PLAUSIBLE in production.**

The exposure window when nothing is wrong is one push. Sampling every 200 ms, local was ahead of
origin for 3.7% / 40.2% / 81.0% of samples at 0 / 150 / 600 ms push — but that is a *duty cycle*
under twenty writers saturating the lock, not a statement about a working day, and
`max_commits_ahead` was **1** everywhere. The durable statement is: every save has a ~600 ms window
in which the commit exists only on the instance, so at N saves/second the expected number of
at-risk commits is 0.6·N and it is never more than one at a time.

### Loss 2 — `_merge_body` drops one of two edits beginning on the same line, and answers `merged`

`_merge_body` calls two edits a conflict only where they overlap by a half-open test
(`store.py:145`) or where their spans are *equal*. An insertion has an **empty** span, so an
insertion at line N and a replacement starting at line N satisfy neither arm and are merged
silently. The assembly loop below it (`store.py:157-165`) then walks the union of both sides'
spans with one cursor and `continue`s past any span starting behind it — so of two spans beginning
on the same line, **the second one the set happens to yield is dropped entirely**. Which one that
is depends on the hash order of two integer tuples, i.e. on the line number.

Re-verified today, end to end through `Store.write`, on this machine:

```
offset  0  MERGED, and Bob's committed line is gone
offset  1  merged, both kept
offset  2  MERGED, and Bob's committed line is gone
…
bob   -> committed 5a44f3f
ann   -> merged c45196b conflict=None
LOST — bob's commit 5a44f3f is in the history and his line is not in the file.
```

`store.py:859` passes `stored` — what is already in git — as `theirs`, so when the dropped side is
theirs, **a colleague's commit is reverted by a save that answered 200 with no conflict to read**.
Fuzzed over 50,000 random three-way pairs on 4–12 line documents: 43,237 merged with no conflict,
and **1,192 of those (2.8%) dropped a line the stored commit had**; 1,028 (2.4%) dropped a line the
incoming save had.

**It did not fire once in the six load scenarios, and the reason matters.** The scenario that
aimed at it — twelve people inserting into one shaping document — had every writer *inserting*, and
two insertions at different line indices merge cleanly while two at the same index are already a
conflict. The drop needs one **insertion** and one **replacement** starting on the same line: a
person adding a bullet where another person rewrote the line. That is not exotic — it is
"somebody appended to the checklist while somebody else fixed the wording of the item above it" —
but it did not occur in a harness that only appends.

### Loss 3 — a room refused once is refused for ever, and the refusal has no exit

Not loss under the strict definition, and the distinction is worth keeping: every refusal is
broadcast as a `refused` frame to *every* socket in the room, and `render.py` un-hides a box with
the full conflict report and calls `announce('not saved')`. The text stays in every editor. This is
a compare-and-swap working and saying so.

What is defective is that there is no way forward. `_commit_room` returns before `room.settled` on
a conflict, so **`room.base` never moves after a refusal**; every subsequent quiet window, every
Save and the last-person-out commit re-run the identical three-way merge against the identical base
with a `mine` that only grows. And the join path's absorb is gated on `not room.pending()` — false
for exactly the room that is stuck — so a page reload does not clear it either; the rejoining
socket is welcomed with the stale base.

Measured, and then measured again more carefully. First observation: a colleague's `git push`
appending a line to a record three people were co-editing, after which **373 characters typed by
three people, acknowledged in three browsers, never reached the plan** (248→135, 261→131, 260→130).
The control room in the same run, which nobody pushed onto, lost nothing (586 typed, 586 in the
plan).

Then a four-cell probe built to find the real trigger, using an ordinary `PATCH` as the outside
write — no remote, no fetch, no `_absorb_remote`:

| room types at | outsider saves at | room's sentences reaching git | room's base after |
|---|---|---|---|
| **end** | **end** | **0 of 15** | still the room's *first* save |
| end | middle | 15 of 15 | advanced |
| middle | end | 15 of 15 | advanced |
| middle | middle | 15 of 15 | advanced |

Three things that changes. **The trigger is not "a colleague with a terminal"** — it is any write to
that file that lands while a room holds text and touches the same line index, which includes a
second tab's Save, an inline edit on `/table`, and the drag-to-refile. **Pressing Enter does not
help**: the typists inserted a fresh line every round and were still refused, because
`touching = span == other_span` makes two insertions at the same index a conflict regardless of
content, and two people appending at the end of a file always produce the same index. And **the
terminus is loss**: the room lingers 420 s after emptying and is then swept, `--timeout 300` empties
it every five minutes, and the only backstop is `localStorage`, which by construction holds the
typist's own text and nobody else's — everybody else's arrived over the socket and was never an
`input` event. So one instance lost mid-session does not cost one draft; it costs the merged
document, and four people each hold a different quarter of it.

Call it **an announced, unrecoverable refusal that ends in loss unless a person acts on a message
that does not tell them what to do.** The message names the file, the lines and both texts. It does
not say "copy this out of the editor before you close the tab", which is the one action that works.

### Two more room-level exposures, measured in the reading phase and not since

* **A busy room never commits.** `Room.apply` restarts `_quiet_since` on *every* update from
  *anybody*, and `_watch` commits at `quiet_for() >= 20`. Four people typing put an update into the
  room every ~50 ms; fifteen, every ~15 ms. Measured: **zero commits in 90 s of continuous typing**,
  the first commit landing 19.9 s after the last keystroke, with **8,243 characters standing in one
  process's heap**; and in the churn run, git received nothing at all for 55 s while **7,127
  characters stood in five rooms**. The magnitude is an artefact — simulated people type
  continuously and real drafting has gaps — but the mechanism is exact, and it is *worse* in
  production than in the harness: the harness closed all sockets at once, which empties a room and
  flushes it, while Cloud Run's per-connection 300 s deadline is staggered, so a four-person room
  may never be empty and may never commit at all. `--timeout 300` is currently an accidental
  checkpoint that nobody designed.
* **A room past `MAX_BODY_BYTES` can never commit again.** The snapshot raises `ValueError('this
  document is too large to commit')`; `WRITE_FAILURES` turns it into a refusal that writes nothing
  and moves no base; nothing trims a room and no frame stops anybody typing, because the transport
  ceiling is deliberately 4× the policy ceiling. Measured: **277,800 bytes in the room against
  1,051 in git**, every Save and every quiet window answering the same refusal, and the
  last-person-out commit not rescuing it either. It takes a 262 kB document to reach, which a
  shaping document will not do by typing — but a paste will.

### Refused, and the user was told — all of these are fine

Kept separate on purpose, because these are the cases most likely to be mistaken for loss:

* **105 of 142 same-field saves refused (73.9%)** when twelve people move the same `person_weeks`
  in a minute. Lossless, correct, and the final value was one somebody sent — verified off the
  commit graph, not off wall-clock order. It is a stress figure, not a forecast.
* **396 of 556 saves refused (71%)** when writers keep the base their page was drawn at — a tab left
  open. Nothing lost, no marker, the edit simply not written. The refusal rate is a property of the
  harness's aggression, not a forecast.
* **`_lost_the_race`**: three external pushes inside one save, nothing committed, a 409 and the
  sentence *"the plan moved three times while this was being saved. Nothing was written. Reload and
  try again."* Honest, distinguishable from both success and a merge conflict, and it costs ~7 s of
  lock time to reach at 600 ms.
* **Delete-versus-edit**, in both directions, including the cascade shape.

### One case that is neither

**`StoreDiverged` as an unhandled 500, for the life of the container.** Once a commit exists locally
that never reached the remote (Loss 1) and a human then pushes, neither history contains the other.
`_absorb_remote` refusing to guess which commits to discard is *correct*. What is missing is
anything that says so: `WRITE_FAILURES` names `StoreDiverged`, but it is caught in exactly one place
— `_commit_room` — and there is no exception handler on any HTTP write route and no exception
middleware. Measured: **16 of 16 subsequent saves answered 500** with a bare traceback, including
saves to unrelated files. And **`GET /` answered 200 throughout** — 5 of 5 — because every page is
drawn from the local ref. A service that cannot write a single character looks completely healthy,
`/api/health` included.

It does not need a redeploy to recover: `deploy/boot.py` re-clones at container start and
`--min-instances 0` replaces the instance on its own. So it **self-heals by discarding the unpushed
commits**, which is a worse sentence than "it needs a restart".

---

## 5. Plan-repo conflicts

**Can the repository end in a state a human has to repair by hand? On this evidence, no.**

No conflict marker reached any blob in any run. The app never forked the remote by itself: the
push is inside the write lock, so the instance is level with origin or exactly one commit ahead of
it, never beside it. Branch protection on `icon4py-plan` refuses force-push and deletion, including
for admins, so the worst the service can do is add commits.

**A human pushing from a terminal works, and this was measured rather than argued about.** Four real
pushes from a real clone during a live run: the push is rejected as non-fast-forward, `_absorb_remote`
fetches and fast-forwards, the retry re-runs the three-way merge against what actually landed, and
the write lands. All four reconciled on the first attempt; all four markers in the final tree;
nobody's concurrent write lost; no divergence at any of 600 samples. **This is the path the design
was built for and it does its job.**

Three caveats, in order of how likely they are to bite:

**The instance is blind to the remote between writes.** Nothing polls. `store.head()` reads the
local ref, and `fetch` happens only inside `_absorb_remote` on the retry path and in `_send`'s
failure branch. In a busy run the remote was ahead for 3.7% of samples and never for more than
3.1 s — but that is an artefact of five people saving constantly. **On a quiet afternoon, a
colleague's `git push` is invisible on every page until the next person saves something**, which
could be hours. The cold start does re-read from disk, but the disk is a clone made when the
instance started.

**A terminal push onto a line a room is holding locks that room out** (Loss 3). The repository stays
clean; the *room* is the casualty. Worth naming here because "somebody added a checklist item at the
bottom" is exactly what a terminal push looks like, and the bottom of the file is where both a
terminal push and a room's typing tend to land.

**`pushed: false` on an ephemeral filesystem is a commit that exists nowhere else.** Section 4,
Loss 1. The repository is not damaged by it — it simply never hears about the commit. The damage is
to the person who was told "saved".

**And the one state that does need a human is not on the repository.** `StoreDiverged` is a
condition of the *container's clone*: it holds commits the remote does not, and the remote holds
commits it does not. The remote is fine. The repair is "lose the unpushed commits", and Cloud Run
performs it by replacing the instance — silently, which is the problem.

**Two instances is the one integrity risk this audit could not close.** `deploy/RUNBOOK.md` says
`--max-instances 1` *can* be briefly exceeded and that "the flock is the real guard". It is not:
`deploy/boot.py` clones the plan into each container's own in-memory filesystem, so each instance
takes its own flock on its own file and neither can see the other. A two-server probe
(`tests/load/probe_twoinstances.py`, run once in the reading phase against one `file://` origin,
never in any of the six scenarios and never against a real remote) measured exactly that: **two lock
files, both granted**; each editor's roster showing only themselves, because rooms and presence are
a dict in one process; the loser of the push race refused. Git integrity survived in that probe —
the non-fast-forward is caught, rewound and re-merged — and the CRDT doubling the module docstring
warns about did not occur, because both instances produced the same seed sha. But two independent
writers against one remote is also the fastest route to Loss 1 followed by `StoreDiverged`, and
nobody has looked at `container/instance_count` to see whether it has already happened.

---

## 6. What to change, ranked

Ranked by risk removed over effort, which puts two one-line changes at the top and the hardest
problem in the audit at 8. Items 1 to 5 are each a line or an afternoon and can ride inside other
work; 6, 7 and 8 are design decisions with their own risks, and 6 must come before 7.

### 1. Filter before you render, in `render_detail`

**Problem.** `render.py:19651-19653` builds a row — including `_body_html`, i.e. a full
`markdown_it` render — for **every record in the plan**, and then keeps the one the route asked
for.

**Evidence.** In-process, best of 3, 561 records: `/detail` 236.0 ms, of which `_detail_rows` alone
is 182.9 ms; the same page on a 41-record plan is 68.0 ms. The fit is 55 ms fixed + **0.32 ms per
record in the plan**. In the adversarial run, 369 `/detail` renders were 92.6 of the server's 113.4
CPU-seconds, so ~63% of the whole machine was work discarded. At 1,500 records the page becomes
~540 ms before the 2–3× throttle factor.

**Change.** Build rows for `only` alone when `only is not None`; leave the `None` path building all
of them, because the static export renders every record into one page and that is deliberate.

**Cost.** One line, one test that the served page and the static export still agree.

**What it might break.** `_detail_rows` is a pure per-record comprehension over
`sorted(index.records.items())` with no cross-row state, so nothing depends on the discarded rows —
but preserve the current behaviour for an `only` that names a record not in the index (today it
yields an empty list; the route 404s first, so only a non-route caller can reach it). And the
sorting becomes irrelevant for one row, which is fine as long as nothing downstream assumes rows are
sorted.

### 2. Refuse where `_merge_body` currently drops

**Problem.** Section 4, Loss 2: an insertion at line N and a replacement starting at line N are
merged with one of them silently discarded, half the time the one already in git.

**Evidence.** The offset sweep above, re-verified today; the end-to-end case where Bob's commit is
in the history and his line is not in the file; 2.8% of 43,237 fuzzed merges dropping a stored line.

**Change.** Widen the conflict test from `touching = span == other_span` to spans that *start*
together: `span[0] == other_span[0]`. That is a strict superset of today's test and adds exactly the
dropping case. While in the function, fix the message: an empty span renders as `lines 3-2`.

**Cost.** One line, plus tests for the four span shapes.

**What it might break.** Saves that today merge correctly — the 50% of same-start pairs where the set
happens to yield the right order — become 409s. That is the trade, and it is the right direction: a
refusal is announced and a drop is not. It does not touch the shape that matters most: twelve people
inserting under twelve different headings produced 116 merges and zero conflicts, and all of those
are insertions at *different* indices, unaffected.

**Rejected alternative: fix the assembly loop to keep both spans.** That is what you actually want,
and it means deciding an order between two edits at the same point — which is what a CRDT is for and
what a line merge cannot do. Getting it silently wrong is worse than refusing, and this function is
the one everything else in the audit rests on.

### 3. Warm the index before uvicorn binds

**Problem.** `index_now()` reads the memo, misses, and builds, with no lock and no in-flight marker,
so N concurrent misses are N builds. `--min-instances 0` re-arms this on every idle period, every
deploy and every recycle.

**Evidence.** Twenty first requests to a fresh server all completed within 5 ms of each other **at
10.35 s** — 20 × ~0.6 s of parsing serialised by the GIL. The first `GET /` on a fresh server is
621 ms and the second is 32 ms. The affected minute delivered 355 pages against 431 for the same
load on a warm server: **16% of a minute's throughput consumed by the first ten seconds.**

**Change.** One line in `cli._serve`, next to `app.state.warm_edited()` — which is already there,
four lines above, with a comment saying that the first history walk runs before uvicorn binds so it
can never ride a request. The index deserves the same sentence.

**Cost.** ~0.6 s added to cold start, inside the window `--cpu-boost` pays for.

**What it might break.** Nothing at runtime. It moves the discovery of an unparseable plan from the
first request to startup, which is arguably better and is a behaviour change worth noticing.

**Rejected alternative: a single-flight guard inside `index_now`.** It would work, and it adds a
lock to a read path that is deliberately lock-free and whose comment explains why. The herd is a
cold-start artefact, not a steady-state one — after warming there is no herd left to collapse.

### 4. Put `pushed` on every write response, and say something when it is false

**Problem.** Section 4, Loss 1: the one loss the API has no field in which to describe. `pushed` is
set honestly and read by exactly one caller in the application.

**Evidence.** `web.py:1801` `_result` builds `{outcome, commit, conflict, head}`. Every `pushed`
field in every run's JSON reads `unknown` for `PATCH`; the co-editing socket's `saved` frame is the
only reader in the application. Ten saves answered 200 for commits that reached no origin.

**Change.** One key in `_result`, and something in the page when it is false — the co-editing socket
already renders "saved here, not yet pushed", so the wording exists.

**Cost.** One key, one banner. Additive on the API.

**What it might break.** Nothing. But be clear about what it buys: it does not stop the loss, it
makes it visible. Somebody who sees "saved here, not yet pushed" and copies their text out has lost
nothing; somebody who closes the tab still has.

### 5. Catch `StoreDiverged` on the write routes, and let health say the service cannot write

**Problem.** A permanent, silent write outage that every page reports as healthy.

**Evidence.** 16 of 16 saves → bare 500 with a traceback body, including to unrelated files, for the
life of the container, while `GET /` answered 200 (5 of 5) and `/api/health` kept saying `ok`.
`grep exception_handler web.py` returns nothing; `_commit_room` is the only catcher.

**Change.** An exception handler on the write routes answering with the sentence `_absorb_remote`
already wrote, plus a flag `/api/health` can report. Do **not** add a fetch to the health route —
report the local condition (last raise, and unpushed depth against the last successfully pushed sha),
not a network probe.

**Cost.** An afternoon.

**What it might break.** Nothing, and it does not fix the wedge — it names it. The RUNBOOK's verify
step and any uptime check currently pass through this state, which is why the health flag belongs in
the same change.

### 6. Give a refused room a way forward

**Problem.** Section 4, Loss 3. `room.base` never moves after a refusal, the join-time absorb is
gated on `not room.pending()`, and the room retries the same losing merge until it is swept.

**Evidence.** The four-cell probe: 0 of 15 sentences reaching git in the failing cell, five explicit
Saves refused with the identical report, the last-person-out commit refused too, and a fresh
socket's `welcome.base` still pointing at the room's *first* save. 373 characters in the earlier
60-second run, typed and acknowledged in three browsers.

**Change, interim and cheap:** one sentence in the refusal — *copy this out of the editor before you
close the tab* — and a log line, so a stuck room is discoverable at all. **Change, real:** when the
refusal's conflicting lines are ones no member is holding, re-seat the room on the current file
(absorb, then settle on the new head).

**Cost.** The sentence is an hour. The re-seat is a cycle.

**What it might break.** The re-seat touches the invariant `_commit_room` guards by construction —
no `await` between the snapshot and `room.settled`, or the absorb deletes what was typed during the
suspension. That is exactly the property the loosened `pending()` gate protects. Schedule it; do not
squeeze it in.

### 7. A ceiling on a room's unwritten text

**Problem.** `_quiet_since` resets on every update from anybody, so the room that most needs a
checkpoint is precisely the room that never gets one. The guaranteed flush is "everybody leaves",
and with staggered per-connection timeouts a four-person room may never be empty.

**Evidence.** Zero commits in 90 s of continuous typing, 8,243 characters held in memory; nothing in
git for 55 s of the churn run with 7,127 characters standing in five rooms. Magnitude inflated by
harness typists who never pause; mechanism exact.

**Change.** A second condition in `_watch`'s `if`: commit if pending and nothing has been committed
for N seconds, regardless of quiet.

**Cost.** One condition.

**What it might break.** Two interactions, both real. Each extra commit freezes the event loop for
one push (item 8), so this trades unwritten text against stutter — the same currency. And more
commits means more merges against outside writers, which means more chances to hit item 6's lockout.
**So do item 6 before item 7**, or the fix for the smaller problem widens the bigger one.

### 8. Get `_commit_room` off the event loop

**Problem.** The one writer not handed to `asyncio.to_thread`, so a room's push stalls every SSE
stream, every other room and every HTTP route in the process.

**Evidence.** One Save silenced all fifteen sockets in a room for 665–699 ms at a 600 ms push, with
an A/B against a free push showing no gap above 190 ms. Eight rooms saving every 3 s put
`/api/health` at p95 5738 ms and max 15300 ms, and 48 probes completed in 60 s against 713 with a
free push. At twenty rooms, 16 of 20 sockets stopped answering inside a 10 s client timeout.

**Change.** Real design work. The code says why it is where it is, and the reason is sound.

**Cost.** A cycle, and it changes an invariant whose test was written by construction rather than
observed.

**What it might break.** The thing the comment names: a keystroke arriving during the write being
deleted by the absorb after it. Any version of this needs that case as a test before it needs a
measurement.

### 9. Throttle the caret fan-out

**Problem.** `sit()` fires on every caret move — which while typing is every character — *and* again
on every incoming update, and the server answers each with a `who` frame carrying the whole roster
and every position, to N−1 members.

**Evidence.** With carets on, 15 typists produced 1698.6 frames/s and **685.4 kB/s** against 39.4
kB/s without them: 1.98× the frames and **17.4× the bytes**, for 1.52× the CPU. Latency did not
move, so this is bandwidth and CPU rather than responsiveness — but 787 bytes per `who` frame
against 47 per update, fanned to N−1, and the roster itself grows with N, makes it **O(N³) bytes**.

**Change.** Throttle `sit()` to ~10 Hz in the page.

**Cost.** A few lines in `render.py`.

**What it might break.** Somebody's caret marker lagging by up to 100 ms. Nobody will notice.

### 10. `put_asset`: check the dedupe before taking the lock, and drop the fetch inside it

**Problem.** `put_asset` takes the writer lock, then fetches, then checks whether the asset already
exists, then pushes — two round trips inside the mutex where an ordinary save has one, and a
duplicate paste of the same image costs the full fetch anyway.

**Evidence.** Code (`store.py:701-718`); ~1.2 s at 600 ms against ~0.6 s for an ordinary save. Not
exercised under load — `POST /api/asset` is one of six write routes no scenario touched.

**Change.** Read the dedupe outside the lock; take the lock for the commit and push only.

**Cost.** A few lines.

**What it might break.** The dedupe becomes advisory — two people pasting the same image
simultaneously could both commit it. That is a wasted blob, not a conflict, and the content hash
makes them the same path anyway. Note that this route's docstring records that it *once* caused a
permanent `StoreDiverged` by committing without the lock; whoever touches it should read that first.

### Operational, and mostly measurement

These are cheap, and two of them decide recommendations above.

* **Time 50 pushes to `github.com` from a container in `europe-west1`, and take p50/p95/p99.** The
  entire write ceiling is `1000 / (20 + that)`. Everything in section 3's write column is 600 ms
  substituted from a comment. If the p99 is 3 s rather than 1 s, the burst ceiling is a third of
  what is quoted.
* **Read `container/instance_count` over the last months.** It answers whether the two-instance
  hazard in section 5 is theoretical or has already happened, and it costs one console query.
* **Print `os.cpu_count()` in the container.** It sets `asyncio.to_thread`'s default executor width
  to `min(32, n+4)`, which is the second queue every HTTP write sits in. If it reports 1, that width
  is 5.
* **Run `readload.py` against the deployed revision**, or in a container pinned to `--cpus=1`. It
  replaces the 2–3× estimate — the softest number in this document, and a multiplier on everything
  in section 3 — with a measurement.
* **Consider raising `--timeout`**, up to Cloud Run's 60-minute ceiling, *after* item 7 and not
  before. It would cut reconnection from every five minutes to hourly, and the connection budget can
  afford it (200 slots, 2 per editor, 20 editors is 40). But `--timeout 300` is currently the only
  thing reliably flushing a busy room, so removing it without item 7 makes section 4's exposure
  larger, not smaller.
* **`--min-instances 1` — rejected for now.** It would remove the cold start, the herd and the
  "instance torn down holding an unpushed commit" window in one flag. The RUNBOOK already prices it:
  one instance for a month is 14× the free tier. Item 3 buys most of the same thing for nothing;
  revisit this only if cold starts remain a complaint after it.
* **Compression — rejected for now, and this is not the usual answer.** There is no `GZipMiddleware`
  anywhere and the pages are large (`/graph` 2.69 MB, `/detail` 1.23 MB). But the audit's central
  finding is that **CPU is the binding constraint and bytes are nearly free**: 2.69 MB rendered in
  29.7 ms. Gzipping would spend the one resource the instance has none of. Measure whether Google's
  frontend already compresses on the client's behalf before writing any code.
* **Item 1 changes the memory question too.** 320–330 MB RSS at 20 readers against `--memory 512Mi`
  looks alarming and is probably overstated — macOS `ps rss`, 16 KB pages, 24 GB of headroom, no
  cgroup, nothing asking the allocator to give anything back, and no run came near OOM. Measure it
  under the actual limit before believing it, and measure it *after* item 1, which removes 560
  discarded HTML bodies per request.

---

## 7. What was not tested

The edges of this document, so nobody quotes it past them.

* **Real GitHub.** Not one push in the whole audit went to a real remote. `--rtt-ms` charges a
  constant sleep against a `file://` origin on the same SSD: no TLS, no packfile negotiation, no
  installation-token refresh, no variance, no secondary rate limits, and a remote that never refuses
  and never disappears. `store.py` records that the *first* version of the push-rejection
  discrimination was wrong precisely because it was tested on `file://` and GitHub words the error
  differently. It asks git rather than parsing text now, so it should be fine — but "should be fine"
  is what an audit exists to replace. The `_Rejected` retry ladder is therefore essentially
  untested, and its "about 1.8 s" comment remains an estimate: with one instance and one serialised
  writer, nothing *inside* the service can move the remote, so zero of 481 saves in the contention
  runs ever reached it.
* **A genuinely throttled single core.** Every CPU figure is from an M4-class laptop core. The 2–3×
  factor is an estimate, applied identically in six reports because they all took it from the same
  place — their agreement is not corroboration.
* **Real browsers.** No Chrome, anywhere. Every "what a person experiences" number stops at the
  socket, so the parse of 594 KB of inlined Ace and the render of a 1.23 MB page are not in any of
  them — and item 1 removes server CPU without touching either. This also leaves the one open
  index-space defect unmeasured: `render.py:reflect()` scans a common prefix and suffix in UTF-16
  code units rather than through the `units()` boundary declared eighty lines above it, so its
  `head`/`tail` can stop between the halves of a surrogate pair. A `<textarea>` re-pairs and loses
  nothing; the Ace surface's intermediate document holds a lone surrogate. The server side is clean
  — two sockets splicing either side of 👍 and either side of an em dash converged with the bytes
  exact — and the browser half needs `tests/js/drive.js` with `aceSurface`, plus a repeat in Chrome,
  because `setRangeText` with a lone surrogate is a browser fact and not a claim about this code.
* **Signed-in multi-user flows.** Every run used `--auth dev` with simulated cookies. Nothing here
  exercised the real OAuth path, session expiry mid-edit, or the 60-second writer re-verification
  against a session that has gone away. The commits are attributed correctly (zero `unsigned`
  authors), which is the property that matters for the plan; the sign-in *experience* under load is
  untested.
* **Six of the seven write routes, under concurrency.** Every load probe issues exactly one verb:
  `PATCH /api/entity/{id}`, plus the co-editing socket's own `store.write`. Never touched
  concurrently: `POST /api/promote` (the only multi-path compare-and-swap, where a conflict on *any*
  path writes nothing), `DELETE /api/entity/{id}` (three refusal paths, each with an incident in its
  docstring), `POST /api/asset` (which holds the writer lock for an upload plus a push, and whose
  docstring records that it once caused a permanent `StoreDiverged`), `PUT /api/cycle/{n}`, `PUT
  /api/icon`, `POST /api/entity`. **That is where the next probe should go**, not on more readers.
* **Two instances, properly.** Run once in the reading phase on two servers against one `file://`
  origin; never in the six scenarios, never against a real remote, and never with a room on each
  side under load. `tests/load/probe_twoinstances.py` is the instrument and it is written.
* **`/api/events` under load.** An SSE stream per open tab, held for the life of the page. Twenty
  people is 20 streams + 20 sockets + page requests against `--concurrency 200`, and the deploy
  script's own reasoning says the budget is connections. Only the earlier `mixed` scenario opened
  them at all.
* **A broken file arriving under load.** `readable` / `Unreadable` is the invariant `AGENTS.md`
  spends the most words on, and a person committing a file that will not parse while twenty people
  read is exactly the situation it was written for. No probe did it.
* **A soak.** Every run was 25–120 s by instruction. So: no memory trend is claimed from three
  60-second phases, `rooms.sweep()`'s 420-second linger was never observed expiring under load, and
  the history walk's growth with commit count (~0.5 ms per commit) was never exercised over a real
  history.
* **The join path's stale-head window.** `coedit_socket` reads `head = store.head()` before `await
  socket.accept()` and uses it after, in `room.settled(head, room.body())`. With `wsproto` — what
  `pyproject.toml` depends on, and `websockets` is not installed — the accept performs no suspension
  at all, so the two lines are one uninterrupted stretch and the head cannot go stale. 2,000+ joins,
  including 66 fired microseconds ahead of a room save and 867 more with an artificial suspension
  charged to the accept, produced zero rewinds. **A latent defect with a named trigger**: the day
  `websockets` arrives as a transitive dependency, or somebody passes `--ws websockets`, the accept
  starts suspending and only join ordering stands between this code and a silent revert. Re-reading
  `store.head()` after the accept closes it for one line.

---

## 8. How to re-run it

The harness is committed under `tests/load/` and every run writes its raw numbers to
`design/probes/load/*.json`. Each driver builds a fresh plan in a temporary directory, starts one
server on a loopback port, drives it, and kills the server and deletes the plan from a `trap` or a
`finally` — a load harness that leaves a uvicorn holding a flock is worse than no measurement.

```bash
uv sync --frozen
SCRATCH=$(mktemp -d -t openproj-audit)   # the two probes that take a working directory

# the six scenarios
uv run python tests/load/readload.py --readers 20 --seconds 60 --size medium --think 0.5
uv run python tests/load/run.py --scenario spread --writers 20 --readers 0 --seconds 60 \
    --gap 3 --gap-max 8 --size medium --seed 7 --rtt-ms 600 --watch-remote
uv run python tests/load/write_same.py --variant all --writers 12 --seconds 50 --size medium
uv run python tests/load/coedit_same_room.py --users 15 --seconds 90 --size medium --seed 11
uv run python tests/load/churn.py --users 20 --rooms 5 --size medium --rtt-ms 300 \
    --phase-a 55 --phase-b 55 --phase-c 45 --phase-d 45
uv run python tests/load/adversarial.py --seconds 120

# the probes that settle a specific claim
uv run python tests/load/lockout.py                    # does a refused room ever recover
uv run python tests/load/detail_cost.py                # where /detail's 236 ms go
uv run python tests/load/index_warm.py                 # per process, not per commit
uv run python tests/load/lost_line.py    "$SCRATCH"    # a committed line, silently dropped
uv run python tests/load/writer_ceiling.py "$SCRATCH" 8  # the mutex alone, by push latency
uv run python tests/load/diverge.py --seconds 30       # unpushed, forked, and wedged
uv run python tests/load/probe_twoinstances.py         # two flocks that cannot see each other
```

`tests/load/verify.py` runs over the bare repository after every scenario and is what turns a
latency percentile into a measurement: it accounts for every accepted write, walks every commit for
conflict markers, compares local against origin, re-parses every record, and checks that no commit
was authored by `unsigned`. It was mutation-tested by its author before any of these numbers were
believed — revert a scalar, invent a value, move a line into the next paragraph, drop a hunk, drop a
key: five mutations, five fires, silence on an honest tip.

Ports: everything binds `127.0.0.1` in 8900–8999. **8000 is not used by anything here.**
