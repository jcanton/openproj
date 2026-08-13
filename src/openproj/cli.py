"""`openproj check`, `openproj render`, `openproj schedule`.

The CLI can do everything the web view can. That is deliberate: if the service is
down, being upgraded, or never comes back, the plan is still readable and still
checkable with one command against a clone.

`check` is the load-bearing one. It exits non-zero on blockers and zero on
warnings, because a warning that fails the build is a rule that gets reverted
rather than adopted.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

from .index import build_index
from .model import load_repo, validate_all


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="openproj", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)

    check = commands.add_parser("check", help="validate a plan repository")
    check.add_argument("repo", type=Path)

    render = commands.add_parser("render", help="write the three static pages")
    render.add_argument("repo", type=Path)
    render.add_argument("out_dir", type=Path)
    render.add_argument("--today", type=date.fromisoformat, default=None)

    serve = commands.add_parser("serve", help="run the editable server")
    serve.add_argument("--repo", type=Path, required=True, help="a bare clone of the plan repo")
    serve.add_argument("--auth", choices=("dev", "github"), default="dev")
    serve.add_argument("--org", default="C2SM")
    # Cloud Run sets PORT and requires 0.0.0.0 — "notably not 127.0.0.1". Local
    # runs keep the loopback default, so a development server is not quietly
    # listening to the network.
    serve.add_argument("--host", default=os.environ.get("OPENPROJ_HOST", "127.0.0.1"))
    serve.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8000)))

    schedule = commands.add_parser("schedule", help="print the computed schedule")
    schedule.add_argument("repo", type=Path)
    schedule.add_argument("--json", action="store_true")
    schedule.add_argument("--today", type=date.fromisoformat, default=None)
    return parser


def _check(repo: Path) -> int:
    entities, config = load_repo(repo)
    problems = sorted(
        validate_all(entities, config), key=lambda p: (p.severity, p.entity_id, p.field or "")
    )
    for problem in problems:
        print(f"{problem.severity}: {problem.entity_id}: {problem.field}: {problem.message}")
    blockers = [p for p in problems if p.severity == "blocker"]
    print(f"{len(blockers)} blockers, {len(problems) - len(blockers)} warnings")
    return 1 if blockers else 0


def _render(repo: Path, out_dir: Path, today: date | None) -> int:
    from .render import render_static

    entities, config = load_repo(repo)
    render_static(build_index(entities, config, today or date.today()), out_dir)
    print(f"wrote index.html, graph.html and timeline.html to {out_dir}")
    return 0


def _serve(args) -> int:
    """Run the server against a plan repository.

    Secrets come from the environment, never from the command line: an argument is
    visible in `ps` to every other process on the machine, and shell history keeps
    it long after the process is gone.
    """
    import uvicorn

    from .web import create_app

    app = create_app(
        args.repo,
        auth=args.auth,
        org=args.org,
        secret=os.environ.get("OPENPROJ_SECRET", "dev-secret"),
        client_id=os.environ.get("OPENPROJ_CLIENT_ID", ""),
        client_secret=os.environ.get("OPENPROJ_CLIENT_SECRET", ""),
    )
    # proxy_headers matters behind Cloud Run: TLS is terminated upstream, and
    # without it the app believes it is serving plain HTTP and stops marking the
    # session cookie Secure.
    # A bounded graceful shutdown as the backstop: a client that ignores the
    # stream ending must not keep Ctrl-C waiting forever.
    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        proxy_headers=True,
        timeout_graceful_shutdown=5,
    )
    return 0


def _schedule(repo: Path, as_json: bool, today: date | None) -> int:
    entities, config = load_repo(repo)
    when = today or date.today()
    index = build_index(entities, config, when)
    if as_json:
        print(
            json.dumps(
                {
                    "today": when.isoformat(),
                    "entities": sorted(index.entities),
                    "spans": {i: json.loads(s.model_dump_json()) for i, s in index.spans.items()},
                    "explanations": {
                        i: e.text for i, e in sorted(index.explanations.items())
                    },
                },
                indent=1,
            )
        )
        return 0
    for entity_id in sorted(index.spans, key=lambda i: (index.spans[i].start, i)):
        span = index.spans[entity_id]
        note = index.explanations.get(entity_id)
        print(f"{span.start}  {span.end}  {entity_id:16}  {note.text if note else ''}")
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
    except SystemExit as exit_code:  # argparse exits 2 on a bad command line
        return int(exit_code.code or 2)
    if args.command == "check":
        return _check(args.repo)
    if args.command == "render":
        return _render(args.repo, args.out_dir, args.today)
    if args.command == "serve":
        return _serve(args)
    return _schedule(args.repo, args.json, args.today)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
