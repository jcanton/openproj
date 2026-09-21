"""`openproj rekind`, which is the command line's half of the kind chip.

The web app has changed a record's kind since the chip landed: open the editor,
click the kind, pick another. The command line had no equivalent, so anybody
working against a checkout — an agent reshaping a corpus, somebody on a plane —
did it by hand: mint an id, move the file, walk every other record looking for
the old one. That is four `git mv`s and a grep, and the grep is the part that
gets forgotten. It was forgotten on 2026-09-21, in a sync that promoted a pitch
to a project and three tasks to pitches; the references happened to be caught by
reading, not by anything that would have failed.

The rules are the route's rules, and these tests hold the CLI to them rather
than to a second opinion: refusals come from the containment ladder both ways
(what this record is filed under, and what is filed under it), losing a field is
a question before it is a write, and the whole change is one commit or none.
"""

from pathlib import Path

import pytest

from openproj.cli import main


def _write(root: Path, kind_dir: str, name: str, text: str) -> Path:
    (root / kind_dir).mkdir(parents=True, exist_ok=True)
    path = root / kind_dir / name
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def plan(tmp_path: Path) -> Path:
    """A project, a pitch under it, two tasks under the pitch, and an onlooker.

    The shape of the icon4py-plan Documentation restructure, which is the
    gesture this command exists for: the pitch in the middle is the one that has
    to become a project, and the two tasks under it are what makes the naive
    implementation wrong.
    """
    _write(tmp_path, "products", "prod-aaa001.md", "\n".join([
        "---", "id: prod-aaa001", "kind: product", "title: The codebase",
        "---", "", "A codebase.", ""]))
    _write(tmp_path, "projects", "proj-bbb001.md", "\n".join([
        "---", "id: proj-bbb001", "kind: project", "title: Replace the old thing",
        "status: shaping", "priority: medium", "parent: prod-aaa001", "---", "", "A project.", ""]))
    _write(tmp_path, "pitches", "pitch-ccc001.md", "\n".join([
        "---", "id: pitch-ccc001", "kind: pitch", "title: Documentation",
        "status: thinking", "priority: medium", "parent: proj-bbb001", "---", "", "A pitch.", ""]))
    _write(tmp_path, "tasks", "task-ddd001.md", "\n".join([
        "---", "id: task-ddd001", "kind: task", "title: Write the config docs",
        "status: thinking", "priority: medium", "parent: pitch-ccc001",
        "---", "", "A task.", ""]))
    _write(tmp_path, "tasks", "task-eee001.md", "\n".join([
        "---", "id: task-eee001", "kind: task", "title: Write the code docs",
        "status: thinking", "priority: medium", "parent: pitch-ccc001",
        "---", "", "Another task.", ""]))
    # The onlooker: it names the pitch in `depends_on` and nowhere else, so it is
    # the only thing that fails if the repointing loop reads `parent` alone.
    _write(tmp_path, "pitches", "pitch-fff001.md", "\n".join([
        "---", "id: pitch-fff001", "kind: pitch", "title: Something that waits",
        "status: thinking", "priority: medium", "parent: proj-bbb001",
        "depends_on: [pitch-ccc001]", "---", "", "Waits on the docs.", ""]))
    return tmp_path


def _ids(root: Path) -> dict[str, Path]:
    return {p.stem.split("--")[0]: p for p in root.rglob("*.md")}


def test_rekind_turns_a_pitch_into_a_project_and_carries_its_children(plan: Path, capsys):
    """The gesture this exists for, end to end.

    The new record is a project, the old file is gone, and both tasks are filed
    under the new id — not under an id that no longer names anything.
    """
    assert main(["rekind", "pitch-ccc001", "project", str(plan)]) == 0

    live = _ids(plan)
    assert "pitch-ccc001" not in live
    made = [one for one in live if one.startswith("proj-") and one != "proj-bbb001"]
    assert len(made) == 1, live
    new_id = made[0]

    assert "kind: project" in live[new_id].read_text(encoding="utf-8")
    assert "title: Documentation" in live[new_id].read_text(encoding="utf-8")
    for child in ("task-ddd001", "task-eee001"):
        assert f"parent: {new_id}" in live[child].read_text(encoding="utf-8")


def test_rekind_repoints_depends_on_and_not_only_parent(plan: Path):
    """`parent` is the obvious edge and the one a hand-written sweep catches.

    `depends_on` is the one it does not, which is why a record that names the
    old id only there is in the fixture.
    """
    assert main(["rekind", "pitch-ccc001", "project", str(plan)]) == 0
    live = _ids(plan)
    new_id = next(one for one in live if one.startswith("proj-") and one != "proj-bbb001")
    waiting = live["pitch-fff001"].read_text(encoding="utf-8")
    assert "pitch-ccc001" not in waiting
    assert new_id in waiting


def test_rekind_refuses_when_nothing_could_be_filed_under_the_new_kind(plan: Path, capsys):
    """A pitch with tasks under it cannot become a task: nothing is filed under
    one, so the two children would be orphaned by the write."""
    assert main(["rekind", "pitch-ccc001", "task", str(plan)]) == 1
    said = capsys.readouterr().out
    assert "Write the config docs" in said and "Write the code docs" in said
    assert "Move them first" in said
    assert _ids(plan).keys() >= {"pitch-ccc001", "task-ddd001", "task-eee001"}


def test_rekind_refuses_when_the_parent_cannot_hold_the_new_kind(plan: Path, capsys):
    """The other half of the ladder: a project cannot be filed under a project,
    and this pitch is under one."""
    assert main(["rekind", "pitch-fff001", "project", str(plan)]) == 1
    said = capsys.readouterr().out
    assert "Replace the old thing" in said
    assert "pitch-fff001" in said
    assert "Move it first" in said or "take its parent off" in said


def test_rekind_refuses_until_the_fields_it_would_drop_are_named(tmp_path: Path, capsys):
    """Losing a field is a question before it is a write.

    A product reads none of the work fields, so turning a task into one drops
    every one it carries. The command says which, and writes nothing.
    """
    _write(tmp_path, "tasks", "task-999001.md", "\n".join([
        "---", "id: task-999001", "kind: task", "title: A chore nobody pitched",
        "status: ready", "owner: jackdawrie", "reviewers: [merganserly]",
        "person_weeks: 1", "priority: low", "---", "", "A chore.", ""]))

    assert main(["rekind", "task-999001", "product", str(tmp_path)]) == 1
    said = capsys.readouterr().out
    assert "owner" in said and "person_weeks" in said
    assert "Nothing was changed" in said
    assert (tmp_path / "tasks" / "task-999001.md").exists()


def test_rekind_takes_the_change_once_the_drops_are_named(tmp_path: Path):
    """And goes through when the caller names them back."""
    _write(tmp_path, "tasks", "task-999001.md", "\n".join([
        "---", "id: task-999001", "kind: task", "title: A chore nobody pitched",
        "status: ready", "owner: jackdawrie", "reviewers: [merganserly]",
        "person_weeks: 1", "priority: low", "---", "", "A chore.", ""]))

    code = main([
        "rekind", "task-999001", "product", str(tmp_path),
        "--drop", "owner,person_weeks,priority,reviewers,status",
    ])
    assert code == 0
    made = list((tmp_path / "products").glob("*.md"))
    assert len(made) == 1
    text = made[0].read_text(encoding="utf-8")
    assert "kind: product" in text
    for gone in ("owner:", "person_weeks:", "reviewers:"):
        assert gone not in text
    assert not (tmp_path / "tasks" / "task-999001.md").exists()


def test_rekind_refuses_a_drop_list_that_does_not_match_what_would_be_lost(tmp_path: Path, capsys):
    """The echo is a compare-and-swap on the shape of the change, not a --yes.

    A list that disagrees with what the server computes means the plan moved
    under whoever typed it, and a caller who was told about one field and would
    lose five was not asked.
    """
    _write(tmp_path, "tasks", "task-999001.md", "\n".join([
        "---", "id: task-999001", "kind: task", "title: A chore nobody pitched",
        "status: ready", "owner: jackdawrie", "reviewers: [merganserly]",
        "person_weeks: 1", "priority: low", "---", "", "A chore.", ""]))

    assert main(["rekind", "task-999001", "product", str(tmp_path), "--drop", "owner"]) == 1
    assert "Nothing was changed" in capsys.readouterr().out
    assert (tmp_path / "tasks" / "task-999001.md").exists()


def test_rekind_refuses_a_kind_it_is_already(plan: Path, capsys):
    assert main(["rekind", "pitch-ccc001", "pitch", str(plan)]) == 1
    assert "already" in capsys.readouterr().out


def test_rekind_refuses_an_id_that_names_nothing(plan: Path, capsys):
    assert main(["rekind", "pitch-000000", "project", str(plan)]) == 1
    assert "pitch-000000" in capsys.readouterr().out
    assert len(_ids(plan)) == 6


def test_rekind_writes_nothing_when_the_result_would_not_validate(plan: Path, capsys):
    """`_new`'s order, held here too: build every file, parse it back, validate
    the whole plan with the change applied, and only then touch the disk.

    A rekind that `check` would refuse must not be a thing somebody has to `rm`
    their way out of — and unlike `new`, this one has already deleted a file by
    the time anybody runs `check`.
    """
    before = {one: path.read_text(encoding="utf-8") for one, path in _ids(plan).items()}
    # A product is not filed under anything, and this one is under a project.
    assert main(["rekind", "pitch-ccc001", "product", str(plan)]) == 1
    assert {one: path.read_text(encoding="utf-8") for one, path in _ids(plan).items()} == before
