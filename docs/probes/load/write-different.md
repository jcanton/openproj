# `write-different` — twenty people, twenty records, one writer lock

The store's intended load: twenty form writers editing twenty *different* records
and saving as fast as a person plausibly would. No co-editing, no readers, no
overlap — nothing here can legitimately conflict, so every refusal and every
missing marker would be a defect rather than the scenario.

Raw numbers: [`write-different.json`](write-different.json). Nothing under
`src/openproj/` was changed to take them; the only shim is
`tests/load/server.py:shim`, which sleeps inside `pygit2.Remote.push`/`.fetch`
from outside the application.

## The bench

| | |
|---|---|
| machine | Apple `Mac16,12`, 10 cores, 24 GB, CPython 3.12.13, pygit2 1.20.0 / libgit2 1.9.6 |
| also running | two other Claude Code sessions (idle), nvim ×2, Firefox, iTerm2; load average 1.7 before the runs |
| corpus | `tests/load/corpus.py` medium — 561 records, bodies the length of a real shaping document |
| server | one uvicorn, one worker, `--auth dev`, bare `file://` origin, 127.0.0.1:8900 |
| writers | 20, each on its own `task-*`, each save preceded by `GET /detail/<id>` + `GET /api/health`, then `PATCH /api/entity/<id>`, then a pause drawn from 3–8 s |
| window | 60 s per point, 25 s per control. 230 s of server load in total. |

**Cloud Run runs this on 1 throttled vCPU** (`--cpu 1 --max-instances 1
--concurrency 200 --min-instances 0`). Every CPU-bound number below is a floor.

## One writer, no contention — what a save actually costs

| | rtt 0 | rtt 600 ms |
|---|---|---|
| `PATCH /api/entity/<id>` p50 | **14.9 ms** | **636.5 ms** |
| p90 / max | 15.7 / 16.2 | 639.6 / 639.7 |
| `GET /detail/<id>` p50 | 303.2 ms | 303.5 ms |
| `GET /api/health` p50 | 1.3 ms | 1.3 ms |

636.5 − 14.9 = 621.6 ms. **Exactly one remote round trip per save**, and it is
inside `self._writing`. The "no fetch before the write" decision in
`store.py:780` is visibly paid off here: the pre-fetch it removed would have made
this three round trips.

The record page costs 20× what the save costs. That is the number that decides
everything below.

## Twenty writers, twenty records, 60 s

| | rtt 0 | rtt 150 ms | rtt 600 ms |
|---|---|---|---|
| accepted saves | 143 | 147 | 93 |
| **saves/second** | **2.14** | **2.25** | **1.29** |
| `PATCH` p50 | 696 ms | 1069 ms | **7247 ms** |
| `PATCH` p90 | 1359 ms | 2282 ms | **8821 ms** |
| `PATCH` p99 | 1950 ms | 3392 ms | **12819 ms** |
| `PATCH` max | 1960 ms | 3566 ms | 12819 ms |
| `GET /detail/<id>` p50 | 1635 ms | 986 ms | 496 ms |
| `GET /detail/<id>` p90 | 4946 ms | 4973 ms | 5060 ms |
| `GET /api/health` p50 | **739 ms** | 175 ms | 18 ms |
| `GET /api/health` max | 2054 ms | 2196 ms | 641 ms |
| store outcomes | 26 committed, 117 retried | 38 / 109 | 1 / 92 |
| **conflicts (409)** | **0** | **0** | **0** |
| **lost saves** | **0** | **0** | **0** |
| unpushed at the end | 0 | 0 | 0 |
| server CPU / wall | 47.5 s / 66.7 s | 47.2 s / 65.4 s | 30.0 s / 72.3 s |

`retried` is the store's own word for "somebody committed, but not to your file".
**82 % of saves took that path and nobody was ever told.** That is the
compare-and-swap doing precisely the job its docstring claims.

## The queue in front of the lock

`tests/load/queueing.py`, computed from the ledger after the fact.

| | rtt 0 | rtt 150 | rtt 600 |
|---|---|---|---|
| saves in flight when a save began, p50 | 4 | 4 | **11** |
| p90 / max | 9 / 17 | 7 / 9 | 13 / 15 |
| time-weighted mean in flight | 1.68 | 3.06 | **9.99** |
| Little's law `X·W` | 1.43 | 2.59 | 9.21 |

Little's law is quoted against the whole window and the sweep against
first-start-to-last-end, which is why the two differ by ~15 %; over the sweep's
own window they agree to two decimals.

At rtt 600, **ten of the twenty people are waiting at any instant** and the
per-bucket throughput is flat at 1.5/s with a flat p50 of ~7.2 s. That is a
closed loop at equilibrium, not a queue running away — the system is stable, it
is just stably slow.

## The ceiling, in saves/second, as a function of push latency

`tests/load/writer_ceiling.py` — one `Store`, eight threads, eight different
files, no HTTP and no rendering, so this is the mutex alone.

| push rtt | saves/s | implied in-lock ms | p50 ms | p90 ms |
|---|---|---|---|---|
| 0 | 49.6 | 20.1 | 153 | 242 |
| 25 ms | 13.8 | 72.5 | 575 | 604 |
| 50 ms | 9.3 | 107.8 | 856 | 885 |
| 150 ms | 4.3 | 230.2 | 1842 | 1860 |
| 300 ms | 2.6 | 392.0 | 3136 | 3152 |
| 600 ms | **1.44** | 693.8 | 5536 | 5557 |

699 writes, **every one `pushed=True`**, zero conflicts, `local == origin` at the
end.

Above ~150 ms the curve is a straight line through one round trip:

```
ceiling(rtt) ≈ 1000 / (20 + rtt_ms)   saves per second
```

The 20 ms floor is git work — CAS reads, tree build, commit. Below 150 ms the
implied cost rises above `20 + rtt` because eight threads are then contending for
the GIL rather than sleeping in a push; that excess is the instrument's laptop,
not the store.

**So: GitHub at 600 ms ⇒ 1.4 saves/second for the entire service.** At 300 ms,
2.6/s. At 150 ms, 4.3/s.

## Durability: how many saves report `pushed: false`

None of them can. `WriteResult.pushed` exists, `store.py:921` sets it honestly,
and `web.py:_result` (line 1801) builds `{outcome, commit, conflict, head}` and
drops it. **431 HTTP saves across these five runs, 431 rows of `pushed: unknown`.**
The only place in the application that surfaces the field is the co-editing
socket's `saved` frame.

Asked from outside instead — `queueing.RemoteLag` samples the plan's HEAD against
the bare origin's every 200 ms:

| | rtt 0 | rtt 150 | rtt 600 | 1 writer @ rtt 600 |
|---|---|---|---|---|
| samples with local ahead of origin | 3.7 % | 40.2 % | **81.0 %** | 43.2 % |
| max commits ahead | 1 | 1 | 1 | 1 |

Never more than one commit — the push is inside the lock, so local can be at most
one commit ahead, which is exactly what that design buys. But at GitHub latency,
**for four fifths of the wall clock there is a commit on the instance's disk that
the remote does not have**, and on Cloud Run that disk is memory.

## What `GET /detail/<id>` does to everyone else

`@app.get("/detail/{entity_id}")` is `def`, not `async def` (web.py:1643), so
Starlette runs it in the threadpool. Twenty simultaneous renders are therefore
twenty OS threads round-robining one GIL, and they all finish *together* rather
than in order — which is why the slowest decile clusters within 130 ms of 5.0 s
in all three runs while p50 varies from 0.5 s to 1.6 s.

At rtt 0, 149 record pages × ~300 ms = 44.7 s of CPU out of 47.5 s the server
burned. **94 % of the service's CPU in a pure-write scenario was drawing record
pages.** `GET /api/health`, which costs 0.7 ms alone, reached a p50 of 739 ms and
a max of 2054 ms behind it.

## What was verified after every run

`tests/load/verify.py`, against git and not against the responses:

- 431 saves answered 200, **431 markers in the tree, 0 lost, 0 ambiguous**
- 0 conflict markers in any committed blob
- `local == origin`, 0 unpushed commits, no fork, on all five runs
- `git fsck` clean on plan and origin
- 561 records still parse, 0 unreadable, 41 blockers before and 41 after
- no commit authored by `unsigned` — every cookie verified, six real logins
- no `person_weeks` in the tree that nobody sent

## Left behind

Nothing. `ps` checked after every run; ports 8900 only; every temporary plan
removed by the harness's `__exit__`.
