"""Where do the 250 milliseconds of `GET /detail/<id>` actually go?

`read-load` measured the record page at **251 ms warm** and then explained it:
*"the reason is visible in the byte counts: `render.py` inlines the Ace 1.44
bundle into the page … 594 KB of JavaScript"*. `adversarial` took the number
forward — 369 detail requests × 251 ms ≈ 82% of everything the server did — and
made "cache or trim `render_detail`" its fourth recommendation.

The explanation does not survive the same file's other rows. `/graph` is
**2.69 MB served in 36.5 ms** and `/table` is **1.03 MB in 44.5 ms**; `/detail`
is 1.23 MB in 251 ms. Per byte the record page is fifteen times slower than the
graph, so whatever costs 250 ms it is not the production of bytes, and a 594 KB
constant concatenated into a template is the cheapest 594 KB in the app.

So this asks the question in the place the answer lives: the same index, the same
`render_detail`, three editors, and a profiler. Two numbers decide it —
`?editor=plain` against the default, which is what removing Ace from the page
would buy, and the profile, which says what is left.

In process and with no server, because the claim is about a pure function.
Nothing here is load: it is four renders and one profile of a fifth.
"""

from __future__ import annotations

import cProfile
import io
import json
import pstats
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

from openproj import render  # noqa: E402
from openproj.index import build_index  # noqa: E402
from openproj.store import Store  # noqa: E402
from openproj.web import _config_at, _records_at  # noqa: E402

DRAWN = date(2026, 8, 17)


def index_at(store: Store, commit: str):
    """`web._build_index_at`, through the same two helpers it calls.

    Spelled by importing them rather than by writing the reads out again: a
    second copy of the index build is a probe that can measure something the
    server does not do, which is the failure mode this directory has already
    had twice.
    """
    config, unreadable_config = _config_at(store, commit)
    records, unreadable_records = _records_at(store, commit)
    return build_index(
        records,
        config,
        DRAWN,
        unreadable=sorted([*unreadable_config, *unreadable_records], key=lambda one: one.path),
    )


def timed(what, repeats: int = 3) -> tuple[float, int]:
    best = None
    size = 0
    for _ in range(repeats):
        start = time.perf_counter()
        out = what()
        elapsed = (time.perf_counter() - start) * 1000
        size = len(out)
        best = elapsed if best is None else min(best, elapsed)
    return round(best, 1), size


def main() -> None:
    work = Path(tempfile.mkdtemp(prefix="openproj-detail-"))
    try:
        plan = work / "plan.git"
        corpus.build(plan, pitches=40, tasks_each=10, notes=60, issues=60)
        store = Store(plan)
        commit = store.head()
        start = time.perf_counter()
        index = index_at(store, commit)
        build_ms = round((time.perf_counter() - start) * 1000, 1)
        record = sorted(rid for rid in index.records if rid.startswith("task-"))[0]

        def detail(editor: str, may_write: bool = True) -> str:
            return render.render_detail(
                index,
                render.ROUTES,
                only=record,
                base_commit=commit,
                may_write=may_write,
                editor=editor,
                signed_in="jcanton" if may_write else "",
            )

        rows = {
            "index_build_ms": build_ms,
            "record_count": len(index.records),
            # The line the profile points at. `render_detail` builds a row for
            # EVERY record — markdown and all — and only then keeps the one the
            # URL asked for.
            "detail_rows_for_every_record_ms": timed(
                lambda: render._detail_rows(index, render.ROUTES)
            )[0],
            "detail_default_editor": timed(lambda: detail("")),
            "detail_ace": timed(lambda: detail(render.ACE)),
            "detail_plain": timed(lambda: detail(render.PLAIN)),
            "detail_read_only": timed(lambda: detail("", may_write=False)),
            "graph": timed(lambda: render.render_graph(index, render.ROUTES)),
            "table": timed(lambda: render.render_table(index, render.ROUTES)),
            "records": timed(lambda: render.render_records(index, render.ROUTES)),
        }
        rows["records_count"] = len(index.records)

        # The same page against a plan an eighth the size, because "O(the plan)"
        # is a claim about a slope and one point is not one.
        small = work / "small.git"
        corpus.build(small, pitches=8, tasks_each=3, notes=4, issues=4)
        small_store = Store(small)
        small_commit = small_store.head()
        small_index = index_at(small_store, small_commit)
        small_record = sorted(r for r in small_index.records if r.startswith("task-"))[0]
        rows["small_record_count"] = len(small_index.records)
        rows["small_detail_ms"] = timed(
            lambda: render.render_detail(
                small_index,
                render.ROUTES,
                only=small_record,
                base_commit=small_commit,
                may_write=True,
                editor="",
                signed_in="jcanton",
            )
        )

        profile = cProfile.Profile()
        profile.enable()
        for _ in range(5):
            detail("")
        profile.disable()
        stream = io.StringIO()
        pstats.Stats(profile, stream=stream).sort_stats("tottime").print_stats(18)
        rows["profile_tottime_top"] = stream.getvalue()

        print(json.dumps({k: v for k, v in rows.items() if k != "profile_tottime_top"}, indent=1))
        print(rows["profile_tottime_top"])
        out = ROOT / "design/probes/load/detail-cost.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"probe": "detail-cost", **rows}, indent=1) + "\n")
        print(f"wrote {out}")
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
