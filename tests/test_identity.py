"""An entity's identity is written twice, and the two have to agree.

The id is in the frontmatter and it is in the filename. Nothing compared them, and
the two halves of the application resolved a collision in opposite directions:
`build_index` keeps the last file in tree order for an id, `_path_for` writes to
the first filename that matches. So a second file claiming an id took that id in
the index while the write kept landing on the first — a reader edited the record
on screen, pressed save, and a different record changed on disk, with a 200 and no
warning, while `openproj check` printed `0 blockers, 0 warnings`.

The corpus below is the audit's, reproduced: an impostor file whose name says one
id and whose frontmatter says another.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from openproj.model import Config, load_repo, named_for, parse_text, validate_all

IMPOSTOR = """---
id: task-0a1001
kind: task
title: IMPOSTOR
effort_weeks: 1
---
not the record you were shown
"""

HONEST = """---
id: task-0f0001
kind: task
title: An honest record
effort_weeks: 1
---
body
"""


def _plan(tmp_path: Path, files: dict[str, str]) -> Path:
    for directory in ("projects", "pitches", "tasks", "cycles", "config"):
        (tmp_path / directory).mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (tmp_path / name).write_text(text, encoding="utf-8")
    return tmp_path


def test_a_file_named_for_one_id_declaring_another_is_a_blocker(tmp_path: Path):
    """The half that hides: `check` said the plan was fine while the id in the
    index belonged to a file the write path would never touch."""
    root = _plan(
        tmp_path,
        {
            "tasks/task-0f0009--impostor.md": IMPOSTOR,
            "tasks/task-0f0001--honest.md": HONEST,
        },
    )
    entities, config, unreadable = load_repo(root)

    # It loads. Blocked, not dropped: a record you cannot see is a record nobody
    # can fix, and this one is readable — it is only lying about which one it is.
    assert unreadable == [], "a mismatch is a problem about a record, not an unreadable file"
    assert {entity.id for entity in entities} == {"task-0a1001", "task-0f0001"}

    problems = validate_all(entities, config)
    named = [p for p in problems if p.field == "id" and p.severity == "blocker"]
    assert named, "the plan reported nothing at all before this"
    assert any("impostor" in p.message for p in named), named
    assert all(p.rule_version == 1 for p in named), "identity is never grandfathered"


def test_two_files_claiming_one_id_both_say_so(tmp_path: Path):
    """Neither wins. Picking either is the defect restated with better manners —
    the index picks the last, the write path picked the first, and the whole
    failure is that those are different files."""
    twin = IMPOSTOR.replace("IMPOSTOR", "The other one")
    root = _plan(
        tmp_path,
        {
            "tasks/task-0a1001--first.md": IMPOSTOR,
            "tasks/task-0a1001--second.md": twin,
        },
    )
    entities, config, _ = load_repo(root)
    problems = [p for p in validate_all(entities, config) if p.field == "id"]

    assert problems, "two files, one id, and nothing said so"
    assert any("claims this id too" in p.message for p in problems)
    # Each names the other, so the report is actionable from either end.
    assert any("second" in p.message for p in problems)
    assert any("first" in p.message for p in problems)


def test_a_renamed_slug_is_still_the_same_record(tmp_path: Path):
    """The slug is decoration and renaming it is legal; the id is the fact. A rule
    that fired on this would make every retitle a blocker."""
    root = _plan(tmp_path, {"tasks/task-0f0001--a-name-nobody-uses-now.md": HONEST})
    entities, config, _ = load_repo(root)

    assert [p for p in validate_all(entities, config) if p.field == "id"] == []


def test_the_bare_id_with_no_slug_is_legal(tmp_path: Path):
    root = _plan(tmp_path, {"tasks/task-0f0001.md": HONEST})
    entities, config, _ = load_repo(root)

    assert [p for p in validate_all(entities, config) if p.field == "id"] == []


def test_a_record_built_in_memory_has_no_filename_to_disagree_with():
    """Every other test in this suite constructs entities directly. None of them
    came from a file, so none of them can be named wrong."""
    entity = parse_text(HONEST, "")
    assert named_for(entity) is False or entity._source == ""
    assert validate_all([entity], Config()) == [] or all(
        p.field != "id" for p in validate_all([entity], Config())
    )


def test_the_seed_corpus_reports_no_identity_problem():
    """If this rule is right, the corpus everybody uses does not trip it. If it
    fires here, the rule is wrong and not the corpus."""
    root = Path(__file__).resolve().parents[1] / "seed"
    entities, config, _ = load_repo(root)

    assert [p for p in validate_all(entities, config) if p.field == "id"] == []


@pytest.mark.parametrize("today", [date(2026, 8, 17)])
def test_the_index_and_the_write_path_no_longer_disagree(tmp_path: Path, today: date):
    """The two mechanisms are asked the same question and have to give the same
    answer. Before, one kept the last file and the other wrote to the first."""
    from openproj.index import build_index

    root = _plan(
        tmp_path,
        {
            "tasks/task-0f0009--impostor.md": IMPOSTOR,
            "tasks/task-0f0001--honest.md": HONEST,
        },
    )
    entities, config, unreadable = load_repo(root)
    index = build_index(entities, config, today, unreadable=unreadable)

    # The impostor is in the index under the id it claims, which is exactly why
    # the write path must refuse: the file it would find is the other one.
    assert "task-0a1001" in index.entities
    assert index.problems, "and the page says so"
    assert any(p.field == "id" for p in index.problems)


def test_a_save_refuses_when_the_file_does_not_declare_the_id_it_is_named_for(tmp_path: Path):
    """The half that costs work.

    PATCH /api/entity/task-0a1001 answered 200 "committed" and `git show` proved
    the commit landed in the file named for that id — a file that was not in the
    index and was not the record the page had shown. A person read one record,
    pressed save, and a different record changed on disk.
    """
    import pygit2
    from fastapi.testclient import TestClient

    from openproj.web import create_app

    plan = tmp_path / "plan"
    plan.mkdir()
    repo = pygit2.init_repository(str(plan))
    (plan / "tasks").mkdir()
    # Named for the id it declares. The honest one.
    (plan / "tasks" / "task-0a1001--the-real-record.md").write_text(
        IMPOSTOR.replace("IMPOSTOR", "The real record"), encoding="utf-8"
    )
    # Named for a different id, and claiming the one above.
    (plan / "tasks" / "task-0f0009--impostor.md").write_text(IMPOSTOR, encoding="utf-8")
    repo.index.add_all()
    repo.index.write()
    who = pygit2.Signature("d", "d@x")
    repo.create_commit("HEAD", who, who, "seed", repo.index.write_tree(), [])

    app = create_app(plan, auth="dev", secret="s", client_id="", client_secret="")
    with TestClient(app) as client:
        head = client.get("/api/index.json").json()["head"]
        answer = client.patch(
            "/api/entity/task-0a1001",
            json={"base_commit": head, "fields": {"priority": "low"}},
        )

    assert answer.status_code == 409, answer.text
    assert "not the one you were shown" in answer.text
    # And nothing moved: the refusal is before the write, not after it.
    assert repo.revparse_single("HEAD").short_id
    on_disk = (plan / "tasks" / "task-0a1001--the-real-record.md").read_text()
    assert "priority: low" not in on_disk, "a save landed on the record nobody was looking at"
