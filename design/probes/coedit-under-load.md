# The co-editing path under 10-20 people

Measured 2026-08-23 against `5a09f6d` (v0.14.0), on a real `openproj serve` in a
child process, driven by real TCP websockets. Every number below is reproducible
with one command; the probe that produced it is named beside it. Nothing in
`src/openproj/` was changed — this is an audit.

**Read the caveat first.** These runs have **no remote**, or a `file://` one.
`store.py:783` records the production term this cannot measure: about **600 ms**
per push from a laptop, and about **1.8 s** for the collision tail that rewinds,
fetches and retries. Every "loop held" number below is the local floor; add one
push per commit for what Cloud Run actually does. And this laptop's core is
faster than a Cloud Run 1 vCPU — the index-build number below is 60 ms here
against the 502 ms `web.py:1093` records for a corpus of the same size.

```bash
uv run python tests/load/probe_fanout.py 90 15      # one room, fifteen typists
uv run python tests/load/probe_manyrooms.py 8 20 --pages --big
uv run python tests/load/probe_saverace.py          # a form Save against a live room
uv run python tests/load/probe_twoinstances.py      # two instances, one record
uv run python tests/load/probe_seats.py 6 10        # sixty abrupt departures
uv run python tests/load/probe_shutdown.py          # what SIGTERM rescues
uv run python tests/load/probe_writecost.py         # how long a commit holds the loop
uv run python tests/load/probe_ceiling.py           # a room past MAX_BODY_BYTES
uv run python tests/load/probe_emoji.py             # concurrent splices around an emoji
```

## What works

| Claim                                                                                      | Evidence                                                                                                                                                                                                                                                                                            |
| ------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Fan-out is not the bottleneck.                                                             | 15 typists, 5 chars/s, one room, 90 s: **2.15 CPU-seconds**, 2.4% of one core. 6,133 frames per member. Propagation p50 1.5 ms, p99 4.5 ms. `probe_fanout.py`                                                                                                                                       |
| Seats do not leak, including on abrupt disconnects.                                        | 60 departures over 6 rounds, half RST with `SO_LINGER 0` and half polite: roster peaks at 11 and settles to exactly the one survivor, `leaked: []`, RSS flat at 80.6 MB. The fix is in the socket handler's `finally` (`web.py:2963`), which uvicorn runs however the socket ends. `probe_seats.py` |
| A reconnection through the five-minute teardown loses nothing *for a tab that comes back*. | Reset the socket, type into the document while there is none, reconnect: seed matched, no `reload`, the room still held the pre-drop text, and the offline text reached everybody else once the returning tab sent its state-vector diff. `probe_seats.py`                                          |
| The deterministic seed really does prevent the doubling the module docstring warns about.  | Two independent instances built rooms for one record at one commit and produced **the same seed sha**. That is what lets a bounced client be welcomed rather than merged into itself twice. `probe_twoinstances.py`                                                                                 |
| Concurrent splices around astral characters are safe on the server.                        | Two sockets splicing either side of `👍` and either side of `—` at the same moment: converged, emoji intact, no U+FFFD, no lone surrogate, and git holds the exact characters. `probe_emoji.py`                                                                                                     |
| A SIGTERM rescues every OCCUPIED room.                                                     | 20 rooms, all pending, one SIGTERM: **20 of 20 committed**, in 0.26 s. `probe_shutdown.py`                                                                                                                                                                                                          |
| Git integrity survives two instances.                                                      | Instance A's commit landed and pushed; instance B's push lost the race, rewound, re-merged, and refused honestly with the line-overlap report. No corruption, no conflict markers. `probe_twoinstances.py`                                                                                          |

## What does not

### 1. A busy room never commits

`Room.apply` restarts `_quiet_since` on **every** update (`coedit.py:228`), and
`_watch` commits only at `quiet_for() >= 20.0` (`web.py:2719`). With anybody
typing anywhere in the room, the clock never reaches twenty.

**Measured: 15 typists, 90 seconds of continuous typing, `commits_while_typing: 0`.**
8,024 characters lived in one process's memory and in no commit. The first
commit landed 18.3 s after the last keystroke.

The floor is not the twenty seconds the docstring promises. It is *twenty
seconds after the room goes quiet*, which in a room of fifteen is however long
the meeting lasts.

### 2. The upper bound on unpersisted text is `MAX_BODY_BYTES`, and crossing it is permanent

`web.py:2557` raises when the snapshot exceeds 256 KB. The raise is a
`ValueError`, `WRITE_FAILURES` catches it, and it becomes a refusal that writes
nothing and moves nothing. There is no path that trims a room and no frame that
stops anybody typing — the transport ceiling is four times the policy ceiling
by design (`web.py:193`), so nothing refuses on the way in.

**Measured: 277,800 bytes in the room, 1,051 in git.** No frame was refused
while growing. Every Save and every quiet window answered
`"this document is too large to commit"`, and the last-person-out commit did not
rescue it either. `probe_ceiling.py`

### 3. A form Save silently overwrites a room's uncommitted text, and wedges the room for ever

`PATCH /api/entity` (`web.py:1812`) never consults `rooms`. It reads the file at
`base`, patches, writes. If `base == HEAD` — which it is, because the room has
not committed — `store.py:830` takes the fast path and commits it **verbatim**.

Measured, in order (`probe_saverace.py`):

```
a_patch_outcome            "committed"     the form Save landed
a_git_has_ann              false           the room's text was not merged against
a_room_still_has_ann       true            the room still holds it, in memory only
b_room_save_answer         "refused"       lines 1-1: stored 'BO-…' · yours 'ANN-…'
c_reload_welcome_base      f1d2d64…        the OLD base — a reload does not clear it
c_after_reload_save        "refused"
d_refusals_seen_in_30s     2               one per quiet window, for ever
d_git_has_ann              false           it never reaches git
```

Three things make this worse than an ordinary conflict:

- **The person who pressed Save saw a 200.** Only the room hears the refusal.
- **A reload does not clear it.** The join-time absorb is gated on
  `not room.pending()` (`web.py:2767`), which is false for exactly the room that
  is stuck; the rejoining socket is welcomed with the **stale base** and a body
  git does not have.
- **`room.base` never moves on a refusal**, so the same losing three-way merge
  is retried every twenty seconds until everybody leaves.

### 4. A warm, empty, pending room is covered by nothing

`_watch`'s loop is `while room.members:`, and the socket's `finally` cancels the
task the moment the room empties (`web.py:2980`). So the shutdown hook covers
occupied rooms and nothing else. `Rooms.sweep` (`coedit.py:394`) drops a room
after `LINGER_SECONDS` **without asking whether it is pending**, and
`web.py:2985` discards what it returns.

The ordinary way to reach that state is finding 3: the last-person-out commit
refuses, so the room is left empty, pending, and untimered.

**Measured: `git_has_ann_after_sigterm: false`.** The paragraph was in git
neither before the SIGTERM nor after it. With `--min-instances 0` the instance is
torn down whenever the service goes idle, so this is not a rare path.
`probe_shutdown.py`

### 5. The flock is not a guard against a second instance

`deploy/RUNBOOK.md:273` says *"max-instances can be briefly exceeded, so the
`flock` is the real guard."* The flock is taken on `self._path / LOCK_FILE`
(`store.py:439`), and `self._path` is the **container's own** bare clone
(`deploy/boot.py:34`, `/srv/plan.git`). Two instances have two filesystems.

**Measured: two servers, two lock files, pids 7261 and 7262, both granted.**
`probe_twoinstances.py`

What actually guards git is the non-fast-forward push (`store.py:877`), and it
does hold. What is not guarded is everything above git:

```
ann_sees_bos_text   false      two rooms for one record, no updates between them
bo_sees_anns_text   false
ann_roster          ["ann"]    each person is told they are alone in the document
bo_roster           ["bo"]
```

Two people editing one shaping document, each shown an empty "also editing"
line, each with a divergent body — and then one of them loses the push race and
lands in finding 3's permanent refusal, holding text git will never take.

### 6. A commit holds the event loop, and the "saving…" cannot arrive until it is over

`_commit_room` is the one writer that does not run on a thread (`web.py:2591`),
deliberately: between the snapshot and `room.settled` there must be no `await`.
So the whole of `store.write` — tree, three-way merge, commit, **push** — holds
the loop.

Measured with `/api/health` as a stopwatch from outside the loop
(`probe_writecost.py`, idle floor 3.0-3.6 ms):

| condition                 | loop held, mean | worst   |
| ------------------------- | --------------- | ------- |
| no remote                 | 8.6 ms          | 17.2 ms |
| `file://` remote          | 20.0 ms         | 32.6 ms |
| every write has to merge  | 21.9 ms         | 34.3 ms |
| the same on a 210 kB body | 23.1 ms         | 41.6 ms |

And a by-product worth writing down: `_to_room({"t": "saving"})` only *queues*
the frame, and the task that drains queues needs the loop the write is holding.
**The "saving…" a room shows everybody cannot reach them until the write it
announces has already finished.** Measured `saving`→`saved` gap: 0.1 ms in every
condition, including the 210 kB merge.

Twenty rooms going quiet in the same second is twenty of those in a row. Locally
that is ~0.4 s. With one real push each it is **~12 seconds of frozen event
loop** — during which nobody's keystroke is relayed, no outbox drains, and no
other room's timer runs. Under `timeout_graceful_shutdown=10` and Cloud Run's
own ten-second SIGTERM grace, a burst that size at shutdown does not finish.

### 7. Everything an index rebuild costs is paid on the loop, and every room commit buys one

`index_now()` (`web.py:1119`) is a single entry keyed on `(commit, today)`, and
`PATCH /api/entity` calls it twice from an `async def` (`web.py:1840`, `1888`).
Every room commit moves HEAD and empties it.

Measured on a 480-task corpus during a 20-room commit burst
(`probe_manyrooms.py --big`): page p50 62 ms, p99 78 ms, worst 113 ms, against a
695 ms cold first build. So the rebuild is ~60 ms **here**; `web.py:1093` records
502 ms for a corpus of that size on the hardware that matters. Propagation in an
unrelated room rose from p99 38 ms (calm) to p99 88 ms (during the burst) —
2.3x, with no network in the writes.

## The emoji question, answered narrowly

The server side is closed: `byte_offset` is the one boundary, a syntax test holds
every `pycrdt` index to coming from it, and `probe_emoji.py` shows concurrent
splices either side of an astral character converging with the characters
intact, through a merged commit and an `absorb`.

The residual is in the browser and is reachable **only** from concurrent
editing. `reflect()` (`render.py:14339-14343`) is the one splice in this codebase
that scans a common prefix and suffix in **UTF-16 code units** rather than
through the `units()` boundary declared eighty lines above it — because it is
the path a *remote* keystroke takes into the surface. Its head and tail can stop
between the halves of a surrogate pair. The final value is `want` either way, so
a `<textarea>` re-pairs and nothing is lost; on the Ace surface the same range
goes through `indexToPosition` and `session.replace`, whose intermediate
document holds a lone surrogate, and `AGENTS.md` records that the Ace-surface
tests still splice only ASCII.

A harness that would settle it: drive the shipped `_COEDIT` with `aceSurface`
under `tests/js/drive.js` `{socket: true}`; seed `AB👍CD`; apply a **remote**
update, produced by a real `Room`, that rewrites `👍` to `👎` and separately one
that inserts between two adjacent emoji; then assert on `SURFACE.text()` that no
code unit in `[0xD800, 0xDFFF]` stands alone at any point and that the value
equals the room's, and repeat the same two cases in Chrome because `setRangeText`
with a lone surrogate is a browser fact rather than a claim about this code.

🤖 Written by an agent on behalf of @jcanton
