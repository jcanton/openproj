"""Two ways the plan repository stops accepting writes, and what a route says.

    .venv/bin/python tests/load/divergence.py <scratch dir>

Four scenes, each on its own throwaway repository, each ending in a printed
verdict:

  A  the remote is unreachable for one save. The commit is real and local,
     `WriteResult.pushed` is False — and the HTTP routes never read that field,
     so the browser is told the same thing it is told for a save that landed.

  B  somebody with a terminal pushes to the plan while the app is running,
     which `store.py`'s own docstring says happens in week one. The store
     recovers: the push is rejected, `_absorb_remote` fast-forwards, the retry
     lands.

  C  A and then B, in that order. Local holds a commit the remote never got and
     the remote holds a commit local never had, so neither contains the other.
     `_absorb_remote` raises `StoreDiverged` — and goes on raising it for every
     write for the life of the process, because nothing reconciles.

  D  the remote moves under every one of the three attempts `_attempt` makes.
     The fourth is never tried: the ref is rewound, nothing is committed, and
     the caller is answered with a conflict that says so in its own words.

Read-only with respect to anything anybody owns: every repository here is built
under the scratch directory given on the command line.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from openproj.store import Store, StoreDiverged, build_plan_repository  # noqa: E402

PATH = "tasks/task-000001--a.md"
OTHER = "tasks/task-000002--b.md"


def record(rid: str, note: str) -> str:
    return (
        f"---\nid: {rid}\nkind: task\ntitle: {rid}\nstatus: todo\n"
        f"created_schema_version: 2\n---\n\n{note}\n"
    )


def git(where: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "--git-dir", str(where), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def fresh(scratch: Path, name: str) -> tuple[Path, Path, str]:
    local, remote = scratch / f"{name}.git", scratch / f"{name}-remote.git"
    for path in (local, remote):
        if path.exists():
            shutil.rmtree(path)
    first = build_plan_repository(
        local, {PATH: record("task-000001", "one"), OTHER: record("task-000002", "two")}, "seed"
    )
    subprocess.run(
        ["git", "clone", "--bare", "--quiet", str(local), str(remote)],
        check=True,
        capture_output=True,
    )
    return local, remote, first


def human_pushes(remote: Path, scratch: Path, text: str) -> str:
    """A person with a terminal, committing to the plan repository directly."""
    work = scratch / "human"
    if work.exists():
        shutil.rmtree(work)
    subprocess.run(
        ["git", "clone", "--quiet", str(remote), str(work)], check=True, capture_output=True
    )
    (work / OTHER).write_text(record("task-000002", text))
    for args in (
        ["add", "-A"],
        ["-c", "user.email=h@x", "-c", "user.name=human", "commit", "-qm", "human: edited by hand"],
        ["push", "-q", "origin", "HEAD:main"],
    ):
        subprocess.run(["git", "-C", str(work), *args], check=True, capture_output=True)
    return subprocess.run(
        ["git", "-C", str(work), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()


def scene_a(scratch: Path) -> None:
    print("\n=== A. the remote is unreachable for one save ===")
    local, remote, first = fresh(scratch, "a")
    gone = remote.with_name("a-remote-moved.git")
    if gone.exists():
        shutil.rmtree(gone)
    store = Store(local, remote=f"file://{remote}")
    try:
        shutil.move(str(remote), str(gone))
        written = store.write(
            PATH, record("task-000001", "saved while GitHub was down"), first, "ann", "ann: edit"
        )
        print(f"outcome={written.outcome!r}  commit={written.commit[:7]}  pushed={written.pushed}")
        print(
            "the PATCH route builds its answer from `_result` (web.py:1801), which "
            "carries outcome, commit, conflict and head — and not `pushed`."
        )
        print(
            "so the browser is told: 200, outcome 'committed'. Identical to a save "
            "that reached GitHub."
        )
    finally:
        store.close()
        shutil.move(str(gone), str(remote))


def scene_b(scratch: Path) -> None:
    print("\n=== B. a human pushes to the plan while the app is running ===")
    local, remote, first = fresh(scratch, "b")
    store = Store(local, remote=f"file://{remote}")
    try:
        theirs = human_pushes(remote, scratch, "edited from a terminal")
        print(f"human pushed {theirs[:7]} to the remote; the app has not fetched")
        written = store.write(
            PATH, record("task-000001", "saved from the app"), first, "ann", "ann: edit"
        )
        print(
            f"outcome={written.outcome!r}  commit={written.commit and written.commit[:7]}  "
            f"pushed={written.pushed}"
        )
        print("remote main   =", git(remote, "rev-parse", "main")[:7])
        print("local main    =", git(local, "rev-parse", "refs/heads/main")[:7])
        kept = "edited from a terminal" in (store.read(store.head(), OTHER) or "")
        print(f"the human's edit is still in the tree: {kept}")
    finally:
        store.close()


def scene_c(scratch: Path) -> None:
    print("\n=== C. an unpushed commit, and then a human pushes ===")
    local, remote, first = fresh(scratch, "c")
    gone = remote.with_name("c-remote-moved.git")
    if gone.exists():
        shutil.rmtree(gone)
    store = Store(local, remote=f"file://{remote}")
    try:
        shutil.move(str(remote), str(gone))
        stranded = store.write(
            PATH, record("task-000001", "while the remote was away"), first, "ann", "ann: edit"
        )
        print(
            f"app committed {stranded.commit[:7]} with pushed={stranded.pushed} "
            "(200 to the browser)"
        )
        shutil.move(str(gone), str(remote))
        theirs = human_pushes(remote, scratch, "edited from a terminal")
        print(f"human pushed {theirs[:7]}; neither history contains the other")
        try:
            written = store.write(
                PATH, record("task-000001", "the next save"), stranded.commit, "bob", "bob: edit"
            )
            print(f"outcome={written.outcome!r} pushed={written.pushed}")
        except StoreDiverged as error:
            print(f"StoreDiverged: {error}")
            print(
                "`WRITE_FAILURES` (web.py:111) names StoreDiverged, but only "
                "`_commit_room` catches it. PATCH, POST, DELETE, PUT and "
                "POST /api/asset let it out of the handler: a 500 with a "
                "plain-text traceback."
            )
        for attempt in range(2):
            try:
                store.write(
                    OTHER,
                    record("task-000002", f"try {attempt}"),
                    store.head(),
                    "cara",
                    "cara: a different file",
                )
                print(f"a write to a DIFFERENT file succeeded on try {attempt}")
            except StoreDiverged:
                print(
                    f"a write to a DIFFERENT file also raises StoreDiverged "
                    f"(try {attempt}) — nothing reconciles, so this is the "
                    "state of every write for the life of the process"
                )
    finally:
        store.close()


def scene_d(scratch: Path) -> None:
    print("\n=== D. the remote moves under all three attempts ===")
    local, remote, first = fresh(scratch, "d")

    class Outrun(Store):
        """A store whose remote genuinely moves between the commit and the push.

        Not a stubbed exception: a real commit is pushed to the real remote
        immediately before each attempt's push, so libgit2 refuses it for the
        reason it refuses one in production.
        """

        pushes = 0

        def _send(self):
            Outrun.pushes += 1
            human_pushes(remote, scratch, f"terminal edit {Outrun.pushes}")
            return super()._send()

    store = Outrun(local, remote=f"file://{remote}")
    try:
        written = store.write(
            PATH, record("task-000001", "a save nobody can land"), first, "ann", "ann: edit"
        )
        print(f"attempts made: {Outrun.pushes}")
        print(f"outcome={written.outcome!r} commit={written.commit} pushed={written.pushed}")
        print("conflict text the browser is given:")
        print("   " + (written.conflict or "").replace("\n", "\n   "))
        print(
            "`_result` (web.py:1801) turns outcome=='conflict' into HTTP 409, so this "
            "is distinguishable from a save that landed — by the status and by the "
            "sentence, which does not mention a merge."
        )
        still = store.read(store.head(), PATH)
        print(f"the save's text is in the tree: {'nobody can land' in still}")
    finally:
        store.close()


if __name__ == "__main__":
    where = Path(sys.argv[1])
    scene_a(where)
    scene_b(where)
    scene_c(where)
    scene_d(where)
