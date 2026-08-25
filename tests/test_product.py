"""The rung above project, and the ladder every kind is now read from.

A product groups the codebases one plan spans — hearth under kiln4py, and the
tools beside them —
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
    list — `_RECORD_DIRS` in `model.py`, `DIRECTORY` in `web.py`, `PREFIX`,
    `_KIND_MODELS` and `KINDS` in `render.py` — and the one that failed silently
    was `_RECORD_DIRS`: a plan holding two products loaded thirty-three records,
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
    # and which were therefore still spelled out by hand. `POST /api/record` with
    # `kind: product` raised KeyError twice over and answered 500 on the only
    # route that can create one, on a branch whose whole subject was the ladder.
    assert web.MODELS == {rung.name: rung.model for rung in KINDS}
    assert web.PREFIX == {rung.name: rung.prefix for rung in KINDS}
    # Every field of every kind, so a rung that declares one is writable through
    # the API on the commit that adds it.
    for rung in KINDS:
        assert set(rung.model.model_fields) <= set(web.RECORD_FIELDS), rung.name


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
    one = Product(id="prod-000001", kind="product", title="hearth",
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
        "---\nid: prod-000001\nkind: product\ntitle: hearth\n"
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
    one = Product(id="prod-000001", kind="product", title="hearth",
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

    from openproj.model import Record

    with pytest.raises(ValidationError):
        Record(id="task-abc123", kind="epic", title="T")


@pytest.fixture
def plan(tmp_path: Path) -> Path:
    """Two products, and a pitch in one waiting on a pitch in the other — the
    cross-product dependency this kind exists for."""
    root = tmp_path / "plan"
    for name in ("products", "projects", "pitches", "config"):
        (root / name).mkdir(parents=True)
    (root / "config" / "defaults.yaml").write_text("schema_version: 2\n")
    (root / "products" / "prod-000001.md").write_text(
        "---\nid: prod-000001\nkind: product\ntitle: kiln4py\n---\n\nThe port.\n")
    (root / "products" / "prod-000002.md").write_text(
        "---\nid: prod-000002\nkind: product\ntitle: hearth\n---\n\nThe DSL under it.\n")
    (root / "projects" / "proj-000001.md").write_text(
        "---\nid: proj-000001\nkind: project\ntitle: The port\nparent: prod-000001\n"
        "status: ready\nowner: ann\nreviewers: [bo]\n---\n\nx\n")
    (root / "projects" / "proj-000002.md").write_text(
        "---\nid: proj-000002\nkind: project\ntitle: The DSL\nparent: prod-000002\n"
        "status: ready\nowner: bo\nreviewers: [ann]\n---\n\nx\n")
    (root / "pitches" / "pitch-000002.md").write_text(
        "---\nid: pitch-000002\nkind: pitch\ntitle: Stencil lowering\n"
        "parent: proj-000002\nstatus: ready\nowner: bo\nreviewers: [ann]\n"
        "person_weeks: 3\n---\n\nx\n")
    (root / "pitches" / "pitch-000001.md").write_text(
        "---\nid: pitch-000001\nkind: pitch\ntitle: Port the transport\n"
        "parent: proj-000001\nstatus: ready\nowner: ann\nreviewers: [bo]\n"
        "person_weeks: 2\ndepends_on: [pitch-000002]\n---\n\nx\n")
    return root


def test_work_in_one_product_can_wait_on_work_in_another(plan: Path):
    """The whole reason for the kind. Four separate plans cannot express this at
    all; one plan expresses it as an ordinary dependency."""
    records, config, unreadable = load_repo(plan)
    assert not unreadable, unreadable
    assert sorted(e.id for e in records if e.kind == "product") == [
        "prod-000001", "prod-000002",
    ]

    index = build_index(records, config, date(2026, 8, 20))
    assert index.blocked_by["pitch-000001"] == ["pitch-000002"]

    # And each side knows which product it is in, walking past its project.
    assert _product_of(index.plan["pitch-000001"], index.plan) == "prod-000001"
    assert _product_of(index.plan["pitch-000002"], index.plan) == "prod-000002"
    # `project` still means project, not "the top of the tree".
    assert _project_of(index.plan["pitch-000001"], index.plan) == "proj-000001"

    blockers = [p for p in validate_all(records, config) if p.severity == "blocker"]
    assert not blockers, [(p.record_id, p.message) for p in blockers]


def test_a_product_draws_no_bar_on_the_timeline(plan: Path):
    """It groups work and does none, so it has no dates to draw. Given a span it
    drew a bar spanning everything beneath it — a rectangle behind every real bar,
    saying nothing the bars do not."""
    from openproj.render import ROUTES, render_timeline

    records, config, _ = load_repo(plan)
    index = build_index(records, config, date(2026, 8, 20))

    assert "prod-000001" not in index.spans
    assert "pitch-000001" in index.spans, "the rest of the plan stopped being scheduled"
    assert 'data-id="prod-000001"' not in render_timeline(index, ROUTES)


def test_a_product_adds_no_indent_to_the_work_beneath_it(seed_root: Path):
    """A rung the timeline never draws must not be a level it indents by either.

    `_containment_rows` walks the chain and counts, and the product rung was put
    above `project` after that arithmetic was written. Nothing has run it against
    a chain four rungs long: the synthetic plans in `test_render` stop at
    project, and every project in every committed file had `parent: null` until
    the frozen corpus grew a product over both of its projects. An off-by-one
    here is silent — every row on the page shifts one level, the page renders,
    nothing raises, and the drawing reads as a plan with a different shape.

    Asked of the frozen corpus rather than of a plan built for the question,
    because the two projects under two different products are what make it a
    walk rather than a subtraction of one.
    """
    from openproj.render import _containment_rows

    records, config, _ = load_repo(seed_root)
    index = build_index(records, config, date(2026, 8, 17))
    depth = dict(_containment_rows(index, set(index.spans)))

    assert index.plan["proj-9a4c25"].parent == "prod-7c2b81"
    assert "prod-7c2b81" not in index.spans, "a product with a span would be a row of its own"
    assert depth["proj-9a4c25"] == 0, "the product above it is not a level"
    assert depth["pitch-6f2d18"] == 1
    assert depth["task-6a5c02"] == 2

    # And the older half of the corpus, which gained a product without moving.
    assert index.plan["proj-7e57a0"].parent == "prod-6d1a70"
    assert (depth["proj-7e57a0"], depth["task-0e4b7a"]) == (0, 1)
    assert not {"prod-6d1a70", "prod-7c2b81"} & set(depth), "no product is a row"


def test_a_product_is_drawn_differently_and_shows_no_card(plan: Path):
    """jcanton asked for both: a shape of its own, and no hover card.

    The card would be a box of dashes — a product has no owner, no dates, no
    appetite and no shaping document — and a card of dashes teaches a reader that
    cards are not worth hovering for. `carded` is on the ladder because the same
    question gets asked on more than one page.
    """
    from openproj.render import ROUTES, render_graph

    records, config, _ = load_repo(plan)
    index = build_index(records, config, date(2026, 8, 20))
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
        "---\nid: prod-000001\nkind: product\ntitle: hearth\nstatus: ready\n---\n\nx\n",
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
        "---\nid: prod-000001\nkind: product\ntitle: hearth\n---\n\nx\n",
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
            "/api/record",
            json={"base_commit": base,
                  "fields": {"kind": "product", "title": "hearth"},
                  "body": "The DSL under kiln4py.\n"},
        )
        assert made.status_code == 201, made.json()
        product = made.json()["id"]
        assert product.startswith("prod-")
        assert client.get(f"/detail/{product}").status_code == 200

        # And a project files under it, which is the whole point of the rung.
        index = client.get("/api/index.json").json()
        assert index["plan"][product]["kind"] == "product"
        project = next(i for i, e in index["plan"].items() if e["kind"] == "project")
        filed = client.patch(
            f"/api/record/{project}",
            json={"base_commit": index["head"], "fields": {"parent": product}, "body": None},
        )
        assert filed.status_code == 200, filed.json()
        after = client.get("/api/index.json").json()["plan"]
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
            "/api/record",
            json={"base_commit": head,
                  "fields": {"kind": "product", "title": "hearth", "status": "ready"},
                  "body": "The DSL under kiln4py.\n"},
        )
        assert made.status_code == 201, made.json()
        product = made.json()["id"]
        said = [
            (p["severity"], p["field"])
            for p in client.get("/api/index.json").json()["problems"]
            if p["record_id"] == product
        ]
        assert said == [("warning", "status")], said


def test_a_product_can_be_patched_and_deleted(tmp_path: Path):
    """`ID_PATTERN` was hand-written as three kinds while `PREFIX` three lines
    under it was derived, so `POST /api/record` minted `prod-` ids that
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
            "/api/record",
            json={"base_commit": head,
                  "fields": {"kind": "product", "title": "hearth"},
                  "body": "The DSL under kiln4py.\n"},
        )
        assert made.status_code == 201, made.json()
        product = made.json()["id"]

        renamed = client.patch(
            f"/api/record/{product}",
            json={"base_commit": made.json()["commit"],
                  "fields": {"title": "hearth-next"}, "body": None},
        )
        assert renamed.status_code == 200, renamed.json()
        records = client.get("/api/index.json").json()["plan"]
        assert records[product]["title"] == "hearth-next"

        gone = client.request(
            "DELETE", f"/api/record/{product}",
            json={"base_commit": renamed.json()["commit"]},
        )
        assert gone.status_code == 200, gone.json()
        assert client.get(f"/detail/{product}").status_code == 404


def test_a_products_row_is_empty_where_a_product_holds_nothing(plan: Path):
    """The table draws one row shape for every kind, and a product reads eleven
    fewer fields than the rows around it.

    jcanton, 2026-08-25: "a product has no status, but in the table the status
    cell has a chip with background and color, that should not be there, nor
    should any of the other cells contain anything (currently I see blockers and
    progress)". Three separate mechanisms put content in those cells, and only
    one of them was a value:

    - `status` arrived as `null` — `_row` has withheld it since the ladder gained
      `Rung.statuses` — and the cell drew the chip anyway. `priority` beside it
      was guarded and `status` was not, so the ground colour of an unknown rung
      sat behind an empty word, which reads as a status this record has and
      nobody can name.
    - `blocked_by` was counted for every row. A product cannot depend on
      anything, so the count was always `0` and always drawn: a nought is not an
      empty cell, and a column headed Blockers saying `0` about a codebase is a
      field the record does not have, answered.
    - `progress` rolled its children up in weeks, correctly and irrelevantly. A
      product groups the codebases a plan spans; "42% done" beside one is a
      sentence about the plan wearing the name of the thing it is filed under.

    Driven rather than read off the payload, because the cells are built by
    `cellHtml` at runtime and appear in no rendered file — the row is the claim,
    and `_row` returning `None` says nothing about what the script does with it.
    Two rows are read: a product, and a pitch beneath it as the control that
    would fail if this test simply found an empty table.
    """
    from pages import elements
    from test_injection import run_js

    from openproj.render import ROUTES, render_table

    records, config, _ = load_repo(plan)
    index = build_index(records, config, date(2026, 8, 20))
    counted = index.progress.get("prod-000001")
    assert counted is not None, (
        "the fixture's product rolls nothing up, so the progress half of this "
        "test would pass on an empty column"
    )

    page = render_table(index, ROUTES, base_commit="0" * 40, may_write=True)
    drawn = run_js(page, "null", page=True)
    assert not drawn["errors"], drawn["errors"]
    body = next((str(s) for s in drawn["written"] if 'data-id="prod-000001"' in str(s)), None)
    assert body is not None, "the table drew no row for the product"

    def cells(row_id: str) -> dict[str, dict]:
        """One row's cells: column -> the text, the td's classes, and every
        element drawn INSIDE it.

        The inside is the half that matters here and the half a text comparison
        cannot see: `human(null)` is the empty string and so is the glyph beside
        it, so the status chip this test exists for contains no text at all. It
        is a coloured box, and a cell that reads `''` while painting one is
        exactly what jcanton was looking at.
        """
        found: dict[str, dict] = {}
        inside = False
        column: str | None = None
        for element in elements(body):
            if element.tag == "tr":
                inside, column = element.attrs.get("data-id") == row_id, None
            elif element.tag == "td":
                column = element.attrs.get("data-col", "") if inside else None
                if column is not None:
                    found[column] = {
                        "text": element.text,
                        "classes": element.attrs.get("class", "").split(),
                        "inside": [],
                    }
            elif inside and column is not None:
                found[column]["inside"].append(
                    (element.tag, element.attrs.get("class", ""))
                )
        return found

    product = cells("prod-000001")
    assert product, "the product's row has no cells"
    # What a product IS: an id and a title, and tags if anybody wrote any.
    holds = {"id", "title", "tags"}
    for column, cell in product.items():
        if column in holds:
            continue
        assert cell["text"] == "", (
            f"the product's {column} cell says {cell['text']!r}, and a product "
            f"has no {column}"
        )
        assert cell["inside"] == [], (
            f"the product's {column} cell draws {cell['inside']} — an empty cell "
            "that paints something is the chip this was reported as"
        )
        assert "edit" not in cell["classes"], (
            f"the product's {column} cell has no value and still opens an editor "
            "that would write the field into the file"
        )

    # The control. The same columns on the pitch beneath it, which does read
    # them — without this every assertion above passes on a table of empty rows.
    pitch = cells("pitch-000001")
    assert ("span", "chip st-ready") in pitch["status"]["inside"], (
        f"the pitch lost the chip a status is drawn as: {pitch['status']}"
    )
    assert "edit" in pitch["status"]["classes"], (
        "the per-kind gate took the editor off a row that does read a status"
    )
    assert pitch["blocked_by"]["text"] == "1", (
        "the pitch waits on one thing and its cell no longer says so: "
        f"{pitch['blocked_by']}"
    )
    assert pitch["owner"]["text"] == "ann", pitch["owner"]
