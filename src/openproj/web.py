"""The server: the Phase 1 pages, plus the ability to change them.

Five decisions shape almost everything here.

**Reads are public, writes are not.** The content is public by decision, so every
GET answers an anonymous browser. The gate lives on the two write endpoints and is
checked *per request* from the signed session. A server that asks about membership
only at `/auth/callback` and then issues a cookie to whoever authenticated has
handed write access to every GitHub user on earth.

**The author is the session and only the session.** The author/committer split in
`store.py` is the team's only audit trail, and it is worth exactly as much as the
guarantee that nobody can name themselves in a request body.

**The writable surface is closed by construction.** An id is admitted against a
regex before anything is concatenated, and the directory comes from its prefix.
`projects|pitches|tasks/<id>.md` is therefore the whole writable surface — which
matters more than usual because branch protection means a bad write cannot be
force-pushed away afterwards.

**A save preserves the file.** Only touched fields travel, and `patch_text` applies
them through a round-trip loader so comments, key order and list style survive.

**A refusal writes nothing.** A conflict is a 409 carrying a rendered report with
no conflict markers in it, because a marker that reaches the client reaches a
textarea and is then saved back.
"""

from __future__ import annotations

import asyncio
import json
import math
import re
import secrets
import threading
from datetime import date
from pathlib import Path
from typing import Literal

import httpx
from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse

from . import render
from .auth import User, exchange_code, identify, login_url, read_session, sign_session
from .index import build_index
from .model import (
    CONFIG_FILES,
    Config,
    Cycle,
    Entity,
    Pitch,
    Project,
    Task,
    Unreadable,
    parse_cycle_text,
    parse_text,
    patch_text,
    read_config,
    readable,
    validate_all,
    what_json_can_carry,
    why_it_will_not_read,
)
from .store import Store

SESSION_COOKIE = "__Host-openproj_session"
STATE_COOKIE = "op_state"

ID_PATTERN = re.compile(r"^(proj|pitch|task)-[0-9a-f]{6}$")
DIRECTORY = {"project": "projects", "pitch": "pitches", "task": "tasks"}
PREFIX = {"project": "proj", "pitch": "pitch", "task": "task"}

# Starlette does not bound a request body and Cloud Run will happily carry 32 MB.
# A blob committed to git is permanent and branch protection blocks the force-push
# that would take it back out, so the only place to stop it is before the commit.
MAX_BODY_BYTES = 256 * 1024
# A screenshot of a plot is well under this; a photograph pasted by accident is
# not. Every byte here is a byte in the plan repository forever — git keeps it
# after the markdown that referenced it is deleted.
MAX_ASSET_BYTES = 2 * 1024 * 1024
# No SVG: it is a document that can carry script, and these are served from the
# same origin as the editor.
IMAGE_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
}
ASSET_PATTERN = re.compile(r"^[0-9a-f]{16}\.(png|jpg|gif|webp)$")

_DEV_SECRETS = {"", "dev-secret", "change-me", "secret"}


CYCLE_DIR = "cycles"
# A cycle file is named by its number alone, zero-padded so that the order the
# store lists paths in is also the order a person means. Kept separate from
# ID_PATTERN rather than folded into it: the entity id pattern is what keeps the
# writable surface closed by construction, and widening it to admit a fourth
# shape is how that property gets lost by degrees.
CYCLE_PATTERN = re.compile(r"^[0-9]{1,4}$")
# The longest a build or a cool-down may be. Shape Up's cycle is six weeks and
# the box beside it had no bound at all, so `build_weeks: 500000` — three
# keystrokes and a confirmation — committed a cycle whose end date is past the
# end of the calendar, and every page that reads a cycle answered 500 to
# everybody, permanently, on a branch whose protection means the commit cannot
# be force-pushed away. Ten years is not a cycle by any reading; the number is
# refused here so it never reaches a file, and `Cycle._last_day` clamps anyway
# for the file somebody writes by hand.
MAX_CYCLE_WEEKS = 520.0


def _cycles_at(store: Store, commit: str) -> tuple[list[Cycle], list[Unreadable]]:
    return readable(
        [
            path
            for path in store.paths(commit)
            if path.endswith(".md") and path.split("/")[0] == CYCLE_DIR
        ],
        lambda path: parse_cycle_text(store.read(commit, path), path),
    )


def _cycle_path(number: int) -> str:
    return f"{CYCLE_DIR}/{number:04d}.md"


def _config_at(store: Store, commit: str) -> tuple[Config, list[Unreadable]]:
    """The configuration at this commit, and every plan file that is not a record.

    `CONFIG_FILES` is the same list the CLI reads. Hardcoded here, it was missing
    people.yaml, so `known_people` was empty under `serve` and the roster check
    that rejects an unknown login was silently off in the browser and on in CI —
    and `read_config` is now shared with the CLI for the same reason, so a config
    file that will not scan costs the same thing in both.

    The reads all happen inside `read_config`'s guard: `store.read` decodes, and
    a config file somebody saved in latin-1 was a UnicodeDecodeError on every
    route before the YAML parser was ever reached.
    """
    present = set(store.paths(commit))
    config, refused = read_config(
        [path for name in CONFIG_FILES if (path := f"config/{name}") in present],
        lambda path: store.read(commit, path) or "",
    )
    # The cycle records last, so a record supersedes the dates in cycles.yaml the
    # same way it does under the CLI.
    plans, refused_plans = _cycles_at(store, commit)
    return config.with_plans(plans), [*refused, *refused_plans]


def _entities_at(store: Store, commit: str) -> tuple[list[Entity], list[Unreadable]]:
    return readable(
        [
            path
            for path in store.paths(commit)
            if path.endswith(".md") and path.split("/")[0] in DIRECTORY.values()
        ],
        lambda path: parse_text(store.read(commit, path), path),
    )


# A form returns strings, and `priority: soon` is valid YAML that parses fine and
# then breaks the scheduler on the next read.
def _reject_bad_cycle(fields: dict) -> None:
    """The one place that decides what a cycle field may hold.

    A form returns strings here too, and an availability of `"half"` is valid
    YAML that parses and then divides a date by a word. The boxes now send what
    was typed rather than a coerced number, because a refusal is only useful if
    it can quote the value — so this is where a word becomes a 422 instead of a
    date the record cannot hold.
    """
    if "starts_on" in fields:
        fields["starts_on"] = _as_iso_date(fields["starts_on"], "starts_on")
    # `in fields`, not `is not None`. Skipping a null let it through to the file,
    # and `build_weeks: null` is a ValidationError inside `parse_cycle_text` —
    # an unhandled 500 whose body is not even JSON, so the page could not say
    # what was wrong. Null still arrives from anything that coerces before it
    # sends — `Number('six')` is NaN and `JSON.stringify` writes NaN as null —
    # and this endpoint answers browsers it did not render.
    for name in ("build_weeks", "cooldown_weeks"):
        if name in fields:
            fields[name] = _as_positive(fields[name], name, most=MAX_CYCLE_WEEKS)
    rates = fields.get("availability")
    if rates is not None:
        if not isinstance(rates, dict):
            raise HTTPException(422, "availability must be a map of login to fraction")
        fields["availability"] = {
            str(who): _as_positive(rate, f"availability of {who}") for who, rate in rates.items()
        }


def _as_iso_date(value: object, name: str) -> str:
    """A date the record can hold, spelled the way the corpus spells one.

    An empty date box posts `""`, which is not a refusal anywhere on the way in
    and is a ValidationError on the way back out — so clearing the date and
    pressing Save was a 500.
    """
    if isinstance(value, str):
        try:
            return date.fromisoformat(value).isoformat()
        except ValueError:
            pass
    raise HTTPException(422, f"{name} must be a date like 2026-09-01, not {value!r}")


def _as_positive(value: object, name: str, most: float = math.inf) -> float:
    # Said as "blank" rather than as `None`: null arrives here from a box
    # somebody emptied or typed a word into, and `None` is a word from this
    # language rather than from anything on their screen.
    if value is None:
        raise HTTPException(422, f"{name} must be a number, and this one is blank")
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise HTTPException(422, f"{name} must be a number, not {value!r}") from None
    # `float("inf")` is a number and passes every test below it, and a cycle
    # `.inf` weeks long is every date on every page gone. `nan` fails the
    # comparison, but says "not nan" rather than naming what was typed.
    if not math.isfinite(number):
        raise HTTPException(422, f"{name} must be an ordinary number, not {value!r}")
    if number <= 0:
        raise HTTPException(422, f"{name} must be greater than zero, not {number:g}")
    if number > most:
        raise HTTPException(422, f"{name} must be at most {most:g}, not {number:g}")
    return number


_NUMERIC = ("cycle", "appetite_weeks", "effort_weeks")
_LISTS = ("assignees", "reviewers", "tags", "prs", "depends_on", "shaped_by")


def _reject_bad_types(fields: dict) -> None:
    for name in _NUMERIC:
        value = fields.get(name)
        if value is not None and not isinstance(value, int | float) or isinstance(value, bool):
            if name in fields and fields[name] is not None:
                raise HTTPException(422, f"{name} must be a number, not {fields[name]!r}")
        # `Infinity` and `NaN` are valid JSON to Python's parser, so both arrive
        # here as ordinary floats and pass every check above. `effort_weeks:
        # Infinity` committed, and then `math.ceil` raised inside the
        # scheduler's own end-of-calendar guard: every page 500, permanently.
        # The guard no longer raises; this stops the value at the door, the way
        # the cycle route already stops it.
        if isinstance(value, float) and not math.isfinite(value):
            raise HTTPException(422, f"{name} must be an ordinary number, not {value!r}")
    for name in _LISTS:
        if name in fields and not isinstance(fields[name], list):
            raise HTTPException(422, f"{name} must be a list, not {fields[name]!r}")
    if "review_waived" in fields and not isinstance(fields["review_waived"], bool):
        raise HTTPException(422, "review_waived must be true or false")


async def _sent(request: Request) -> dict:
    """The JSON object a request carried, or a refusal that says so.

    Every route below reads keys off whatever `request.json()` hands back, and
    for four of them that was the first unguarded line in the handler. A
    truncated POST, a proxy that rewrote the body, `JSON.stringify` over the
    wrong variable — the first arrives as a JSONDecodeError and the others as a
    list or a string, and all three were an `AttributeError` under the router,
    which is a 500 with a `text/plain` body. That is the one answer the page
    cannot read back to say what happened, which is the whole reason the field
    checks below exist; the envelope those checks live inside had none.
    """
    try:
        payload = await request.json()
    except ValueError:
        raise HTTPException(400, "that request body is not JSON") from None
    if not isinstance(payload, dict):
        raise HTTPException(422, "a request here is a JSON object, and this one is not")
    return payload


def _base_in(store: Store, payload: dict) -> str:
    """The commit the page was rendered at, checked before anything reads at it.

    Missing, not a string, and a sha this repository never had are one situation
    from the route's side: there is nothing to compare the save against. The
    entity save learned it when a restored draft began carrying the commit it
    was drafted against — older than HEAD by design, and gone entirely after a
    re-clone of the plan. The cycle save beside it had the same four ways to
    fault and none of the guard, so the same stale tab was a 500 there.
    """
    base = payload.get("base_commit")
    if not isinstance(base, str) or not store.has(base):
        raise HTTPException(
            422,
            "this page was written against a commit that is not in the plan "
            "repository; copy anything unsaved, reload, and paste it back",
        )
    return base


def _body_in(payload: dict) -> str | None:
    """The body a save carries: text, absent, or a refusal — never a number.

    `len(body.encode(...))` is the size check, and it is also where a body that
    is not text stopped being a save and became an AttributeError.
    """
    body = payload.get("body")
    if body is None:
        return None
    if not isinstance(body, str):
        raise HTTPException(422, f"a body is text, not {body!r}")
    if len(body.encode("utf-8")) > MAX_BODY_BYTES:
        raise HTTPException(413, "that body is too large to commit")
    return body


def _fields_in(payload: dict) -> dict:
    """The touched fields, as a map. `.items()` on anything else was a 500."""
    fields = payload.get("fields")
    if fields is None:
        return {}
    if not isinstance(fields, dict):
        raise HTTPException(422, f"fields is a map of name to value, not {fields!r}")
    return dict(fields)


def _patched(original: str, fields: dict, body: str | None, path: str) -> str:
    """The file with those fields applied, or a refusal naming the file.

    About the file being edited, not about the edit. `patch_text` loads the
    frontmatter it is going to change, so a record somebody wrote in git whose
    YAML never closes raised a ruamel ParserError under the router — a 500 with a
    `text/plain` body, which is the one answer the editor cannot read back to say
    what happened. The page below it is already telling the reader that this file
    is not a record; this is what Save says when they try anyway.
    """
    try:
        return patch_text(original, fields, body)
    except Exception as error:  # noqa: BLE001 - a file in git can be anything
        raise HTTPException(
            422,
            f"{path} is not a record, so it cannot be saved from here: "
            f"{why_it_will_not_read(error, path)}. Fix it in git.",
        ) from None


def _directory_for(entity_id: str) -> str:
    """The directory an id belongs in, or a refusal. The one place an id becomes
    part of a path — everything else must come through here."""
    if not ID_PATTERN.match(entity_id):
        raise HTTPException(400, f"{entity_id!r} is not an entity id")
    prefix = entity_id.split("-")[0]
    kind = next(k for k, p in PREFIX.items() if p == prefix)
    return DIRECTORY[kind]


def _path_for(store: Store, commit: str, entity_id: str) -> str | None:
    """Where this entity's file actually is, at this commit.

    Filenames are `<id>--<slug>.md` and the slug drifts as titles are edited, so
    the path cannot be reconstructed from the id — it has to be found. Guessing
    `<id>.md` works on a corpus nobody has renamed and fails on every real one.
    """
    directory = _directory_for(entity_id)
    for path in store.paths(commit):
        if not path.startswith(f"{directory}/") or not path.endswith(".md"):
            continue
        stem = path[len(directory) + 1 : -len(".md")]
        if stem == entity_id or stem.startswith(f"{entity_id}--"):
            return path
    return None


MODELS = {"project": Project, "pitch": Pitch, "task": Task}


def _as_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _as_zoom(value: str) -> float | None:
    """Pixels per day, clamped. Unbounded, one typed zero makes an SVG megapixels
    wide and the tab stops responding."""
    try:
        return min(60.0, max(0.5, float(value)))
    except ValueError:
        return None


def create_app(
    repo: Path,
    *,
    auth: Literal["dev", "github"] = "dev",
    org: str = "C2SM",
    secret: str = "dev-secret",
    client_id: str = "",
    client_secret: str = "",
) -> FastAPI:
    if auth == "github":
        if secret in _DEV_SECRETS:
            raise ValueError(
                "refusing to start: auth='github' with a development signing secret would let "
                "anyone who has read this source mint a session for anybody."
            )
        if not client_id or not client_secret:
            raise ValueError(
                "refusing to start: auth='github' without a client id and secret cannot "
                "complete a sign-in, so nobody could ever write."
            )

    store = Store(Path(repo))
    app = FastAPI(title="openproj")
    watchers: set[asyncio.Queue] = set()
    # An event stream is a request that never ends, and uvicorn waits for in-flight
    # requests BEFORE it runs lifespan shutdown — so a flag set there arrives after
    # the wait it was meant to shorten. Installing a signal handler here does not
    # work either: uvicorn installs its own afterwards and replaces it. The runner
    # sets this from uvicorn's own exit hook, which is the only thing that fires
    # early enough. See cli._serve.
    closing = threading.Event()
    app.state.closing = closing

    def index_now():
        commit = store.head()
        config, unreadable_config = _config_at(store, commit)
        entities, unreadable_entities = _entities_at(store, commit)
        return commit, build_index(
            entities,
            config,
            date.today(),
            # Sorted by path, because a reader works through the list by opening
            # files and two walks finishing in whatever order is not that order.
            unreadable=sorted(
                [*unreadable_config, *unreadable_entities], key=lambda one: one.path
            ),
        )

    def viewer(request: Request) -> User | None:
        return read_session(request.cookies.get(SESSION_COOKIE), secret)

    def writer(request: Request) -> User:
        """Who is allowed to write, decided per request rather than at login.

        In dev mode anybody may write, but the session still decides *who they
        are*: dev never invents an author, because a commit attributed to nobody
        is worse than no commit.
        """
        user = viewer(request)
        if auth == "dev":
            return user or User(login="dev", member=True)
        if user is None:
            raise HTTPException(401, "sign in to make changes")
        if not user.member:
            raise HTTPException(403, f"{user.login} is not a member of {org}")
        return user

    def secure_for(request: Request) -> bool:
        """Whether cookies are marked Secure, from the scheme actually in use.

        A `__Host-` cookie is only ever accepted or cleared when Secure is set, so
        hard-coding it true makes sign-out silently fail over plain HTTP — which is
        every local run and every test. Behind Cloud Run the TLS is terminated
        upstream, so uvicorn must run with --proxy-headers for this to see https.
        """
        return request.url.scheme == "https"

    async def announce(commit: str, changed: list[str]) -> None:
        for queue in list(watchers):
            queue.put_nowait({"commit": commit, "changed": changed})

    # -- pages --------------------------------------------------------------

    def page(html: str) -> HTMLResponse:
        return HTMLResponse(html)

    @app.get("/", response_class=HTMLResponse)
    def table() -> HTMLResponse:
        commit, index = index_now()
        return page(render.render_table(index, render.ROUTES, base_commit=commit))

    @app.get("/graph", response_class=HTMLResponse)
    def graph() -> HTMLResponse:
        commit, index = index_now()
        return page(render.render_graph(index, render.ROUTES, base_commit=commit))

    @app.get("/timeline", response_class=HTMLResponse)
    def timeline(
        from_: str = Query("", alias="from"), to: str = "", zoom: str = ""
    ) -> HTMLResponse:
        """The window and the day width come off the URL, so a view is a link.

        Every one of the three is typed by hand as easily as it is picked, so all
        three are parsed leniently: a nonsense value falls back to the default view
        rather than turning a bookmark into a 422.
        """
        window = (_as_date(from_), _as_date(to))
        return page(render.render_timeline(index_now()[1], render.ROUTES, window, _as_zoom(zoom)))

    @app.get("/cycles", response_class=HTMLResponse)
    def cycles() -> HTMLResponse:
        commit, index = index_now()
        return page(render.render_cycles(index, render.ROUTES, commit))

    @app.get("/cycle/{number}", response_class=HTMLResponse)
    def cycle(number: int) -> HTMLResponse:
        """Typed `int`, so nothing that is not a number ever reaches a path.

        Stronger than a pattern: FastAPI refuses a non-integral value before the
        handler body runs, so `..` and `%2F` cannot get as far as being rejected
        by a regex somebody might later relax.

        Bounded to the same numbers the save accepts. `int` admits -1 and 99999,
        which rendered a whole editable cycle page whose every Save was a 422
        from `CYCLE_PATTERN` — the read path and the write path disagreeing about
        which cycles exist, which is a dead end a person can only find by filling
        the form in first.
        """
        if not CYCLE_PATTERN.match(str(number)):
            raise HTTPException(404, "a cycle is numbered 0 to 9999")
        commit, index = index_now()
        return page(render.render_cycle(index, number, render.ROUTES, commit))

    @app.get("/people", response_class=HTMLResponse)
    def people() -> HTMLResponse:
        return page(render.render_people(index_now()[1], render.ROUTES))

    @app.get("/new", response_class=HTMLResponse)
    def new(kind: str = "task") -> HTMLResponse:
        if kind not in DIRECTORY:
            raise HTTPException(422, f"kind must be one of {sorted(DIRECTORY)}")
        commit, index = index_now()
        return page(render.render_new(kind, commit, render.ROUTES, index))

    @app.get("/detail", response_class=HTMLResponse)
    def detail_index() -> HTMLResponse:
        return page(render.render_detail(index_now()[1], render.ROUTES))

    @app.get("/detail/{entity_id}", response_class=HTMLResponse)
    def detail(entity_id: str) -> HTMLResponse:
        commit, index = index_now()
        if entity_id not in index.entities:
            raise HTTPException(404, f"no entity {entity_id!r}")
        # The page carries the commit it was rendered at, so a save is compared
        # against what the person actually saw rather than against whatever HEAD
        # has become while the tab sat open.
        return page(
            render.render_detail(index, render.ROUTES, only=entity_id, base_commit=commit)
        )

    @app.post("/api/preview")
    async def preview(request: Request) -> JSONResponse:
        """Render markdown the same way the page will, on the server.

        A second markdown implementation in JavaScript would eventually disagree
        with this one, and the renderer people trust would not be the one whose
        output gets committed.

        The title comes with the body because the page drops a leading heading
        that only restates it, and the title being previewed is the one in the
        form — not the one in the repository, which the same Save is about to
        change.
        """
        payload = await _sent(request)
        # `str()` rather than a refusal: this route renders, it does not write, and
        # a preview is worth showing for whatever was typed. But the markdown
        # parser takes text and a number reached it as a TypeError — a 500 on the
        # only write-adjacent route that answers an anonymous visitor.
        return JSONResponse(
            {
                "html": render.preview_html(
                    str(payload.get("body") or ""), title=str(payload.get("title") or "")
                )
            }
        )

    @app.get("/healthz")
    def healthz() -> dict:
        return {"ok": True, "head": store.head()}

    @app.get("/api/index.json")
    def index_json() -> JSONResponse:
        commit, index = index_now()
        # Through the same door the pages' data blocks go through. `JSONResponse`
        # encodes with `allow_nan=False`, so a size somebody hand-edited to
        # `.inf` raised inside the encoder — after the response object existed,
        # which is a 500 in plain text on a route whose readers are scripts.
        return JSONResponse(
            what_json_can_carry(
                {
                    "head": commit,
                    "entities": {i: e.model_dump(mode="json") for i, e in index.entities.items()},
                    "spans": {i: s.model_dump(mode="json") for i, s in index.spans.items()},
                    "explanations": {i: e.text for i, e in index.explanations.items()},
                    "problems": [p.model_dump(mode="json") for p in index.problems],
                    # A script reading this has to be able to tell "the plan
                    # holds sixteen tasks" from "the plan holds sixteen tasks
                    # that parsed", and nothing else in this payload says so.
                    "unreadable": [u.model_dump(mode="json") for u in index.unreadable],
                }
            )
        )

    # -- writing ------------------------------------------------------------

    def _result(written, commit_before: str) -> JSONResponse:
        """One shape for every answer. A caller should not have to know whether it
        succeeded to know which keys exist."""
        payload = {
            "outcome": written.outcome,
            "commit": written.commit,
            "conflict": written.conflict,
            "head": commit_before,
        }
        return JSONResponse(payload, status_code=409 if written.outcome == "conflict" else 200)

    @app.patch("/api/entity/{entity_id}")
    async def save(entity_id: str, request: Request) -> JSONResponse:
        user = writer(request)
        payload = await _sent(request)
        body = _body_in(payload)
        # A commit this repository does not have is a refusal, not a crash. This
        # is the one route that is handed a base older than HEAD by design — a
        # restored draft carries the commit it was drafted against — so a draft
        # that has sat in a browser through a re-clone of the plan arrives with a
        # sha `store.paths` throws on.
        base = _base_in(store, payload)
        path = _path_for(store, base, entity_id)
        if path is None:
            raise HTTPException(404, f"no entity {entity_id!r}")
        original = store.read(base, path)

        fields = {k: v for k, v in _fields_in(payload).items() if k != "id"}
        _reject_bad_types(fields)
        content = _patched(original, fields, body, path)
        # Parse before writing, the same refusal the cycle route beside this one
        # makes, and for a worse reason: a record that fails to load takes `/`,
        # `/detail/<id>` and `/api/index.json` down for everybody, on every read,
        # and the file is already in git — on a protected branch, so the commit
        # cannot be force-pushed away and the repair is a second crafted PATCH
        # against a sha the 500ing pages will not give you. `_reject_bad_types`
        # names numbers, lists and one bool; everything it does not name — a
        # title that is a number, a date that is a word, a tag that is null —
        # came through here and committed.
        try:
            parse_text(content, path)
        except ValueError as error:
            raise HTTPException(
                422, f"that would not read back as an entity: {why_it_will_not_read(error)}"
            ) from None
        written = store.write(
            path=path,
            content=content,
            base_commit=base,
            author=user.login,
            message=f"{entity_id}: {', '.join(fields) or 'body'}",
        )
        if written.commit:
            await announce(written.commit, [entity_id])
        return _result(written, base)

    @app.put("/api/cycle/{number}")
    async def save_cycle(number: int, request: Request) -> JSONResponse:
        """Create or update one cycle record.

        PUT rather than PATCH because a cycle is set up in one sitting: the whole
        roster is written at once, and a missing name means somebody was removed
        rather than left alone. That is the opposite of an entity's per-field
        merge, and conflating the two would make removing a person impossible.
        """
        user = writer(request)
        payload = await _sent(request)
        body = _body_in(payload)
        if not CYCLE_PATTERN.match(str(number)):
            raise HTTPException(422, "a cycle is numbered 0 to 9999")

        base = _base_in(store, payload)
        path = _cycle_path(number)
        original = store.read(base, path) or "---\n---\n"
        fields = _fields_in(payload)
        fields["cycle"] = number
        _reject_bad_cycle(fields)

        content = _patched(original, fields, body, path)
        # Parse before writing, not after: a roster that fails to load would take
        # every date on every page with it, and the file would already be in git.
        # Refused rather than raised — everything the checks above do not name
        # reached here as an unhandled ValidationError, which is a 500 with a
        # plain-text body, and a plain-text body is a client that cannot even
        # report the failure.
        try:
            parse_cycle_text(content, path)
        except ValueError as error:
            raise HTTPException(
                422, f"that would not read back as a cycle: {why_it_will_not_read(error)}"
            ) from None
        written = store.write(
            path=path,
            content=content,
            base_commit=base,
            author=user.login,
            message=f"cycle {number}: {', '.join(k for k in fields if k != 'cycle') or 'goal'}",
        )
        if written.commit:
            await announce(written.commit, [f"cycle-{number}"])
        return _result(written, base)

    @app.post("/api/asset")
    async def upload(request: Request) -> JSONResponse:
        """Raw bytes with a content-type header, not a multipart form.

        Multipart would mean another dependency for a request that carries one
        file and nothing else, and `fetch` posts a File object as a raw body
        without any help.
        """
        user = writer(request)
        kind = request.headers.get("content-type", "").split(";")[0].strip().lower()
        if kind not in IMAGE_TYPES:
            raise HTTPException(415, f"images only: {', '.join(sorted(IMAGE_TYPES))}")
        data = await request.body()
        if not data:
            raise HTTPException(422, "that file is empty")
        if len(data) > MAX_ASSET_BYTES:
            raise HTTPException(
                413, f"that image is {len(data) // 1024} KB; the limit is "
                     f"{MAX_ASSET_BYTES // 1024} KB"
            )
        path, fresh = store.put_asset(data, IMAGE_TYPES[kind], user.login)
        # The sha goes back to the uploader as well as out to everybody else. The
        # shell's banner suppresses news of a commit the tab made itself, and it
        # can only do that if the request that made it hands the sha back — an
        # upload that only announced popped "The plan changed." over its own paste.
        commit = store.head()
        if fresh:
            await announce(commit, [])
        return JSONResponse(
            {"path": path, "url": f"/{path}", "fresh": fresh, "commit": commit}
        )

    @app.get("/assets/{name}")
    def asset(name: str) -> Response:
        if not ASSET_PATTERN.match(name):
            raise HTTPException(404, "no such asset")
        data = store.read_asset(store.head(), f"assets/{name}")
        if data is None:
            raise HTTPException(404, "no such asset")
        suffix = "." + name.rsplit(".", 1)[-1]
        return Response(
            data,
            media_type=next(k for k, v in IMAGE_TYPES.items() if v == suffix),
            # The name IS the hash of the contents, so this bytes-for-bytes
            # cannot change under a cache.
            headers={"cache-control": "public, max-age=31536000, immutable"},
        )

    @app.post("/api/entity")
    async def create(request: Request) -> JSONResponse:
        user = writer(request)
        payload = await _sent(request)
        fields = _fields_in(payload)
        body = _body_in(payload) or ""

        kind = fields.get("kind")
        if kind not in DIRECTORY:
            raise HTTPException(422, f"kind must be one of {sorted(DIRECTORY)}")
        # The same door as the save beside it. Create had no type check at all,
        # so every value the save route refuses could be created instead — the
        # closed writable surface is only closed if both ways in are.
        _reject_bad_types(fields)

        # A pitch has an appetite and a task has an effort. The create page carries
        # every kind's fields and hides the ones that do not apply, so what belongs
        # to this kind is decided here rather than by which controls a script left
        # visible: fields are written to the file before the model ever sees them,
        # and a key the model does not own would sit in the frontmatter unread.
        allowed = set(MODELS[kind].model_fields)
        unknown = sorted(set(fields) - allowed)
        if unknown:
            raise HTTPException(422, f"a {kind} has no {', '.join(unknown)}")

        # Minted here, never accepted from the client: an id supplied by a browser
        # is a path supplied by a browser once it becomes `tasks/<id>.md`.
        entity_id = f"{PREFIX[kind]}-{secrets.token_hex(3)}"
        commit = store.head()
        config, _ = _config_at(store, commit)
        fields["id"] = entity_id
        # Grandfathering protects the corpus that already exists, not the entity
        # being written right now: something created today is held to today's rules.
        fields.setdefault("created_schema_version", config.schema_version)
        content = patch_text("---\n---\n", fields, body)
        # The same refusal the save route makes, on the other door. `_reject_bad_types`
        # names numbers, lists and one bool; a title that is a number, a date that is
        # a word, a tag that is null and a reviewer that is an integer all passed it
        # and raised here as a bare ValidationError — a 500 whose body is plain text,
        # which is the one answer the create form cannot read back to say what was
        # wrong. Nothing was committed either way, so what this changes is whether the
        # person is told which field it was.
        try:
            candidate = parse_text(content, entity_id)
        except ValueError as error:
            raise HTTPException(
                422, f"that would not read back as an entity: {why_it_will_not_read(error)}"
            ) from None
        problems = [
            p
            # A file already in the plan that will not parse is not this entity's
            # problem and must not stop it being created: the validator only
            # needs the neighbours it can read, and the banner is what says the
            # rest are missing.
            for p in validate_all([*_entities_at(store, commit)[0], candidate], config)
            if p.entity_id == entity_id and p.severity == "blocker"
        ]
        if problems:
            return JSONResponse(
                {"problems": [p.model_dump(mode="json") for p in problems]}, status_code=422
            )

        written = store.write(
            path=f"{DIRECTORY[kind]}/{entity_id}.md",
            content=content,
            # A base is optional here — a create has nothing to be stale against
            # — but one that was sent has to be real, because `store.write` reads
            # at it the moment HEAD has moved, which is exactly when a person
            # with an old tab open presses New.
            base_commit=_base_in(store, payload) if payload.get("base_commit") else commit,
            author=user.login,
            message=f"{entity_id}: create",
        )
        if written.commit:
            await announce(written.commit, [entity_id])
        if written.outcome == "conflict":
            return _result(written, commit)
        return JSONResponse(
            {"id": entity_id, "outcome": written.outcome, "commit": written.commit},
            status_code=201,
        )

    # -- events -------------------------------------------------------------

    @app.get("/api/events")
    async def events() -> StreamingResponse:
        """Server-Sent Events, not WebSockets: the traffic is one way, it survives
        a proxy that has never heard of an upgrade handshake, and the browser
        reconnects on its own."""
        queue: asyncio.Queue = asyncio.Queue()
        watchers.add(queue)

        async def stream():
            try:
                # A comment, not an event: it flushes the headers so a client knows
                # the stream is live, without looking like something happened.
                yield b": connected\n\n"
                waited = 0.0
                while not closing.is_set():
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=1)
                    except TimeoutError:
                        # A short wait so a shutdown is noticed in about a second,
                        # but a keepalive only every fifteen: the wakeup is for us,
                        # the bytes are for the client.
                        waited += 1
                        if waited >= 15:
                            waited = 0
                            yield b": keepalive\n\n"
                        continue
                    yield f"data: {json.dumps(event)}\n\n".encode()
            finally:
                watchers.discard(queue)

        return StreamingResponse(stream(), media_type="text/event-stream")

    # -- sign in ------------------------------------------------------------

    @app.get("/login")
    def login(request: Request) -> RedirectResponse:
        state = secrets.token_urlsafe(32)
        redirect_uri = str(request.url_for("callback"))
        response = RedirectResponse(login_url(client_id, redirect_uri, state))
        # SameSite=Lax, not Strict: the callback is a top-level cross-site GET, and
        # Strict would drop this cookie so every login would fail state validation.
        response.set_cookie(
            STATE_COOKIE, state, max_age=600, httponly=True, samesite="lax", path="/"
        )
        return response

    @app.get("/auth/callback", name="callback")
    async def callback(request: Request) -> Response:
        expected = request.cookies.get(STATE_COOKIE)
        given = request.query_params.get("state")
        if not expected or not given or not secrets.compare_digest(expected, given):
            raise HTTPException(400, "that sign-in did not start here")

        async with httpx.AsyncClient() as client:
            token = await exchange_code(
                request.query_params.get("code", ""), client_id, client_secret, client
            )
            user = await identify(token, org, client)
        # The token established who they are and is now dropped: it is never
        # written to the session and never used to push.
        response = RedirectResponse("/", status_code=303)
        response.set_cookie(
            SESSION_COOKIE,
            sign_session(user, secret),
            max_age=86400,
            httponly=True,
            secure=secure_for(request),
            samesite="lax",
            path="/",
        )
        response.delete_cookie(STATE_COOKIE, path="/")
        return response

    @app.post("/logout")
    def logout(request: Request) -> Response:
        response = RedirectResponse("/", status_code=303)
        # A __Host- cookie is only matched when Secure and Path=/ agree, so a
        # deletion that disagrees leaves the session quietly in place.
        response.delete_cookie(
            SESSION_COOKIE,
            path="/",
            secure=secure_for(request),
            httponly=True,
            samesite="lax",
        )
        return response

    return app
