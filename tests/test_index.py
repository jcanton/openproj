"""The index and its filters.

The index is the single in-memory snapshot the table, the graph and the timeline
are all rendered from, so these tests pin the two things a view cannot recover on
its own: that every derived structure is DERIVED (`blocks` is the reverse of
`depends_on`, never a stored field), and that the filter model is exactly the one
the spec promises — AND across fields, OR within a field, plus the computed
predicates.

Two conventions are fixed here because query parameters are the only filter state
there is: facet values and filter values are always strings, and `apply_filters`
returns ids sorted by id so that a shared URL renders identically twice.
"""

from datetime import date
from pathlib import Path

import pytest

from openproj.index import (
    COMPUTED_PREDICATES,
    NO_VALUE,
    Index,
    _matches_predicate,
    apply_filters,
    build_index,
)
from openproj.model import (
    Config,
    Pitch,
    Product,
    Project,
    Record,
    Task,
    load_repo,
    parse_text,
    validate_all,
)
from openproj.schedule import schedule

TODAY = date(2026, 8, 13)

CONFIG = Config(
    schema_version=2,
    nominal_availability=1.0,
    cycles={36: (date(2026, 6, 22), date(2026, 8, 14))},
)


def a_product(id: str, title: str = "A product", **fields) -> Product:
    return Product(id=id, kind="product", title=title, **fields)


def a_project(id: str, title: str = "A project", **fields) -> Project:
    return Project(id=id, kind="project", title=title, **fields)


def a_pitch(id: str, title: str = "A pitch", **fields) -> Pitch:
    return Pitch(id=id, kind="pitch", title=title, **fields)


def a_task(id: str, title: str = "A task", **fields) -> Task:
    return Task(id=id, kind="task", title=title, **fields)


def a_family() -> list[Record]:
    """One project, one pitch under it, two tasks under the pitch, one dependency."""
    return [
        a_project("proj-a00001", "Griddle", owner="alice", reviewers=["bob"]),
        a_pitch(
            "pitch-b00001", "Halo exchange", parent="proj-a00001", person_weeks=2.0, status="ready"
        ),
        a_task("task-c00001", "First", parent="pitch-b00001", owner="alice", person_weeks=1.0),
        a_task(
            "task-c00002",
            "Second",
            parent="pitch-b00001",
            owner="bob",
            person_weeks=1.0,
            depends_on=["task-c00001"],
        ),
    ]


@pytest.fixture
def family_index() -> Index:
    return build_index(a_family(), CONFIG, TODAY)


@pytest.fixture
def seed_index(seed_root: Path) -> Index:
    records, config, _ = load_repo(seed_root)
    return build_index(records, config, TODAY)


# --- structure -------------------------------------------------------------


def test_children_lists_each_parents_children_by_id(family_index: Index):
    assert family_index.children["proj-a00001"] == ["pitch-b00001"]
    assert family_index.children["pitch-b00001"] == ["task-c00001", "task-c00002"]


def test_every_record_is_a_key_in_every_edge_map(family_index: Index):
    """A childless or unblocked record gets an empty list, not a missing key: the
    views index these maps directly and a KeyError there is a blank page. The
    maps are total over `records`, not over the plan — the record page draws
    fact rows for every kind."""
    ids = set(family_index.records)
    assert set(family_index.children) == ids
    assert set(family_index.blocked_by) == ids
    assert set(family_index.blocks) == ids
    assert family_index.children["task-c00001"] == []
    assert family_index.blocked_by["task-c00001"] == []


def test_blocks_is_the_reverse_of_depends_on(family_index: Index):
    assert family_index.blocked_by["task-c00002"] == ["task-c00001"]
    assert family_index.blocks["task-c00001"] == ["task-c00002"]
    assert family_index.blocks["task-c00002"] == []


def test_a_stored_blocks_key_in_frontmatter_is_ignored():
    """`blocks` is derived, always. A hand-written `blocks:` key is stale data by
    construction, so reading it would let a file contradict the graph."""
    text = "\n".join(
        [
            "---",
            "id: task-c00001",
            "kind: task",
            "title: First",
            "depends_on: []",
            "blocks: [task-c00002]",
            "---",
            "",
            "Body.",
        ]
    )
    lying = parse_text(text, "task-c00001.md")
    records = [lying, a_task("task-c00002", "Second")]
    index = build_index(records, CONFIG, TODAY)

    assert not hasattr(lying, "blocks")
    assert index.blocks["task-c00001"] == []
    assert index.blocked_by["task-c00002"] == []


def test_blocked_by_keeps_only_edges_to_records_that_exist():
    """A dangling id is already a validation blocker; carrying it into the edge
    maps would invent a node the graph and the reverse map cannot agree on."""
    records = [a_task("task-c00001", depends_on=["task-ffffff"])]
    index = build_index(records, CONFIG, TODAY)

    assert index.blocked_by["task-c00001"] == []
    assert "task-ffffff" not in index.blocks


def test_a_parent_that_names_nothing_does_not_take_the_whole_index_down():
    """A parent chain may end at an id no file was ever written for.

    `ancestors` returns the chain as *named*, so its last link can be an id that
    is absent from `by_id` — and `_project_of` looked that link up with `[]`.
    The KeyError came out of `build_index`, which is on the read path of `/`,
    `/detail/<id>` and `/api/index.json`, so one committed `parent` field
    answered 500 to every reader on every page, permanently, on a branch whose
    protection means the commit cannot be force-pushed away.

    A dangling parent is deliberately not a validation problem — see the `task()`
    helper in `test_validate` — so it has to be a plan the index can render.
    Unresolvable means "no project", the same answer as no parent at all.
    """
    records = [a_task("task-c00001", parent="proj-ffffff", owner="alice", person_weeks=1.0)]

    index = build_index(records, CONFIG, TODAY)

    # Unresolvable means "no project" — the same answer as no parent at all, and
    # since that is now askable from the menu it is `[NO_VALUE]` rather than the
    # empty list.
    assert index.facets["project"] == [NO_VALUE]
    assert set(index.plan) == {"task-c00001"}


def test_a_parent_chain_that_ends_outside_the_plan_still_finds_the_project_it_names():
    """The half of the same walk that must keep working: a chain that reaches a
    real project reports it, even though a later link is missing."""
    records = [
        a_project("proj-a00001", "Griddle"),
        a_pitch("pitch-b00001", parent="proj-a00001"),
        a_task("task-c00001", parent="pitch-b00001"),
        a_task("task-c00002", parent="pitch-ffffff"),
    ]

    index = build_index(records, CONFIG, TODAY)

    # `task-c00002` names a pitch that does not exist, so it is in no project and
    # contributes the `(none)` option; the chain that does resolve still reports
    # the project it reaches.
    assert index.facets["project"] == [NO_VALUE, "proj-a00001"]


def test_the_plan_is_keyed_by_id(family_index: Index):
    assert family_index.plan["task-c00001"].title == "First"
    assert set(family_index.plan) == {
        "proj-a00001",
        "pitch-b00001",
        "task-c00001",
        "task-c00002",
    }


# --- wiring ----------------------------------------------------------------


def test_spans_and_explanations_come_from_the_scheduler():
    records = a_family()
    spans, explanations = schedule(records, CONFIG, TODAY)
    index = build_index(records, CONFIG, TODAY)

    assert index.spans == spans
    assert index.explanations == explanations
    assert index.spans["task-c00001"].start >= TODAY


def test_problems_come_from_validate_all():
    """With the SPANS, which is not a detail of the call. `validate_all` applies
    the rollup rule only when it is handed a schedule — whether a pitch's tasks
    fit is a comparison between two numbers the scheduler computes, and
    `model.py` cannot reach the scheduler to compute them — so an index that
    passed only the records would carry a strictly smaller problem set than
    `openproj check` reports about the same plan, and the page and the CLI would
    disagree about a bet with nothing to say why.
    """
    records = a_family()
    index = build_index(records, CONFIG, TODAY)
    spans, _ = schedule(records, CONFIG, TODAY)

    # `TODAY` on both sides. One rule compares a date against the day the plan is
    # drawn around — a start date that has gone by with the work not begun — so
    # asking the index about one day and the validator about another is a
    # comparison of two different questions that would agree until the pinned day
    # and the real one fell on opposite sides of a corpus date.
    assert index.problems == validate_all(records, CONFIG, spans, TODAY)
    assert index.problems, "the pitch has no owner, so the family cannot validate clean"


# --- facets and search blob ------------------------------------------------


def test_facets_cover_every_filterable_field(family_index: Index):
    assert set(family_index.facets) == {
        "kind",
        "status",
        "owner",
        "assignees",
        "reviewers",
        "priority",
        "cycle",
        "product",
        "project",
        "tags",
        "predicate",
    }


def test_the_predicate_facet_is_the_one_predicate_list(family_index: Index):
    """The filter menu is generated from the facet, so it must not be able to
    drift from the predicates `apply_filters` actually implements."""
    assert family_index.facets["predicate"] == sorted(COMPUTED_PREDICATES)


def test_facets_are_sorted_distinct_values_as_strings():
    records = [
        a_task("task-c00001", owner="bob", priority="low", cycle=36, tags=["ci", "gpu"]),
        a_task("task-c00002", owner="alice", priority="high", cycle=36, tags=["gpu"]),
        a_task("task-c00003", owner="alice", priority="high", cycle=None, tags=[]),
    ]
    facets = build_index(records, CONFIG, TODAY).facets

    assert facets["owner"] == ["alice", "bob"]
    assert facets["priority"] == ["high", "low"]
    # Two of the three name a cycle and one does not, so the menu offers both the
    # number and the question. `tags` likewise: `task-c00003` carries none.
    assert facets["cycle"] == [NO_VALUE, "36"]
    assert facets["tags"] == [NO_VALUE, "ci", "gpu"]
    assert facets["kind"] == ["task"]


def test_an_absent_value_is_a_question_and_not_a_fake_name():
    """An unset field is still not a facet VALUE — there is no owner called
    "unowned" in the menu. What there is now is one option that is not a value at
    all: `(none)`, which selects the records where the field is empty.

    It had to be added because emptiness was otherwise unaskable. An unset field
    yields nothing to select, and the blank option every menu already had means
    "no constraint" rather than "empty" — so "which pitches are not in a cycle
    yet" and "what has no reviewer", the two questions a betting table actually
    asks, had no answer anywhere in the UI.
    """
    facets = build_index([a_task("task-c00001")], CONFIG, TODAY).facets

    assert facets["owner"] == [NO_VALUE]
    assert facets["cycle"] == [NO_VALUE]
    assert facets["reviewers"] == [NO_VALUE]
    # And it is the only thing there: no invented name sits beside it.
    assert all(values == [NO_VALUE] for values in (facets["owner"], facets["cycle"]))


def test_the_project_facet_follows_the_parent_closure(family_index: Index):
    """A task names its pitch, never its project, so the project facet has to be
    walked up the parent chain or grouping by project is empty."""
    assert family_index.facets["project"] == ["proj-a00001"]
    assert apply_filters(family_index, {"project": ["proj-a00001"]}, "") == [
        "pitch-b00001",
        "proj-a00001",
        "task-c00001",
        "task-c00002",
    ]


def test_a_record_outside_any_project_matches_no_project_filter():
    records = [a_task("task-c00001", "Orphan")]
    index = build_index(records, CONFIG, TODAY)

    # The menu offers the question — an orphan is exactly what `(none)` is for —
    # and naming a project it is not in still matches nothing.
    assert index.facets["project"] == [NO_VALUE]
    assert apply_filters(index, {"project": ["proj-a00001"]}, "") == []
    assert apply_filters(index, {"project": [NO_VALUE]}, "") == ["task-c00001"]


def test_the_searchable_text_is_the_fields_and_not_the_document():
    """Fields, not bodies — jcanton, 2026-08-19.

    The shaping document IS the record, and it is still not the record's index: a
    900-word pitch in a substring search makes every long word in the plan a
    match for something, and nothing on the row says which word matched.
    """
    record = a_task(
        "task-c00001",
        "Reproduce the 2-GPU Seam Artefact",
        tags=["GPU", "ci"],
        body="Only on Firebrick.\n",
    )
    blob = build_index([record], CONFIG, TODAY).search_blob["task-c00001"]

    assert "reproduce the 2-gpu seam artefact" in blob
    assert "gpu" in blob
    assert "ci" in blob
    assert "firebrick" not in blob
    assert blob == blob.lower()


def test_the_searchable_text_holds_the_names_a_record_is_known_by():
    """The people on a record and its id are searchable, and were not.

    The rule this replaces said the opposite, and its reason was the body: with a
    whole shaping document in the blob, `alice` matched every record that merely
    *mentioned* her, so a name had to go through the dropdown to mean anything.
    The document is out now, so a login in this text means the one thing it
    should — that somebody's name is on this record.
    """
    record = a_task("task-c00001", "Something", owner="alice", reviewers=["bob"])
    blob = build_index([record], CONFIG, TODAY).search_blob["task-c00001"]

    assert "alice" in blob
    assert "bob" in blob
    assert "task-c00001" in blob


def test_the_searchable_text_holds_an_inbox_records_author():
    """`reported_by` and `written_by` are names a record is known by too.

    The two inbox list pages matched an issue by its reporter and a note by
    its writer; when they folded into the shared blob, both names fell out of
    it — "the issue hoopoegrove reported" found the issue on the old page and
    nothing on the landing that replaced it. The fields ride `SEARCH_FIELDS`
    like `owner` does, and on a kind without them `getattr` answers None, so
    the plan rows above are untouched.
    """
    issue = parse_text(
        "---\nid: issue-0aa000\nkind: issue\ntitle: The halo drops a rank\n"
        "status: ready\nreported_by: hoopoegrove\n---\n\nSeen on 2 nodes.\n",
        "issues/issue-0aa000.md",
    )
    note = parse_text(
        "---\nid: note-0bb000\nkind: note\ntitle: Burner thought\n"
        "status: thinking\nwritten_by: dabchickly\n---\n\nHalf a thought.\n",
        "notes/note-0bb000.md",
    )
    blobs = build_index([issue, note], CONFIG, TODAY).search_blob

    assert "hoopoegrove" in blobs["issue-0aa000"]
    assert "dabchickly" in blobs["note-0bb000"]


# --- apply_filters ---------------------------------------------------------


def test_no_filters_and_no_query_returns_the_whole_plan_sorted_by_id(family_index: Index):
    assert apply_filters(family_index, {}, "") == [
        "pitch-b00001",
        "proj-a00001",
        "task-c00001",
        "task-c00002",
    ]


def test_values_within_one_field_are_ored():
    records = [
        a_task("task-c00001", owner="alice"),
        a_task("task-c00002", owner="bob"),
        a_task("task-c00003", owner="carol"),
    ]
    index = build_index(records, CONFIG, TODAY)

    assert apply_filters(index, {"owner": ["alice", "carol"]}, "") == [
        "task-c00001",
        "task-c00003",
    ]


def test_fields_are_anded_across():
    records = [
        a_task("task-c00001", owner="alice", status="ready"),
        a_task("task-c00002", owner="alice", status="in_progress"),
        a_task("task-c00003", owner="bob", status="in_progress"),
    ]
    index = build_index(records, CONFIG, TODAY)

    filters = {"owner": ["alice"], "status": ["in_progress"]}
    assert apply_filters(index, filters, "") == ["task-c00002"]


def test_a_list_valued_field_matches_if_any_element_matches():
    records = [
        a_task("task-c00001", tags=["ci", "gpu"], reviewers=["bob"]),
        a_task("task-c00002", tags=["ci"], reviewers=["carol"]),
    ]
    index = build_index(records, CONFIG, TODAY)

    assert apply_filters(index, {"tags": ["gpu"]}, "") == ["task-c00001"]
    assert apply_filters(index, {"reviewers": ["bob", "carol"]}, "") == [
        "task-c00001",
        "task-c00002",
    ]


def test_a_value_nothing_carries_matches_nothing(family_index: Index):
    assert apply_filters(family_index, {"owner": ["nobody"]}, "") == []


def test_the_blocked_predicate_needs_a_blocker_that_is_neither_done_nor_shelved():
    records = [
        a_task("task-c00001", status="done"),
        a_task("task-c00002", status="shelved"),
        a_task("task-c00003", status="ready"),
        a_task("task-c00004", depends_on=["task-c00001", "task-c00002"]),
        a_task("task-c00005", depends_on=["task-c00003"]),
    ]
    index = build_index(records, CONFIG, TODAY)

    assert apply_filters(index, {"predicate": ["blocked"]}, "") == ["task-c00005"]


def test_the_unblocked_predicate_is_the_complement_of_blocked():
    records = [
        a_task("task-c00001", status="ready"),
        a_task("task-c00002", depends_on=["task-c00001"]),
        a_task("task-c00003"),
    ]
    index = build_index(records, CONFIG, TODAY)

    blocked = apply_filters(index, {"predicate": ["blocked"]}, "")
    unblocked = apply_filters(index, {"predicate": ["unblocked"]}, "")
    assert blocked == ["task-c00002"]
    assert unblocked == ["task-c00001", "task-c00003"]
    assert sorted(blocked + unblocked) == sorted(index.plan)


def test_the_overruns_cycle_predicate_reads_the_span():
    records = [
        a_task("task-c00001", owner="alice", person_weeks=6.0, cycle=36),
        a_task("task-c00002", owner="bob", person_weeks=0.2, cycle=None),
    ]
    index = build_index(records, CONFIG, TODAY)

    assert index.spans["task-c00001"].overruns_cycle_weeks is not None
    assert apply_filters(index, {"predicate": ["overruns_cycle"]}, "") == ["task-c00001"]


def test_the_missing_required_fields_predicate_reads_the_problems():
    """Severity-agnostic on purpose: a grandfathered rule reports a warning, and a
    field the team has decided it wants is still missing whichever way it reports."""
    records = [
        a_project(
            "proj-a00001",
            owner="alice",
            assignees=["alice"],
            reviewers=["bob"],
            status="in_progress",
            start_date=TODAY,
        ),
        a_pitch(
            "pitch-b00001",
            parent="proj-a00001",
            owner="alice",
            assignees=["alice"],
            reviewers=["bob"],
            person_weeks=2.0,
            status="ready",
        ),
        a_task(
            "task-c00001",
            parent="pitch-b00001",
            status="ready",
            owner="alice",
            assignees=["alice"],
            reviewers=["bob"],
            person_weeks=1.0,
        ),
        a_task("task-c00002", parent="pitch-b00001", status="ready"),
    ]
    index = build_index(records, CONFIG, TODAY)

    assert apply_filters(index, {"predicate": ["missing_required_fields"]}, "") == ["task-c00002"]


def test_the_has_blocker_predicate_is_the_strict_half_of_missing_required_fields(
    seed_index: Index,
):
    """The table's headline counts blocking problems and now links to a filter.

    Linked to `missing_required_fields` — the only predicate that read the
    problem list before this one — the count would have sent people to rows whose
    only complaint is a warning. A number that lands you on more rows than it
    counted is a number that stops being clicked.

    Both predicates are asked over `index.records`, which is what the population
    has to be for the identity below to be about the predicates at all.
    `apply_filters` defaults to `index.plan`, and `validate_all` judges every
    rung — so with the default population `note-b14d6a`, whose `became` names a
    pitch nobody wrote, is a warning in `problems` that no filter over the plan
    can ever return. That is not a defect in either predicate; it is the plan and
    the records being different maps, which this corpus is the first to be able
    to say.
    """
    over = seed_index.records
    any_problem = set(
        apply_filters(seed_index, {"predicate": ["missing_required_fields"]}, "", over=over)
    )
    blocking = set(apply_filters(seed_index, {"predicate": ["has_blocker"]}, "", over=over))

    assert blocking == {p.record_id for p in seed_index.problems if p.severity == "blocker"}
    assert blocking < any_problem, "a warning is a problem and is not a blocker"
    assert (
        any_problem - blocking
        == {p.record_id for p in seed_index.problems if p.severity == "warning"} - blocking
    )
    # And the unplanned half is really in there, so that a future `over` reverting
    # to the plan fails here rather than passing narrower.
    assert "note-b14d6a" in any_problem - blocking
    assert "note-b14d6a" not in seed_index.plan


def test_the_review_waived_predicate_finds_deliberate_waivers_only():
    """`review_waived` is a recorded human decision; empty `reviewers` is nobody
    having decided yet. Collapsing the two would hide a team waiving everything."""
    records = [
        a_task("task-c00001", review_waived=True),
        a_task("task-c00002", reviewers=[]),
        a_task("task-c00003", reviewers=["bob"]),
    ]
    index = build_index(records, CONFIG, TODAY)

    assert apply_filters(index, {"predicate": ["review_waived"]}, "") == ["task-c00001"]


def test_every_computed_predicate_is_filterable(family_index: Index):
    for predicate in COMPUTED_PREDICATES:
        assert isinstance(apply_filters(family_index, {"predicate": [predicate]}, ""), list)


def test_predicates_are_ored_within_the_field():
    records = [
        a_task("task-c00001", status="ready"),
        a_task("task-c00002", depends_on=["task-c00001"]),
        a_task("task-c00003", review_waived=True),
    ]
    index = build_index(records, CONFIG, TODAY)

    assert apply_filters(index, {"predicate": ["blocked", "review_waived"]}, "") == [
        "task-c00002",
        "task-c00003",
    ]


def test_search_is_a_case_insensitive_substring_match():
    records = [
        a_task("task-c00001", "Reproduce the 2-GPU seam artefact"),
        a_task("task-c00002", "Downgrade numpy", tags=["reductions"]),
        a_task(
            "task-c00003", "Read the paper", body="The 2014 stable-summation paper on REDUCTIONS."
        ),
    ]
    index = build_index(records, CONFIG, TODAY)

    assert apply_filters(index, {}, "SEAM") == ["task-c00001"]
    # And the third one, whose only `reductions` is in its shaping document, is
    # not a match any more: the case-insensitivity is the claim here, and the
    # corpus quietly carried the body rule as well.
    assert apply_filters(index, {}, "reductions") == ["task-c00002"]
    assert apply_filters(index, {}, "nothing here") == []


def test_filters_and_search_narrow_together():
    records = [
        a_task("task-c00001", "Downgrade numpy", owner="alice"),
        a_task("task-c00002", "Downgrade numpy again", owner="bob"),
        a_task("task-c00003", "Try deterministic means", owner="alice"),
    ]
    index = build_index(records, CONFIG, TODAY)

    assert apply_filters(index, {"owner": ["alice"]}, "downgrade") == ["task-c00001"]


# --- the seed corpus -------------------------------------------------------


def test_the_seed_index_has_the_shape_of_the_corpus(seed_index: Index):
    # `plan` and `records` are different maps and this corpus is the only place
    # that can prove it: 26 planned rungs, and four more — two issues and two
    # notes — that are records and are not plan. There is no type boundary
    # between the two, so the sixty-odd `.records` sites in the app are held by
    # a corpus where picking the wrong map is a visible number and not a
    # tautology.
    assert len(seed_index.plan) == 26
    assert len(seed_index.records) == 30
    assert seed_index.records.keys() - seed_index.plan.keys() == {
        "issue-8e1a37",
        "issue-9f2b48",
        "note-a03c59",
        "note-b14d6a",
    }
    kinds = [e.kind for e in seed_index.plan.values()]
    assert (
        kinds.count("product"),
        kinds.count("project"),
        kinds.count("pitch"),
        kinds.count("task"),
    ) == (2, 2, 7, 15)

    assert seed_index.children["proj-7e57a0"] == ["task-0e4b7a"]
    # The product rung, walked rather than assumed: `_product_of` was a constant
    # `None` for the whole repository until two products with a project each
    # existed to tell a walk from a constant.
    assert seed_index.children["prod-6d1a70"] == ["proj-7e57a0"]
    assert seed_index.children["prod-7c2b81"] == ["proj-9a4c25"]
    assert seed_index.children["proj-9a4c25"] == ["pitch-6f2d18", "pitch-7b3e94"]
    assert seed_index.children["pitch-6f2d18"] == ["task-6a5c02", "task-6b7d31"]
    assert seed_index.children["pitch-3c9a41"] == [
        "task-31f6c4",
        "task-3a52d8",
        "task-3d84e9",
        "task-3e07b2",
    ]
    assert seed_index.children["pitch-1b3f9a"] == []


def test_the_seed_diamond_reverses_into_blocks(seed_index: Index):
    assert seed_index.blocks["task-5a4e39"] == ["task-5c1d84", "task-5f062b"]
    assert seed_index.blocked_by["task-58d7c6"] == ["task-5c1d84", "task-5f062b"]
    assert seed_index.blocks["task-58d7c6"] == []


def test_task_2b6c94_is_unblocked_because_its_only_blocker_is_done(seed_index: Index):
    """The corpus's live-item-behind-finished-work case. Reading `depends_on`
    non-empty as "blocked" would park this task behind work that is already over."""
    assert seed_index.plan["task-2b6c94"].status == "ready"
    assert seed_index.blocked_by["task-2b6c94"] == ["task-31f6c4"]
    assert seed_index.plan["task-31f6c4"].status == "done"

    assert "task-2b6c94" not in apply_filters(seed_index, {"predicate": ["blocked"]}, "")
    assert "task-2b6c94" in apply_filters(seed_index, {"predicate": ["unblocked"]}, "")


def test_the_seed_blocked_set_is_exactly_the_live_diamond(seed_index: Index):
    assert apply_filters(seed_index, {"predicate": ["blocked"]}, "") == [
        "pitch-7b3e94",
        "prod-7c2b81",
        "task-58d7c6",
        "task-5c1d84",
        "task-5f062b",
        "task-7d9f52",
    ]
    # `prod-7c2b81` is in that list because it names a `depends_on` and a product
    # is not allowed one. The index reads what is written and the validator says
    # it is wrong; those are two different jobs and the honest answer is that
    # both happen. Pinned rather than tidied away — see the file's own body.
    assert seed_index.blocked_by["prod-7c2b81"] == ["prod-6d1a70"]
    assert "depends_on" in {p.field for p in seed_index.problems if p.record_id == "prod-7c2b81"}
    # `task-7d9f52` waits on a task and on an ISSUE. The issue is a record, so the
    # edge survives into `blocked_by`; it is not part of the plan, so it never
    # reaches the scheduler and cannot move a date. That gap is the whole of
    # `off_plan_deps`, and this is the only file in either corpus that has one.
    assert seed_index.blocked_by["task-7d9f52"] == ["task-7c8e40", "issue-9f2b48"]
    assert "issue-9f2b48" not in seed_index.spans


def test_a_pitchs_dependency_is_inherited_by_its_tasks(seed_index: Index):
    """`task-7c8e40` carries no `depends_on` of its own and starts three working
    days after `pitch-6f2d18` ends anyway, because its parent pitch waits on it.

    The demo shipped with this broken — a bet drawn starting a month before the
    bet it declared it waited for — and until this corpus grew, GOLDEN_SPANS
    contained no inherited edge at all, so `blockers_of`'s ancestor loop could
    have been deleted without a red test.

    Stated as a relation rather than as two dates: this fixture's `today` is not
    GOLDEN_TODAY, and the dates themselves belong beside the derivation that
    produced them, in `test_schedule.py`.
    """
    assert seed_index.plan["task-7c8e40"].depends_on == []
    assert seed_index.plan["task-7c8e40"].start_date is None
    assert seed_index.plan["pitch-7b3e94"].depends_on == ["pitch-6f2d18"]

    ends = seed_index.spans["pitch-6f2d18"].end
    starts = seed_index.spans["task-7c8e40"].start
    assert starts > ends
    # The next WORKING day, so the gap is a weekend and nothing else.
    assert (starts - ends).days == 3
    assert ends.weekday() == 4 and starts.weekday() == 0


def test_the_seed_facets_are_the_menus_the_table_will_show(seed_index: Index):
    assert seed_index.facets["kind"] == ["pitch", "product", "project", "task"]
    # A sequence, not a set: alphabetical put `done` at the top of the status
    # menu and read `high, low, medium` for priority, which is not an order
    # anybody means by priority. Everything else is genuinely alphabetical.
    #
    # Status and priority BOTH lead with `(none)` now, and the reason is worth
    # reading before anybody "fixes" it. The model defaults every record's status
    # to `thinking` and its priority to `medium`, so a product would answer both
    # menus as though somebody had jotted it down — and filtering to `thinking`
    # would bring back a codebase. `_facet_values` asks `unread_fields(kind)`
    # first and a product reads neither field, so it contributes no value and
    # falls to `(none)`. Until two products existed, that branch could not fire
    # on any file anybody had written.
    assert seed_index.facets["status"] == ["(none)", "ready", "in_progress", "done", "shelved"]
    assert seed_index.facets["priority"] == ["(none)", "high", "medium", "low"]
    # The word moved on 2026-08-24, when `thinking` was widened to the planned
    # rungs and became where a record opens. The seed's two product files carry
    # no `status:` key at all, so what they hold is whatever `Record.status`
    # defaults to — which is exactly why this is asserted here: it is the one
    # place the base default reaches a page for a kind that does not read it.
    assert {e.status for e in seed_index.plan.values() if e.kind == "product"} == {"thinking"}
    assert "thinking" not in seed_index.facets["status"]
    # `(none)` leads the menus where something is actually missing — it is not a
    # value, it is the question "which of these has nobody in it", and it is the
    # only way to ask it: an unset field yields no facet value at all, so before
    # this it could never be selected. Cycle grows one because a pitch that is
    # not bet yet is the ordinary case rather than an error.
    assert seed_index.facets["cycle"] == ["(none)", "28", "34", "35", "36", "37", "38"]
    assert seed_index.facets["project"] == ["(none)", "proj-7e57a0", "proj-9a4c25"]
    assert seed_index.facets["product"] == ["(none)", "prod-6d1a70", "prod-7c2b81"]
    # `sorted()` on `str`, so a capitalised login leads. Four names below appear
    # on nothing but the hearth island — `redpollard`, `chiffchaffy`,
    # `Whimbrelson`, `stonechatty` — and that is not decoration: the scheduler's
    # third property only promises that adding an item sharing NO worker and NO
    # ancestor leaves an existing span alone, so new people are what let this
    # corpus grow without re-deriving GOLDEN_SPANS by hand.
    assert seed_index.facets["owner"] == [
        "(none)",
        "Oxpeckerly",
        "Whimbrelson",
        "eveningtern",
        "hoopoegrove",
        "jackdawrie",
        "merganserly",
        "nightjarelli",
        "redpollard",
        "sanderlingly",
        "stonechatty",
    ]
    assert seed_index.facets["assignees"] == [
        "(none)",
        "Dunnocksen",
        "Oxpeckerly",
        "Whimbrelson",
        "chiffchaffy",
        "jackdawrie",
        "merganserly",
        "nightjarelli",
        "redpollard",
        "stonechatty",
        "yellowhammer7",
    ]
    assert seed_index.facets["reviewers"] == [
        "(none)",
        "Whimbrelson",
        "accentor9",
        "eiderdowny",
        "hornbillow",
        "ibisbillie",
        "jackdawrie",
        "merganserly",
        "mudlarkish",
        "redpollard",
    ]
    # No `(none)`: every record on this corpus is tagged, products included.
    assert seed_index.facets["tags"] == [
        "api",
        "backend",
        "benchmark",
        "bitwise-reproducibility",
        "buggy",
        "ci",
        "distributed",
        "dsl",
        "f2py",
        "fortran-module",
        "gpu",
        "griddle",
        "halo-exchange",
        "hardening",
        "hearth",
        "kiln4py",
        "model",
        "mpi",
        "numpy",
        "reading",
        "reductions",
        "scan-operator",
        "standalone-driver",
        "synthetic",
        "throughflow",
        "transport",
        "unit-tests",
        "validation",
        "verification",
        "whole-roast",
    ]


def test_the_seed_review_waiver_is_the_only_one(seed_index: Index):
    assert apply_filters(seed_index, {"predicate": ["review_waived"]}, "") == ["task-5a4e39"]


def test_the_seed_incomplete_records_are_the_ones_missing_fields(seed_index: Index):
    """pitch-1b3f9a is missing only the grandfathered `assignees`, so it has to
    show up here despite reporting as a warning.

    The corpus's tasks carry a `cycle` their pitch now owns, which is a v4
    warning apiece — and this predicate is severity-agnostic on purpose, so they
    are all in here. `task-3d84e9` is the one task left out: it is shelved, and
    shelved records are exempt from every rule.

    `prod-7c2b81` is in here for a different reason and a deliberate one: it
    carries `person_weeks`, `depends_on` and `owner`, none of which a product
    reads. Until that file was written the `unread_fields` rules had no document
    anywhere in the repository to fire on — they were exercised only by records
    the tests built in memory, which proves the rule and not the reading of a
    file. Do not tidy it; the file's own body says so too.

    The NINE planned records of the hearth island are all absent, and that is the
    other half of the assertion: they are `created_schema_version: 2`, so this is
    the first corpus where grandfathering is a contrast inside one directory
    rather than a rule with nothing on either side of it."""
    incomplete = set(apply_filters(seed_index, {"predicate": ["missing_required_fields"]}, ""))

    assert {"pitch-1b3f9a", "pitch-48ea9e", "task-3e07b2", "prod-7c2b81"} <= incomplete
    assert "task-3d84e9" not in incomplete
    assert incomplete.isdisjoint(
        {
            "prod-6d1a70",
            "proj-9a4c25",
            "pitch-6f2d18",
            "pitch-7b3e94",
            "task-6a5c02",
            "task-6b7d31",
            "task-7c8e40",
            "task-7d9f52",
        }
    )


def test_the_seed_index_carries_the_scheduler_and_validator_output(seed_root: Path):
    records, config, _ = load_repo(seed_root)
    index = build_index(records, config, TODAY)
    spans, explanations = schedule(records, config, TODAY)

    assert index.spans == spans
    assert index.explanations == explanations
    # `TODAY` for the reason `test_problems_come_from_validate_all` gives: the
    # problem set is a function of the day the plan is drawn around now.
    assert index.problems == validate_all(records, config, spans, TODAY)


def test_searching_the_seed_corpus_finds_the_task_by_its_title(seed_index: Index):
    assert apply_filters(seed_index, {}, "bed2drum") == ["task-0e4b7a"]
    assert apply_filters(seed_index, {"owner": ["merganserly"], "kind": ["task"]}, "seam") == [
        "task-53a9f0"
    ]


def test_a_predicate_never_touches_a_record_that_has_no_span(seed_index: Index):
    """Six seed records are done or shelved and get no span at all. A predicate
    that indexes index.spans directly turns the whole page into a KeyError."""
    result = apply_filters(seed_index, {"predicate": ["overruns_cycle"]}, "")
    assert set(result).isdisjoint({"pitch-2a7f3e", "pitch-3c9a41", "task-3d84e9"})


def test_a_dangling_dependency_does_not_count_as_a_blocker():
    """blocked_by already drops a target that does not exist; the predicate must
    agree with it, or a record blocked by a typo looks blocked forever."""
    records = [a_task("task-c00001", depends_on=["task-ffffff"])]
    index = build_index(records, CONFIG, TODAY)
    assert apply_filters(index, {"predicate": ["blocked"]}, "") == []
    assert apply_filters(index, {"predicate": ["unblocked"]}, "") == ["task-c00001"]


# --------------------------------------------------------------------------- #
# Load, and the carryover it used to miss
# --------------------------------------------------------------------------- #


def _two_cycles() -> Config:
    return CONFIG.model_copy(
        update={
            "cycles": {
                36: (date(2026, 6, 22), date(2026, 8, 14)),
                37: (date(2026, 8, 17), date(2026, 10, 9)),
            }
        }
    )


def _three_cycles() -> Config:
    """`_two_cycles` with the one before them, so a bet can be made in a cycle
    that is over and then asked about in two that are not."""
    two = _two_cycles()
    return two.model_copy(
        update={"cycles": {35: (date(2026, 4, 27), date(2026, 6, 19)), **two.cycles}}
    )


def test_work_bet_in_an_earlier_cycle_and_still_running_counts_against_this_one():
    """`cycle:` records where a bet was MADE and is never re-stamped (D-C1), which
    is what keeps an overrun accusing. It also means a filter on `cycle == N`
    cannot see carryover — and the cycle page exists to add up who is full."""
    records = [
        a_task("task-c00001", owner="ann", person_weeks=2.0, cycle=37, status="ready"),
        a_task(
            "task-c00002",
            owner="ann",
            person_weeks=3.0,
            cycle=36,
            status="in_progress",
            start_date=date(2026, 8, 3),
        ),
    ]
    index = build_index(records, _two_cycles(), TODAY)

    assert index.load(37) == {"ann": 5.0}
    assert index.carried_into(37) == ["task-c00002"]


def test_work_finished_in_the_earlier_cycle_is_not_carried_into_this_one():
    records = [
        a_task(
            "task-c00001",
            owner="ann",
            person_weeks=3.0,
            cycle=36,
            status="done",
            prs=["kilnlab/kiln4py#1"],
            start_date=date(2026, 7, 1),
        ),
    ]
    index = build_index(records, _two_cycles(), TODAY)
    assert index.load(37) == {}
    assert index.carried_into(37) == []


def test_work_nobody_has_sized_charges_nobody_and_is_counted_where_it_went():
    """The half of `load` that used to be invisible because it was invented.

    Shaping work carries no appetite by design — the validator asks for one at
    `ready` and never before — and `counts_in` says it is still what somebody's
    next weeks are spent on, so each of these used to be charged the default half
    a week. Charging nothing is the right answer and a smaller total with no
    explanation is not, so the records that could not be counted are counted
    themselves, per person, and the pages draw the pair.
    """
    records = [
        a_task("task-c00001", owner="ann", person_weeks=2.0, cycle=37, status="ready"),
        a_pitch("pitch-b00001", owner="ann", cycle=37, status="shaping"),
        # Two names on one unsized bet: one record on the cycle's count, and one
        # on each of their rows.
        a_pitch("pitch-b00002", owner="ann", assignees=["bo"], cycle=37, status="shaping"),
    ]
    index = build_index(records, _two_cycles(), TODAY)

    assert index.load(37) == {"ann": 2.0}
    assert index.unsized_in(37) == {
        "ann": ["pitch-b00001", "pitch-b00002"],
        "bo": ["pitch-b00002"],
    }
    # The same three gates on both answers, which is why they are one walk: a
    # cycle nobody has bet this into counts none of it either way.
    assert index.load(36) == {} and index.unsized_in(36) == {}


def test_a_pitch_with_children_is_no_more_unsized_than_it_is_charged():
    """A rollup charges nothing because its children do, and for exactly the same
    reason it cannot be missing from the total: it was never in it."""
    records = [
        a_pitch("pitch-b00001", owner="ann", cycle=37, status="shaping"),
        a_task("task-c00001", parent="pitch-b00001", owner="ann", cycle=37, status="shaping"),
    ]
    index = build_index(records, _two_cycles(), TODAY)

    assert index.load(37) == {}
    assert index.unsized_in(37) == {"ann": ["task-c00001"]}


def test_a_bet_nobody_has_sized_is_counted_where_it_was_bet_and_carried_into_nothing():
    """A bet is a fact somebody stated; a placement is what says it is still
    running. An unsized bet has the first and not the second, so it counts once.

    `counts_in` used to answer True for a record with no span in every dated
    cycle after the one it was bet into, on the reading that no span meant the
    scheduler had tried and failed and that losing such a record was worse than
    counting it late. With no default appetite, no span is instead the normal
    state of every `shaping` and `thinking` bet — the exact population
    `unsized_in` exists to count — so this pitch was in the badge on cycle 36,
    37 and every cycle after them for ever, and `carried_into` named it as
    carryover in cycles it has nothing to do with. The sized task beside it is
    the control: real carryover is decided by the dates and still is.
    """
    records = [
        a_pitch("pitch-b00001", owner="ann", cycle=35, status="shaping"),
        a_task(
            "task-c00001",
            owner="ann",
            person_weeks=1.0,
            cycle=35,
            status="in_progress",
            start_date=date(2026, 6, 22),
        ),
    ]
    index = build_index(records, _three_cycles(), TODAY)

    assert index.unsized_in(35) == {"ann": ["pitch-b00001"]}
    assert index.unsized_in(36) == {} and index.unsized_in(37) == {}
    # The task runs 22–26 June, which is inside 36's window and finished long
    # before 37's opens: the same walk drops it from one and not the other.
    assert index.carried_into(36) == ["task-c00001"]
    assert index.carried_into(37) == []


def test_the_scheduler_having_no_answer_is_not_the_same_as_there_being_nothing_to_place():
    """The two states the old `span is None` clause could not tell apart, which is
    why it counted both for ever.

    A record the scheduler genuinely cannot place — these two wait on each other
    — is given an `unscheduled` span at today rather than nothing, so it goes on
    being counted where today is, which is what that clause was written to
    protect and it no longer needs the clause to do it. Having no span at all now
    means having no length anybody stated, and that is the pitch.
    """
    records = [
        a_task(
            "task-c00001",
            owner="ann",
            person_weeks=1.0,
            cycle=35,
            status="ready",
            depends_on=["task-c00002"],
        ),
        a_task(
            "task-c00002",
            owner="ann",
            person_weeks=1.0,
            cycle=35,
            status="ready",
            depends_on=["task-c00001"],
        ),
        a_pitch("pitch-b00001", owner="bo", cycle=35, status="shaping"),
    ]
    index = build_index(records, _three_cycles(), TODAY)

    assert index.spans["task-c00001"].unscheduled and index.spans["task-c00002"].unscheduled
    assert "pitch-b00001" not in index.spans
    # 13 August is in 36's window, and an unscheduled span is that date twice.
    assert index.carried_into(36) == ["task-c00001", "task-c00002"]
    assert index.carried_into(37) == []


def test_an_undated_cycle_counts_only_what_was_bet_into_it_by_name():
    """A number nobody has given a window to is a hypothetical. Letting it absorb
    every running item would put the whole plan's load on the page for a cycle
    that may never run."""
    records = [
        a_task(
            "task-c00001",
            owner="ann",
            person_weeks=3.0,
            cycle=36,
            status="in_progress",
            start_date=date(2026, 8, 3),
        ),
    ]
    index = build_index(records, _two_cycles(), TODAY)
    assert index.load(99) == {}


def test_a_carried_parent_charges_nothing_because_its_children_already_did():
    """The same rule `load` applies to anything else (D-C2). A rollup counted as
    well as its children double-books the same weeks."""
    records = [
        a_pitch(
            "pitch-b00001",
            owner="ann",
            person_weeks=4.0,
            cycle=36,
            status="in_progress",
            start_date=date(2026, 8, 3),
        ),
        a_task(
            "task-c00001",
            parent="pitch-b00001",
            owner="ann",
            person_weeks=1.0,
            cycle=36,
            status="in_progress",
            start_date=date(2026, 8, 3),
        ),
    ]
    index = build_index(records, _two_cycles(), TODAY)

    # Charged to 36, which is the cycle the work is actually in: it is in
    # progress and started on 3 August, so it runs 08-03 to 08-07, inside
    # 36's window. It used to charge 37 only because the floor at `today` pushed
    # every live span forward into the next cycle — an artefact, not a carry.
    assert index.load(36) == {"ann": 1.0}
    assert index.load(37) == {}


# --------------------------------------------------------------------------- #
# What the body says
# --------------------------------------------------------------------------- #


def test_a_pitch_is_as_far_along_as_its_tasks_weighted_by_their_sizes():
    """Half a bet is half its weeks, not half its rows: a four-week task beside a
    half-week one is not two equal halves of anything. Ticked from each task's own
    `status`, so closing one from the table moves this and there is no checkbox
    for the two to disagree about."""
    records = [
        a_pitch("pitch-b00001", person_weeks=6.0),
        a_task(
            "task-c00001",
            parent="pitch-b00001",
            person_weeks=4.0,
            status="done",
            prs=["kilnlab/kiln4py#1"],
        ),
        a_task("task-c00002", parent="pitch-b00001", person_weeks=2.0),
    ]
    counted = build_index(records, CONFIG, TODAY).progress["pitch-b00001"]

    assert (counted.done, counted.total, counted.unit) == (4.0, 6.0, "weeks")
    assert counted.text == "4/6 wk"
    assert counted.of == ["task-c00001", "task-c00002"]


def test_a_container_is_weighed_by_what_is_under_it_and_not_by_half_a_week():
    """`size_weeks` said a container "has no size of its own" and then returned
    `config.default_task_effort` anyway, because that fallback was written for an
    unsized TASK. Nothing noticed until a product existed: `Rung.under` lets
    nothing but a product nest a container, so a container could not be somebody's
    child.

    The moment one could, a product holding a project worth five weeks reported
    `0/0.5 wk` on the record page, under a meter reading "0 per cent of this bet
    is done" — a denominator nobody typed. The fallback is gone and this is the
    test that keeps the answer: what a container weighs is what is under it.
    """
    records = [
        a_product("prod-a00001"),
        a_project("proj-b00001", parent="prod-a00001"),
        a_pitch("pitch-c00001", parent="proj-b00001", person_weeks=3.0),
        a_pitch("pitch-c00002", parent="proj-b00001", person_weeks=2.0),
    ]
    index = build_index(records, CONFIG, TODAY)

    assert index.progress["proj-b00001"].text == "0/5 wk"
    assert index.progress["prod-a00001"].text == "0/5 wk", (
        "the product was charged the default task effort for a project"
    )
    assert index.progress["prod-a00001"].of == ["proj-b00001"]


def test_a_container_is_as_far_along_as_the_work_beneath_it():
    """The done half rolls up too — jcanton, 2026-08-23, choosing between this and
    a container counting only once every descendant is finished. `Progress` says
    a record is "as far along as its tasks are, weighted by their sizes", and a
    container has no completion of its own to fall back on.

    Weighed as leaves, a project whose two pitches stood at 4/7.5 and 3/7.5 read
    **0/31**: both pitches were `sized`, so each was taken at its appetite and
    credited nothing, and everything finished underneath them was invisible one
    rung up.
    """
    records = [
        a_product("prod-a00001"),
        a_project("proj-b00001", parent="prod-a00001"),
        a_pitch("pitch-c00001", parent="proj-b00001", person_weeks=6.0),
        a_task(
            "task-d00001",
            parent="pitch-c00001",
            person_weeks=4.0,
            status="done",
            prs=["kilnlab/kiln4py#1"],
        ),
        a_task("task-d00002", parent="pitch-c00001", person_weeks=2.0),
        a_pitch("pitch-c00002", parent="proj-b00001", person_weeks=4.0, status="done"),
    ]
    index = build_index(records, CONFIG, TODAY)

    # The pitch from its tasks; the project from the pitch's finished weeks plus
    # the whole of the one that is done; the product straight through.
    assert index.progress["pitch-c00001"].text == "4/6 wk"
    assert index.progress["proj-b00001"].text == "8/10 wk"
    assert index.progress["prod-a00001"].text == "8/10 wk"


def test_a_child_that_is_done_counts_for_all_of_it_even_with_work_left_under_it():
    """`status: done` is the only completion this model stores, so it wins over
    what its children say. The alternative — believing the tasks — would mean a
    pitch somebody closed on purpose reads unfinished for ever because one task
    was never ticked."""
    records = [
        a_project("proj-b00001"),
        a_pitch("pitch-c00001", parent="proj-b00001", person_weeks=6.0, status="done"),
        a_task("task-d00001", parent="pitch-c00001", person_weeks=4.0),
    ]
    index = build_index(records, CONFIG, TODAY)

    assert index.progress["pitch-c00001"].text == "0/4 wk"  # its own tasks, untouched
    assert index.progress["proj-b00001"].text == "6/6 wk", "a done child is done"


def test_a_container_with_nothing_under_it_shows_no_fraction_at_all():
    """Rather than half a week. An empty project contributes no weeks because
    there are no weeks under it, and inventing some puts the same made-up number
    back in a smaller place."""
    records = [a_product("prod-a00001"), a_project("proj-b00001", parent="prod-a00001")]
    index = build_index(records, CONFIG, TODAY)

    assert "proj-b00001" not in index.progress
    assert "prod-a00001" not in index.progress


def test_a_shelved_task_is_in_neither_half_of_its_pitchs_progress():
    """Otherwise parking a task makes a pitch look less finished than it was the
    day before."""
    records = [
        a_pitch("pitch-b00001", person_weeks=6.0),
        a_task(
            "task-c00001",
            parent="pitch-b00001",
            person_weeks=4.0,
            status="done",
            prs=["kilnlab/kiln4py#1"],
        ),
        a_task("task-c00002", parent="pitch-b00001", person_weeks=2.0, status="shelved"),
    ]
    counted = build_index(records, CONFIG, TODAY).progress["pitch-b00001"]
    assert (counted.done, counted.total) == (4.0, 4.0)


def test_a_pitch_with_tasks_ignores_its_own_body_checklist():
    """Two answers to one question is one answer too many, and the tasks are the
    ones anybody else can see."""
    records = [
        a_pitch("pitch-b00001", person_weeks=6.0, body="- [x] a\n- [x] b\n- [x] c\n"),
        a_task("task-c00001", parent="pitch-b00001", person_weeks=4.0),
    ]
    counted = build_index(records, CONFIG, TODAY).progress["pitch-b00001"]
    assert (counted.done, counted.unit) == (0.0, "weeks")


def test_a_task_under_a_pitch_is_counted_in_the_cycle_its_pitch_was_bet_into():
    """The bet is made once, on the thing the room named. A task carries no cycle
    of its own, and the capacity sum has to find it anyway."""
    records = [
        a_pitch(
            "pitch-b00001",
            cycle=36,
            person_weeks=4.0,
            status="in_progress",
            start_date=date(2026, 7, 1),
        ),
        a_task(
            "task-c00001",
            parent="pitch-b00001",
            owner="ann",
            person_weeks=2.0,
            status="in_progress",
            start_date=date(2026, 7, 1),
        ),
    ]
    index = build_index(records, _two_cycles(), TODAY)

    assert index.load(36) == {"ann": 2.0}
    assert index.counts_in(index.plan["task-c00001"], 36)


def test_a_ready_task_carried_into_this_cycle_is_counted_by_its_dates():
    """Carryover is decided by the dates, not by the status: a task that has not
    started is still what somebody's next weeks are spent on, and it was dropped
    from the total for not having begun."""
    records = [
        a_pitch(
            "pitch-b00001",
            cycle=36,
            person_weeks=4.0,
            status="in_progress",
            start_date=date(2026, 7, 1),
        ),
        a_task("task-c00001", parent="pitch-b00001", owner="ann", person_weeks=2.0, status="ready"),
    ]
    index = build_index(records, _two_cycles(), TODAY)

    span = index.spans["task-c00001"]
    assert span.start <= date(2026, 10, 9) and span.end >= date(2026, 8, 17), "it lands in 37"
    assert index.load(37) == {"ann": 2.0}
    assert index.carried_into(37) == ["pitch-b00001", "task-c00001"]


def test_a_checklist_in_the_body_is_counted_once_into_the_index():
    records = [a_task("task-c00001", body="## Progress\n\n- [x] a\n- [ ] b\n")]
    index = build_index(records, CONFIG, TODAY)
    counted = index.progress["task-c00001"]
    assert (counted.done, counted.total, counted.unit) == (1, 2, "items")
    # With its unit, like the weeks a rollup counts: one column holding `1/2`
    # beside `0/1 wk` reads as two measurements of one thing.
    assert counted.text == "1/2 items"


def test_live_work_with_no_checklist_is_findable_and_shaping_work_is_not():
    """A note, not a rule: the template asks for a checklist and this finds the
    records where nobody kept one. An idea nobody has bet on owes nothing."""
    records = [
        a_task("task-c00001", status="in_progress", body="prose"),
        a_task("task-c00002", status="in_progress", body="- [ ] a"),
        a_task("task-c00003", status="shaping", body="prose"),
    ]
    index = build_index(records, CONFIG, TODAY)
    assert apply_filters(index, {"predicate": ["untracked"]}, "") == ["task-c00001"]


def test_a_for_later_list_is_the_only_record_of_scope_being_cut():
    records = [
        a_pitch("pitch-b00001", body="## Solution\n\nX\n\n## For later\n\n- the rest\n"),
        a_pitch("pitch-b00002", body="## Solution\n\nX\n"),
        # Present but empty is not a record of anything.
        a_pitch("pitch-b00003", body="## For later\n"),
    ]
    index = build_index(records, CONFIG, TODAY)
    assert index.for_later == ["pitch-b00001"]
    assert apply_filters(index, {"predicate": ["for_later"]}, "") == ["pitch-b00001"]


def test_a_status_nobody_uses_is_left_out_of_the_menu_and_a_strange_one_is_not(seed_index: Index):
    """Present-only, ordered by the sequence, and anything off the sequence lands
    at the end rather than being dropped — a menu that silently omits a value is
    a filter that cannot find the rows holding it."""
    from openproj.index import _ordered

    assert _ordered("status", {"done", "shaping"}) == ["shaping", "done"]
    assert _ordered("status", {"done", "wip"}) == ["done", "wip"]
    assert _ordered("priority", {"low", "high"}) == ["high", "low"]
    assert _ordered("owner", {"bo", "ann"}) == ["ann", "bo"]


# --- automations that cannot be wrong ---------------------------------------


def test_a_pr_reference_is_searchable(demo_root: Path):
    """ "Which record is #1364?" is asked in front of a screen, and the answer was
    findable only if the number also happened to appear in the prose."""
    records, config, _ = load_repo(demo_root)
    index = build_index(records, config, TODAY)
    cited = {ref for e in index.plan.values() for ref in e.prs}
    assert cited, "the demo corpus cites PRs"

    for ref in cited:
        number = ref.split("#")[1]
        assert [i for i, blob in index.search_blob.items() if number in blob], ref


def test_work_running_past_its_cycles_build_is_a_filter(demo_root: Path):
    """Shape Up's circuit breaker. Derived from dates the tool already has, rather
    than from anything a person remembers to set."""
    records, config, _ = load_repo(demo_root)
    index = build_index(records, config, TODAY)
    caught = [i for i in index.plan if _matches_predicate(index, i, "past_cycle_build")]

    assert caught, "the demo corpus has work running past its build"
    for record_id in caught:
        record = index.plan[record_id]
        assert record.status == "in_progress"
        assert index.spans[record_id].end > index.build_end(record.cycle)


def test_the_build_end_a_predicate_uses_is_the_one_the_timeline_uses(seed_index: Index):
    """Rebuilding a Config to ask would substitute the default cool-down for the
    repository's own, and a filter that quietly disagrees with the timeline it
    explains is worse than no filter."""
    from openproj.model import Config, Cycle
    from openproj.schedule import build_end

    config = Config(
        cycles=seed_index.cycles,
        plans=seed_index.plans,
        cooldown_weeks=seed_index.cooldown_weeks,
    )
    for number, window in seed_index.cycles.items():
        assert seed_index.build_end(number) == build_end(number, window, config)

    # And the carried figure is the repository's, not the default.
    odd = Config(cycles={9: (date(2026, 1, 5), date(2026, 3, 1))}, cooldown_weeks=1.0)
    assert build_index([], odd, date(2026, 1, 5)).cooldown_weeks == 1.0
    assert isinstance(seed_index.plans.get(37), (Cycle, type(None)))


def test_a_record_in_progress_with_nothing_linked_is_a_question_not_a_rule(seed_index: Index):
    """Opening a PR early to get CI machine time is a good habit; a validation
    rule against it would teach people to stop listing PRs. It is a filter."""
    from openproj.model import Task, validate_all

    loose = Task(id="task-ff0001", kind="task", title="x", status="in_progress")
    index = build_index([loose], Config(), date(2026, 8, 17))

    assert _matches_predicate(index, "task-ff0001", "in_progress_without_prs")
    assert not any(
        "pr" in problem.message.lower() and problem.severity == "blocker"
        for problem in validate_all([loose], Config())
        if problem.field == "prs"
    )


# --- filtering for what is not there ----------------------------------------


def test_a_field_nobody_filled_in_can_be_asked_for():
    """ "Which pitches are not in a cycle yet" and "what has no reviewer" are the
    two questions a betting table actually asks, and neither could be asked at
    all: an unset field yields no facet value, so it could never appear in the
    menu, and the blank option at the top means "no constraint" rather than
    "empty"."""
    bet = Pitch(id="pitch-000001", kind="pitch", title="Bet", status="ready", cycle=37)
    loose = Pitch(id="pitch-000002", kind="pitch", title="Loose", status="ready")
    index = build_index([bet, loose], Config(), TODAY)

    assert NO_VALUE in index.facets["cycle"]
    assert apply_filters(index, {"cycle": [NO_VALUE]}, "") == ["pitch-000002"]
    assert apply_filters(index, {"cycle": ["37"]}, "") == ["pitch-000001"]
    # OR within a field still holds: empty is one more thing to be, not a mode.
    assert apply_filters(index, {"cycle": [NO_VALUE, "37"]}, "") == [
        "pitch-000001",
        "pitch-000002",
    ]


def test_a_menu_never_offers_an_option_that_can_select_nothing():
    """Every record has a status, so Status must not grow an empty option; the
    day a pitch is written and not bet, Cycle must."""
    bet = Pitch(id="pitch-000001", kind="pitch", title="Bet", status="ready", cycle=37)
    index = build_index([bet], Config(), TODAY)

    assert NO_VALUE not in index.facets["status"]
    assert NO_VALUE not in index.facets["cycle"]
    assert NO_VALUE in index.facets["owner"], "nobody owns it, so the question is askable"


def test_empty_is_spelled_the_same_on_both_sides_of_the_wire():
    """The browser filters and the server filters, and they must agree. The
    client's copy is a literal in a constant script block rather than a template
    variable, so nothing but this test stops the two drifting — and a drift would
    filter differently in the two places with neither one erroring."""
    from openproj.render import _FILTER_JS

    assert f"const NO_VALUE = '{NO_VALUE}';" in _FILTER_JS
