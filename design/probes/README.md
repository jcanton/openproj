# Probe log — the write path under twenty people

A lab notebook for `tests/load/`, not a design document. It records what was
measured, on what, and the command that measures it again. The report these
numbers were taken for is `concurrency-audit.md`, beside this file. **Nothing under
`src/openproj/` was changed to take any of these numbers**: the only shim is
`tests/load/server.py:shim`, which charges `pygit2.Remote.push`/`.fetch` a
sleep so a `file://` remote on the same SSD can stand in for GitHub over HTTPS.

## The bench

|         |                                                                                                                                                              |
| ------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| machine | Apple Silicon laptop, CPython 3.12.13, pygit2 1.20.0 / libgit2 1.9.6                                                                                         |
| corpus  | `tests/load/corpus.py` — 40 pitches × 10 tasks + 1 project + 60 notes + 60 issues = **561 records, 566 files**, bodies the length of a real shaping document |
| server  | one uvicorn, one worker, `--auth dev`, `file://` remote, bound 127.0.0.1                                                                                     |
| ports   | 8931–8942, loopback only                                                                                                                                     |

Cloud Run runs this on **1 throttled vCPU**. Every CPU number below is a floor,
not a forecast: a laptop core is several times a throttled Cloud Run core, and
everything here that costs CPU is pure Python holding the GIL.

## Running them

```bash
uv sync --frozen
.venv/bin/python tests/load/micro.py       "$SCRATCH"   # piece-by-piece costs
.venv/bin/python tests/load/counters.py    "$SCRATCH"   # store calls per request
.venv/bin/python tests/load/merge_probe.py              # the three-way merge, by hand
.venv/bin/python tests/load/lost_line.py   "$SCRATCH"   # a committed line, silently dropped
.venv/bin/python tests/load/divergence.py  "$SCRATCH"   # unpushed / human push / fork / retry ladder
./tests/load/run.sh <scenario> <seconds> <writers> <readers> <rtt_ms> [port] [gap_s]
```

`run.sh` builds a fresh plan in a temp dir, starts one server, drives it, and
kills the server and deletes the plan from a `trap` on `EXIT INT TERM PIPE HUP`.
Scenarios: `read`, `spread`, `same`, `same-stale`, `mixed`, `rooms`, `herd`.

## What one thing costs, alone

`tests/load/micro.py`, and `render_*` measured the same way.

|                                                               | 81 records | 561 records | 1921 records |
| ------------------------------------------------------------- | ---------- | ----------- | ------------ |
| `store.head()` (opens a fresh `pygit2.Repository` every call) | 0.19 ms    | 0.19 ms     | 0.19 ms      |
| `store.blobs()` — whole tree walk                             | 0.02       | 0.30        | 1.25         |
| `_entities_at` — warm `_PARSED` cache                         | 0.04       | 0.42        | 1.70         |
| **`build_index`**                                             | 3.1        | **25.7**    | 136          |
| `store.last_edited()` full history walk                       | 0.30       | 1.05        | 3.52         |
| `render_table`                                                | 26.0       | 40.1        | 154          |
| **`render_detail`**                                           | 82.6       | **240**     | **718**      |

`store.write` on 561 records: **3.1 ms** with no remote, **10.3 ms** over a
`file://` remote. One `fetch` round trip on `file://` is 1.5 ms — GitHub over
HTTPS is priced at ~600 ms by `store.py`'s own comment, which is what `rtt_ms`
substitutes.

## What one request asks the store for

`tests/load/counters.py`, warm index cache, 561 records.

| route                                                    | ms        | `head()` | tree walks | blob reads |
| -------------------------------------------------------- | --------- | -------- | ---------- | ---------- |
| `GET /api/health`                                        | 0.7       | 1        | 0          | 0          |
| `GET /`                                                  | 29.1      | 2        | 0          | 0          |
| `GET /table`                                             | 43.3      | 1        | 0          | 0          |
| `GET /api/index.json`                                    | 5.7       | 1        | 0          | 0          |
| `GET /detail/<id>`                                       | **240.7** | 1        | 0          | 0          |
| `PATCH /api/entity/<id>` (+ the `/api/health` before it) | 47.2      | **7**    | **5**      | 5.8        |

## Serialisation

`with self._writing:` is taken at `store.py:780` and released at `store.py:799`.
Inside it, and in this order: `head()`, per-path compare-and-swap reads, blob and
tree writes, `create_commit`, and then `_finish` → `_send` → **`Remote.push`**
(`store.py:639`). The network round trip to GitHub is inside the mutex.

`run.sh spread 90 20 5 600` — 20 writers, one save each per 10 s (2 saves/s
demanded), 600 ms simulated push:

```
PATCH   p50 3009 ms   p95 8262 ms   max 12693 ms
GET /   p50  105 ms   p95  265 ms
throughput 1.39 saves/second        142 saves, 0 conflicts, 0 unpushed
```

The same shape with a free push (`rtt 0`, 2 s gap): 6.95 saves/s, PATCH p50
389 ms, `GET /` p50 818 ms.

Read-only floor, no writers: 20 concurrent readers → `GET /` p50 560 ms,
25.6 pages/s. Two concurrent readers → 103 ms.

## Contention on one record

`run.sh same 60 10 3 0` (each writer re-reads HEAD before saving) versus
`run.sh same-stale 60 10 3 0` (each writer keeps the base its page was drawn at,
which is a tab left open):

|                  | fresh base | stale base    |
| ---------------- | ---------- | ------------- |
| committed        | 240        | 1             |
| merged           | 60         | 149           |
| retried          | 193        | 10            |
| **409 conflict** | **0**      | **396** (71%) |
| saves/s          | 8.08       | 2.63          |

No conflict marker ever reached the plan in either run, and `local == remote`
at the end of every run.

## The co-editing room

`_commit_room` is the one writer not handed to `asyncio.to_thread`
(web.py:2605, and the reason is written out above it). `run.sh rooms 60 8 0 <rtt> … 3`
— eight rooms, Save every 3 s, while one thread times `GET /api/health`:

|                                | rtt 0  | rtt 600      |
| ------------------------------ | ------ | ------------ |
| `/api/health` p50              | 4.8 ms | 5.2 ms       |
| `/api/health` p95              | 6.6 ms | **5738 ms**  |
| `/api/health` max              | 141 ms | **15300 ms** |
| probes completed in the window | 713    | 48           |

At 20 rooms with rtt 600, 16 of 20 sockets stopped getting an answer inside the
client's 10 s read timeout.

## The index cache herd

`index_now` (web.py:1119–1128) reads the memo, tests `(commit, today)`, and on a
miss builds and stores. No lock, no in-flight marker. `run.sh herd 0 10 0 0` fires
10 simultaneous `GET /api/index.json` against a warm memo, invalidates it with one
PATCH, and fires the same 10 again:

```
warm burst wall  86.7  86.4  74.1  83.5 ms
cold burst wall 391.0 406.1 417.3 147.4 ms
extra per write  304   320   343    64  ms   (median 312)
```

312 ms against a single `build_index` of 25.7 ms: **one write costs about one
index rebuild per reader that was in flight**, not one. The herd window is one
`build_index` wide, so it grows with the plan (136 ms at 1921 records).

## The three-way merge

`tests/load/merge_probe.py` and `tests/load/lost_line.py`.

- Two people appending a line at the end of a document — the commonest
  co-editing shape there is — is **refused**, not merged, and the refusal reads
  `lines 3-2:` (an insertion span is empty, so `span[0] + 1 > span[1]`).

- `_merge_body` calls two edits a conflict only where they overlap by a
  half-open test (`store.py:145`). An insertion's span is empty, so an insertion
  at line N and a replacement starting at line N are merged silently — and the
  assembly loop (`store.py:157–165`) walks the union of both sides' spans with
  one cursor and **skips any span starting behind the cursor**. Of two spans
  beginning on the same line, the second one the *set* yields is dropped.
  Whether that happens is decided by the hash order of two integer tuples, i.e.
  by the line number:

  ```
  offset  0  MERGED, and Bob's committed line is gone
  offset  1  merged, both kept
  offset  2  MERGED, and Bob's committed line is gone
  offset  3  merged, both kept
  …
  ```

  Driven through `Store.write` end to end: Bob's commit is in the history, his
  sentence is not in the file, and Ann was answered `outcome: "merged"`, 200,
  with no conflict to read.

- Fuzzed over 50,000 random three-way pairs on 4–12 line documents: 43,237
  merged with no conflict, and of those **1,192 (2.8%) dropped a line the
  STORED commit had** and 1,028 (2.4%) dropped a line the incoming save had.
  `store.py:859` passes `stored` as `theirs`, so the first number is a commit
  already in git being reverted by a save that answered 200.

## Divergence

`tests/load/divergence.py`, four scenes, all real repositories and a real
`git push` from a scratch clone standing in for a person with a terminal.

- **A** — remote unreachable for one save: `outcome='committed' pushed=False`.
  `_result` (web.py:1801) carries `outcome, commit, conflict, head` and not
  `pushed`, so the browser is told what a landed save is told.
- **B** — human pushes while the app runs: push rejected → `_absorb_remote`
  fast-forwards → retry lands. `outcome='retried' pushed=True`, the human's
  edit still in the tree, local == remote. **This works.**
- **C** — A and then B: neither history contains the other. `StoreDiverged`,
  and it is raised again by every subsequent write, including writes to
  unrelated files, for the life of the process. No HTTP route catches it.
- **D** — the remote moves under all three attempts: nothing is committed, the
  ref is rewound, and the caller gets `outcome='conflict'` → HTTP 409 with
  *"the plan moved three times while this was being saved. Nothing was written.
  Reload and try again."*

## Left behind

Nothing. Every run kills its server from a trap and deletes its plan; `ps` and
`lsof` were checked after each. Ports 8931–8942 only.
