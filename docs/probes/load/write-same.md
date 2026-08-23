# `write-same` — twelve people, one record, three ways to disagree

The compare-and-swap under genuine overlap. Twelve form writers all aimed at
`task-000000`, saving through the page the way a person does — `GET
/detail/<id>`, `GET /api/health`, `PATCH /api/entity/<id>`, pause 0.8–2.5 s — and
varied in the only way that changes what the store has to decide:

| variant | what each writer touches | what `store.py` should do |
|---|---|---|
| `fields` | a **different** frontmatter key each (twelve keys, twelve people) | merge per key |
| `field` | the **same** key (`person_weeks`), a value only they send | refuse |
| `body` | a **different paragraph** of the shaping document each | merge per hunk |

Raw numbers: [`write-same.json`](write-same.json). Driver:
[`tests/load/write_same.py`](../../../tests/load/write_same.py). Nothing under
`src/openproj/` was changed to take them; the only shim is
`tests/load/server.py:shim`, which sleeps inside `pygit2.Remote.push`/`.fetch`
from outside the application.

## The bench

| | |
|---|---|
| machine | Apple M4, 10 cores, 24 GB, macOS 25.5.0 |
| also running | three other Claude Code sessions with their own `python -m http.server` and one `openproj demo` on 8792/8917/8765, nvim ×2, iTerm2; load average 1.22 before the runs |
| corpus | `tests/load/corpus.py` medium — 561 records, bodies the length of a real shaping document |
| server | one uvicorn, one worker, `--auth dev`, bare `file://` origin, 127.0.0.1:8900 |
| window | 50 s per variant, 40 s for the rtt-600 point. **200 s of load in total.** |
| seed | 7 — the same requests in the same order, run to run |

**Cloud Run runs this on 1 throttled vCPU** (`--cpu 1 --max-instances 1
--concurrency 200 --min-instances 0`). Every CPU-bound number below is a floor;
the extrapolation is at the end and is stated as an extrapolation.

## The store did exactly what it says it does

| | `fields` | `field` | `body` |
|---|---|---|---|
| PATCHes attempted | 138 | 142 | 139 |
| `committed` (base was still HEAD) | 19 (13.8%) | 37 (26.1%) | 23 (16.5%) |
| `merged` | **119 (86.2%)** | **0** | **116 (83.5%)** |
| `retried` | 0 | 0 | 0 |
| `conflict` → 409 | **0** | **105 (73.9%)** | **0** |
| **saves answered 200 and absent from the plan** | **0** | **0** | **0** |

Three shapes, three different answers, and each is the answer the design
promises. Nothing merged that should have refused; nothing refused that should
have merged; no outcome word was wrong about what landed.

`retried` is zero in all three by construction and that is correct: `retried`
is the "somebody edited a **different** file" fast path, and here there is only
one file. This scenario is the branch that path exists to avoid.

The three checks behind the bottom row, each of which was shown a mutation
before it was believed (revert a scalar, invent a value, move a line into the
next paragraph, drop a hunk, drop a key — five mutations, five fires, silence on
the honest tip):

* **`fields`** — all seven last-writer-wins scalars hold the exact value their
  only writer was last answered 200 for: `title` → `Task under twelve hands
  WS05.0011`, `owner` → `ws06.0011`, `person_weeks` → `1.12`, `assigned_on` →
  `2026-01-13`, `priority` → `high`, `review_waived` → `True`, `status` →
  `shelved`. All 59 list-append markers across `tags`/`prs`/`assignees`/
  `reviewers`/`depends_on` are in the tip.
* **`field`** — the final `person_weeks` is `18.12`, which is (a) one of the 142
  values somebody sent and (b) the value carried by the newest accepted commit,
  read off the commit graph rather than off wall-clock order. No average, no
  invention, no resurrection of an older save.
* **`body`** — all 139 inserted lines are present **and each is under the
  heading its author aimed at**. Not one landed in a neighbour's paragraph.
  Marker presence alone would not have seen that; `lane_placement` looks for it
  specifically, because a line in the wrong paragraph is a document neither
  person wrote and is the exact failure `_merge_body`'s single-cursor assembly
  can produce.

And in every run, on both repositories: `git fsck` clean, **local HEAD ==
origin HEAD, 0 unpushed commits**, no `<<<<<<<` in the tip or in any blob any
commit in the run wrote, no file that stopped being a record, and **no
validation blocker the corpus did not arrive with** (41 before, 41 after, on all
four runs). 481 concurrent saves to one file and the plan still loads.

`nothing_vanished` — every line of the document and every frontmatter key
present before the run is present after it — held in all four. The `fields` and
`field` runs ended with the body at exactly the 36 lines they started with; the
`body` runs grew 87 → 225 lines and lost none of the original 87.

## Speed, at 12 writers on one core

`file://` origin — the merge with the network taken out:

| | `fields` | `field` | `body` |
|---|---|---|---|
| `PATCH` p50 | 303.7 ms | 112.8 ms | 284.1 ms |
| p90 | 761.8 ms | 883.3 ms | 972.3 ms |
| p99 | 1566.6 ms | 1992.1 ms | 2151.3 ms |
| max | 1584.1 ms | 2045.4 ms | 2202.9 ms |
| `GET /detail/<id>` p50 | **1935 ms** | **1987 ms** | **2113 ms** |
| `GET /detail/<id>` p90 | 2788 ms | 2797 ms | 2801 ms |
| `GET /api/health` p50 | 199 ms | 173 ms | 198 ms |
| `GET /api/health` p99 | 1517 ms | 1518 ms | 1498 ms |
| accepted writes/s | 2.69 | 0.69 | 2.69 |
| PATCHes handled/s | 2.68 | 2.65 | 2.69 |
| server CPU | 44.1 s in 51.4 s (**86% of one core**) | 43.6 s in 53.5 s (81%) | 43.5 s in 51.7 s (84%) |
| RSS | 150 MB | 175 MB | 173 MB |

**The merge is not the bottleneck.** `write-different` — twenty people on twenty
*different* records, so nothing can legitimately conflict — got 2.14 accepted
saves/s at rtt 0. Twelve people on **one** record, where 86% of the writes have
to be three-way merged, get **2.69**. Contention on one file costs nothing
measurable against the serialised writer that both scenarios share. The three-way
merge of a 36-line frontmatter and a 90-line body is cheap next to rendering the
page the writer came from.

That is the real shape of the cost: `GET /detail/<id>` p50 is **1.9–2.1 s** and
p90 is **2.8 s**, six times the p50 of the save itself. `GET /api/health` — a
route that reads one ref — has a p99 of **1.5 s**, which is the event loop
losing to twelve renders and twelve merges on one core.

### With a GitHub-priced push (`--rtt-ms 600`), 12 writers, `body`

| | |
|---|---|
| `PATCH` p50 | **6200 ms** |
| p90 / p99 / max | 6862 / 8056 / 8056 ms |
| accepted writes/s | **1.31** |
| saves in flight at the writer lock | p50 **8**, p90 9, max 10, time-weighted mean **7.61 of 12** |
| Little's law | L measured 7.61 · L predicted 7.71 |
| `GET /detail/<id>` p50 / p90 | 385 ms / 3049 ms |
| server CPU | 20.6 s in 47.3 s (43% of one core) |
| lost / conflicted / misplaced | **0 / 0 / 0** |

Little's law agrees with the measurement to 1.3%, which means this is an
ordinary single-server queue and can be reasoned about as one. Service time is
1/1.31 = **763 ms per accepted write**, of which 600 ms is the push. Eight of the
twelve people are, on average, sitting in the queue rather than working.

Note the CPU fell to 43%: at rtt 600 the writers spend most of their time
blocked in a push that releases the GIL, so there is *more* core available for
reads and `GET /detail` p50 improves from 2.1 s to 0.4 s. The service is not
CPU-saturated when it is network-bound — the two ceilings trade against each
other rather than adding.

## What works

Plainly, and this is most of the report:

1. **Nothing was lost.** 376 writes answered 200 across four runs; 376 of them
   are in git. Not one 200 whose content is absent, not one 409 whose content is
   present anyway.
2. **The per-key frontmatter merge is right, and it is right for the reason it
   was built.** Twelve people moving twelve different fields of one record all
   land, with no refusals at all. File-level locking would have refused 119 of
   138 saves here.
3. **The per-hunk body merge is right in the shape people actually use.** Twelve
   people adding a bullet to twelve different sections of one shaping document:
   139 for 139, every line under its own heading.
4. **Same-key contention refuses, and refusing is clean.** A 409 writes nothing:
   no partial file, no conflict marker, no half-merged frontmatter. The refusal
   names the field and both values (`person_weeks: stored X · yours Y`).
5. **A merge does not reformat the file.** Checked directly on the pure
   functions: `_merge` re-dumps the whole frontmatter through ruamel round-trip,
   and a key nobody touched — including a `# comment` line above it, the blank
   lines, the key order, and a quoted `prs: ["C2SM/icon4py#1223"]` — comes back
   byte-identical. "Edit it in git if you prefer" survives concurrency.
6. **The push kept up.** Local HEAD equalled origin HEAD at the end of every
   run, including the one where every save had to merge first.
7. **Throughput is flat under contention.** 2.69 accepted writes/s with 86%
   merges is the same number the uncontended scenario gets. There is no
   collapse, no livelock, no retry storm.

## What doesn't

1. **The read path is what people will feel, not the write path.** At 12 writers
   on one core, `GET /detail/<id>` p50 is 1.9–2.1 s and p90 2.8 s, while the save
   itself is 0.3 s. Every writer pays that page before every save. openproj will
   be experienced as slow long before it is experienced as unsafe.
   *Reproduce:* `uv run python tests/load/write_same.py --variant body --writers
   12 --seconds 50 --size medium`.
2. **Same-field contention refuses three saves in four.** 105 of 142 at 12
   people. Correct, lossless, and still a bad afternoon: the person retypes.
   This is a stress figure and not a forecast — twelve people do not really set
   `person_weeks` on one task in the same minute — but it is the curve the
   design sits on, and it is steep. *Reproduce:* `--variant field --writers 12`.
3. **With a real push, Save takes 6.2 s at the median and 8.1 s at p99, at
   twelve people.** The throughput ceiling is 1/service-time and does not move
   when you add people; only the wait moves. See the extrapolation below.
4. **`WriteResult.pushed` never reaches an HTTP caller.** The PATCH route builds
   its answer in `web.py:_result`, which carries `outcome`, `commit`, `conflict`
   and `head` — and drops `pushed`. Only the co-editing socket's `saved` frame
   surfaces it. So a browser that is told 200 cannot know whether the commit
   reached GitHub or is sitting on an in-memory filesystem that `--min-instances
   0` will delete. In these four runs nothing was ever unpushed, and the API
   still could not have said so.
5. **Cosmetic, and not a concurrency defect at all — but found on the way:**
   `model.patch_text` rewrites a flow-style list to block style whenever a save
   touches it. `tags: [icon4py, load]` becomes a four-line block after any PATCH
   that sets `tags`, on the first save, with no contention involved. Untouched
   lists are untouched. Checked directly on `patch_text`, not through the server.

## What I could not measure

* **A slower core.** The extrapolation below is arithmetic on a measured CPU
  fraction, not a measurement on Cloud Run hardware.
* **Whether the push-retry path ever fires in production.** `_attempt`'s
  rewind-fetch-retry (`tries=3`, costed at "about 1.8 s") answers a
  non-fast-forward push, which requires somebody *else* to have moved the
  remote. With `--max-instances 1` and one serialised writer, nothing inside the
  service can do that; only a human pushing to the plan repository, or the
  briefly-exceeded second instance the RUNBOOK admits to, can. Zero of the 481
  saves here exercised it, so its cost is untested by this scenario and the
  1.8 s figure remains an estimate.
* **The latency of a refusal separately from the latency of an acceptance.** The
  `field` run's PATCH p50 of 112.8 ms mixes 105 fast refusals with 37 slow
  acceptances; `--rows` would separate them and I did not spend a run on it.
* **A tab left open on this record.** `--stale` exists and this scenario did not
  use it: every writer re-read `/api/health` before every save, which is the
  optimistic case. A base commit that is minutes old on a record twelve people
  are editing refuses far more often — the earlier phase measured 71–75%
  refusals with `--stale` on *uncontended* records.
* **Two instances.** Out of scope here; `tests/load/probe_twoinstances.py` is
  the instrument for it.

## On 1 vCPU, which is the deployment

Two of the three numbers scale differently and mixing them is how a laptop
measurement becomes a wrong forecast.

**The push does not care about the core.** 600 ms of GitHub round trip is 600 ms
on any CPU. Service time at the writer lock is 763 ms measured, of which ~600 ms
is network and ~163 ms is merge + commit + index invalidation. On a core 2–3×
slower — the range I would assume for a throttled Cloud Run vCPU against an M4
performance core on single-threaded CPython, and it is an assumption, not a
measurement — that becomes roughly **930 ms–1.1 s**, so the write ceiling falls
from 1.31/s to about **0.9–1.1 accepted saves per second**. Not a cliff.

**The page render does care, completely.** The server burned 86% of one core at
12 writers with the network taken out; it is already single-core-bound here,
because it is one uvicorn process holding one GIL. `GET /detail/<id>` at
1.9–2.1 s p50 becomes roughly **4–6 s p50**, and its p90 of 2.8 s becomes
**6–8 s**. That is the number that decides whether the tool is usable.

**At 20 people on one record, with GitHub, on that core:** throughput is capped
by service time, not by how many people are waiting, so 20 writers do not get
more saves — they get a longer queue. Little's law on the measured ceiling gives
a cycle of 20 ÷ ~1.0 saves/s ≈ **20 s per person per save**, of which the
`PATCH` itself is the bulk once the think-time and the page are subtracted:
**Save p50 in the region of 12–16 s, p99 worse.** Cloud Run's `--timeout 300`
will not kill it. A person will.

### So: is this scenario safe at 20 people on one throttled core?

**Safe, yes. Usable, no.**

Safe in the sense jcanton asked about first, and I would say so without
hedging: this design does not lose writing. Four runs, 481 concurrent saves to a
single file, three genuinely different merge shapes, and the integrity checks
came back clean every time — no lost 200, no phantom 409, no conflict marker in
git, no divergence between the instance and the remote, no file that stopped
parsing. The serialised writer plus the per-path compare-and-swap plus the
structured three-way merge is the right architecture for this problem and it is
behaving as documented under exactly the load it was written for. **The risk of
ending up with merge conflicts on the plan repo is, on this evidence, not the
risk to worry about.**

Not usable in the sense that a 12–16 s Save and a 4–6 s record page is what
twenty simultaneous editors would actually experience, and long before that they
would experience the *read* path — which twenty people browsing, not editing,
already saturate on their own. The failure mode of this system under twenty
people is not corruption; it is that everybody waits, and the thing they wait
for most is a page that nobody is even writing to.

The two things that would move the numbers are both on the read side and neither
is a concurrency fix: make `GET /detail/<id>` cheaper (it is 6× the cost of the
save it precedes), and stop the render competing with the merge for the one core
they share. The write path — the part this scenario was aimed at — is limited by
one GitHub round trip inside one lock, which is a deliberate and defensible
trade, and it is the *cheapest* thing on the page.

One thing worth fixing regardless of load: **surface `WriteResult.pushed` on the
HTTP write routes.** It costs one key in `_result` and it is the only signal
that distinguishes "your writing is in GitHub" from "your writing is on a
filesystem that will be deleted when the instance scales to zero."
