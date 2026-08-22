"""The rung above project, and the ladder every kind is now read from.

A product groups the codebases one plan spans — gt4py under icon4py, dace, pmap —
and it exists for one reason, in jcanton's words: separate corpora "would prevent
cross-dependencies", and a dependency this tool cannot express is one somebody
tracks in their head.

It is a container and nothing else: a title, a sentence, and a place for projects
to sit. What it may not have is declared on the ladder rather than in a validator
per field, so the answer to "what is different about a product" is one table.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from openproj.index import _product_of, _project_of, build_index
from openproj.model import (
    KIND_NAMES,
    KINDS,
    PARENT_KINDS,
    RUNG,
    Config,
    Product,
    load_repo,
    parse_text,
    validate_all,
)


def test_the_ladder_is_the_only_place_the_kinds_are_written_down():
    """Every map about kinds is derived from `KINDS`, in order, coarsest first.

    Adding `product` had to find and edit five hand-written copies of the same
    list — `_ENTITY_DIRS` in `model.py`, `DIRECTORY` in `web.py`, `PREFIX`,
    `_KIND_MODELS` and `KINDS` in `render.py` — and the one that failed silently
    was `_ENTITY_DIRS`: a plan holding two products loaded thirty-three records,
    none of them a product, with nothing reported, because a directory nobody
    walks is a directory whose files do not exist.

    So this asserts the derivation rather than the values: any map that disagrees
    with the ladder is a sixth copy.
    """
    from openproj import render, web
    from openproj.model import _ID_PREFIXES, _MODELS, _PREFIX_FOR_KIND

    assert KIND_NAMES == tuple(rung.name for rung in KINDS)
    assert _MODELS == {rung.name: rung.model for rung in KINDS}
    assert _ID_PREFIXES == {rung.prefix: rung.name for rung in KINDS}
    assert _PREFIX_FOR_KIND == {rung.name: rung.prefix for rung in KINDS}
    assert PARENT_KINDS == {rung.name: rung.under for rung in KINDS}
    assert web.DIRECTORY == {rung.name: rung.directory for rung in KINDS}
    assert render.PREFIX == {rung.name: rung.prefix for rung in KINDS}
    assert render.KINDS == KIND_NAMES
    assert render._KIND_MODELS == {rung.name: rung.model for rung in KINDS}
    # The write path's two, which this test did not name when it was written —
    # and which were therefore still spelled out by hand. `POST /api/entity` with
    # `kind: product` raised KeyError twice over and answered 500 on the only
    # route that can create one, on a branch whose whole subject was the ladder.
    assert web.MODELS == {rung.name: rung.model for rung in KINDS}
    assert web.PREFIX == {rung.name: rung.prefix for rung in KINDS}
    # Every field of every kind, so a rung that declares one is writable through
    # the API on the commit that adds it.
    for rung in KINDS:
        assert set(rung.model.model_fields) <= set(web.ENTITY_FIELDS), rung.name


def test_a_product_is_the_top_and_a_project_sits_under_one():
    """`project: ()` used to say "a project is the top", three hundred lines from
    anywhere a rung would be added."""
    assert PARENT_KINDS["product"] == ()
    assert PARENT_KINDS["project"] == ("product",)
    # And a task may still skip its pitch, which is why `under` is written per
    # rung rather than derived as "everything coarser": derived, a task could be
    # filed straight under a product, three rungs up.
    assert PARENT_KINDS["task"] == ("pitch", "project")
    assert "product" not in PARENT_KINDS["task"]


def test_a_product_waits_on_nothing():
    """Its projects, pitches and tasks do. jcanton: it "should not be allowed to
    have dependencies (only its projects/pitches/tasks can)"."""
    one = Product(id="prod-000001", kind="product", title="gt4py",
                  depends_on=["proj-000001"])
    problems = validate_all([one], Config())
    waiting = [p for p in problems if p.field == "depends_on" and p.severity == "blocker"]
    assert waiting, "a product was allowed to wait on something"
    assert "waits on nothing" in waiting[0].message


def test_a_product_carries_no_appetite_and_is_never_scheduled():
    """Parsed from text and not built in Python, because that is where the
    appetite has to survive to be reported: `Product` has no `person_weeks` field
    at all, so parsing drops the key, and a rule reading the object alone would
    be a rule that can never fire on any file anybody writes."""
    one = parse_text(
        "---\nid: prod-000001\nkind: product\ntitle: gt4py\n"
        "person_weeks: 4\nowner: ann\n---\n\nThe DSL.\n",
        "products/prod-000001.md",
    )
    assert "person_weeks" in one._unread
    problems = {(p.field, p.severity) for p in validate_all([one], Config())}
    assert ("person_weeks", "blocker") in problems
    assert ("owner", "warning") in problems, (
        "an owner on a container is a warning, not a blocker: it is ignored rather "
        "than wrong, and refusing the file would be refusing to load the plan"
    )


def test_the_product_rules_are_as_old_as_the_kind():
    """Grandfathering exists so a rule invented today does not turn a year-old
    file red. No file can predate a KIND, though — every product that will ever
    exist is written after the rules about products — so those rules are stamped
    version 1 and are blockers on a hand-written file, which defaults to 1."""
    one = Product(id="prod-000001", kind="product", title="gt4py",
                  depends_on=["proj-000001"], created_schema_version=1)
    waiting = [
        p for p in validate_all([one], Config())
        if p.field == "depends_on" and "waits on nothing" in p.message
    ]
    assert waiting and waiting[0].severity == "blocker", (
        "the rule was grandfathered away on a file that cannot predate it"
    )


def test_an_unknown_kind_is_still_refused():
    """`kind` stopped being a `Literal` when it became a rung of the ladder, and
    strictness had to come back with it — unlike `status`, which is deliberately
    permissive. An unknown status is a word beside a record that still draws; an
    unknown kind has no directory, no prefix, no parent rule and no model."""
    from pydantic import ValidationError

    from openproj.model import Entity

    with pytest.raises(ValidationError):
        Entity(id="task-abc123", kind="epic", title="T")


@pytest.fixture
def plan(tmp_path: Path) -> Path:
    """Two products, and a pitch in one waiting on a pitch in the other — the
    cross-product dependency this kind exists for."""
    root = tmp_path / "plan"
    for name in ("products", "projects", "pitches", "config"):
        (root / name).mkdir(parents=True)
    (root / "config" / "defaults.yaml").write_text("schema_version: 2\n")
    (root / "products" / "prod-000001.md").write_text(
        "---\nid: prod-000001\nkind: product\ntitle: icon4py\n---\n\nThe port.\n")
    (root / "products" / "prod-000002.md").write_text(
        "---\nid: prod-000002\nkind: product\ntitle: gt4py\n---\n\nThe DSL under it.\n")
    (root / "projects" / "proj-000001.md").write_text(
        "---\nid: proj-000001\nkind: project\ntitle: The port\nparent: prod-000001\n"
        "status: ready\nowner: ann\nreviewers: [bo]\n---\n\nx\n")
    (root / "projects" / "proj-000002.md").write_text(
        "---\nid: proj-000002\nkind: project\ntitle: The DSL\nparent: prod-000002\n"
        "status: ready\nowner: bo\nreviewers: [ann]\n---\n\nx\n")
    (root / "pitches" / "pitch-000002.md").write_text(
        "---\nid: pitch-000002\nkind: pitch\ntitle: Field view lowering\n"
        "parent: proj-000002\nstatus: ready\nowner: bo\nreviewers: [ann]\n"
        "person_weeks: 3\n---\n\nx\n")
    (root / "pitches" / "pitch-000001.md").write_text(
        "---\nid: pitch-000001\nkind: pitch\ntitle: Port the advection\n"
        "parent: proj-000001\nstatus: ready\nowner: ann\nreviewers: [bo]\n"
        "person_weeks: 2\ndepends_on: [pitch-000002]\n---\n\nx\n")
    return root


def test_work_in_one_product_can_wait_on_work_in_another(plan: Path):
    """The whole reason for the kind. Four separate plans cannot express this at
    all; one plan expresses it as an ordinary dependency."""
    entities, config, unreadable = load_repo(plan)
    assert not unreadable, unreadable
    assert sorted(e.id for e in entities if e.kind == "product") == [
        "prod-000001", "prod-000002",
    ]

    index = build_index(entities, config, date(2026, 8, 20))
    assert index.blocked_by["pitch-000001"] == ["pitch-000002"]

    # And each side knows which product it is in, walking past its project.
    assert _product_of(index.entities["pitch-000001"], index.entities) == "prod-000001"
    assert _product_of(index.entities["pitch-000002"], index.entities) == "prod-000002"
    # `project` still means project, not "the top of the tree".
    assert _project_of(index.entities["pitch-000001"], index.entities) == "proj-000001"

    blockers = [p for p in validate_all(entities, config) if p.severity == "blocker"]
    assert not blockers, [(p.entity_id, p.message) for p in blockers]


def test_a_product_draws_no_bar_on_the_timeline(plan: Path):
    """It groups work and does none, so it has no dates to draw. Given a span it
    drew a bar spanning everything beneath it — a rectangle behind every real bar,
    saying nothing the bars do not."""
    from openproj.render import ROUTES, render_timeline

    entities, config, _ = load_repo(plan)
    index = build_index(entities, config, date(2026, 8, 20))

    assert "prod-000001" not in index.spans
    assert "pitch-000001" in index.spans, "the rest of the plan stopped being scheduled"
    assert 'data-id="prod-000001"' not in render_timeline(index, ROUTES)


def test_a_product_is_drawn_differently_and_shows_no_card(plan: Path):
    """jcanton asked for both: a shape of its own, and no hover card.

    The card would be a box of dashes — a product has no owner, no dates, no
    appetite and no shaping document — and a card of dashes teaches a reader that
    cards are not worth hovering for. `carded` is on the ladder because the same
    question gets asked on more than one page.
    """
    from openproj.render import ROUTES, render_graph

    entities, config, _ = load_repo(plan)
    index = build_index(entities, config, date(2026, 8, 20))
    page = render_graph(index, ROUTES, base_commit="0" * 40)

    assert 'node[kind = "product"]' in page, "a product is drawn like everything else"
    assert "'border-style': 'dashed'" in page
    assert "const CARDED" in page and '"product": false' in page.replace(", ", ", ")
    assert RUNG["product"].carded is False
    assert RUNG["project"].carded is True


def test_a_container_has_no_work_state_to_gate():
    """`ready` on a pitch demands an owner, a reviewer and an appetite. A product
    has no status at all — jcanton, 2026-08-20: "the product should also not have
    a status nor PRs" — so there is nothing to gate, and a file that writes one
    is told the field is not read.

    Both halves matter. The gate not firing is what stopped `status: ready` on a
    container demanding an owner it is also told it must not have; the warning is
    what stops the field being written in silence.
    """
    from openproj.model import required_at

    assert required_at("product") == {}
    assert "owner" in required_at("pitch")

    ready = parse_text(
        "---\nid: prod-000001\nkind: product\ntitle: gt4py\nstatus: ready\n---\n\nx\n",
        "products/prod-000001.md",
    )
    said = validate_all([ready], Config())
    assert [(p.severity, p.field) for p in said] == [("warning", "status")], said
    assert "not read" in said[0].message


def test_the_editors_do_not_offer_a_field_the_rung_does_not_read():
    """The other half of `unread_fields`. A form offering an owner box that the
    validator then warns about is the two disagreeing in the most annoying
    possible order, so both read the same function."""
    from openproj.render import _editable_for, _new_row_fields

    one = parse_text(
        "---\nid: prod-000001\nkind: product\ntitle: gt4py\n---\n\nx\n",
        "products/prod-000001.md",
    )
    offered = {field["name"] for field in _editable_for(one)}
    assert offered == {"title", "tags"}, (
        "a product is a title, a sentence and somewhere to file projects; every "
        f"other box on the form belongs to the work inside it: {sorted(offered)}"
    )
    assert not offered & set(RUNG and ("owner", "cycle", "priority", "depends_on",
                                       "status", "prs"))
    # And no parent picker on the top rung: there is nothing to file it under.
    assert "parent" not in offered
    assert "parent" in {f["name"] for f in _editable_for(parse_text(
        "---\nid: proj-000001\nkind: project\ntitle: The port\n---\n\nx\n",
        "projects/proj-000001.md"))}

    columns = _new_row_fields()
    assert "owner" not in columns["product"] and "owner" in columns["project"]
    assert "size" not in columns["product"]


def test_a_product_can_be_made_through_the_api(tmp_path: Path):
    """The route that creates one, driven — because every map this needed was
    derived except the two on the write path.

    `MODELS` and `PREFIX` in `web.py` were written out as three kinds, three
    lines apart from a `DIRECTORY` that was derived, so creating a product raised
    KeyError and answered 500 while every read path in the app drew products
    perfectly. A test that asserts the derivation is only as good as the list of
    maps it names, which is why this one drives the route instead.
    """
    import re

    import pygit2
    from fastapi.testclient import TestClient
    from test_store import commit_directly
    from test_web import ANN, SECRET, SEED, SESSION_COOKIE, sign_session

    from openproj.web import create_app

    plan = tmp_path / "plan.git"
    pygit2.init_repository(str(plan), bare=True, initial_head="main")
    commit_directly(plan, SEED, "seed")

    with TestClient(create_app(plan, auth="dev", secret=SECRET)) as client:
        client.cookies.set(SESSION_COOKIE, sign_session(ANN, SECRET))
        page = client.get("/new?kind=product").text
        base = re.search(r'name="base_commit" value="([0-9a-f]{40})"', page).group(1)

        made = client.post(
            "/api/entity",
            json={"base_commit": base,
                  "fields": {"kind": "product", "title": "gt4py"},
                  "body": "The DSL under icon4py.\n"},
        )
        assert made.status_code == 201, made.json()
        product = made.json()["id"]
        assert product.startswith("prod-")
        assert client.get(f"/detail/{product}").status_code == 200

        # And a project files under it, which is the whole point of the rung.
        index = client.get("/api/index.json").json()
        assert index["entities"][product]["kind"] == "product"
        project = next(i for i, e in index["entities"].items() if e["kind"] == "project")
        filed = client.patch(
            f"/api/entity/{project}",
            json={"base_commit": index["head"], "fields": {"parent": product}, "body": None},
        )
        assert filed.status_code == 200, filed.json()
        after = client.get("/api/index.json").json()["entities"]
        assert after[project]["parent"] == product


def test_a_status_on_a_product_still_warns_rather_than_refuses(tmp_path: Path):
    """The `statuses=()` half of the write gate: a kind that does not read the
    field gets no vocabulary check at the door. `status: ready` written into a
    product's file by hand is a warning beside the record, not a refusal
    (`test_a_container_has_no_work_state_to_gate` above), and the API door has
    to answer the same — 201 with the warning — or the two ways of writing a
    record stop being equal, which the README calls first-class on purpose.
    """
    import pygit2
    from fastapi.testclient import TestClient
    from test_store import commit_directly
    from test_web import ANN, SECRET, SEED, SESSION_COOKIE, sign_session

    from openproj.web import create_app

    plan = tmp_path / "plan.git"
    pygit2.init_repository(str(plan), bare=True, initial_head="main")
    commit_directly(plan, SEED, "seed")

    with TestClient(create_app(plan, auth="dev", secret=SECRET)) as client:
        client.cookies.set(SESSION_COOKIE, sign_session(ANN, SECRET))
        head = client.get("/healthz").json()["head"]
        made = client.post(
            "/api/entity",
            json={"base_commit": head,
                  "fields": {"kind": "product", "title": "gt4py", "status": "ready"},
                  "body": "The DSL under icon4py.\n"},
        )
        assert made.status_code == 201, made.json()
        product = made.json()["id"]
        said = [
            (p["severity"], p["field"])
            for p in client.get("/api/index.json").json()["problems"]
            if p["entity_id"] == product
        ]
        assert said == [("warning", "status")], said


def test_a_product_can_be_patched_and_deleted(tmp_path: Path):
    """`ID_PATTERN` was hand-written as three kinds while `PREFIX` three lines
    under it was derived, so `POST /api/entity` minted `prod-` ids that
    `_directory_for` then answered 400 to: a product could be created and never
    edited or removed again. The pattern is derived from `KINDS` now; this
    drives both doors that opens.
    """
    import pygit2
    from fastapi.testclient import TestClient
    from test_store import commit_directly
    from test_web import ANN, SECRET, SEED, SESSION_COOKIE, sign_session

    from openproj.web import create_app

    plan = tmp_path / "plan.git"
    pygit2.init_repository(str(plan), bare=True, initial_head="main")
    commit_directly(plan, SEED, "seed")

    with TestClient(create_app(plan, auth="dev", secret=SECRET)) as client:
        client.cookies.set(SESSION_COOKIE, sign_session(ANN, SECRET))
        head = client.get("/healthz").json()["head"]
        made = client.post(
            "/api/entity",
            json={"base_commit": head,
                  "fields": {"kind": "product", "title": "gt4py"},
                  "body": "The DSL under icon4py.\n"},
        )
        assert made.status_code == 201, made.json()
        product = made.json()["id"]

        renamed = client.patch(
            f"/api/entity/{product}",
            json={"base_commit": made.json()["commit"],
                  "fields": {"title": "gt4py-next"}, "body": None},
        )
        assert renamed.status_code == 200, renamed.json()
        entities = client.get("/api/index.json").json()["entities"]
        assert entities[product]["title"] == "gt4py-next"

        gone = client.request(
            "DELETE", f"/api/entity/{product}",
            json={"base_commit": renamed.json()["commit"]},
        )
        assert gone.status_code == 200, gone.json()
        assert client.get(f"/detail/{product}").status_code == 404
