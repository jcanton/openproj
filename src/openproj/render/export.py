"""The static export: every page this plan has, written to a directory."""

from __future__ import annotations

import shutil
from functools import partial
from pathlib import Path

from ..index import Index
from ..model import reachable
from .cycles import render_cycles, render_people
from .detail import render_detail
from .graph import render_graph
from .help import render_help
from .records import render_records
from .shell import STATIC, links_for, opened
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

    The export is the server's answer written to disk, so a view the plan does
    not list is written and not linked, exactly as the server answers its address
    and links nowhere to it (`model.reachable`, `render.opened`): every page is
    drawn with `links_for(index.views, STATIC)`, and an unlisted view's own file
    with its own links put back. Only the Issues and Notes lists of a kind the
    plan has turned off are not written, because there they do not exist. `deck`
    is a view and has no file here at all.

    **And a file of a list that does not exist is removed**, if an earlier export
    into the same directory wrote it — a plan that turns `issue` off and is
    exported into the `out/` the README names would otherwise leave last run's
    `issues.html` there, drawing the old plan, for any bookmark or publish of the
    directory. Only the names in the table and never a glob: this is a directory
    somebody chose, and the export owns its own ten files in it and nothing else.
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
    landing = partial(render_records, index, edited=edited, now=now)
    written: list[str] = []
    # The file, the view it is — None for the three that are no view and that no
    # setting reaches — and how to draw it, given the links its own page is drawn
    # with. Drawn only once it is known to be written: a page that does not exist
    # is not rendered to be thrown away.
    for name, item, draw in (
        ("index.html", None, landing),
        ("table.html", "table", partial(render_table, index)),
        ("detail.html", None, partial(render_detail, index)),
        ("people.html", "people", partial(render_people, index)),
        ("cycles.html", "cycles", partial(render_cycles, index)),
        ("graph.html", "graph", partial(render_graph, index)),
        ("timeline.html", "timeline", partial(render_timeline, index)),
        # The two inbox views of the landing, which exist exactly when their kind
        # does: a file of a list of nothing would be one the nav cannot name.
        ("issues.html", "issues", partial(landing, only="issue")),
        ("notes.html", "notes", partial(landing, only="note")),
        # The documentation, because every exported page's footer names it. It is
        # also the one page in this list that is not about the plan — an export is
        # what a reader has left when the service is gone, and instructions are the
        # thing they will want first.
        ("help.html", None, partial(render_help, index)),
    ):
        if item is not None and not reachable(item, index.kinds):
            (out_dir / name).unlink(missing_ok=True)
            continue
        own = opened(links, STATIC, item) if item is not None else links
        (out_dir / name).write_text(draw(own), encoding="utf-8")
        written.append(name)
    return tuple(written)
