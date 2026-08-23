from datetime import date
from pathlib import Path

import pytest

from openproj.model import (
    Config,
    Pitch,
    Project,
    Record,
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
    pitch = parse_file(seed_root / "pitches" / "pitch-2a7f3e--transport-port-blend-coeffs.md")
    assert isinstance(pitch, Pitch)
    assert pitch.id == "pitch-2a7f3e"
    assert pitch.title == "Transport port blend coeffs"
    assert pitch.status == "done"
    assert pitch.person_weeks is None
    assert pitch.assignees == ["nightjarelli", "Dunnocksen"]
    assert pitch.cycle == 34
    assert "transport" in pitch.tags


def test_parse_dispatches_to_the_subclass_named_by_kind(seed_root: Path):
    project = parse_file(seed_root / "projects" / "proj-7e57a0--testing.md")
    task = parse_file(seed_root / "tasks" / "task-53a9f0--reproduce-2gpu-seam-artefact.md")
    assert type(project) is Project
    assert type(task) is Task
    assert task.person_weeks == 2
    assert task.assigned_on == date(2026, 8, 13)


def test_the_markdown_body_survives_parsing(seed_root: Path):
    pitch = parse_file(seed_root / "pitches" / "pitch-1b3f9a--mpi-on-ci-verify-with-serial.md")
    assert pitch.body.startswith("# MPI on CI verify with serial")
    assert "github.com/kilnlab/kiln4py" in pitch.body
    assert "id: pitch-1b3f9a" not in pitch.body


def test_parse_tolerates_a_file_that_states_almost_nothing():
    record = parse_text("---\nid: task-abc123\nkind: task\n---\n", "nearly-empty.md")
    assert record.title == ""
    assert record.owner is None
    assert record.reviewers == []
    assert record.body == ""


def test_parse_tolerates_explicit_nulls_where_a_default_belongs():
    """A hand-written `reviewers: null` must not take the repository down; it means
    the same as the field being absent."""
    record = parse_text(
        "---\nid: task-abc123\nkind: task\ntitle: null\nreviewers: null\n"
        "status: null\nassigned_on: null\n---\n",
        "nulls.md",
    )
    assert record.title == ""
    assert record.reviewers == []
    assert record.status == "shaping"
    assert record.assigned_on is None


def test_parse_falls_back_to_the_id_prefix_when_kind_is_missing():
    record = parse_text("---\nid: pitch-abc123\ntitle: P\n---\n", "no-kind.md")
    assert isinstance(record, Pitch)
    assert record.kind == "pitch"


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
    record = parse_text(text, FIXTURE.name)
    record.status = "done"
    record.prs = ["kilnlab/kiln4py#1234"]
    output = serialise(record, text)
    assert "status: done\n" in output
    assert "prs: [kilnlab/kiln4py#1234]\n" in output
    assert "owner: \"grünfink\"      # quoted on purpose" in output
    assert output.split("---\n")[1].count("\n") == text.split("---\n")[1].count("\n")


def test_one_shaper_keeps_the_spelling_the_corpus_is_written_in():
    """`shaped_by` grew from a scalar to a list, because shaping is usually done in
    pairs. Every existing file writes one name as a bare string, and rewriting all
    of them to `[jackdawrie]` on an unrelated save is a diff nobody asked for in a
    file somebody else is reading."""
    text = "---\nid: pitch-abc123\nkind: pitch\ntitle: P\nshaped_by: jackdawrie\n---\n\nb\n"
    pitch = parse_text(text, "p.md")
    assert pitch.shaped_by == ["jackdawrie"]
    assert serialise(pitch, text) == text

    pitch.shaped_by = ["jackdawrie", "merganserly"]
    assert "shaped_by:\n  - jackdawrie\n  - merganserly\n" in serialise(pitch, text)


def test_serialise_appends_a_field_the_file_never_had():
    text = "---\nid: task-abc123\nkind: task\ntitle: T\n---\n\nbody\n"
    record = parse_text(text, "sparse.md")
    record.owner = "jackdawrie"
    assert serialise(record, text) == (
        "---\nid: task-abc123\nkind: task\ntitle: T\nowner: jackdawrie\n---\n\nbody\n"
    )


def test_serialise_without_an_original_writes_the_whole_skeleton():
    task = Task(id="task-abc123", kind="task", title="T", body="Why this matters.\n")
    output = serialise(task)
    assert output.startswith("---\nid: task-abc123\nkind: task\ntitle: T\nparent: null\n")
    assert output.endswith("---\n\nWhy this matters.\n")
    assert "person_weeks: null\n" in output


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
    records, _, _ = load_repo(seed_root)
    by_id = {record.id: record for record in records}
    assert ancestors("task-2b6c94", by_id) == ["pitch-2a7f3e"]
    # Three rungs, not two: `proj-7e57a0` hangs from a product now, and the chain
    # is walked as far as it is named. This is the only assertion in the suite
    # that would notice a walk stopping at the project.
    assert ancestors("task-0e4b7a", by_id) == ["proj-7e57a0", "prod-6d1a70"]
    assert ancestors("task-6a5c02", by_id) == ["pitch-6f2d18", "proj-9a4c25", "prod-7c2b81"]


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
    pitch = Pitch(id="pitch-abc123", kind="pitch", title="P", person_weeks=3.0)
    task = Task(id="task-abc123", kind="task", title="T", person_weeks=3.0)
    assert size_weeks(pitch, config) == (3.0, False)
    assert size_weeks(task, config) == (3.0, False)


def test_size_weeks_keeps_a_stated_zero():
    """Zero is a size somebody chose; only absence may be defaulted."""
    task = Task(id="task-abc123", kind="task", title="T", person_weeks=0)
    assert size_weeks(task, Config()) == (0.0, False)


def test_load_repo_loads_the_whole_seed_corpus(seed_root: Path):
    records, config, _ = load_repo(seed_root)
    assert len(records) == 30
    kinds = [record.kind for record in records]
    assert kinds.count("product") == 2
    assert kinds.count("project") == 2
    assert kinds.count("pitch") == 7
    assert kinds.count("task") == 15
    # `load_repo` returns every rung, planned or not. The four below are why
    # `Index.records` and `Index.plan` are different sizes on this corpus — see
    # `test_the_seed_index_has_the_shape_of_the_corpus`.
    assert kinds.count("issue") == 2
    assert kinds.count("note") == 2
    assert config.schema_version == 2
    assert all(isinstance(record, Record) for record in records)


def test_a_template_quoted_inside_a_fence_is_not_this_records_own_plan(seed_root: Path):
    """The fence rule, asked of a document somebody wrote rather than of a body
    a test built two lines above the assertion.

    `task-7c8e40` is asked to write an API document and quotes the shape of it:
    a `## <symbol>` heading and a `- [ ] one line on what it is for`, inside a
    fence, in the middle of its Solution. It is the first file in either corpus
    that quotes markdown at all.

    What the fence protects is counted rather than displayed, which is why this
    is worth a test on a file: a broken toggle invents a section nobody wrote
    and reports three items of work as three of four. Both are numbers on a page
    that look like numbers, and neither raises anything.
    """
    from openproj.index import build_index
    from openproj.model import sections

    records, config, _ = load_repo(seed_root)
    index = build_index(records, config, date(2026, 8, 17))
    body = index.plan["task-7c8e40"].body
    done, total = index.progress["task-7c8e40"].done, index.progress["task-7c8e40"].total

    assert "## <symbol>" in body and "- [ ] one line on what it is for" in body
    assert "<symbol>" not in sections(body), "a heading in a fence is somebody else's document"
    assert set(sections(body)) == {
        "freeze the backend api before the shutdown", "problem", "solution", "progress",
    }
    assert (done, total) == (0, 3), "the quoted point is not a fourth thing to do"


def test_load_repo_of_an_empty_directory_is_empty(tmp_path: Path):
    records, config, _ = load_repo(tmp_path)
    assert records == []
    assert config == Config()
