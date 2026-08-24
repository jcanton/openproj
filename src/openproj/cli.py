"""`openproj check`, `openproj render`, `openproj schedule`, `openproj demo`.

The CLI can do everything the web view can. That is deliberate: if the service is
down, being upgraded, or never comes back, the plan is still readable and still
checkable with one command against a clone.

`check` is the load-bearing one. It exits non-zero on blockers and zero on
warnings, because a warning that fails the build is a rule that gets reverted
rather than adopted.

`demo` is the one somebody runs first. `serve` wants a bare clone of a plan
repository, which is the right seam for a deployment and the wrong first
instruction for a person who has just run `uv sync` — the README used to answer
it with `serve --repo seed`, which pointed the server at a directory that is not
a repository, and the command was deleted rather than fixed. `demo` is the fix:
one command, no network, and a plan repository it builds for itself.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import socket
import sys
import tempfile
import time
from datetime import date
from pathlib import Path

from .index import build_index
from .model import Config, edited_by_id, load_repo, validate_all


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

    demo = commands.add_parser("demo", help="serve the bundled demo corpus, offline")
    demo.add_argument(
        "--today",
        type=date.fromisoformat,
        default=None,
        help="the day to draw the plan around (default: the demo corpus's own)",
    )
    demo.add_argument(
        "--as",
        dest="signed_in",
        default=None,
        help="the login to be signed in as (default: the first name on the demo's roster)",
    )
    demo.add_argument("--host", default="127.0.0.1")
    demo.add_argument("--port", type=int, default=8000)

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
    records, config, unreadable = load_repo(repo)
    for one in unreadable:
        print(f"blocker: {one.path}: this file is not a record, so nothing in it is in the plan: "
              f"{one.why}")
    problems = sorted(
        validate_all(records, config), key=lambda p: (p.severity, p.record_id, p.field or "")
    )
    for problem in problems:
        print(f"{problem.severity}: {problem.record_id}: {problem.field}: {problem.message}")
    blockers = [p for p in problems if p.severity == "blocker"]
    print(f"{len(blockers) + len(unreadable)} blockers, {len(problems) - len(blockers)} warnings")
    return 1 if blockers or unreadable else 0


def _render(repo: Path, out_dir: Path, today: date | None) -> int:
    from .render import render_static
    from .store import last_edited_in

    records, config, unreadable = load_repo(repo)
    # Walk when the directory is a repository; otherwise the landing renders
    # WITHOUT the time column — omitted, not blank, because blank looks broken
    # and file mtimes lie after a fresh clone.
    stamps = last_edited_in(repo)
    written = render_static(
        build_index(records, config, today or date.today(), unreadable),
        out_dir,
        repo,
        edited=edited_by_id(stamps) if stamps is not None else None,
        now=int(time.time()),
    )
    print(f"wrote {', '.join(written)} to {out_dir}")
    # Said here as well as drawn on the pages: a build log is where somebody
    # notices, and a static export of a plan missing three of its files that
    # announces only success is how it ships.
    for one in unreadable:
        print(f"left out {one.path}: {one.why}")
    return 0


def _seed_dir() -> Path:
    """Where the bundled demo corpus lives.

    The same shape as `render._static_dir` and for the same reason: `seed/` is
    not in the wheel, so an installed layout resolves `parents[2]` past
    site-packages to a directory that is not there. Said rather than crashed, and
    said with what to do about it.
    """
    for candidate in (
        Path(__file__).resolve().parents[2] / "seed",
        Path(__file__).resolve().parent / "seed",
    ):
        if candidate.is_dir():
            return candidate
    raise RuntimeError(
        "the bundled seed/ corpus is missing. It is part of the source tree and not of "
        "the wheel, so `openproj demo` runs from a checkout; against a real plan the "
        "command is `openproj serve --repo <bare clone>`."
    )


def _seed_files(seed: Path) -> dict[str, str]:
    """The seed, as the files a plan repository is made of.

    Two things are left out on purpose.

    `store.LOCK_FILE` is the writer's flock. It holds the pid of whoever last
    opened a `Store` against the directory, and it was committed to this
    repository once — so a copy of `seed/` handed a fresh server a lock file
    naming a process that had been dead for months, and the second run of the
    demo would have inherited the first run's pid. It is deleted from git in the
    same commit as this, and skipped here as well, because a checkout that has
    run a server against `seed/` will have made another one.

    And anything that is not markdown or YAML, which is what a plan repository
    holds. A `.DS_Store` beside the records is not part of anybody's plan, and it
    is not UTF-8 either — so a rule of "every file under here" would have made
    `openproj demo` fail on a Mac that had once opened the folder in Finder.
    """
    from .store import LOCK_FILE

    return {
        found.relative_to(seed).as_posix(): found.read_text(encoding="utf-8")
        for found in sorted(seed.rglob("*"))
        if found.is_file() and found.name != LOCK_FILE and found.suffix in (".md", ".yaml")
    }


def _demo_today(config: Config) -> date | None:
    """The day the demo corpus is written around: the first day of the last cycle
    it plans.

    Derived and not typed in. That date is already written down four times in
    `seed/` — the cycles table, a comment above it, cycle 37's own record, and a
    sentence of prose in `seed/README.md` — and one more copy in here would be
    the one that goes stale the day somebody adds cycle 38. Asked of the corpus,
    the demo's "today" moves with the corpus, which is what "today" means to it.

    `None` for a plan with no cycles at all, which is every plan on its first
    day; the caller falls back to the real one.
    """
    return config.cycles[max(config.cycles)][0] if config.cycles else None


def _taken(host: str, port: int) -> bool:
    """Whether something else is already listening there.

    Asked before the repository is built and before the URL is printed, and not
    left to uvicorn: uvicorn discovers it at the end, after this command has
    already told somebody to open a link — which by then belongs to whatever else
    is on that port. A wrong URL on screen is worse than a refusal, because it is
    a refusal you go looking for in the wrong place.

    Through `getaddrinfo` rather than a bare `socket()`, which is AF_INET: a
    `--host ::1` bound on an IPv4 socket raises the same OSError a busy port
    does, and this would have answered "already in use" about a port nothing was
    on. The probe has to be the socket uvicorn is going to open.
    """
    family, kind, proto, _, address = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)[0]
    with socket.socket(family, kind, proto) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(address)
        except OSError:
            return True
    return False


def _demo(args) -> int:
    """The demo corpus, in a throwaway repository, served offline.

    **A fresh directory every run, and it goes when the server does.** The
    alternative — a stable path under the cache directory, reused — was rejected
    twice over. A demo that keeps yesterday's edits is not the demo any more and
    nothing on screen says which parts are the corpus and which are yours; two
    runs at once would fight over one writer lock; and the durable copy would be
    a repository nobody backs up. So: built from `seed/` each time, and the
    banner says it is going, so that everything in here is safe to press.

    **Nothing here can lose anybody's work.** The temporary directory is the only
    thing written to. `seed/` is read; no remote is configured, so the server has
    nowhere to push; and a plan of your own is not reachable from this command at
    all — that is `serve --repo`, which is where a real repository belongs.
    """
    from .store import build_plan_repository
    from .web import create_app

    if _taken(args.host, args.port):
        print(
            f"port {args.port} is already in use on {args.host}. Stop what is there, "
            f"or run `openproj demo --port {args.port + 1}`.",
            file=sys.stderr,
        )
        return 1

    seed = _seed_dir()
    _, config, _ = load_repo(seed)
    when = args.today or _demo_today(config)
    # The first name on the plan's own roster, so the picker on the People page
    # has a row to hang off. `dev` is nobody in any corpus.
    signed_in = args.signed_in or (config.known_people[0] if config.known_people else "dev")

    with tempfile.TemporaryDirectory(prefix="openproj-demo-") as room:
        repo = Path(room) / "plan.git"
        build_plan_repository(repo, _seed_files(seed), f"the {seed.name}/ corpus, for a demo")
        app = create_app(
            repo,
            auth="dev",
            org="C2SM",
            # A signing secret of its own, thrown away with the directory. The
            # default is `dev-secret`, and a cookie is scoped to a HOST and not to
            # a port — so a session left in the browser by any other openproj on
            # 127.0.0.1 verified here and signed you in as somebody else. The
            # banner below then said "you are ann" while the page believed
            # otherwise, and on a corpus where that name holds nothing the People
            # page quietly had no picker on it. Nothing signs in on a demo, so
            # there is no session this needs to be able to read.
            secret=secrets.token_urlsafe(32),
            dev_login=signed_in,
            today=when,
        )
        # Same rule as `_serve`: startup owns the first walk and the first index.
        # On a demo corpus both are microseconds, so they earn no log line.
        app.state.warm_edited()
        app.state.warm_index()
        # One write and flushed, because stdout is a pipe as often as it is a
        # terminal and Python buffers it when it is. uvicorn logs to stderr, which
        # is not buffered — so unflushed, the four lines that say what this is
        # arrived after the server had already started and printed over them, and
        # the URL a person is meant to open was the last thing on screen at exit.
        print(
            f"plan     {repo}\n"
            f"         a fresh copy of the bundled seed/ corpus, and deleted when this\n"
            f"         stops. Nothing here reaches seed/ itself, or a plan of your own.\n"
            f"today    {when}, which is the corpus's own — --today moves it\n"
            f"you are  {signed_in}, and may write; --auth dev, so nothing asks you to sign in\n"
            f"\n"
            f"         http://{args.host}:{args.port}/\n",
            flush=True,
        )
        return _exit_aware_server(app, args.host, args.port).run() or 0


def _serve(args) -> int:
    """Run the server against a plan repository.

    Secrets come from the environment, never from the command line: an argument is
    visible in `ps` to every other process on the machine, and shell history keeps
    it long after the process is gone.
    """

    from .github import GitHubApp
    from .web import create_app

    credentials = GitHubApp.from_environment(dict(os.environ))
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
        credentials=credentials,
    )
    # The push credential, minted before uvicorn binds, for the same reason as
    # the two warms below: work that every cold instance has to do once should
    # not be done inside somebody's save.
    #
    # `GitHubApp.token` caches until five minutes before the hour is out, so this
    # costs nothing after the first call — but the first call is one HTTPS round
    # trip to api.github.com plus the first import of `cryptography`, measured at
    # 150 to 400 ms, and `--min-instances 0` means a cold instance is the normal
    # case rather than the rare one. The whole of a save is 1.5 to 2 seconds and
    # nearly all of it is GitHub's receive-pack; this is the one part of it that
    # was ours to move, and moving it is all it took.
    #
    # Swallowed on purpose, and this is the arm to read twice: a token that
    # cannot be minted at startup is a token `_send` will try to mint again at
    # the first push, where the failure has somebody to report it to. Refusing to
    # start would turn a GitHub outage into a service that will not boot, and
    # then into a Cloud Run revision that never goes ready.
    if credentials is not None:
        begun = time.perf_counter()
        try:
            credentials.token()
            said = f"minted the push credential in {time.perf_counter() - begun:.2f}s"
        except Exception as error:  # noqa: BLE001 - reported, never fatal
            said = f"could not mint the push credential at startup ({error}); the first save will"
        print(said, file=sys.stderr, flush=True)
    # The first walk runs before uvicorn binds, so it can never ride a request.
    # Logged so the drift is visible long before it hurts: the cost grows with
    # history length (~0.5 ms per commit measured), not with the plan.
    begun = time.perf_counter()
    walked, stamps = app.state.warm_edited()
    print(
        f"walked the plan's history: {len(stamps)} paths at {walked[:7]} "
        f"in {time.perf_counter() - begun:.2f}s",
        file=sys.stderr,
        flush=True,
    )

    # The index too, and for a sharper reason than the history walk: `index_now`
    # takes no lock, so the first N requests to a cold instance each build their
    # own index instead of queueing behind one. Twenty first requests to a fresh
    # server all completed within 5 ms of each other at 10.35 SECONDS. Doing it
    # here means the herd never forms, at the cost of ~0.6 s of startup — inside
    # the window `--cpu-boost` already pays for.
    #
    # It also moves the discovery of an unparseable plan from the first request
    # to startup, which is better and is a behaviour change worth noticing.
    begun = time.perf_counter()
    app.state.warm_index()
    print(
        f"built the index in {time.perf_counter() - begun:.2f}s",
        file=sys.stderr,
        flush=True,
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
    records, config, unreadable = load_repo(repo)
    when = today or date.today()
    index = build_index(records, config, when, unreadable)
    for one in unreadable:
        # To stderr, so `--json` stays a document a script can pipe while the
        # person watching still finds out the plan was read short.
        print(f"left out {one.path}: {one.why}", file=sys.stderr)
    if as_json:
        print(
            json.dumps(
                {
                    "today": when.isoformat(),
                    "plan": sorted(index.plan),
                    "spans": {i: json.loads(s.model_dump_json()) for i, s in index.spans.items()},
                    "explanations": {
                        i: e.text for i, e in sorted(index.explanations.items())
                    },
                },
                indent=1,
            )
        )
        return 0
    for record_id in sorted(index.spans, key=lambda i: (index.spans[i].start, i)):
        span = index.spans[record_id]
        note = index.explanations.get(record_id)
        print(f"{span.start}  {span.end}  {record_id:16}  {note.text if note else ''}")
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
    if args.command == "demo":
        return _demo(args)
    return _schedule(args.repo, args.json, args.today)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
