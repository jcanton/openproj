"""`openproj` — init, check, new, render, serve, schedule and demo, against a plan repository.

The CLI can do everything the web view can. That is deliberate: if the service is
down, being upgraded, or never comes back, the plan is still readable, still
checkable, and still WRITABLE with one command against a clone.

This line is the parser's own description — `_parser` reads it — so a command
that is not on it is a command missing from `openproj --help`. `new` was, for
exactly as long as it took to run the published package once and read the output.

`check` is the load-bearing one. It exits non-zero on blockers and zero on
warnings, because a warning that fails the build is a rule that gets reverted
rather than adopted.

`new` is the other half of that: the rules `check` reports on afterwards, run at
the moment a record is written, so a record that would fail the gate never
becomes a file. It is the write path for anything without a browser — a script,
a CI job, an agent working in the codebase a plan is about.

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
from typing import get_args, get_origin

from ruamel.yaml import YAML

from .index import build_index
from .model import (
    DIRECTORY,
    MODELS,
    Config,
    _an,
    edited_by_id,
    in_model_order,
    load_repo,
    mint_id,
    opening_fields,
    parse_text,
    patch_text,
    unknown_fields,
    validate_all,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="openproj", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)

    check = commands.add_parser("check", help="validate a plan repository")
    check.add_argument("repo", type=Path)
    # The same flag `render` and `schedule` carry, and for the reason those two
    # have it: one rule now compares a stated start date against the day the plan
    # is judged around, so a plan drawn around a pinned day has to be checkable
    # around that same day. Without it `openproj check seed/` reports eleven
    # start dates as passed that `openproj demo`, which pins 2026-08-17, draws as
    # future — the tool disagreeing with itself about one corpus.
    check.add_argument("--today", type=date.fromisoformat, default=None)

    init = commands.add_parser(
        "init",
        help="start a plan repository: its configuration, committed, and nothing invented",
        description=(
            "Write the four config files a plan needs, at the newest schema version, "
            "with an empty calendar and a roster of at most one — and commit them under "
            "your git identity, so the next command is `openproj new`. At a terminal it "
            "asks for what the flags did not say; anywhere else it asks nothing."
        ),
    )
    init.add_argument("dir", type=Path, help="a directory that does not exist yet, or is empty")
    init.add_argument(
        "--org", help="the GitHub org whose members may write, for `serve --auth github`"
    )
    init.add_argument("--remote", help="the plan repository's URL; becomes `origin`")
    init.add_argument("--as", dest="author", metavar="LOGIN", help="a first name for the roster")
    init.add_argument(
        "--deploy",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="repeatable; a Cloud Run deployment described in deploy/openproj.env "
        "(the keys are those of deploy/example.env)",
    )
    init.add_argument("--no-prompt", action="store_true", help="ask nothing, even at a terminal")
    init.add_argument(
        "--no-commit", action="store_true", help="write the files and leave git alone"
    )
    init.add_argument("--json", action="store_true", help="print the path and commit as JSON")

    new = commands.add_parser(
        "new",
        help="write a new record into a plan repository",
        description=(
            "Mint a record, hold it to every rule `check` holds it to, and write "
            "it — or refuse and write nothing. The id, the directory and the "
            "body template all come off the kind, so none of them is a thing to "
            "guess from the records already there."
        ),
    )
    new.add_argument("kind", choices=sorted(DIRECTORY))
    new.add_argument("repo", type=Path)
    new.add_argument("--title", required=True)
    new.add_argument(
        "--tag",
        action="append",
        default=[],
        metavar="TAG",
        help="repeatable; sugar for --set tags=[...]",
    )
    new.add_argument(
        "--status",
        help="default: the status this kind opens in, which is the one that requires nothing",
    )
    new.add_argument(
        "--as",
        dest="author",
        metavar="LOGIN",
        help="who is filing this, for the kinds that record it (an issue's "
        "reported_by, a note's written_by). Omitted by default: this "
        "command knows a git identity and the plan is written in GitHub "
        "logins, and guessing one from the other names the wrong person.",
    )
    new.add_argument(
        "--set",
        action="append",
        default=[],
        metavar="FIELD=VALUE",
        dest="assignments",
        help="repeatable. The value is read as YAML, so 1.5 is a number, "
        "[a, b] is a list and true is a boolean; repeating a FIELD makes "
        "its values a list.",
    )
    new.add_argument(
        "--body-file",
        type=Path,
        metavar="FILE",
        help="the shaping document to use instead of this kind's template; - is stdin",
    )
    new.add_argument(
        "--commit",
        action="store_true",
        help="commit the new file, authored by your git identity. The next "
        "command is `git push` and nothing else.",
    )
    new.add_argument("--json", action="store_true", help="print the id and path as JSON")

    render = commands.add_parser("render", help="write the static pages")
    render.add_argument("repo", type=Path)
    render.add_argument("out_dir", type=Path)
    render.add_argument("--today", type=date.fromisoformat, default=None)

    serve = commands.add_parser("serve", help="run the editable server")
    serve.add_argument("--repo", type=Path, required=True, help="a bare clone of the plan repo")
    serve.add_argument("--auth", choices=("dev", "github"), default="dev")
    # No default. Membership of the org is the write permission, and a default
    # of one team's org made every other deployment that team's — silently, with
    # `--auth github` refusing everybody outside it.
    serve.add_argument(
        "--org",
        default=os.environ.get("OPENPROJ_ORG"),
        help="the GitHub org whose members may write; required with --auth github "
        "(default: OPENPROJ_ORG)",
    )
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


def _assigned(assignments: list[str]) -> dict:
    """`--set` pairs, with each value read as YAML and a repeated field made a list.

    YAML rather than a string, because half the fields on a record are not
    strings: `--set person_weeks=1.5` has to arrive as a number and
    `--set review_waived=true` as a boolean, and a caller quoting YAML into a
    shell should get the same answer the file would give. It is also the loader
    the record is about to be read back through, so a value that survives here
    and fails there is a type error the model gets to name, not a parse this
    function has to anticipate.

    `#` does not start a comment mid-token in YAML, which is what lets
    `--set prs=kilnlab/kiln4py#1359` — the exact thing somebody will type — arrive
    whole.
    """
    yaml = YAML()
    fields: dict = {}
    for pair in assignments:
        field, sep, raw = pair.partition("=")
        if not sep:
            raise ValueError(f"blocker: --set wants FIELD=VALUE, not {pair!r}")
        value = yaml.load(raw) if raw else ""
        if field in fields:
            # Repeating a field is how a list is written without shell-quoting
            # brackets. The first repeat promotes; the rest append.
            was = fields[field]
            fields[field] = [*was, value] if isinstance(was, list) else [was, value]
        else:
            fields[field] = value
    return fields


def _takes_a_list(annotation) -> bool:
    """Does this model field hold a list? True through an optional, too."""
    if get_origin(annotation) is list:
        return True
    return any(get_origin(inside) is list for inside in get_args(annotation))


def _widened_to_lists(kind: str, fields: dict) -> dict:
    """A scalar becomes a list of one wherever the model asks for a list.

    Because that is what somebody typing it means. `--set prs=kilnlab/kiln4py#1359`
    is the exact string a person writes, and a `prs` that holds a list would
    otherwise answer with a pydantic type error naming `list_type` — correct, and
    no help at all when the fix is a pair of brackets that the shell also wants
    quoting. Repeating the field already builds a list, so this is that same rule
    applied to the first one.

    This side only. The create route reaches the same fields through JSON, which
    has real lists and a `_reject_bad_types` that already refuses a scalar where
    one belongs — there is no ambiguity there to resolve, and resolving it anyway
    would quietly accept a payload that route means to refuse.

    It only ever widens, and only in the direction the model asks for; everything
    else is left exactly as the caller wrote it, for the model to accept or to
    refuse by name.
    """
    known = MODELS[kind].model_fields
    return {
        field: [value]
        if _takes_a_list(known[field].annotation) and not isinstance(value, list)
        else value
        for field, value in fields.items()
    }


def _new(args) -> int:
    """Mint a record, hold it to every rule, and write it — or write nothing.

    The order is the whole design. The file is built, parsed back, and validated
    against the plan it is about to join BEFORE anything touches the disk, so a
    record that `check` would refuse never becomes a file somebody has to `rm`
    their way out of. That is the difference between this and the recipe it
    replaces — write the file, then run `check`, then fix it — which leaves the
    repository in the state the command was run to avoid.

    Warnings are printed and do not stop it, exactly as in `check`, and that is
    the case this was written for. An agent asked to file an issue against a plan
    repository copied the schema off the three issues already in it and put a
    `prs` on one; `prs` is a real field on the model, so nothing refuses it, and
    an issue is simply never scheduled so its `prs` is never read. The rule
    existed. Nothing ran it at the moment the record was written.

    Everything that is not the caller's — the id, the directory, the body
    template, the opening status, the date, the schema version — comes off the
    kind or off the repository. Those are the six things somebody reverse-
    engineering a corpus gets wrong, and none of them is a question this command
    asks.
    """
    from .render import TEMPLATES  # jinja2 lives under here; `check` must not pay for it

    kind = args.kind
    # First, because a refusal here has to write nothing, like every other
    # refusal in this function — and because "your record is on the disk but the
    # commit you asked for did not happen" is the one outcome with no good next
    # step.
    if args.commit and (refusal := _cannot_commit_in(args.repo)) is not None:
        print(f"blocker: {refusal}")
        return 1

    records, config, _ = load_repo(args.repo)
    try:
        fields = _assigned(args.assignments)
    except ValueError as error:
        print(str(error))
        return 1

    fields["kind"] = kind
    fields["title"] = args.title
    if args.tag:
        # Added to whatever `--set tags=` said rather than over it. `--tag` is
        # documented as sugar for the same field, and sugar that silently drops
        # the thing it is sugar for is the worst of both.
        already = fields.get("tags", [])
        fields["tags"] = [*(already if isinstance(already, list) else [already]), *args.tag]
    if args.status is not None:
        fields["status"] = args.status

    # Before anything is minted: a field the model does not own would sit in the
    # frontmatter unread, and every later reader of that file would believe it
    # meant something. Not a validation problem — a typo, and the only place it
    # can be caught is here.
    unknown = unknown_fields(kind, fields)
    if unknown:
        print(f"blocker: {_an(kind)} has no {', '.join(unknown)}")
        return 1

    body = TEMPLATES.get(kind, "")
    if args.body_file is not None:
        body = (
            sys.stdin.read()
            if str(args.body_file) == "-"
            else args.body_file.read_text(encoding="utf-8")
        )

    # `taken` because this side can see the whole directory for the price of a
    # glob; the create route mints without it, having no cheap way to enumerate
    # what exists and a compare-and-swap underneath it either way.
    record_id = mint_id(kind, {path.stem for path in args.repo.glob(f"{DIRECTORY[kind]}/*.md")})
    opening = opening_fields(kind, fields, config, record_id=record_id, who=args.author)
    content = patch_text("---\n---\n", in_model_order(kind, _widened_to_lists(kind, opening)), body)

    try:
        candidate = parse_text(content, record_id)
    except ValueError as error:
        print(f"blocker: {record_id}: that would not read back as a record: {error}")
        return 1
    problems = sorted(
        (
            problem
            # The neighbours matter: a parent that does not exist, an id already
            # claimed and a dependency cycle are all facts about the plan rather
            # than about this file. Files already in the repository that will not
            # parse are not this record's problem and do not stop it — `check` is
            # what lists those.
            for problem in validate_all([*records, candidate], config)
            if problem.record_id == record_id
        ),
        key=lambda p: (p.severity, p.field or ""),
    )
    for problem in problems:
        print(f"{problem.severity}: {record_id}: {problem.field}: {problem.message}")
    if any(problem.severity == "blocker" for problem in problems):
        print("nothing written")
        return 1

    relative = f"{DIRECTORY[kind]}/{record_id}.md"
    destination = args.repo / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(content, encoding="utf-8")

    committed = (
        _commit_one(args.repo, relative, f"{record_id}: {args.title}") if args.commit else None
    )
    if args.json:
        print(json.dumps({"id": record_id, "path": relative, "commit": committed}))
    elif committed:
        print(f"{relative}\ncommitted {committed[:7]} — `git push` when you are ready")
    else:
        print(f"{relative}\ngit add {relative} && git commit && git push")
    return 0


def _not_a_bare_clone(repo: Path) -> str | None:
    """What `serve --repo` on a checkout still cannot promise, said once at startup.

    `Store` commits by building a tree and moving the branch, and `_freshen` then
    mirrors each landed commit into a checkout's working tree — so serving one
    works, and `git status` stays clean. What it cannot do is land a browser save
    on a file holding uncommitted local edits: that file is left alone and shows
    in `git status` as divergence to resolve by hand. A warning, not a refusal:
    somebody serving their checkout chose it on purpose.

    NO_SEARCH for the reason `Store` gives: a directory that is not a repository
    must not resolve to whatever repository encloses it. A path that is not a
    repository at all is `Store`'s to refuse, in its own words, so it is None
    here. `_cannot_commit_in` is the same question asked of `new --commit`, with
    the opposite answer.
    """
    import pygit2
    from pygit2.enums import RepositoryOpenFlag

    try:
        handle = pygit2.Repository(str(repo), RepositoryOpenFlag.NO_SEARCH)
    except pygit2.GitError:
        return None
    if handle.is_bare:
        return None
    return (
        f"{repo} is a checkout, not a bare clone. Saves from the browser land on its "
        "branch and are mirrored into its working tree — except into files holding "
        "uncommitted local edits, which are left alone and then show in `git status` "
        "as divergence to resolve by hand. A deployment should serve a bare clone: "
        f"`git clone --bare {repo} plan.git`, then `--repo plan.git`."
    )


def _cannot_commit_in(repo: Path) -> str | None:
    """Why `--commit` would fail here, asked BEFORE anything is written.

    Asked early because this command's contract is that a refusal writes nothing,
    and a refusal that arrives after the file is on the disk keeps neither half of
    it: the record exists, the commit does not, and the exit code says the whole
    thing failed. Everything checked here is a property of the repository, so it
    is knowable before the first byte.
    """
    import pygit2

    try:
        handle = pygit2.Repository(str(repo))
    except pygit2.GitError:
        return f"{repo} is not a git repository, so there is nothing to commit to"
    if handle.is_bare or handle.workdir is None:
        return f"{repo} is a bare repository and has no working copy to write into"
    if Path(handle.workdir).resolve() != repo.resolve():
        # `Repository()` searches upwards, so a plan directory nested in some
        # other repository resolves to THAT one — and every path this command
        # computed is relative to the plan, not to it. Committing anyway would
        # stage a path that does not exist.
        return (
            f"{repo} is inside the repository at {handle.workdir}, not the root of "
            "one; commit it from there yourself"
        )
    try:
        # Read for its refusal: `default_signature` is where libgit2 assembles
        # `user.name` and `user.email` from every config level, and a KeyError
        # here is the only honest way to ask whether the pair exists.
        _ = handle.default_signature
    except KeyError:
        return (
            "git has no identity here, so the commit would have no author — set "
            "`git config user.name` and `git config user.email`"
        )
    return None


def _init(args) -> int:
    """A plan repository from nothing: the config files, committed, checked.

    Refusals come first and write nothing — a directory with something in it,
    and a machine git cannot name an author on. The second is asked of the
    repository itself, the way `_commit_one` asks it, because libgit2's
    `default_signature` is the one reader that merges every config level; the
    freshly made `.git` is removed again on that refusal, so a person who reads
    "nothing written" finds nothing.

    The questions are asked only at a terminal and only for what the command
    line left out (`bootstrap.ask_for_the_rest`), so a script, a CI job or an
    agent gets a plan from the flags alone and is never left waiting on stdin.
    """
    import shutil

    import pygit2

    from .bootstrap import Options, ask_for_the_rest, plan_files

    target: Path = args.dir
    if target.exists() and any(target.iterdir()):
        print(f"blocker: {target} is not empty\nnothing written")
        return 1
    try:
        deploy = dict(pair.split("=", 1) for pair in args.deploy)
    except ValueError:
        print("blocker: --deploy takes KEY=VALUE\nnothing written")
        return 1
    if unknown := sorted(set(deploy) - {key for key, _, _ in _deploy_keys()}):
        print(f"blocker: --deploy has no {', '.join(unknown)}\nnothing written")
        return 1

    given = Options(
        org=args.org or "", remote=args.remote or "", login=args.author or "", deploy=deploy
    )
    options = given if args.no_prompt or not sys.stdin.isatty() else ask_for_the_rest(given, input)
    if options.deploy:
        options.deploy.setdefault("ORG", options.org)
        options.deploy.setdefault("REMOTE", options.remote)

    made_the_directory = not target.exists()
    target.mkdir(parents=True, exist_ok=True)
    handle = pygit2.init_repository(str(target), initial_head="main")
    if not args.no_commit:
        try:
            _ = handle.default_signature
        except KeyError:
            shutil.rmtree(target if made_the_directory else target / ".git")
            print(
                "blocker: git has no identity here, so the first commit would have no author "
                "— set `git config --global user.name` and `git config --global user.email`, "
                "or pass --no-commit\nnothing written"
            )
            return 1

    files = plan_files(target.resolve().name, options)
    for relative, text in files.items():
        path = target / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    if options.remote:
        handle.remotes.create("origin", options.remote)

    committed = (
        None if args.no_commit else _commit_everything(target, "A plan, with nothing in it yet")
    )
    # Held to the same rules as any plan, out loud: a template that `check`
    # would refuse is a bug here, not a fact about the plan.
    if _check(target, None) != 0:
        return 1

    if args.json:
        print(json.dumps({"path": str(target), "commit": committed, "files": sorted(files)}))
        return 0
    print(f"{target}: a plan repository" + (f", committed as {committed[:7]}" if committed else ""))
    print("next:")
    print(f'  openproj new pitch {target} --title "…"')
    if options.remote:
        print(f"  git -C {target} push -u origin main")
    print(f"  git clone --bare {target} plan.git && openproj serve --repo plan.git --auth dev")
    return 0


def _deploy_keys():
    from .bootstrap import DEPLOY_KEYS

    return DEPLOY_KEYS


def _commit_everything(repo: Path, message: str) -> str:
    """Every file in the working tree, in one commit — the shape `init` needs.

    Through the index, like `_commit_one` and for its reason: a commit that
    moves the branch without the index leaves a checkout whose `git status`
    reports everything as both deleted and untracked.
    """
    import pygit2

    handle = pygit2.Repository(str(repo))
    handle.index.add_all()
    handle.index.write()
    tree = handle.index.write_tree()
    author = handle.default_signature
    return str(handle.create_commit("HEAD", author, author, message, tree, []))


def _commit_one(repo: Path, relative: str, message: str) -> str:
    """One file, one commit, authored by whoever ran the command.

    Through the index, not around it. `Store` commits by building a tree and
    moving the branch, which is right for a bare clone with no working copy and
    wrong here: in an ordinary checkout it leaves a repository whose `git status`
    reports the new record as staged-for-deletion AND untracked at the same time,
    which is a worse place to be than never having offered `--commit`.

    The identity is git's, deliberately. A commit somebody makes from their own
    terminal is theirs, and the server's bot signature belongs on the commits the
    server makes.

    Every way this can refuse was asked and answered by `_cannot_commit_in`
    before the record was written, so there is no arm here for a repository that
    cannot take a commit.
    """
    import pygit2

    handle = pygit2.Repository(str(repo))
    who = handle.default_signature
    handle.index.read()
    handle.index.add(relative)
    handle.index.write()
    tree = handle.index.write_tree()
    parents = [] if handle.head_is_unborn else [handle.head.target]
    return str(handle.create_commit("HEAD", who, who, message, tree, parents))


def _check(repo: Path, today: date | None) -> int:
    """Every file that is not a record, then every problem, then the count.

    The files come first and are counted as blockers because they are the worst
    thing this command can find: a record that is wrong is on screen with a note
    beside it, and a file that will not parse is not in the plan at all. It used
    to raise on the first one — a traceback instead of a report, and no word
    about the second bad file until the first was fixed — which is the same
    failure as "0 blockers, 0 warnings" on a plan that answered 500 everywhere.

    **Through the index, and not through a schedule and a validation of its
    own.** Two of the rules are questions only a schedule can answer — whether a
    pitch's tasks fit in the calendar weeks its bet bought, and whether a stated
    start date has gone by — so this command has to schedule before it validates,
    and `build_index` is the one place that pairs the two around a single day.
    Written out here instead, it was a second such pairing, and it read the clock
    where the index takes the day it is drawn around: `openproj demo` pins
    2026-08-17 for the seed corpus, so `openproj check seed/` reported eleven
    start dates as passed that every page of the running demo drew as future.
    The two now take the same day by the same route, and `--today` is how a
    person names it.
    """
    records, config, unreadable = load_repo(repo)
    for one in unreadable:
        print(
            f"blocker: {one.path}: this file is not a record, so nothing in it is in the plan: "
            f"{one.why}"
        )
    index = build_index(records, config, today or date.today(), unreadable)
    problems = sorted(
        index.problems,
        key=lambda p: (p.severity, p.record_id, p.field or ""),
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
    """Where the bundled demo corpus lives: in a checkout, or beside the package
    in a wheel.

    The same shape as `vendor._static_dir` and for the same reason: `parents[2]`
    resolves past site-packages in an installed layout, so the wheel carries
    `seed/` beside the package (`force-include` in `pyproject.toml`) and that is
    the second candidate. Said rather than crashed, and said with what to do
    about it.
    """
    for candidate in (
        Path(__file__).resolve().parents[2] / "seed",
        Path(__file__).resolve().parent / "seed",
    ):
        if candidate.is_dir():
            return candidate
    raise RuntimeError(
        "the bundled seed/ corpus is missing: not in a source tree and not beside the "
        "package. A wheel built before seed/ was packaged runs `openproj demo` from a "
        "checkout only; against a real plan the command is "
        "`openproj serve --repo <bare clone>`."
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

    if args.auth == "github" and not args.org:
        print(
            "refusing to start: --auth github needs the org whose members may write. "
            "Pass --org, or set OPENPROJ_ORG.",
            file=sys.stderr,
        )
        return 2
    credentials = GitHubApp.from_environment(dict(os.environ))
    app = create_app(
        args.repo,
        auth=args.auth,
        org=args.org or "",
        secret=os.environ.get("OPENPROJ_SECRET", "dev-secret"),
        client_id=os.environ.get("OPENPROJ_CLIENT_ID", ""),
        client_secret=os.environ.get("OPENPROJ_CLIENT_SECRET", ""),
        # A remote and its credential both come from the environment, so a
        # development run needs neither and a deployment sets both or is refused.
        remote=os.environ.get("OPENPROJ_REMOTE", ""),
        credentials=credentials,
    )
    # After `create_app`, so a path that is no repository at all is refused by
    # the store in its own words rather than warned about here and then refused.
    checkout = _not_a_bare_clone(args.repo)
    if checkout is not None:
        print(f"warning: {checkout}", file=sys.stderr, flush=True)
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
                    # `text` and never `drawn`: this is the document a script
                    # pipes, `today` and every span date in it are ISO, and a
                    # sentence saying `28.08.2026` in the middle of that is a
                    # date nothing else here would parse. The pages ask the same
                    # explanation for `drawn` and get the same wording read out
                    # the way they draw every other date.
                    "explanations": {i: e.text for i, e in sorted(index.explanations.items())},
                },
                indent=1,
            )
        )
        return 0
    for record_id in sorted(index.spans, key=lambda i: (index.spans[i].start, i)):
        span = index.spans[record_id]
        note = index.explanations.get(record_id)
        # The first two columns are the span's own dates, printed as the model
        # holds them, so the sentence after them is asked for the same format.
        # It briefly was not, and the line read
        # `2026-08-28  2026-09-15  task-0a1002  Starts on 28.08.2026: …` — the
        # same day written both ways with sixty characters between them, which
        # invites the reader to work out what the difference means.
        print(f"{span.start}  {span.end}  {record_id:16}  {note.text if note else ''}")
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
    except SystemExit as exit_code:  # argparse exits 2 on a bad command line
        return int(exit_code.code or 2)
    if args.command == "init":
        return _init(args)
    if args.command == "check":
        return _check(args.repo, args.today)
    if args.command == "new":
        return _new(args)
    if args.command == "render":
        return _render(args.repo, args.out_dir, args.today)
    if args.command == "serve":
        return _serve(args)
    if args.command == "demo":
        return _demo(args)
    return _schedule(args.repo, args.json, args.today)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
