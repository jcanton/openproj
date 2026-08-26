"""The static export: every page written to a directory."""

from __future__ import annotations

import shutil
from pathlib import Path

from ..index import Index
from .cycles import render_cycles, render_people
from .detail import render_detail
from .graph import render_graph
from .records import render_records
from .table import render_table
from .timeline import render_timeline


def render_static(
    index: Index,
    out_dir: Path,
    repo: Path | None = None,
    edited: dict[str, int] | None = None,
    now: int = 0,
) -> tuple[str, ...]:
    """The pages, and the images they name. Returns what it wrote, in order.

    Without the copy an exported plan renders every uploaded figure or drawing
    as a broken image — the markdown points at `assets/…` or `drawings/…`
    relative to the page, which is exactly right and exactly useless if the
    directory is not there.

    The names come back rather than being restated by the caller, because they
    already were: the export grew from three pages to six and the CLI went on
    announcing "index.html, graph.html and timeline.html" to somebody who had
    just been handed six files.

    `edited` and `now` feed the landing's time column and come from the caller
    (`cli._render`), which is the one that knows whether the directory it was
    pointed at is a repository at all — None omits the column.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    # Both directories, and by name rather than by "every directory here": the
    # export writes into a place a person chose, and copying whatever happened
    # to be beside the plan is not the same promise.
    for named in ("assets", "drawings"):
        source = (repo / named) if repo else None
        if source and source.is_dir():
            shutil.copytree(source, out_dir / named, dirs_exist_ok=True)
    written: list[str] = []
    for name, html in (
        ("index.html", render_records(index, edited=edited, now=now)),
        ("table.html", render_table(index)),
        ("detail.html", render_detail(index)),
        ("people.html", render_people(index)),
        ("cycles.html", render_cycles(index)),
        ("graph.html", render_graph(index)),
        ("timeline.html", render_timeline(index)),
        # The two inbox views of the landing, because every exported page's nav
        # names them: a nav link into a file nobody wrote is a dead link on
        # all the others.
        ("issues.html", render_records(index, edited=edited, now=now, only="issue")),
        ("notes.html", render_records(index, edited=edited, now=now, only="note")),
    ):
        (out_dir / name).write_text(html, encoding="utf-8")
        written.append(name)
    return tuple(written)
