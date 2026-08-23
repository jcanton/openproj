"""How deep the queue in front of the serialised writer actually got.

`measure.Ledger` says how long a save took. It cannot say *why*, and for a
service whose whole write path is one mutex the why is nearly always the same
one: the save was not slow, it was waiting. These are the two instruments that
tell those apart, and neither of them touches `src/openproj/`.

**`concurrency()` is post-hoc arithmetic on the ledger**, not a counter in the
driver. Every `Action` already carries `began` (seconds since the run's zero)
and `ms`, so each save is a closed interval and "how many other saves were in
flight when this one started" is a sweep over the endpoints. Post-hoc rather
than a shared `AtomicInteger` on purpose: a counter incremented by twenty
threads is a lock the driver takes on the exact path it is timing, and a driver
that contends with itself is measuring itself.

Two numbers come out of it and they mean different things:

* `depth_at_start` — what a person joining the queue found in front of them.
  This is the number Little's law wants, and with N writers in a closed loop it
  can never exceed N. It reaching N *is* the finding: it means every simulated
  person is blocked at once and the demanded rate is above what the store can
  serve.
* `mean_in_flight` — time-weighted, so a brief spike does not read like a
  sustained queue.

And a `buckets` list, because a closed loop and an unstable queue look identical
in a single p50. If throughput is flat while latency climbs across the window,
the run never reached equilibrium and every percentile in it is an artefact of
where the window happened to stop.

**`RemoteLag` is a sampler**, and it exists because of a specific hole: `pushed`
reaches exactly one place in the whole application (the co-editing socket's
`saved` frame), so a form writer answered 200 is told nothing at all about
whether the commit left the machine. `WriteResult.pushed` is dropped by every
HTTP write route. The only remaining way to ask is from outside — compare the
plan's `refs/heads/main` with the bare origin's, repeatedly, while the load
runs. `verify.pushed` already asks it once at the end, which catches a commit
that never landed; this catches a *window* in which local was ahead, which is
the thing that kills data when the instance is torn down mid-write.

Both read the repositories with pygit2 and never write. `Store` holds an
exclusive flock, so opening a `Store` here is not an option.
"""

from __future__ import annotations

import threading
from pathlib import Path

import measure


def _percentiles(values: list[float]) -> dict:
    """Nearest-rank, the same rule `measure.percentiles` uses, so a depth and a
    latency in one report are read the same way."""
    return measure.percentiles(values)


def concurrency(actions: list, kind: str = "PATCH", buckets: float = 10.0) -> dict:
    """What the queue in front of `kind` looked like, from the ledger alone."""
    spans = sorted(
        (one.began, one.began + one.ms / 1000.0, one.ms)
        for one in actions
        if one.kind == kind and one.ms > 0
    )
    if not spans:
        return {"n": 0}

    # How many were already running when each one started. A half-open test:
    # a save that ended at exactly this instant is not in front of anybody.
    starts = [s for s, _, _ in spans]
    depth_at_start: list[float] = []
    for start in starts:
        running = sum(1 for s, e, _ in spans if s < start <= e)
        depth_at_start.append(float(running))

    # Time-weighted mean, by sweeping the endpoints. A queue that was twenty
    # deep for a tenth of a second is not a queue that was twenty deep.
    events = sorted([(s, 1) for s, _, _ in spans] + [(e, -1) for _, e, _ in spans])
    area, height, last = 0.0, 0, events[0][0]
    peak = 0
    for when, delta in events:
        area += height * (when - last)
        last = when
        height += delta
        peak = max(peak, height)
    window = events[-1][0] - events[0][0]

    # Per-bucket throughput and latency. Flat throughput with climbing latency is
    # a queue that never settled; both flat is a closed loop at equilibrium.
    first = min(starts)
    rows: dict[int, list[float]] = {}
    for start, _, ms in spans:
        rows.setdefault(int((start - first) // buckets), []).append(ms)
    over_time = [
        {
            "from_s": round(n * buckets, 1),
            "n": len(values),
            "per_second": round(len(values) / buckets, 2),
            "p50_ms": round(sorted(values)[len(values) // 2], 1),
        }
        for n, values in sorted(rows.items())
    ]

    return {
        "n": len(spans),
        "depth_at_start": _percentiles(depth_at_start),
        "peak_in_flight": peak,
        "mean_in_flight": round(area / window, 2) if window > 0 else 0.0,
        "buckets_seconds": buckets,
        "over_time": over_time,
    }


def littles_law(concurrency_block: dict, latency: dict, throughput: float) -> dict:
    """The queue arithmetic, stated rather than left to the reader.

    `mean_in_flight = throughput × mean_latency` is Little's law and it must hold
    on any honest ledger; printing both sides is the cheapest possible check that
    the sweep above is not lying. They will not agree to the last decimal — the
    sweep weights by the whole window and the mean does not — but a gap of more
    than a few per cent means one of the two is wrong.

    What this deliberately does NOT do is subtract a service time to leave a
    wait: the uncontended service time is a different run with one writer in it,
    and folding a number from another run in here would hide which run it came
    from.
    """
    mean_ms = latency.get("mean")
    if mean_ms is None or not throughput:
        return {}
    predicted = throughput * (mean_ms / 1000.0)
    return {
        "mean_latency_ms": mean_ms,
        "throughput_per_second": round(throughput, 3),
        "little_L_predicted": round(predicted, 2),
        "little_L_measured": concurrency_block.get("mean_in_flight"),
    }


class RemoteLag(threading.Thread):
    """Samples `plan HEAD` against `origin HEAD` while the load runs.

    The question is not "did everything push in the end" — `verify.pushed`
    answers that — but "for how much of this run did the machine hold a commit
    the remote did not have". On Cloud Run the filesystem is in memory and
    `--min-instances 0` tears the instance down, so that window is exactly the
    window in which somebody's save can die after being answered 200.

    Read-only, in the driver process, and every failure is swallowed: the server
    is rewriting these refs underneath, and a sampler that raised would take down
    a run over a ref it caught mid-update.
    """

    def __init__(self, plan: Path, origin: Path | None, every: float = 0.2) -> None:
        super().__init__(name="remote-lag", daemon=True)
        self.plan = plan
        self.origin = origin
        self.every = every
        self.samples = 0
        self.behind = 0
        self.max_commits_behind = 0
        self.errors = 0
        # Not `self._stop`: `threading.Thread` already has a `_stop` METHOD and
        # `join` calls it, so an Event assigned there raises
        # `'Event' object is not callable` on the way out. Exactly the shape that
        # made `CoEditor.join` shadow `Thread.join` one phase ago.
        self._halt = threading.Event()

    def run(self) -> None:
        if self.origin is None:
            return
        import pygit2

        while not self._halt.is_set():
            try:
                local = pygit2.Repository(str(self.plan))
                remote = pygit2.Repository(str(self.origin))
                here = str(local.references["refs/heads/main"].target)
                there = str(remote.references["refs/heads/main"].target)
                self.samples += 1
                if here != there:
                    self.behind += 1
                    ahead = 0
                    for commit in local.walk(local[here].id):
                        if str(commit.id) == there:
                            break
                        ahead += 1
                        if ahead > 50:
                            break
                    self.max_commits_behind = max(self.max_commits_behind, ahead)
            except Exception:  # noqa: BLE001 - a ref caught mid-update is ordinary
                self.errors += 1
            self._halt.wait(self.every)

    def stop(self) -> dict:
        self._halt.set()
        self.join(timeout=5.0)
        return self.report()

    def report(self) -> dict:
        if self.origin is None:
            return {"sampled": False}
        return {
            "sampled": True,
            "every_seconds": self.every,
            "samples": self.samples,
            "samples_with_local_ahead": self.behind,
            "fraction_ahead": round(self.behind / self.samples, 4) if self.samples else None,
            "max_commits_ahead": self.max_commits_behind,
            "read_errors": self.errors,
        }
