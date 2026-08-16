from datetime import date
from pathlib import Path

import pytest

from openproj.model import (
    Config,
    Entity,
    Pitch,
    Project,
    Task,
    ancestors,
    load_repo,
    parse_file,
    parse_text,
    serialise,
    size_weeks,
)

SEED = Path(__file__).resolve().parents[1] / "seed"
SEED_FILES = sorted(
    path
    for directory in ("projects", "pitches", "tasks")
    for path in (SEED / directory).glob("*.md")
)
FIXTURE = Path(__file__).parent / "fixtures" / "roundtrip.md"


# --- A4: parsing ---------------------------------------------------------------


def test_parse_file_reads_a_seed_pitch(seed_root: Path):
    pitch = parse_file(seed_root / "pitches" / "pitch-2a7f3e--tracer-adv-port-ls-coeffs.md")
    assert isinstance(pitch, Pitch)
    assert pitch.id == "pitch-2a7f3e"
    assert pitch.title == "Tracer adv port LS coeffs"
    assert pitch.status == "done"
    assert pitch.appetite_weeks is None
    assert pitch.assignees == ["nfarabullini", "DropD"]
    assert pitch.cycle == 34
    assert "tracer-advection" in pitch.tags


def test_parse_dispatches_to_the_subclass_named_by_kind(seed_root: Path):
    project = parse_file(seed_root / "projects" / "proj-7e57a0--testing.md")
    task = parse_file(seed_root / "tasks" / "task-53a9f0--reproduce-2gpu-equator-artefact.md")
    assert type(project) is Project
    assert type(task) is Task
    assert task.effort_weeks == 2
    assert task.assigned_on == date(2026, 8, 13)


def test_the_markdown_body_survives_parsing(seed_root: Path):
    pitch = parse_file(seed_root / "pitches" / "pitch-1b3f9a--mpi-on-ci-verify-with-serial.md")
    assert pitch.body.startswith("# MPI on CI verify with serial")
    assert "hackmd.io" in pitch.body
    assert "id: pitch-1b3f9a" not in pitch.body


def test_parse_tolerates_a_file_that_states_almost_nothing():
    entity = parse_text("---\nid: task-abc123\nkind: task\n---\n", "nearly-empty.md")
    assert entity.title == ""
    assert entity.owner is None
    assert entity.reviewers == []
    assert entity.body == ""


def test_parse_tolerates_explicit_nulls_where_a_default_belongs():
    """A hand-written `reviewers: null` must not take the repository down; it means
    the same as the field being absent."""
    entity = parse_text(
        "---\nid: task-abc123\nkind: task\ntitle: null\nreviewers: null\n"
        "status: null\nassigned_on: null\n---\n",
        "nulls.md",
    )
    assert entity.title == ""
    assert entity.reviewers == []
    assert entity.status == "shaping"
    assert entity.assigned_on is None


def test_parse_falls_back_to_the_id_prefix_when_kind_is_missing():
    entity = parse_text("---\nid: pitch-abc123\ntitle: P\n---\n", "no-kind.md")
    assert isinstance(entity, Pitch)
    assert entity.kind == "pitch"


def test_parse_refuses_a_file_it_cannot_classify():
    with pytest.raises(ValueError, match="mystery.md"):
        parse_text("---\ntitle: what am I\n---\n", "mystery.md")


# --- A5: serialisation ---------------------------------------------------------


def test_round_trip_of_the_hand_formatted_fixture_is_byte_identical():
    """The critical test. Comments, key order, quoting and non-ASCII must all
    come back unchanged, or a web save silently rewrites a human's file."""
    text = FIXTURE.read_text(encoding="utf-8")
    assert serialise(parse_text(text, FIXTURE.name), text) == text


@pytest.mark.parametrize("path", SEED_FILES, ids=lambda path: path.name.split("--")[0])
def test_every_seed_file_round_trips_byte_identically(path: Path):
    text = path.read_text(encoding="utf-8")
    assert serialise(parse_text(text, path.name), text) == text


def test_serialise_writes_one_edited_key_and_leaves_its_neighbours_alone():
    text = FIXTURE.read_text(encoding="utf-8")
    entity = parse_text(text, FIXTURE.name)
    entity.status = "done"
    entity.prs = ["C2SM/icon4py#1234"]
    output = serialise(entity, text)
    assert "status: done\n" in output
    assert "prs: [C2SM/icon4py#1234]\n" in output
    assert "owner: \"müller\"        # quoted on purpose" in output
    assert output.split("---\n")[1].count("\n") == text.split("---\n")[1].count("\n")


def test_one_shaper_keeps_the_spelling_the_corpus_is_written_in():
    """`shaped_by` grew from a scalar to a list, because shaping is usually done in
    pairs. Every existing file writes one name as a bare string, and rewriting all
    of them to `[jcanton]` on an unrelated save is a diff nobody asked for in a
    file somebody else is reading."""
    text = "---\nid: pitch-abc123\nkind: pitch\ntitle: P\nshaped_by: jcanton\n---\n\nb\n"
    pitch = parse_text(text, "p.md")
    assert pitch.shaped_by == ["jcanton"]
    assert serialise(pitch, text) == text

    pitch.shaped_by = ["jcanton", "msimberg"]
    assert "shaped_by:\n  - jcanton\n  - msimberg\n" in serialise(pitch, text)


def test_serialise_appends_a_field_the_file_never_had():
    text = "---\nid: task-abc123\nkind: task\ntitle: T\n---\n\nbody\n"
    entity = parse_text(text, "sparse.md")
    entity.owner = "jcanton"
    assert serialise(entity, text) == (
        "---\nid: task-abc123\nkind: task\ntitle: T\nowner: jcanton\n---\n\nbody\n"
    )


def test_serialise_without_an_original_writes_the_whole_skeleton():
    task = Task(id="task-abc123", kind="task", title="T", body="Why this matters.\n")
    output = serialise(task)
    assert output.startswith("---\nid: task-abc123\nkind: task\ntitle: T\nparent: null\n")
    assert output.endswith("---\n\nWhy this matters.\n")
    assert "effort_weeks: null\n" in output


def test_serialise_never_writes_the_body_into_the_frontmatter():
    task = Task(id="task-abc123", kind="task", title="T", body="prose")
    frontmatter = serialise(task).split("---\n")[1]
    assert "body" not in frontmatter


# --- A6: chains, sizes, loading ------------------------------------------------


def test_ancestors_are_nearest_first():
    by_id = {
        "task-aaa111": Task(id="task-aaa111", kind="task", title="T", parent="pitch-bbb222"),
        "pitch-bbb222": Pitch(id="pitch-bbb222", kind="pitch", title="P", parent="proj-ccc333"),
        "proj-ccc333": Project(id="proj-ccc333", kind="project", title="J"),
    }
    assert ancestors("task-aaa111", by_id) == ["pitch-bbb222", "proj-ccc333"]
    assert ancestors("proj-ccc333", by_id) == []


def test_ancestors_of_a_seed_task_reach_its_pitch(seed_root: Path):
    entities, _, _ = load_repo(seed_root)
    by_id = {entity.id: entity for entity in entities}
    assert ancestors("task-2b6c94", by_id) == ["pitch-2a7f3e"]
    assert ancestors("task-0e4b7a", by_id) == ["proj-7e57a0"]


def test_ancestors_stops_on_a_parent_cycle():
    """A cycle is a validation blocker, not a reason to hang the index."""
    by_id = {
        "task-aaa111": Task(id="task-aaa111", kind="task", title="A", parent="pitch-bbb222"),
        "pitch-bbb222": Pitch(id="pitch-bbb222", kind="pitch", title="B", parent="task-aaa111"),
    }
    assert ancestors("task-aaa111", by_id) == ["pitch-bbb222"]


def test_ancestors_of_an_unknown_id_is_empty():
    assert ancestors("task-ffffff", {}) == []


def test_size_weeks_defaults_when_no_size_is_stated():
    config = Config()
    assert size_weeks(Task(id="task-abc123", kind="task", title="T"), config) == (0.5, True)
    assert size_weeks(Pitch(id="pitch-abc123", kind="pitch", title="P"), config) == (0.5, True)
    assert size_weeks(Project(id="proj-abc123", kind="project", title="J"), config) == (0.5, True)


def test_size_weeks_reads_appetite_on_a_pitch_and_effort_on_a_task():
    config = Config()
    pitch = Pitch(id="pitch-abc123", kind="pitch", title="P", appetite_weeks=3.0)
    task = Task(id="task-abc123", kind="task", title="T", effort_weeks=3.0)
    assert size_weeks(pitch, config) == (3.0, False)
    assert size_weeks(task, config) == (3.0, False)


def test_size_weeks_keeps_a_stated_zero():
    """Zero is a size somebody chose; only absence may be defaulted."""
    task = Task(id="task-abc123", kind="task", title="T", effort_weeks=0)
    assert size_weeks(task, Config()) == (0.0, False)


def test_load_repo_loads_the_whole_seed_corpus(seed_root: Path):
    entities, config, _ = load_repo(seed_root)
    assert len(entities) == 17
    kinds = [entity.kind for entity in entities]
    assert kinds.count("project") == 1
    assert kinds.count("pitch") == 5
    assert kinds.count("task") == 11
    assert config.schema_version == 2
    assert all(isinstance(entity, Entity) for entity in entities)


def test_load_repo_of_an_empty_directory_is_empty(tmp_path: Path):
    entities, config, _ = load_repo(tmp_path)
    assert entities == []
    assert config == Config()
