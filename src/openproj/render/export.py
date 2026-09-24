"""The static export: every page this plan has, written to a directory."""

from __future__ import annotations

import shutil
from functools import partial
from pathlib import Path

from ..index import Index
from .cycles import render_cycles, render_people
from .detail import render_detail
from .graph import render_graph
from .help import render_help
from .records import render_records
from .shell import STATIC, links_for
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

    A view the plan has switched off is neither written nor linked: every page is
    drawn with `links_for(index.views, STATIC)`, and a file is written only where
    that nav names it. It asks `links.nav` and not `index.views` because the nav is
    what every written page links to, so which files exist and which files are
    linked are one answer rather than two that could disagree — `deck` is a view
    and has no file here at all.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    # Both directories, and by name rather than by "every directory here": the
    # export writes into a place a person chose, and copying whatever happened
    # to be beside the plan is not the same promise.
    for named in ("assets", "drawings"):
        source = (repo / named) if repo else None
        if source and source.is_dir():
            shutil.copytree(source, out_dir / named, dirs_exist_ok=True)
    links = links_for(index.views, STATIC)
    landing = partial(render_records, index, links, edited=edited, now=now)
    written: list[str] = []
    # The file, the nav item it is — None for the two that are in no nav and that no
    # setting switches off — and how to draw it. Drawn only once it is known to be
    # written: a page that is off is not rendered to be thrown away.
    for name, item, draw in (
        ("index.html", "records", landing),
        ("table.html", "table", partial(render_table, index, links)),
        ("detail.html", None, partial(render_detail, index, links)),
        ("people.html", "people", partial(render_people, index, links)),
        ("cycles.html", "cycles", partial(render_cycles, index, links)),
        ("graph.html", "graph", partial(render_graph, index, links)),
        ("timeline.html", "timeline", partial(render_timeline, index, links)),
        # The two inbox views of the landing, because the nav names them wherever
        # they are on: a nav link into a file nobody wrote is a dead link on all
        # the others.
        ("issues.html", "issues", partial(landing, only="issue")),
        ("notes.html", "notes", partial(landing, only="note")),
        # The documentation, for the same reason the two inboxes are here: every
        # exported page's footer names it. It is also the one page in this list that
        # is not about the plan — an export is what a reader has left when the
        # service is gone, and instructions are the thing they will want first.
        ("help.html", None, partial(render_help, index, links)),
    ):
        if item is not None and item not in links.nav:
            continue
        (out_dir / name).write_text(draw(), encoding="utf-8")
        written.append(name)
    return tuple(written)
