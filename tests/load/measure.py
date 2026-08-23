"""What happened, when, how long it took, and what came back.

One `Ledger` per run, written to by every simulated person on their own thread
and read once at the end. An `Action` is deliberately flat and deliberately
records the ANSWER as well as the latency: a p99 of 40 ms is a different
sentence when the answers were 409s, and "1.39 saves per second" is not a
measurement unless you also know how many of those saves reached the remote.

Percentiles are nearest-rank on the sorted samples — the same rule
`tests/load/room.py` already uses, so two probes in this directory can be read
side by side. No interpolation: with a few hundred samples an interpolated p99
is a number between two real ones and reads as more precise than it is.
"""

from __future__ import annotations

import statistics
import threading
from dataclasses import asdict, dataclass, field


@dataclass
class Action:
    """One thing one simulated person did."""

    who: str
    kind: str
    began: float  # seconds since the run's own zero
    ms: float
    status: str  # "200", "409", "ReadTimeout", "saved", "refused", ...
    outcome: str | None = None  # the store's own word: committed/merged/retried/conflict
    commit: str | None = None
    pushed: bool | None = None
    entity: str | None = None
    marker: str | None = None
    note: str | None = None


def percentiles(values: list[float]) -> dict:
    if not values:
        return {"n": 0}
    ordered = sorted(values)

    def at(fraction: float) -> float:
        return ordered[min(len(ordered) - 1, int(fraction * len(ordered)))]

    return {
        "n": len(ordered),
        "p50": round(at(0.50), 1),
        "p90": round(at(0.90), 1),
        "p99": round(at(0.99), 1),
        "max": round(ordered[-1], 1),
        "mean": round(statistics.fmean(ordered), 1),
    }


@dataclass
class Ledger:
    actions: list[Action] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def record(self, action: Action) -> None:
        with self._lock:
            self.actions.append(action)

    # -- reading it back ----------------------------------------------------

    def by_kind(self) -> dict:
        out: dict[str, list[float]] = {}
        for one in self.actions:
            out.setdefault(one.kind, []).append(one.ms)
        return {kind: percentiles(values) for kind, values in sorted(out.items())}

    def statuses(self) -> dict:
        out: dict[str, dict[str, int]] = {}
        for one in self.actions:
            out.setdefault(one.kind, {})
            out[one.kind][one.status] = out[one.kind].get(one.status, 0) + 1
        return {kind: dict(sorted(v.items())) for kind, v in sorted(out.items())}

    def errors(self) -> dict:
        """Anything that is not a 2xx and not a 409.

        409 is not an error here and putting it in this bucket would be the
        single most misleading thing this file could do: a compare-and-swap that
        refuses is the store working, and it is reported beside the outcomes
        where it belongs.
        """
        out: dict[str, int] = {}
        for one in self.actions:
            status = one.status
            if status.isdigit() and (status.startswith("2") or status == "409"):
                continue
            if status in ("saved", "nothing", "typed", "joined"):
                continue
            out[f"{one.kind} -> {status}"] = out.get(f"{one.kind} -> {status}", 0) + 1
        return dict(sorted(out.items()))

    def outcomes(self) -> dict:
        """The store's own word for what it did, counted."""
        out: dict[str, int] = {}
        for one in self.actions:
            if one.outcome:
                out[one.outcome] = out.get(one.outcome, 0) + 1
        return dict(sorted(out.items()))

    def pushed(self) -> dict:
        """Whether a commit reached the remote.

        Read from the co-editing socket's `saved` frame, which is the only place
        in the whole application that surfaces `WriteResult.pushed`. Every HTTP
        write route drops it, so a form writer's row here is always `unknown` —
        and that is the finding, not a gap in this harness.
        """
        out = {"true": 0, "false": 0, "unknown": 0}
        for one in self.actions:
            if one.outcome is None:
                continue
            out[{True: "true", False: "false", None: "unknown"}[one.pushed]] += 1
        return out

    def writes(self) -> list[Action]:
        return [one for one in self.actions if one.outcome is not None or one.marker is not None]

    def throughput(self, seconds: float) -> dict:
        if seconds <= 0:
            return {}
        accepted = sum(
            1
            for one in self.actions
            if one.outcome in ("committed", "merged", "retried") or one.status == "saved"
        )
        pages = sum(1 for one in self.actions if one.kind.startswith("GET "))
        return {
            "seconds": round(seconds, 1),
            "accepted_writes_per_second": round(accepted / seconds, 2),
            "pages_per_second": round(pages / seconds, 2),
        }

    def report(self, seconds: float) -> dict:
        return {
            "latency_ms": self.by_kind(),
            "statuses": self.statuses(),
            "errors": self.errors(),
            "write_outcomes": self.outcomes(),
            "pushed": self.pushed(),
            "throughput": self.throughput(seconds),
        }

    def rows(self) -> list[dict]:
        return [asdict(one) for one in self.actions]


def table(report: dict) -> str:
    """The latency block as something a person reads without a JSON viewer."""
    lines = [f"{'action':<26}{'n':>6}{'p50':>9}{'p90':>9}{'p99':>9}{'max':>9}"]
    for kind, stats in report["latency_ms"].items():
        if not stats.get("n"):
            continue
        lines.append(
            f"{kind:<26}{stats['n']:>6}{stats['p50']:>9.1f}{stats['p90']:>9.1f}"
            f"{stats['p99']:>9.1f}{stats['max']:>9.1f}"
        )
    return "\n".join(lines)
