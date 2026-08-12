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

from openproj.index import COMPUTED_PREDICATES, Index, apply_filters, build_index
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
        a_pitch("pitch-b00001", "Halo exchange", parent="proj-a00001", appetite_weeks=2.0),
        a_task("task-c00001", "First", parent="pitch-b00001", owner="alice", effort_weeks=1.0),
        a_task(
            "task-c00002",
            "Second",
            parent="pitch-b00001",
            owner="bob",
            effort_weeks=1.0,
            depends_on=["task-c00001"],
        ),
    ]


@pytest.fixture
def family_index() -> Index:
    return build_index(a_family(), CONFIG, TODAY)


@pytest.fixture
def seed_index(seed_root: Path) -> Index:
    entities, config = load_repo(seed_root)
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
        a_task("task-c00001", owner="bob", priority=3, cycle=36, tags=["ci", "gpu"]),
        a_task("task-c00002", owner="alice", priority=1, cycle=36, tags=["gpu"]),
        a_task("task-c00003", owner="alice", priority=1, cycle=None, tags=[]),
    ]
    facets = build_index(entities, CONFIG, TODAY).facets

    assert facets["owner"] == ["alice", "bob"]
    assert facets["priority"] == ["1", "3"]
    assert facets["cycle"] == ["36"]
    assert facets["tags"] == ["ci", "gpu"]
    assert facets["kind"] == ["task"]


def test_facets_omit_absent_values():
    """An unset field is not a facet value; "unowned" is a question for the
    predicate list, not a fake owner name."""
    facets = build_index([a_task("task-c00001")], CONFIG, TODAY).facets

    assert facets["owner"] == []
    assert facets["cycle"] == []
    assert facets["reviewers"] == []


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

    assert index.facets["project"] == []
    assert apply_filters(index, {"project": ["proj-a00001"]}, "") == []


def test_search_blob_is_lowercased_title_tags_and_body():
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
    assert "only on daint." in blob
    assert blob == blob.lower()


def test_search_blob_holds_nothing_but_title_tags_and_body():
    """Searching for a person or an id must go through a filter, not a substring
    match that quietly hits every entity whose body mentions them."""
    entity = a_task("task-c00001", "Something", owner="alice", reviewers=["bob"])
    blob = build_index([entity], CONFIG, TODAY).search_blob["task-c00001"]

    assert "alice" not in blob
    assert "bob" not in blob
    assert "task-c00001" not in blob


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
        a_task("task-c00001", owner="alice", status="todo"),
        a_task("task-c00002", owner="alice", status="wip"),
        a_task("task-c00003", owner="bob", status="wip"),
    ]
    index = build_index(entities, CONFIG, TODAY)

    assert apply_filters(index, {"owner": ["alice"], "status": ["wip"]}, "") == ["task-c00002"]


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
        a_task("task-c00003", status="todo"),
        a_task("task-c00004", depends_on=["task-c00001", "task-c00002"]),
        a_task("task-c00005", depends_on=["task-c00003"]),
    ]
    index = build_index(entities, CONFIG, TODAY)

    assert apply_filters(index, {"predicate": ["blocked"]}, "") == ["task-c00005"]


def test_the_unblocked_predicate_is_the_complement_of_blocked():
    entities = [
        a_task("task-c00001", status="todo"),
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
        a_task("task-c00001", owner="alice", effort_weeks=6.0, cycle=36),
        a_task("task-c00002", owner="bob", effort_weeks=0.2, cycle=None),
    ]
    index = build_index(entities, CONFIG, TODAY)

    assert index.spans["task-c00001"].overruns_cycle_weeks is not None
    assert apply_filters(index, {"predicate": ["overruns_cycle"]}, "") == ["task-c00001"]


def test_the_missing_required_fields_predicate_reads_the_problems():
    """Severity-agnostic on purpose: a grandfathered rule reports a warning, and a
    field the team has decided it wants is still missing whichever way it reports."""
    entities = [
        a_project("proj-a00001", owner="alice", reviewers=["bob"], status="wip", assigned_on=TODAY),
        a_task(
            "task-c00001",
            parent="proj-a00001",
            status="todo",
            owner="alice",
            reviewers=["bob"],
            effort_weeks=1.0,
        ),
        a_task("task-c00002", parent="proj-a00001", status="todo"),
    ]
    index = build_index(entities, CONFIG, TODAY)

    assert apply_filters(index, {"predicate": ["missing_required_fields"]}, "") == ["task-c00002"]


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
        a_task("task-c00001", status="todo"),
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
    assert apply_filters(index, {}, "reductions") == ["task-c00002", "task-c00003"]
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
    assert seed_index.entities["task-2b6c94"].status == "todo"
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
    assert seed_index.facets["status"] == ["done", "shelved", "todo", "wip"]
    assert seed_index.facets["priority"] == ["1", "2", "3"]
    assert seed_index.facets["cycle"] == ["28", "34", "35", "36"]
    assert seed_index.facets["project"] == ["proj-7e57a0"]
    assert seed_index.facets["owner"] == [
        "OngChia",
        "egparedes",
        "halungge",
        "jcanton",
        "msimberg",
        "nfarabullini",
        "samkellerhals",
    ]
    assert seed_index.facets["assignees"] == [
        "DropD",
        "OngChia",
        "jcanton",
        "msimberg",
        "nfarabullini",
        "yiluchen1066",
    ]
    assert seed_index.facets["reviewers"] == [
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
    show up here despite reporting as a warning."""
    incomplete = set(apply_filters(seed_index, {"predicate": ["missing_required_fields"]}, ""))

    assert {"pitch-1b3f9a", "pitch-48ea9e", "task-3e07b2"} <= incomplete
    assert incomplete.isdisjoint({"task-2b6c94", "task-53a9f0", "task-5a4e39", "task-0e4b7a"})


def test_the_seed_index_carries_the_scheduler_and_validator_output(seed_root: Path):
    entities, config = load_repo(seed_root)
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
