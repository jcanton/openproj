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
from openproj.model import Config, Entity, Pitch, Project, Task, load_repo, parse_text, validate_all
from openproj.schedule import schedule

TODAY = date(2026, 8, 13)

CONFIG = Config(
    schema_version=2,
    nominal_availability=1.0,
    default_task_effort=0.5,
    cycles={36: (date(2026, 6, 22), date(2026, 8, 14))},
)


def a_project(id: str, title: str = "A project", **fields) -> Project:
    return Project(id=id, kind="project", title=title, **fields)


def a_pitch(id: str, title: str = "A pitch", **fields) -> Pitch:
    return Pitch(id=id, kind="pitch", title=title, **fields)


def a_task(id: str, title: str = "A task", **fields) -> Task:
    return Task(id=id, kind="task", title=title, **fields)


def a_family() -> list[Entity]:
    """One project, one pitch under it, two tasks under the pitch, one dependency."""
    return [
        a_project("proj-a00001", "Greenline", owner="alice", reviewers=["bob"]),
        a_pitch("pitch-b00001", "Halo exchange", parent="proj-a00001", person_weeks=2.0,
                status="ready"),
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
    entities, config, _ = load_repo(seed_root)
    return build_index(entities, config, TODAY)


# --- structure -------------------------------------------------------------


def test_children_lists_each_parents_children_by_id(family_index: Index):
    assert family_index.children["proj-a00001"] == ["pitch-b00001"]
    assert family_index.children["pitch-b00001"] == ["task-c00001", "task-c00002"]


def test_every_entity_is_a_key_in_every_edge_map(family_index: Index):
    """A childless or unblocked entity gets an empty list, not a missing key: the
    views index these maps directly and a KeyError there is a blank page."""
    ids = set(family_index.entities)
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
    entities = [lying, a_task("task-c00002", "Second")]
    index = build_index(entities, CONFIG, TODAY)

    assert not hasattr(lying, "blocks")
    assert index.blocks["task-c00001"] == []
    assert index.blocked_by["task-c00002"] == []


def test_blocked_by_keeps_only_edges_to_entities_that_exist():
    """A dangling id is already a validation blocker; carrying it into the edge
    maps would invent a node the graph and the reverse map cannot agree on."""
    entities = [a_task("task-c00001", depends_on=["task-ffffff"])]
    index = build_index(entities, CONFIG, TODAY)

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
    entities = [a_task("task-c00001", parent="proj-ffffff", owner="alice", person_weeks=1.0)]

    index = build_index(entities, CONFIG, TODAY)

    # Unresolvable means "no project" — the same answer as no parent at all, and
    # since that is now askable from the menu it is `[NO_VALUE]` rather than the
    # empty list.
    assert index.facets["project"] == [NO_VALUE]
    assert set(index.entities) == {"task-c00001"}


def test_a_parent_chain_that_ends_outside_the_plan_still_finds_the_project_it_names():
    """The half of the same walk that must keep working: a chain that reaches a
    real project reports it, even though a later link is missing."""
    entities = [
        a_project("proj-a00001", "Greenline"),
        a_pitch("pitch-b00001", parent="proj-a00001"),
        a_task("task-c00001", parent="pitch-b00001"),
        a_task("task-c00002", parent="pitch-ffffff"),
    ]

    index = build_index(entities, CONFIG, TODAY)

    # `task-c00002` names a pitch that does not exist, so it is in no project and
    # contributes the `(none)` option; the chain that does resolve still reports
    # the project it reaches.
    assert index.facets["project"] == [NO_VALUE, "proj-a00001"]


def test_entities_are_keyed_by_id(family_index: Index):
    assert family_index.entities["task-c00001"].title == "First"
    assert set(family_index.entities) == {
        "proj-a00001",
        "pitch-b00001",
        "task-c00001",
        "task-c00002",
    }


# --- wiring ----------------------------------------------------------------


def test_spans_and_explanations_come_from_the_scheduler():
    entities = a_family()
    spans, explanations = schedule(entities, CONFIG, TODAY)
    index = build_index(entities, CONFIG, TODAY)

    assert index.spans == spans
    assert index.explanations == explanations
    assert index.spans["task-c00001"].start >= TODAY


def test_problems_come_from_validate_all():
    entities = a_family()
    index = build_index(entities, CONFIG, TODAY)

    assert index.problems == validate_all(entities, CONFIG)
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
    entities = [
        a_task("task-c00001", owner="bob", priority="low", cycle=36, tags=["ci", "gpu"]),
        a_task("task-c00002", owner="alice", priority="high", cycle=36, tags=["gpu"]),
        a_task("task-c00003", owner="alice", priority="high", cycle=None, tags=[]),
    ]
    facets = build_index(entities, CONFIG, TODAY).facets

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
    all: `(none)`, which selects the entities where the field is empty.

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


def test_an_entity_outside_any_project_matches_no_project_filter():
    entities = [a_task("task-c00001", "Orphan")]
    index = build_index(entities, CONFIG, TODAY)

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
    entity = a_task(
        "task-c00001",
        "Reproduce the 2-GPU Equator Artefact",
        tags=["GPU", "ci"],
        body="Only on Daint.\n",
    )
    blob = build_index([entity], CONFIG, TODAY).search_blob["task-c00001"]

    assert "reproduce the 2-gpu equator artefact" in blob
    assert "gpu" in blob
    assert "ci" in blob
    assert "daint" not in blob
    assert blob == blob.lower()


def test_the_searchable_text_holds_the_names_a_record_is_known_by():
    """The people on a record and its id are searchable, and were not.

    The rule this replaces said the opposite, and its reason was the body: with a
    whole shaping document in the blob, `alice` matched every record that merely
    *mentioned* her, so a name had to go through the dropdown to mean anything.
    The document is out now, so a login in this text means the one thing it
    should — that somebody's name is on this record.
    """
    entity = a_task("task-c00001", "Something", owner="alice", reviewers=["bob"])
    blob = build_index([entity], CONFIG, TODAY).search_blob["task-c00001"]

    assert "alice" in blob
    assert "bob" in blob
    assert "task-c00001" in blob


def test_the_searchable_text_holds_an_inbox_records_author():
    """`reported_by` and `written_by` are names a record is known by too.

    The two inbox list pages matched an issue by its reporter and a note by
    its writer; when they folded into the shared blob, both names fell out of
    it — "the issue halungge reported" found the issue on the old page and
    nothing on the landing that replaced it. The fields ride `SEARCH_FIELDS`
    like `owner` does, and on a kind without them `getattr` answers None, so
    the plan rows above are untouched.
    """
    issue = parse_text(
        "---\nid: issue-0aa000\nkind: issue\ntitle: The halo drops a rank\n"
        "status: ready\nreported_by: halungge\n---\n\nSeen on 2 nodes.\n",
        "issues/issue-0aa000.md",
    )
    note = parse_text(
        "---\nid: note-0bb000\nkind: note\ntitle: Radiation thought\n"
        "status: thinking\nwritten_by: dastrm\n---\n\nHalf a thought.\n",
        "notes/note-0bb000.md",
    )
    blobs = build_index([issue, note], CONFIG, TODAY).search_blob

    assert "halungge" in blobs["issue-0aa000"]
    assert "dastrm" in blobs["note-0bb000"]


# --- apply_filters ---------------------------------------------------------


def test_no_filters_and_no_query_returns_every_entity_sorted_by_id(family_index: Index):
    assert apply_filters(family_index, {}, "") == [
        "pitch-b00001",
        "proj-a00001",
        "task-c00001",
        "task-c00002",
    ]


def test_values_within_one_field_are_ored():
    entities = [
        a_task("task-c00001", owner="alice"),
        a_task("task-c00002", owner="bob"),
        a_task("task-c00003", owner="carol"),
    ]
    index = build_index(entities, CONFIG, TODAY)

    assert apply_filters(index, {"owner": ["alice", "carol"]}, "") == [
        "task-c00001",
        "task-c00003",
    ]


def test_fields_are_anded_across():
    entities = [
        a_task("task-c00001", owner="alice", status="ready"),
        a_task("task-c00002", owner="alice", status="in_progress"),
        a_task("task-c00003", owner="bob", status="in_progress"),
    ]
    index = build_index(entities, CONFIG, TODAY)

    filters = {"owner": ["alice"], "status": ["in_progress"]}
    assert apply_filters(index, filters, "") == ["task-c00002"]


def test_a_list_valued_field_matches_if_any_element_matches():
    entities = [
        a_task("task-c00001", tags=["ci", "gpu"], reviewers=["bob"]),
        a_task("task-c00002", tags=["ci"], reviewers=["carol"]),
    ]
    index = build_index(entities, CONFIG, TODAY)

    assert apply_filters(index, {"tags": ["gpu"]}, "") == ["task-c00001"]
    assert apply_filters(index, {"reviewers": ["bob", "carol"]}, "") == [
        "task-c00001",
        "task-c00002",
    ]


def test_a_value_nothing_carries_matches_nothing(family_index: Index):
    assert apply_filters(family_index, {"owner": ["nobody"]}, "") == []


def test_the_blocked_predicate_needs_a_blocker_that_is_neither_done_nor_shelved():
    entities = [
        a_task("task-c00001", status="done"),
        a_task("task-c00002", status="shelved"),
        a_task("task-c00003", status="ready"),
        a_task("task-c00004", depends_on=["task-c00001", "task-c00002"]),
        a_task("task-c00005", depends_on=["task-c00003"]),
    ]
    index = build_index(entities, CONFIG, TODAY)

    assert apply_filters(index, {"predicate": ["blocked"]}, "") == ["task-c00005"]


def test_the_unblocked_predicate_is_the_complement_of_blocked():
    entities = [
        a_task("task-c00001", status="ready"),
        a_task("task-c00002", depends_on=["task-c00001"]),
        a_task("task-c00003"),
    ]
    index = build_index(entities, CONFIG, TODAY)

    blocked = apply_filters(index, {"predicate": ["blocked"]}, "")
    unblocked = apply_filters(index, {"predicate": ["unblocked"]}, "")
    assert blocked == ["task-c00002"]
    assert unblocked == ["task-c00001", "task-c00003"]
    assert sorted(blocked + unblocked) == sorted(index.entities)


def test_the_overruns_cycle_predicate_reads_the_span():
    entities = [
        a_task("task-c00001", owner="alice", person_weeks=6.0, cycle=36),
        a_task("task-c00002", owner="bob", person_weeks=0.2, cycle=None),
    ]
    index = build_index(entities, CONFIG, TODAY)

    assert index.spans["task-c00001"].overruns_cycle_weeks is not None
    assert apply_filters(index, {"predicate": ["overruns_cycle"]}, "") == ["task-c00001"]


def test_the_missing_required_fields_predicate_reads_the_problems():
    """Severity-agnostic on purpose: a grandfathered rule reports a warning, and a
    field the team has decided it wants is still missing whichever way it reports."""
    entities = [
        a_project("proj-a00001", owner="alice", assignees=["alice"], reviewers=["bob"],
            status="in_progress", assigned_on=TODAY),
        a_pitch("pitch-b00001", parent="proj-a00001", owner="alice", assignees=["alice"],
                reviewers=["bob"], shaped_by=["alice"], person_weeks=2.0, status="ready"),
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
    index = build_index(entities, CONFIG, TODAY)

    assert apply_filters(index, {"predicate": ["missing_required_fields"]}, "") == ["task-c00002"]


def test_the_has_blocker_predicate_is_the_strict_half_of_missing_required_fields(
    seed_index: Index,
):
    """The table's headline counts blocking problems and now links to a filter.

    Linked to `missing_required_fields` — the only predicate that read the
    problem list before this one — the count would have sent people to rows whose
    only complaint is a warning. A number that lands you on more rows than it
    counted is a number that stops being clicked.
    """
    any_problem = set(apply_filters(seed_index, {"predicate": ["missing_required_fields"]}, ""))
    blocking = set(apply_filters(seed_index, {"predicate": ["has_blocker"]}, ""))

    assert blocking == {p.entity_id for p in seed_index.problems if p.severity == "blocker"}
    assert blocking < any_problem, "a warning is a problem and is not a blocker"
    assert any_problem - blocking == {
        p.entity_id for p in seed_index.problems if p.severity == "warning"
    } - blocking


def test_the_review_waived_predicate_finds_deliberate_waivers_only():
    """`review_waived` is a recorded human decision; empty `reviewers` is nobody
    having decided yet. Collapsing the two would hide a team waiving everything."""
    entities = [
        a_task("task-c00001", review_waived=True),
        a_task("task-c00002", reviewers=[]),
        a_task("task-c00003", reviewers=["bob"]),
    ]
    index = build_index(entities, CONFIG, TODAY)

    assert apply_filters(index, {"predicate": ["review_waived"]}, "") == ["task-c00001"]


def test_every_computed_predicate_is_filterable(family_index: Index):
    for predicate in COMPUTED_PREDICATES:
        assert isinstance(apply_filters(family_index, {"predicate": [predicate]}, ""), list)


def test_predicates_are_ored_within_the_field():
    entities = [
        a_task("task-c00001", status="ready"),
        a_task("task-c00002", depends_on=["task-c00001"]),
        a_task("task-c00003", review_waived=True),
    ]
    index = build_index(entities, CONFIG, TODAY)

    assert apply_filters(index, {"predicate": ["blocked", "review_waived"]}, "") == [
        "task-c00002",
        "task-c00003",
    ]


def test_search_is_a_case_insensitive_substring_match():
    entities = [
        a_task("task-c00001", "Reproduce the 2-GPU equator artefact"),
        a_task("task-c00002", "Downgrade numpy", tags=["reductions"]),
        a_task("task-c00003", "Read the paper", body="Anurag's IPDPS 2014 paper on REDUCTIONS."),
    ]
    index = build_index(entities, CONFIG, TODAY)

    assert apply_filters(index, {}, "EQUATOR") == ["task-c00001"]
    # And the third one, whose only `reductions` is in its shaping document, is
    # not a match any more: the case-insensitivity is the claim here, and the
    # corpus quietly carried the body rule as well.
    assert apply_filters(index, {}, "reductions") == ["task-c00002"]
    assert apply_filters(index, {}, "nothing here") == []


def test_filters_and_search_narrow_together():
    entities = [
        a_task("task-c00001", "Downgrade numpy", owner="alice"),
        a_task("task-c00002", "Downgrade numpy again", owner="bob"),
        a_task("task-c00003", "Try deterministic means", owner="alice"),
    ]
    index = build_index(entities, CONFIG, TODAY)

    assert apply_filters(index, {"owner": ["alice"]}, "downgrade") == ["task-c00001"]


# --- the seed corpus -------------------------------------------------------


def test_the_seed_index_has_the_shape_of_the_corpus(seed_index: Index):
    assert len(seed_index.entities) == 17
    kinds = [e.kind for e in seed_index.entities.values()]
    assert (kinds.count("project"), kinds.count("pitch"), kinds.count("task")) == (1, 5, 11)

    assert seed_index.children["proj-7e57a0"] == ["task-0e4b7a"]
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
    assert seed_index.entities["task-2b6c94"].status == "ready"
    assert seed_index.blocked_by["task-2b6c94"] == ["task-31f6c4"]
    assert seed_index.entities["task-31f6c4"].status == "done"

    assert "task-2b6c94" not in apply_filters(seed_index, {"predicate": ["blocked"]}, "")
    assert "task-2b6c94" in apply_filters(seed_index, {"predicate": ["unblocked"]}, "")


def test_the_seed_blocked_set_is_exactly_the_live_diamond(seed_index: Index):
    assert apply_filters(seed_index, {"predicate": ["blocked"]}, "") == [
        "task-58d7c6",
        "task-5c1d84",
        "task-5f062b",
    ]


def test_the_seed_facets_are_the_menus_the_table_will_show(seed_index: Index):
    assert seed_index.facets["kind"] == ["pitch", "project", "task"]
    # A sequence, not a set: alphabetical put `done` at the top of the status
    # menu and read `high, low, medium` for priority, which is not an order
    # anybody means by priority. Everything else is genuinely alphabetical.
    assert seed_index.facets["status"] == ["ready", "in_progress", "done", "shelved"]
    assert seed_index.facets["priority"] == ["high", "medium", "low"]
    # `(none)` leads the menus where something is actually missing — it is not a
    # value, it is the question "which of these has nobody in it", and it is the
    # only way to ask it: an unset field yields no facet value at all, so before
    # this it could never be selected. Status does not grow one, because every
    # entity has a status; cycle does, because a pitch that is not bet yet is
    # the ordinary case rather than an error.
    assert seed_index.facets["cycle"] == ["(none)", "28", "34", "35", "36"]
    assert seed_index.facets["project"] == ["(none)", "proj-7e57a0"]
    assert seed_index.facets["owner"] == [
        "(none)",
        "OngChia",
        "egparedes",
        "halungge",
        "jcanton",
        "msimberg",
        "nfarabullini",
        "samkellerhals",
    ]
    assert seed_index.facets["assignees"] == [
        "(none)",
        "DropD",
        "OngChia",
        "jcanton",
        "msimberg",
        "nfarabullini",
        "yiluchen1066",
    ]
    assert seed_index.facets["reviewers"] == [
        "(none)",
        "abishekg7",
        "edopao",
        "havogt",
        "iomaganaris",
        "jcanton",
        "msimberg",
        "muellch",
    ]
    assert seed_index.facets["tags"] == [
        "bitwise-reproducibility",
        "buggy",
        "ci",
        "distributed",
        "f2py",
        "fortran-granule",
        "gpu",
        "greenline",
        "halo-exchange",
        "icon4py",
        "mpi",
        "numpy",
        "reading",
        "reductions",
        "standalone-driver",
        "synthetic",
        "tracer-advection",
        "turbulence",
        "unit-tests",
        "validation",
        "verification",
        "warm-bubble",
    ]


def test_the_seed_review_waiver_is_the_only_one(seed_index: Index):
    assert apply_filters(seed_index, {"predicate": ["review_waived"]}, "") == ["task-5a4e39"]


def test_the_seed_incomplete_entities_are_the_ones_missing_fields(seed_index: Index):
    """pitch-1b3f9a is missing only the grandfathered `shaped_by`, so it has to
    show up here despite reporting as a warning.

    The corpus's tasks carry a `cycle` their pitch now owns, which is a v4
    warning apiece — and this predicate is severity-agnostic on purpose, so they
    are all in here. `task-3d84e9` is the one task left out: it is shelved, and
    shelved records are exempt from every rule."""
    incomplete = set(apply_filters(seed_index, {"predicate": ["missing_required_fields"]}, ""))

    assert {"pitch-1b3f9a", "pitch-48ea9e", "task-3e07b2"} <= incomplete
    assert "task-3d84e9" not in incomplete


def test_the_seed_index_carries_the_scheduler_and_validator_output(seed_root: Path):
    entities, config, _ = load_repo(seed_root)
    index = build_index(entities, config, TODAY)
    spans, explanations = schedule(entities, config, TODAY)

    assert index.spans == spans
    assert index.explanations == explanations
    assert index.problems == validate_all(entities, config)


def test_searching_the_seed_corpus_finds_the_task_by_its_title(seed_index: Index):
    assert apply_filters(seed_index, {}, "geo2cart") == ["task-0e4b7a"]
    assert apply_filters(seed_index, {"owner": ["msimberg"], "kind": ["task"]}, "equator") == [
        "task-53a9f0"
    ]


def test_a_predicate_never_touches_an_entity_that_has_no_span(seed_index: Index):
    """Six seed entities are done or shelved and get no span at all. A predicate
    that indexes index.spans directly turns the whole page into a KeyError."""
    result = apply_filters(seed_index, {"predicate": ["overruns_cycle"]}, "")
    assert set(result).isdisjoint({"pitch-2a7f3e", "pitch-3c9a41", "task-3d84e9"})


def test_a_dangling_dependency_does_not_count_as_a_blocker():
    """blocked_by already drops a target that does not exist; the predicate must
    agree with it, or an entity blocked by a typo looks blocked forever."""
    entities = [a_task("task-c00001", depends_on=["task-ffffff"])]
    index = build_index(entities, CONFIG, TODAY)
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


def test_work_bet_in_an_earlier_cycle_and_still_running_counts_against_this_one():
    """`cycle:` records where a bet was MADE and is never re-stamped (D-C1), which
    is what keeps an overrun accusing. It also means a filter on `cycle == N`
    cannot see carryover — and the cycle page exists to add up who is full."""
    entities = [
        a_task("task-c00001", owner="ann", person_weeks=2.0, cycle=37, status="ready"),
        a_task(
            "task-c00002",
            owner="ann",
            person_weeks=3.0,
            cycle=36,
            status="in_progress",
            assigned_on=date(2026, 8, 3),
        ),
    ]
    index = build_index(entities, _two_cycles(), TODAY)

    assert index.load(37) == {"ann": 5.0}
    assert index.carried_into(37) == ["task-c00002"]


def test_work_finished_in_the_earlier_cycle_is_not_carried_into_this_one():
    entities = [
        a_task("task-c00001", owner="ann", person_weeks=3.0, cycle=36, status="done",
               prs=["C2SM/icon4py#1"], assigned_on=date(2026, 7, 1)),
    ]
    index = build_index(entities, _two_cycles(), TODAY)
    assert index.load(37) == {}
    assert index.carried_into(37) == []


def test_an_undated_cycle_counts_only_what_was_bet_into_it_by_name():
    """A number nobody has given a window to is a hypothetical. Letting it absorb
    every running item would put the whole plan's load on the page for a cycle
    that may never run."""
    entities = [
        a_task("task-c00001", owner="ann", person_weeks=3.0, cycle=36, status="in_progress",
               assigned_on=date(2026, 8, 3)),
    ]
    index = build_index(entities, _two_cycles(), TODAY)
    assert index.load(99) == {}


def test_a_carried_parent_charges_nothing_because_its_children_already_did():
    """The same rule `load` applies to anything else (D-C2). A rollup counted as
    well as its children double-books the same weeks."""
    entities = [
        a_pitch("pitch-b00001", owner="ann", person_weeks=4.0, cycle=36, status="in_progress",
                assigned_on=date(2026, 8, 3)),
        a_task("task-c00001", parent="pitch-b00001", owner="ann", person_weeks=1.0, cycle=36,
               status="in_progress", assigned_on=date(2026, 8, 3)),
    ]
    index = build_index(entities, _two_cycles(), TODAY)

    # Charged to 36, which is the cycle the work is actually in: it is in
    # progress and was assigned on 3 August, so it runs 08-03 to 08-07, inside
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
    entities = [
        a_pitch("pitch-b00001", person_weeks=6.0),
        a_task("task-c00001", parent="pitch-b00001", person_weeks=4.0, status="done",
               prs=["C2SM/icon4py#1"]),
        a_task("task-c00002", parent="pitch-b00001", person_weeks=2.0),
    ]
    counted = build_index(entities, CONFIG, TODAY).progress["pitch-b00001"]

    assert (counted.done, counted.total, counted.unit) == (4.0, 6.0, "weeks")
    assert counted.text == "4/6 wk"
    assert counted.of == ["task-c00001", "task-c00002"]


def test_a_shelved_task_is_in_neither_half_of_its_pitchs_progress():
    """Otherwise parking a task makes a pitch look less finished than it was the
    day before."""
    entities = [
        a_pitch("pitch-b00001", person_weeks=6.0),
        a_task("task-c00001", parent="pitch-b00001", person_weeks=4.0, status="done",
               prs=["C2SM/icon4py#1"]),
        a_task("task-c00002", parent="pitch-b00001", person_weeks=2.0, status="shelved"),
    ]
    counted = build_index(entities, CONFIG, TODAY).progress["pitch-b00001"]
    assert (counted.done, counted.total) == (4.0, 4.0)


def test_a_pitch_with_tasks_ignores_its_own_body_checklist():
    """Two answers to one question is one answer too many, and the tasks are the
    ones anybody else can see."""
    entities = [
        a_pitch("pitch-b00001", person_weeks=6.0, body="- [x] a\n- [x] b\n- [x] c\n"),
        a_task("task-c00001", parent="pitch-b00001", person_weeks=4.0),
    ]
    counted = build_index(entities, CONFIG, TODAY).progress["pitch-b00001"]
    assert (counted.done, counted.unit) == (0.0, "weeks")


def test_a_task_under_a_pitch_is_counted_in_the_cycle_its_pitch_was_bet_into():
    """The bet is made once, on the thing the room named. A task carries no cycle
    of its own, and the capacity sum has to find it anyway."""
    entities = [
        a_pitch("pitch-b00001", cycle=36, person_weeks=4.0, status="in_progress",
                assigned_on=date(2026, 7, 1)),
        a_task("task-c00001", parent="pitch-b00001", owner="ann", person_weeks=2.0,
               status="in_progress", assigned_on=date(2026, 7, 1)),
    ]
    index = build_index(entities, _two_cycles(), TODAY)

    assert index.load(36) == {"ann": 2.0}
    assert index.counts_in(index.entities["task-c00001"], 36)


def test_a_ready_task_carried_into_this_cycle_is_counted_by_its_dates():
    """Carryover is decided by the dates, not by the status: a task that has not
    started is still what somebody's next weeks are spent on, and it was dropped
    from the total for not having begun."""
    entities = [
        a_pitch("pitch-b00001", cycle=36, person_weeks=4.0, status="in_progress",
                assigned_on=date(2026, 7, 1)),
        a_task("task-c00001", parent="pitch-b00001", owner="ann", person_weeks=2.0,
               status="ready"),
    ]
    index = build_index(entities, _two_cycles(), TODAY)

    span = index.spans["task-c00001"]
    assert span.start <= date(2026, 10, 9) and span.end >= date(2026, 8, 17), "it lands in 37"
    assert index.load(37) == {"ann": 2.0}
    assert index.carried_into(37) == ["pitch-b00001", "task-c00001"]


def test_a_checklist_in_the_body_is_counted_once_into_the_index():
    entities = [a_task("task-c00001", body="## Progress\n\n- [x] a\n- [ ] b\n")]
    index = build_index(entities, CONFIG, TODAY)
    counted = index.progress["task-c00001"]
    assert (counted.done, counted.total, counted.unit) == (1, 2, "items")
    # With its unit, like the weeks a rollup counts: one column holding `1/2`
    # beside `0/1 wk` reads as two measurements of one thing.
    assert counted.text == "1/2 items"


def test_live_work_with_no_checklist_is_findable_and_shaping_work_is_not():
    """A note, not a rule: the template asks for a checklist and this finds the
    entities where nobody kept one. An idea nobody has bet on owes nothing."""
    entities = [
        a_task("task-c00001", status="in_progress", body="prose"),
        a_task("task-c00002", status="in_progress", body="- [ ] a"),
        a_task("task-c00003", status="shaping", body="prose"),
    ]
    index = build_index(entities, CONFIG, TODAY)
    assert apply_filters(index, {"predicate": ["untracked"]}, "") == ["task-c00001"]


def test_a_for_later_list_is_the_only_record_of_scope_being_cut():
    entities = [
        a_pitch("pitch-b00001", body="## Solution\n\nX\n\n## For later\n\n- the rest\n"),
        a_pitch("pitch-b00002", body="## Solution\n\nX\n"),
        # Present but empty is not a record of anything.
        a_pitch("pitch-b00003", body="## For later\n"),
    ]
    index = build_index(entities, CONFIG, TODAY)
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
    """"Which entity is #1364?" is asked in front of a screen, and the answer was
    findable only if the number also happened to appear in the prose."""
    entities, config, _ = load_repo(demo_root)
    index = build_index(entities, config, TODAY)
    cited = {ref for e in index.entities.values() for ref in e.prs}
    assert cited, "the demo corpus cites PRs"

    for ref in cited:
        number = ref.split("#")[1]
        assert [i for i, blob in index.search_blob.items() if number in blob], ref


def test_work_running_past_its_cycles_build_is_a_filter(demo_root: Path):
    """Shape Up's circuit breaker. Derived from dates the tool already has, rather
    than from anything a person remembers to set."""
    entities, config, _ = load_repo(demo_root)
    index = build_index(entities, config, TODAY)
    caught = [i for i in index.entities if _matches_predicate(index, i, "past_cycle_build")]

    assert caught, "the demo corpus has work running past its build"
    for entity_id in caught:
        entity = index.entities[entity_id]
        assert entity.status == "in_progress"
        assert index.spans[entity_id].end > index.build_end(entity.cycle)


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


def test_an_entity_in_progress_with_nothing_linked_is_a_question_not_a_rule(seed_index: Index):
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
    """"Which pitches are not in a cycle yet" and "what has no reviewer" are the
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
    """Every entity has a status, so Status must not grow an empty option; the
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
