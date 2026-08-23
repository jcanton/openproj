"""Is the 600 ms index build a cost per commit, or a cost per process?

Every one of the six scenarios quotes it as the first. `read-load` measured
588-624 ms on 561 records and built its headline finding on it — twenty readers
arriving on a cold instance each pay it, 10.35 s apiece, because `index_now()`
has no lock and N concurrent misses are N builds. `write-*` and `adversarial`
both price a write's cost to readers as "an index rebuild".

They all measured the same thing: the FIRST build in a fresh server process. That
is the only build a probe sees if it starts a server, sends one request and reads
the clock, and it is the only build `read-load`'s cold-start block contains.

The number underneath it is different, and it changes which fix is the right one.
`web._read_records` holds `_PARSED`, a process-global cache keyed by (blob id,
path) and NOT by commit, so a second build at any commit re-parses only the files
whose bytes changed. This times three builds in one process: the first, three
more at the same commit, and three more each after one record has been written.

Nothing here is load. One process, no server, no sockets — the question is about
a cache, and a cache is answered in the process that holds it.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import time
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(HERE))

import corpus  # noqa: E402

from openproj.index import build_index  # noqa: E402
from openproj.store import Store  # noqa: E402
from openproj.web import _config_at, _records_at  # noqa: E402

DRAWN = date(2026, 8, 17)


def main() -> None:
    work = Path(tempfile.mkdtemp(prefix="openproj-warm-"))
    try:
        plan = work / "plan.git"
        corpus.build(plan, 40, 10, 60, 60)
        store = Store(plan)

        def build(commit: str):
            config, unreadable_config = _config_at(store, commit)
            records, unreadable_records = _records_at(store, commit)
            return build_index(
                records,
                config,
                DRAWN,
                unreadable=sorted(
                    [*unreadable_config, *unreadable_records], key=lambda one: one.path
                ),
            )

        def ms(commit: str) -> float:
            start = time.perf_counter()
            index = build(commit)
            elapsed = (time.perf_counter() - start) * 1000
            assert index.records
            return round(elapsed, 1)

        head = store.head()
        rows: dict = {"records": len(build(head).records)}
        # Rebuilt in a fresh process for the first row, because that is the row
        # every other probe in this directory measured.
        rows["first_build_in_a_fresh_process_ms"] = None
        rows["same_commit_again_ms"] = [ms(head) for _ in range(3)]

        after = []
        path = next(p for p in store.paths(head) if p.startswith("tasks/"))
        for attempt in range(3):
            text = store.read(head, path) or ""
            store.write(
                path=path,
                content=text + f"\nan edit {attempt}\n",
                base_commit=store.head(),
                author="jcanton",
                message="probe",
            )
            head = store.head()
            after.append(ms(head))
        rows["after_one_record_changed_ms"] = after
        print(json.dumps(rows, indent=1))
        return rows
    finally:
        shutil.rmtree(work, ignore_errors=True)


def cold() -> float:
    """The first build in this process, timed before anything else touches it."""
    work = Path(tempfile.mkdtemp(prefix="openproj-warm-"))
    try:
        plan = work / "plan.git"
        corpus.build(plan, 40, 10, 60, 60)
        store = Store(plan)
        commit = store.head()
        start = time.perf_counter()
        config, unreadable_config = _config_at(store, commit)
        records, unreadable_records = _records_at(store, commit)
        build_index(
            records,
            config,
            DRAWN,
            unreadable=sorted([*unreadable_config, *unreadable_records], key=lambda o: o.path),
        )
        return round((time.perf_counter() - start) * 1000, 1)
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    first = cold()
    rows = main()
    rows["first_build_in_a_fresh_process_ms"] = first
    out = ROOT / "docs/probes/load/index-warm.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"probe": "index-warm", **rows}, indent=1) + "\n")
    print(json.dumps(rows, indent=1))
    print(f"wrote {out}")
