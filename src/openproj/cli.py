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

    render = commands.add_parser("render", help="write the static pages")
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
    """Every file that is not a record, then every problem, then the count.

    The files come first and are counted as blockers because they are the worst
    thing this command can find: a record that is wrong is on screen with a note
    beside it, and a file that will not parse is not in the plan at all. It used
    to raise on the first one — a traceback instead of a report, and no word
    about the second bad file until the first was fixed — which is the same
    failure as "0 blockers, 0 warnings" on a plan that answered 500 everywhere.
    """
    entities, config, unreadable = load_repo(repo)
    for one in unreadable:
        print(f"blocker: {one.path}: this file is not a record, so nothing in it is in the plan: "
              f"{one.why}")
    problems = sorted(
        validate_all(entities, config), key=lambda p: (p.severity, p.entity_id, p.field or "")
    )
    for problem in problems:
        print(f"{problem.severity}: {problem.entity_id}: {problem.field}: {problem.message}")
    blockers = [p for p in problems if p.severity == "blocker"]
    print(f"{len(blockers) + len(unreadable)} blockers, {len(problems) - len(blockers)} warnings")
    return 1 if blockers or unreadable else 0


def _render(repo: Path, out_dir: Path, today: date | None) -> int:
    from .render import render_static

    entities, config, unreadable = load_repo(repo)
    written = render_static(
        build_index(entities, config, today or date.today(), unreadable), out_dir, repo
    )
    print(f"wrote {', '.join(written)} to {out_dir}")
    # Said here as well as drawn on the pages: a build log is where somebody
    # notices, and a static export of a plan missing three of its files that
    # announces only success is how it ships.
    for one in unreadable:
        print(f"left out {one.path}: {one.why}")
    return 0


def _serve(args) -> int:
    """Run the server against a plan repository.

    Secrets come from the environment, never from the command line: an argument is
    visible in `ps` to every other process on the machine, and shell history keeps
    it long after the process is gone.
    """

    from .github import GitHubApp
    from .web import create_app

    app = create_app(
        args.repo,
        auth=args.auth,
        org=args.org,
        secret=os.environ.get("OPENPROJ_SECRET", "dev-secret"),
        client_id=os.environ.get("OPENPROJ_CLIENT_ID", ""),
        client_secret=os.environ.get("OPENPROJ_CLIENT_SECRET", ""),
        # A remote and its credential both come from the environment, so a
        # development run needs neither and a deployment sets both or is refused.
        remote=os.environ.get("OPENPROJ_REMOTE", ""),
        credentials=GitHubApp.from_environment(dict(os.environ)),
    )
    return _exit_aware_server(app, args.host, args.port).run() or 0


def _exit_aware_server(app, host: str, port: int):
    """A uvicorn server that tells the app a shutdown has begun.

    uvicorn waits for in-flight requests and only then runs lifespan shutdown, so
    an event stream — a request that never ends by design — held Ctrl-C until the
    graceful timeout expired and then died to a forced cancel. Installing a signal
    handler from the app does not work either: uvicorn installs its own afterwards
    and replaces it. This hook fires the moment the signal arrives, so the streams
    close themselves while uvicorn is still politely waiting for them.
    """
    import uvicorn

    class Server(uvicorn.Server):
        def handle_exit(self, sig: int, frame: object) -> None:
            app.state.closing.set()
            super().handle_exit(sig, frame)

    # `proxy_headers=True` on its own does nothing behind Cloud Run, which is the
    # trap: it reads as "we handle a proxy" and the setting that decides whether
    # the headers are believed is a different one, defaulted elsewhere.
    #
    # uvicorn only trusts `X-Forwarded-Proto` from `forwarded_allow_ips`, which
    # defaults to 127.0.0.1. Cloud Run's frontend arrives from 169.254.169.126,
    # so the header was dropped and every request looked like plain HTTP on a
    # service reachable only over TLS. Two things then broke quietly:
    # `request.url_for` built `http://…/auth/callback`, which GitHub refuses with
    # "The redirect_uri is not associated with this application" — naming the
    # OAuth App, which was configured correctly — and `secure_for` answered False,
    # so a session cookie on a TLS-only service would have been issued without
    # `Secure`.
    #
    # Not hardcoded to "*": trusting a forwarded scheme from anyone lets a client
    # on a plain-HTTP run claim https. `OPENPROJ_FORWARDED_ALLOW_IPS` is set by
    # `deploy/boot.py` when Cloud Run's own `K_SERVICE` says where it is, and a
    # local run keeps uvicorn's careful default.
    return Server(
        uvicorn.Config(
            app,
            host=host,
            port=port,
            proxy_headers=True,
            forwarded_allow_ips=os.environ.get("OPENPROJ_FORWARDED_ALLOW_IPS", "127.0.0.1"),
            timeout_graceful_shutdown=10,
        )
    )


def _schedule(repo: Path, as_json: bool, today: date | None) -> int:
    entities, config, unreadable = load_repo(repo)
    when = today or date.today()
    index = build_index(entities, config, when, unreadable)
    for one in unreadable:
        # To stderr, so `--json` stays a document a script can pipe while the
        # person watching still finds out the plan was read short.
        print(f"left out {one.path}: {one.why}", file=sys.stderr)
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
