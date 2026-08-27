"""The exclusion: a kind whose rung says `planned=False` is off every PM surface.

Spec §2 ("one record, one page"): `Index.plan` is the plan and only the
plan; `Index.records` is every record that parsed. The inversion makes every
existing consumer safe — a forgotten one sees fewer records, never more — and
the validator on `Index` is the by-construction guarantee the type system gave
up when every kind became a Record.

Two layers, on purpose:

* The KINDS-derived sweep. It iterates the ladder and covers every rung with
  `planned=False`, so a seventh unplanned rung is covered the day it is added
  and the sweep cannot go stale. Until the flip commit lands there is no such
  rung, and the sweep SKIPS WITH A STATED REASON rather than passing vacuously
  — `addopts = -ra` puts that skip in every CI summary, so it is a visible
  countdown, not silence. The flip commit un-skips it by existing: nothing in
  this file needs an edit on that day.
* The machinery tests. They cannot wait for the flip, so they make an unplanned
  rung out of the ladder itself — `RUNG["task"]._replace(planned=False)` under
  `monkeypatch.setitem` — derived from a real rung rather than invented, so the
  fake cannot drift from the shape of one.

Vacuous until the commit that put issue and note on the ladder; from that
commit it seeds one issue and one note and asserts each is absent from /table,
/graph, /timeline, /people, the schedule payload, /api/index.json, every facet
and the suggestions blob's record completions, present on / and its own
/detail page, and refused by the Index validator. (The suggestions blob's
people and tag lists deliberately DO carry unplanned records — the record
completions are the plan-only part — and every seed carries a tag so that
exemption is asserted rather than only documented.) The served corpus also
carries one planned task whose hand-written `depends_on` names the seeded
issue: that is the edge `blocked_by` keeps because it is total over records,
and the one that 500ed /table and leaked into /graph before the plan pages
learned to read the total map and to draw only plan edges. And a second whose
hand-written `parent` names the same issue — the containment twin of that
edge, which rode `_row` onto every plan payload and onto the table's move bar
("Take task-… out of issue-…") until `parent` learned the same resolve-or-null
rule. The corpus holding one of the two edge kinds is exactly how the second
went unseen.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pygit2
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from test_index import CONFIG, TODAY, a_family, a_task
from test_store import commit_directly
from test_web import SEED

from openproj.cli import main
from openproj.index import Index, apply_filters, build_index
from openproj.model import KINDS, RUNG, Rung, parse_text
from openproj.web import create_app

# A word no fixture, template or chrome string contains, so "absent from the
# rendered page" is a claim about this record and nothing else.
NEEDLE = "xsweepneedle"
# A tag with the same property, on every seed, asked the OTHER way round: the
# suggestion blob is records-wide on purpose (`_suggestions` in render.py), so
# this one must be PRESENT where tags are edited. Not a substring of NEEDLE,
# or the absence assertions would ban it too.
TAG = "xsweeptag"

UNPLANNED = tuple(rung for rung in KINDS if not rung.planned)


def _armed() -> tuple[Rung, ...]:
    """The rungs the sweep covers, or a REPORTED skip while there are none.

    A skip and not a pass: with zero unplanned rungs every loop below is
    vacuous, and a vacuous green is indistinguishable from a real one. The
    skip shows in CI's `-ra` summary on every run until the flip commit adds
    the issue and note rungs, at which point this returns them and the sweep
    runs for real — no edit here, ever.
    """
    if not UNPLANNED:
        pytest.skip(
            "no rung with planned=False in KINDS yet - the sweep arms itself on "
            "the flip commit that adds the issue and note rungs"
        )
    return UNPLANNED


def _seed_for(rung: Rung) -> tuple[str, str, str]:
    """(id, path, file text) for one minimal record of `rung`'s kind.

    Derived from the ladder — prefix, directory, status vocabulary — and
    carrying only what every kind has: id, kind, title, and the first word of
    the rung's own ladder. If a future unplanned kind grows a required field,
    `parse_text` refuses this text and the sweep fails LOUDLY, which is the
    correct failure: extend this helper, never skip the kind.

    Plus one hand-written unread field, so every seed carries exactly one
    WARNING: the plan-only problem lists (`/api/index.json`, the table
    payload) are asserted not to name these ids, and an assertion over lists
    that would have been empty anyway is an assertion that cannot fail.
    `review_waived` because it is a work field no unplanned rung reads and it
    feeds no suggestion blob; the sweep asserts the warning exists on the
    record's own page, so if a future unplanned rung starts reading it, the
    non-vacuity check fails loudly rather than this going quiet.

    And one tag, `TAG`, which DOES feed a suggestion blob: the blob is
    records-wide by design, and the seed is what lets a test hold the
    exemption open instead of a tightening closing it in silence.
    """
    eid = f"{rung.prefix}-0faded"
    front = [f"id: {eid}", f"kind: {rung.name}", f"title: {NEEDLE} {rung.name}"]
    if rung.statuses:
        front.append(f"status: {rung.statuses[0]}")
    front.append("review_waived: true")
    front.append(f"tags: [{TAG}]")
    text = "---\n" + "\n".join(front) + "\n---\n\nSeeded by the exclusion sweep.\n"
    return eid, f"{rung.directory}/{eid}.md", text


def test_with_only_planned_kinds_the_records_are_exactly_the_plan():
    """The load-bearing fact of this commit: the inversion lands before any
    unplanned kind exists, so the two populations are equal and every existing
    consumer is untouched by construction."""
    index = build_index(a_family(), CONFIG, TODAY)
    assert index.records == index.plan


def test_build_index_keeps_an_unplanned_kind_out_of_the_plan(monkeypatch):
    """Index purity, testable before the flip: the fake unplanned rung is the
    real task rung with one field changed, so it cannot drift from the shape
    of a rung. Only `planned` flips — the rest of the rung stays as it is, so
    everything else `build_index` does is undisturbed."""
    monkeypatch.setitem(RUNG, "task", RUNG["task"]._replace(planned=False))
    index = build_index(a_family(), CONFIG, TODAY)

    dropped = sorted(eid for eid in index.records if eid.startswith("task-"))
    assert dropped == ["task-c00001", "task-c00002"], "the family's tasks are the fixture"
    for eid in dropped:
        assert eid not in index.plan, f"{eid} leaked into the plan"
        assert eid in index.records

    # The maps a record page and the landing search read are TOTAL: a fact row
    # cannot KeyError and a record cannot be missing from its own search.
    everyone = set(index.records)
    assert set(index.children) == everyone
    assert set(index.blocked_by) == everyone
    assert set(index.blocks) == everyone
    assert set(index.search_blob) == everyone

    # Facets are plan facts: no dropped id anywhere, and the kind menu does
    # not offer the word — a facet that can only ever match nothing.
    for field, values in index.facets.items():
        for eid in dropped:
            assert eid not in values, f"{eid} appears in the {field} facet"
    assert "task" not in index.facets["kind"]

    # One search, two populations: the default is the plan and fails closed;
    # the landing asks for everything by name.
    assert "task-c00001" not in apply_filters(index, {}, "first")
    assert "task-c00001" in apply_filters(index, {}, "first", over=index.records)


def test_a_hand_built_index_smuggling_an_unplanned_kind_is_refused(monkeypatch):
    """`build_index` filtering is one half; the validator is the guarantee that
    no OTHER construction path — a future cache, a test fixture, a refactor —
    can put an unplanned kind in the plan either."""
    monkeypatch.setitem(RUNG, "task", RUNG["task"]._replace(planned=False))
    good = build_index(a_family(), CONFIG, TODAY)
    sneaked = a_task("task-0faded", "Smuggled into the plan")
    with pytest.raises(ValidationError) as refusal:
        Index(**{**dict(good), "plan": {**good.plan, sneaked.id: sneaked}})
    said = str(refusal.value)
    assert "task-0faded is a task" in said, "the refusal names the id and the kind"
    assert ".records" in said, "and says where the record belongs instead"


def test_every_unplanned_kind_is_out_of_the_plan_and_in_the_records():
    unplanned = _armed()
    records = a_family()
    seeded: list[tuple[Rung, str]] = []
    for rung in unplanned:
        eid, path, text = _seed_for(rung)
        records.append(parse_text(text, path))
        seeded.append((rung, eid))

    index = build_index(records, CONFIG, TODAY)
    for rung, eid in seeded:
        assert eid not in index.plan, f"a {rung.name} leaked into the plan"
        assert eid in index.records, f"the {rung.name} fell out of the record population"
        # The scheduler never dates it, so no payload built from spans can name it.
        assert eid not in index.spans and eid not in index.explanations
        for field, values in index.facets.items():
            assert eid not in values, f"{eid} appears in the {field} facet"
        assert rung.name not in index.facets["kind"], "a facet that can only match nothing"
        # Total maps: the fact rows and the landing search cannot KeyError.
        assert eid in index.blocked_by and eid in index.blocks
        assert eid in index.search_blob
        # Found by the landing search, invisible to the table's.
        assert eid in apply_filters(index, {}, NEEDLE, over=index.records)
        assert eid not in apply_filters(index, {}, NEEDLE)


def test_the_schedule_payload_never_names_an_unplanned_kind(tmp_path: Path, capsys):
    unplanned = _armed()
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "defaults.yaml").write_text(
        "schema_version: 2\nnominal_availability: 1.0\ndefault_task_effort: 0.5\n"
    )
    (tmp_path / "tasks").mkdir()
    (tmp_path / "tasks" / "task-c00001.md").write_text(
        "---\nid: task-c00001\nkind: task\ntitle: Planned work\nstatus: ready\n"
        "owner: ann\nreviewers: [bo]\nperson_weeks: 1\n---\n\nA task.\n"
    )
    seeded = []
    for rung in unplanned:
        eid, path, text = _seed_for(rung)
        (tmp_path / rung.directory).mkdir(exist_ok=True)
        (tmp_path / path).write_text(text)
        seeded.append(eid)

    assert main(["schedule", str(tmp_path), "--json", "--today", "2026-08-13"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert "task-c00001" in payload["plan"], "the planned control is scheduled"
    for eid in seeded:
        assert eid not in payload["plan"]
        assert eid not in payload["spans"] and eid not in payload["explanations"]


def test_no_plan_control_offers_an_unplanned_kind():
    """The table's draft row offers `Object.keys` of this map as the kinds a
    new row can be, and the table is a plan view: an issue typed into it would
    be created and then never appear on it — a control whose result is a
    vanishing row. Derived from the ladder, so a seventh unplanned rung is held
    out by this same line."""
    from openproj.render import _new_row_fields

    assert set(_new_row_fields()) == {rung.name for rung in KINDS if rung.planned}


@pytest.fixture
def sweep_client(tmp_path: Path):
    """The SEED corpus plus one record of every unplanned kind, served — and
    one planned task per stored edge kind whose hand-written edge names an
    unplanned seed: `depends_on` on one, `parent` on the other.

    The first is the armed hazard this fixture began with: `blocked_by` is
    total over records, so the edge survives into the plan pages' derivations,
    where a plan-only lookup was a KeyError (a 500 on /table) and an
    unfiltered edge list put the issue's id into /graph. The second is its
    containment twin, added after review: `_row` shipped the stored `parent`
    raw, which put the issue's id into every plan payload and onto the table's
    move bar — the corpus carrying one edge kind of two is the whole reason
    that one went unseen. Without both, the sweep goes green with a page one
    hand-written line away from leaking or 500ing.
    """
    unplanned = _armed()
    path = tmp_path / "plan.git"
    pygit2.init_repository(str(path), bare=True, initial_head="main")
    seeded = dict(SEED)
    for rung in UNPLANNED:
        _, file_path, text = _seed_for(rung)
        seeded[file_path] = text
    blocker_id, _, _ = _seed_for(unplanned[0])
    seeded["tasks/task-0b10c0.md"] = (
        "---\nid: task-0b10c0\nkind: task\ntitle: waits on an unplanned record\n"
        "status: ready\nowner: ann\nassignees: [ann]\nreviewers: [bo]\n"
        f"person_weeks: 1\ndepends_on: [{blocker_id}]\n---\n\nHand-written edge.\n"
    )
    seeded["tasks/task-0b10c1.md"] = (
        "---\nid: task-0b10c1\nkind: task\ntitle: filed under an unplanned record\n"
        "status: ready\nowner: ann\nassignees: [ann]\nreviewers: [bo]\n"
        f"person_weeks: 1\nparent: {blocker_id}\n---\n\nHand-written parent.\n"
    )
    commit_directly(path, seeded, "seed the exclusion sweep corpus")
    with TestClient(create_app(path, auth="dev", secret="a-sweep-signing-secret")) as client:
        yield client


# Every PM page the spec names as a `plan` reader. The whole document is
# one response — rows, embedded payload, facet bar, suggestions datalist — so
# absence of the id and the title needle from the text is absence from all of
# them at once. The cycle pages and the deck render whatever number they are
# asked for, corpus or no corpus, so a bare `1` exercises the same readers;
# /api/table.json is the table's payload served without the page around it,
# and it leaks or it does not exactly as /table does.
PLAN_PAGES = (
    "/table",
    "/graph",
    "/timeline",
    "/people",
    "/cycles",
    "/cycle/1",
    "/deck/1",
    "/api/table.json",
)


def test_an_unplanned_record_is_on_its_own_page_and_the_landing_and_nowhere_else(
    sweep_client: TestClient,
):
    for rung in _armed():
        eid, _, _ = _seed_for(rung)
        for route in PLAN_PAGES:
            page = sweep_client.get(route)
            assert page.status_code == 200
            assert eid not in page.text, f"{eid} leaked onto {route}"
            assert NEEDLE not in page.text, f"the {rung.name}'s title leaked onto {route}"

        listed = sweep_client.get("/api/index.json").json()
        assert eid not in listed["plan"], "the external contract is plan-only"
        assert eid not in listed["spans"]
        # The problems list too: its keys are ids the payload's own `plan`
        # map must be able to resolve, and every seed deliberately carries one
        # warning (see `_seed_for`) so this line has something to hold out.
        assert eid not in {p["record_id"] for p in listed["problems"]}, (
            "a problem keyed by an unplanned id rode the plan-only contract"
        )

        # Present exactly where a record lives: the landing list, and its own page.
        landing = sweep_client.get("/")
        assert landing.status_code == 200 and eid in landing.text
        own = sweep_client.get(f"/detail/{eid}")
        assert own.status_code == 200 and NEEDLE in own.text
        # The seeded warning is real and drawn beside the record — which is what
        # makes the problems assertion above non-vacuous, and what fails loudly
        # if a future unplanned rung starts reading `review_waived`.
        assert "review_waived is not read" in own.text, (
            f"the {rung.name} seed lost its warning, so the problems assertion "
            "above is checking an empty list"
        )


def test_an_inbox_tag_is_offered_where_tags_are_edited_and_its_id_is_not(
    sweep_client: TestClient,
):
    """The one exemption the sweep's docstring names, held open by a tooth.

    `_suggestions` (render.py) reads `index.records` on purpose: an inbox
    record's tags — and its reporter's and writer's names — belong in the
    pickers on the pages where those fields are typed, or `reported_by` could
    never complete a name that only ever appears on issues. Nothing asserted
    that, so a tightening of the blob back to the plan would have narrowed
    every picker in silence while all the absence tests above stayed green.
    The record completions in the SAME blob stay plan-only — offering an issue
    to `parent` or `depends_on` is offering an edge the model refuses — so
    both halves of the one decision are read off one page.
    """
    unplanned = _armed()
    for route in ("/table", "/cycle/1"):
        page = sweep_client.get(route)
        blob = re.search(
            r'<script id="suggest" type="application/json">(.*?)</script>',
            page.text,
            re.S,
        )
        assert blob, f"{route} lost its suggestion blob, so this asserts nothing"
        suggest = json.loads(blob.group(1))
        assert TAG in [t["value"] for t in suggest["tags"]], (
            f"the inbox tag fell out of {route}'s tag picker"
        )
        offered = [e["value"] for e in suggest["records"]]
        for rung in unplanned:
            eid, _, _ = _seed_for(rung)
            assert eid not in offered, f"{eid} is offered where edges are typed"


def test_a_row_filed_under_an_unplanned_record_refuses_the_move_and_says_where(
    sweep_client: TestClient,
):
    """The gesture half of the `parent` hazard, driven in the page's own script.

    The byte half is the sweep above: the payload nulls a parent the plan
    cannot resolve, so the id is not in the page. This half asks what the
    move gesture does with the flag that travels instead. It must refuse the
    way the graph's `off_plan_deps` twin refuses — at pick-up time, nothing
    attempted — because a drop or the unparent bar would PATCH `parent` over
    a hand-written line the table never drew, and the server cannot tell that
    from the record page legitimately refiling it. No grip, `movable` false,
    and the sentence says the two things the graph's refusal says: what this
    page cannot show, and where it is edited.
    """
    from test_injection import run_js

    # No `_armed()` of its own: `sweep_client` is the gate, and it skips this
    # test with the fixture's stated reason while no unplanned rung exists.
    page = sweep_client.get("/table").text
    answer = run_js(
        page,
        "(() => {"
        "  const row = DATA.rows['task-0b10c1'];"
        "  return {parent: row.parent, off: row.off_plan_parent,"
        "          can: movable(row), tip: moveTip(row),"
        "          grip: !!tbody.querySelector('tr[data-id=\"task-0b10c1\"] .rowgrip')};"
        "})()",
        page=True,
    )
    assert not [e for e in answer["errors"] if e.startswith("expression:")], answer["errors"]
    got = answer["value"]
    assert got["parent"] is None, "the raw parent id reached the payload"
    assert got["off"] is True, "the payload lost the flag the refusal turns on"
    assert got["can"] is False and got["grip"] is False, "the move is still offered"
    assert got["tip"] == (
        "task-0b10c1 is filed under something this table cannot show — "
        "where it belongs is edited on its own page"
    )
