"""The git layer's contract, written before the git layer exists.

Four facts drive almost every assertion here, and each one is a decision that was
expensive to reach:

* **The repository is bare and no index is ever created.** Eight concurrent
  writers sharing one worktree lost 87.5% of their commits to `index.lock`
  contention. Trees are built with `TreeBuilder` and commits are created
  directly, so there is no index to contend for — hence
  `test_the_repository_stays_bare_and_no_index_file_is_ever_created`, which fails
  the moment somebody reaches for `repo.index` for convenience.
* **One writer, enforced by an flock on the repository directory.** Single-writer
  is a correctness invariant disguised as a deployment detail, so a second
  `Store` on the same path must fail loudly rather than interleave writes.
* **Compare-and-swap is scoped to the path being written.** A stale base whose
  path nobody touched is retried silently; that is ~95% of collisions and it is
  what lets thirty people work at once. Only a real overlap is refused.
* **A refusal writes nothing and shows no conflict markers.** `<<<<<<<` reaching
  a caller means it reaches a `<textarea>`, and then somebody saves it.

`head`, `read` and `paths` are all commit-scoped on purpose: a Store that answers
from a cached "current" state cannot be reasoned about when a human commits to
the same repository from a terminal, which is point five below and a thing that
will happen in week one.
"""

import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pygit2
import pytest
from openproj.store import Store, WriteResult

from openproj.model import parse_text

PATH = "tasks/task-c00001.md"
OTHER = "tasks/task-c00002.md"

BODY = "First line.\nSecond line.\nThird line.\n"

# Eight, because eight is the number of writers that lost 87.5% of their commits
# to index.lock in the measurement this whole design exists to answer.
WRITERS = 8


def entity(
    *,
    id: str = "task-c00001",
    title: str = "Reproduce the equator artefact",
    status: str = "todo",
    owner: str = "ann",
    priority: int = 2,
    body: str = BODY,
) -> str:
    return (
        "---\n"
        f"id: {id}\n"
        "kind: task\n"
        f"title: {title}\n"
        f"status: {status}\n"
        f"owner: {owner}\n"
        f"priority: {priority}\n"
        "---\n"
        f"\n{body}"
    )


SEED = {
    PATH: entity(),
    OTHER: entity(id="task-c00002", title="Downgrade numpy", owner="bo"),
    "config/defaults.yaml": "nominal_availability: 1.0\n",
}


# --------------------------------------------------------------------------- #
# Fixtures
#
# The fixtures build their trees with TreeBuilder too. A fixture that reaches for
# repo.index would leave an index file in the repository and quietly destroy the
# evidence that the Store never made one.
# --------------------------------------------------------------------------- #


def _write_tree(repo: pygit2.Repository, node: dict) -> pygit2.Oid:
    builder = repo.TreeBuilder()
    for name, value in node.items():
        if isinstance(value, dict):
            builder.insert(name, _write_tree(repo, value), pygit2.enums.FileMode.TREE)
        else:
            blob = repo.create_blob(value.encode("utf-8"))
            builder.insert(name, blob, pygit2.enums.FileMode.BLOB)
    return builder.write()


def commit_directly(
    repo_path: Path, files: dict[str, str], message: str, author: str = "a human"
) -> str:
    """Commit `files` as the whole tree, the way a person with a terminal would.

    Used both to seed the corpus and to simulate the human of point five, who
    pushes to the same repository the server is serving.
    """
    repo = pygit2.Repository(str(repo_path))
    root: dict = {}
    for path, content in files.items():
        node = root
        *directories, name = path.split("/")
        for directory in directories:
            node = node.setdefault(directory, {})
        node[name] = content

    signature = pygit2.Signature(author, f"{author.replace(' ', '.')}@example.invalid")
    parents = [] if repo.head_is_unborn else [repo.head.target]
    oid = repo.create_commit(
        "refs/heads/main", signature, signature, message, _write_tree(repo, root), parents
    )
    return str(oid)


def history(repo_path: Path) -> list[pygit2.Commit]:
    """Every commit reachable from the branch, newest first, read fresh from disk."""
    repo = pygit2.Repository(str(repo_path))
    return list(repo.walk(repo.head.target, pygit2.enums.SortMode.TOPOLOGICAL))


@pytest.fixture
def repo_path(tmp_path: Path) -> Path:
    path = tmp_path / "plan.git"
    pygit2.init_repository(str(path), bare=True, initial_head="main")
    commit_directly(path, SEED, "seed the corpus")
    return path


@pytest.fixture
def store(repo_path: Path):
    store = Store(repo_path)
    yield store
    store.close()


# --------------------------------------------------------------------------- #
# 1. A bare repository, no working copy, no index
# --------------------------------------------------------------------------- #


def test_the_repository_stays_bare_and_no_index_file_is_ever_created(store: Store, repo_path: Path):
    """The whole design is here: no index means no index.lock to lose commits to.

    A single `repo.index.add`/`write_tree` anywhere in the write path creates the
    file this asserts is absent, so this test is the guard on the decision rather
    than on the behaviour.
    """
    store.write(
        path=PATH,
        content=entity(status="wip"),
        base_commit=store.head(),
        author="ann",
        message="task-c00001: status todo -> wip",
    )

    repo = pygit2.Repository(str(repo_path))
    assert repo.is_bare
    assert repo.workdir is None
    assert not (repo_path / "index").exists()
    assert not (repo_path / ".git").exists()


def test_a_write_to_a_directory_that_does_not_exist_yet_builds_the_subtree(
    store: Store, repo_path: Path
):
    """TreeBuilder only ever builds one tree, so nested paths have to be walked.

    A root-only implementation writes a blob literally named `pitches/pitch-b1.md`
    here, which git will happily store and no checkout will ever reproduce.
    """
    result = store.write(
        path="pitches/pitch-b00001.md",
        content=entity(id="pitch-b00001", title="Halo exchange"),
        base_commit=store.head(),
        author="ann",
        message="pitch-b00001: create",
    )

    tree = pygit2.Repository(str(repo_path))[result.commit].tree
    assert isinstance(tree["pitches"], pygit2.Tree)
    assert tree["pitches"]["pitch-b00001.md"].name == "pitch-b00001.md"
    assert store.read(result.commit, "pitches/pitch-b00001.md") is not None
    assert store.read(result.commit, OTHER) == SEED[OTHER]  # the siblings survive the rebuild


# --------------------------------------------------------------------------- #
# 2. One writer
# --------------------------------------------------------------------------- #


def test_a_second_store_on_the_same_repository_refuses_to_start(store: Store, repo_path: Path):
    """Single-writer is a correctness invariant, so the second process dies here
    rather than at the first interleaved commit.

    The lock has to be an flock: an fcntl/`lockf` lock is owned by the process, so
    a second Store in the same process would take it happily and this test would
    pass while proving nothing.
    """
    with pytest.raises(RuntimeError) as caught:
        Store(repo_path)

    assert str(repo_path) in str(caught.value)


def test_closing_a_store_releases_the_lock_for_the_next_one(repo_path: Path):
    first = Store(repo_path)
    first.close()

    second = Store(repo_path)
    try:
        assert second.head() == str(pygit2.Repository(str(repo_path)).head.target)
    finally:
        second.close()


# --------------------------------------------------------------------------- #
# 3. Scoped compare-and-swap
# --------------------------------------------------------------------------- #


def test_a_write_against_the_current_head_is_committed_directly(store: Store, repo_path: Path):
    base = store.head()
    result = store.write(
        path=PATH,
        content=entity(status="wip"),
        base_commit=base,
        author="ann",
        message="task-c00001: status todo -> wip",
    )

    assert result == WriteResult(commit=result.commit, outcome="committed", conflict=None)
    assert store.head() == result.commit
    assert str(history(repo_path)[0].parents[0].id) == base


def test_a_stale_base_whose_path_nobody_touched_is_retried_silently(store: Store, repo_path: Path):
    """~95% of collisions: two people editing two different entities.

    Refusing this pair is what makes a planning tool unusable at thirty people, so
    the retry is invisible — a new commit on the current head, no conflict.
    """
    stale = store.head()
    theirs = store.write(
        path=OTHER,
        content=entity(id="task-c00002", title="Downgrade numpy", owner="bo", status="wip"),
        base_commit=stale,
        author="bo",
        message="task-c00002: status todo -> wip",
    )

    mine = store.write(
        path=PATH,
        content=entity(priority=1),
        base_commit=stale,
        author="ann",
        message="task-c00001: priority 2 -> 1",
    )

    assert mine.outcome == "retried"
    assert mine.conflict is None
    assert str(history(repo_path)[0].parents[0].id) == theirs.commit
    assert parse_text(store.read(mine.commit, PATH), PATH).priority == 1
    assert parse_text(store.read(mine.commit, OTHER), OTHER).status == "wip"  # not clobbered


def test_two_edits_to_different_frontmatter_keys_of_one_file_are_merged(store: Store):
    """Field-level merge, not file-level. They set the status while I set the
    priority; a whole-file compare-and-swap would refuse a pair that has no actual
    disagreement in it, and people learn to keep their editors closed."""
    stale = store.head()
    store.write(
        path=PATH,
        content=entity(status="wip"),
        base_commit=stale,
        author="bo",
        message="task-c00001: status todo -> wip",
    )

    mine = store.write(
        path=PATH,
        content=entity(priority=1),
        base_commit=stale,
        author="ann",
        message="task-c00001: priority 2 -> 1",
    )

    assert mine.outcome == "merged"
    assert mine.conflict is None
    merged = parse_text(store.read(mine.commit, PATH), PATH)
    assert (merged.status, merged.priority) == ("wip", 1)
    assert merged.owner == "ann"  # untouched by both, so it survives unchanged


def test_two_edits_to_different_parts_of_the_body_are_merged(store: Store):
    stale = store.head()
    store.write(
        path=PATH,
        content=entity(body="Their first line.\nSecond line.\nThird line.\n"),
        base_commit=stale,
        author="bo",
        message="task-c00001: reshape the opening",
    )

    mine = store.write(
        path=PATH,
        content=entity(body="First line.\nSecond line.\nMy third line.\n"),
        base_commit=stale,
        author="ann",
        message="task-c00001: reshape the ending",
    )

    assert mine.outcome == "merged"
    body = store.read(mine.commit, PATH)
    assert "Their first line." in body
    assert "My third line." in body


def test_both_changing_one_key_differently_is_a_conflict_that_writes_nothing(store: Store):
    """The genuine collision. Nothing is committed, the refusal carries a rendered
    diff, and the caller is told which of the two values is already stored."""
    stale = store.head()
    theirs = store.write(
        path=PATH,
        content=entity(owner="bo"),
        base_commit=stale,
        author="bo",
        message="task-c00001: owner ann -> bo",
    )

    mine = store.write(
        path=PATH,
        content=entity(owner="cy"),
        base_commit=stale,
        author="ann",
        message="task-c00001: owner ann -> cy",
    )

    assert mine.outcome == "conflict"
    assert mine.commit is None
    assert mine.conflict
    assert "bo" in mine.conflict and "cy" in mine.conflict
    assert store.head() == theirs.commit
    assert parse_text(store.read(store.head(), PATH), PATH).owner == "bo"


def test_both_rewriting_one_body_line_differently_is_a_conflict(store: Store):
    stale = store.head()
    store.write(
        path=PATH,
        content=entity(body="First line.\nTheir second line.\nThird line.\n"),
        base_commit=stale,
        author="bo",
        message="task-c00001: rewrite the middle",
    )

    mine = store.write(
        path=PATH,
        content=entity(body="First line.\nMy second line.\nThird line.\n"),
        base_commit=stale,
        author="ann",
        message="task-c00001: rewrite the middle",
    )

    assert mine.outcome == "conflict"
    assert mine.commit is None


def test_no_conflict_marker_ever_reaches_the_caller_or_the_repository(store: Store):
    """A `<<<<<<<` in the refusal is a `<<<<<<<` in a textarea, and then somebody
    presses Save and the markers are in the corpus for good."""
    markers = ("<<<<<<<", "=======", ">>>>>>>")
    stale = store.head()
    store.write(
        path=PATH,
        content=entity(owner="bo", body="First line.\nTheir second line.\nThird line.\n"),
        base_commit=stale,
        author="bo",
        message="task-c00001: theirs",
    )

    mine = store.write(
        path=PATH,
        content=entity(owner="cy", body="First line.\nMy second line.\nThird line.\n"),
        base_commit=stale,
        author="ann",
        message="task-c00001: mine",
    )

    assert mine.outcome == "conflict"
    assert not [marker for marker in markers if marker in mine.conflict]
    stored = store.read(store.head(), PATH)
    assert not [marker for marker in markers if marker in stored]


# --------------------------------------------------------------------------- #
# 4. Authorship
# --------------------------------------------------------------------------- #


def test_the_author_is_the_person_and_the_committer_is_the_bot(store: Store, repo_path: Path):
    """Splitting the two makes `git log --format=%an` a per-person audit trail for
    free, while any future push credential stays a bot that no human shares."""
    result = store.write(
        path=PATH,
        content=entity(status="wip"),
        base_commit=store.head(),
        author="ann",
        message="task-c00001: status todo -> wip",
    )

    commit = pygit2.Repository(str(repo_path))[result.commit]
    assert commit.author.name == "ann"
    assert commit.committer.name == "openproj-bot"
    assert commit.message == "task-c00001: status todo -> wip"


def test_git_log_reads_back_as_the_audit_trail(store: Store, repo_path: Path):
    """Asserted through git itself, because the claim being made is about what a
    person gets from a terminal, not about what pygit2 returns."""
    for author, status in (("ann", "wip"), ("bo", "done"), ("cy", "shelved")):
        store.write(
            path=PATH,
            content=entity(status=status),
            base_commit=store.head(),
            author=author,
            message=f"task-c00001: status -> {status}",
        )

    log = subprocess.run(
        ["git", "-C", str(repo_path), "log", "--format=%an|%cn"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()

    assert log[:3] == ["cy|openproj-bot", "bo|openproj-bot", "ann|openproj-bot"]


def test_a_retried_write_still_records_the_person_who_asked_for_it(store: Store, repo_path: Path):
    """The retry is a mechanical detail of the store; it must not become the bot's
    edit, or the audit trail loses exactly the writes that collided."""
    stale = store.head()
    store.write(
        path=OTHER,
        content=entity(id="task-c00002", title="Downgrade numpy", owner="bo", status="wip"),
        base_commit=stale,
        author="bo",
        message="task-c00002: status todo -> wip",
    )
    mine = store.write(
        path=PATH,
        content=entity(priority=1),
        base_commit=stale,
        author="ann",
        message="task-c00001: priority 2 -> 1",
    )

    assert mine.outcome == "retried"
    assert pygit2.Repository(str(repo_path))[mine.commit].author.name == "ann"


# --------------------------------------------------------------------------- #
# 5. A human committing to the same repository
# --------------------------------------------------------------------------- #


def test_a_commit_made_outside_the_store_is_seen_by_head(store: Store, repo_path: Path):
    """The store may not cache HEAD. Somebody will `git push` to this repository,
    and a cached head turns their commit into the parent of nothing."""
    before = store.head()
    outside = commit_directly(
        repo_path, {**SEED, "tasks/task-c00003.md": entity(id="task-c00003", title="By hand")},
        "task-c00003: added from a terminal",
    )

    assert store.head() == outside != before


def test_the_next_write_lands_on_top_of_an_external_commit_not_over_it(
    store: Store, repo_path: Path
):
    stale = store.head()
    outside = commit_directly(
        repo_path, {**SEED, "tasks/task-c00003.md": entity(id="task-c00003", title="By hand")},
        "task-c00003: added from a terminal",
    )

    mine = store.write(
        path=PATH,
        content=entity(status="wip"),
        base_commit=stale,
        author="ann",
        message="task-c00001: status todo -> wip",
    )

    assert mine.outcome == "retried"
    assert str(history(repo_path)[0].parents[0].id) == outside
    assert store.read(mine.commit, "tasks/task-c00003.md") is not None
    assert parse_text(store.read(mine.commit, PATH), PATH).status == "wip"


def test_a_human_editing_the_same_entity_is_merged_or_refused_like_anybody_else(
    store: Store, repo_path: Path
):
    """An external commit is not privileged and is not ignored: it is just the
    other side of the compare-and-swap."""
    stale = store.head()
    commit_directly(repo_path, {**SEED, PATH: entity(owner="bo")}, "task-c00001: owner -> bo")

    mine = store.write(
        path=PATH,
        content=entity(owner="cy"),
        base_commit=stale,
        author="ann",
        message="task-c00001: owner -> cy",
    )

    assert mine.outcome == "conflict"
    assert parse_text(store.read(store.head(), PATH), PATH).owner == "bo"


# --------------------------------------------------------------------------- #
# read and paths
# --------------------------------------------------------------------------- #


def test_reading_a_path_that_does_not_exist_gives_none(store: Store):
    """None, not an exception: "no such entity" is a 404 the caller renders, and
    the alternative is a try/except around every read in the index build."""
    assert store.read(store.head(), "tasks/task-ffffff.md") is None
    assert store.read(store.head(), "tasks") is None  # a directory is not a file
    assert store.read(store.head(), PATH) == SEED[PATH]


def test_a_path_is_read_at_the_commit_it_is_asked_for(store: Store):
    before = store.head()
    after = store.write(
        path="tasks/task-c00003.md",
        content=entity(id="task-c00003", title="Later"),
        base_commit=before,
        author="ann",
        message="task-c00003: create",
    ).commit

    assert store.read(before, "tasks/task-c00003.md") is None
    assert store.read(after, "tasks/task-c00003.md") is not None
    assert store.read(before, PATH) == store.read(after, PATH)


def test_paths_lists_every_file_in_the_tree_at_that_commit(store: Store):
    """Every file, nested directories walked, and no directory entries — this is
    what the index build enumerates, so a bare `tasks` in the list is a parse
    error at startup."""
    before = store.head()
    after = store.write(
        path="pitches/pitch-b00001.md",
        content=entity(id="pitch-b00001", title="Halo exchange"),
        base_commit=before,
        author="ann",
        message="pitch-b00001: create",
    ).commit

    assert sorted(store.paths(before)) == sorted(SEED)
    assert sorted(store.paths(after)) == sorted([*SEED, "pitches/pitch-b00001.md"])
    assert "tasks" not in store.paths(after)


# --------------------------------------------------------------------------- #
# Concurrency
# --------------------------------------------------------------------------- #


@pytest.fixture
def preempted():
    """Make the interpreter switch threads *inside* a write.

    Measured: at the default 5 ms switch interval a whole write runs to completion
    before any other thread is scheduled, so a store with no serialisation at all
    passes both tests below — 20 trials, zero interleavings. At 1e-6 the same
    unserialised store fails on the first trial, 20 times out of 20. Without this
    fixture these are not concurrency tests, they are eight sequential writes with
    extra machinery.
    """
    previous = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    yield
    sys.setswitchinterval(previous)


def test_eight_concurrent_writers_all_land_their_commits(
    store: Store, repo_path: Path, preempted: None
):
    """The measurement this design exists to answer: eight writers sharing one
    worktree lost 87.5% of their commits to index.lock. Here all eight must land.

    They all start from the same base, so seven of them are stale by the time they
    are served — every one of those is a different path, so every one is a silent
    retry rather than a refusal.
    """
    base = store.head()
    barrier = threading.Barrier(WRITERS)

    def write(n: int) -> WriteResult:
        barrier.wait()
        return store.write(
            path=f"tasks/task-{n:06d}.md",
            content=entity(id=f"task-{n:06d}", title=f"Concurrent {n}"),
            base_commit=base,
            author=f"user{n}",
            message=f"task-{n:06d}: create",
        )

    with ThreadPoolExecutor(max_workers=WRITERS) as pool:
        results = list(pool.map(write, range(WRITERS)))

    head = store.head()
    written = [f"tasks/task-{n:06d}.md" for n in range(WRITERS)]

    outcomes = [r.outcome for r in results]
    assert outcomes.count("committed") == 1  # whoever the writer lock happens to serve first
    assert outcomes.count("retried") == WRITERS - 1
    assert len({r.commit for r in results}) == WRITERS
    assert {r.commit for r in results} <= {str(c.id) for c in history(repo_path)}
    assert len(history(repo_path)) == WRITERS + 1  # the seed, plus one per writer
    assert sorted(store.paths(head)) == sorted([*SEED, *written])
    for n, path in enumerate(written):
        assert parse_text(store.read(head, path), path).title == f"Concurrent {n}"


def test_concurrent_writers_to_one_path_neither_lose_nor_interleave(
    store: Store, repo_path: Path, preempted: None
):
    """Same file, eight writers, each rebasing on the head it is given. Whatever
    the store decides about each one, the survivors form a single chain and the
    losers changed nothing — a lost update here would be silent data loss."""
    barrier = threading.Barrier(WRITERS)

    def write(n: int) -> WriteResult:
        barrier.wait()
        return store.write(
            path=PATH,
            content=entity(priority=n % 3 + 1),
            base_commit=store.head(),
            author=f"user{n}",
            message=f"task-c00001: priority -> {n % 3 + 1}",
        )

    with ThreadPoolExecutor(max_workers=WRITERS) as pool:
        results = list(pool.map(write, range(WRITERS)))

    landed = [r.commit for r in results if r.commit is not None]
    assert landed, "somebody has to win"
    assert len(set(landed)) == len(landed)
    assert len(history(repo_path)) == len(landed) + 1
    assert parse_text(store.read(store.head(), PATH), PATH).priority in (1, 2, 3)


# --------------------------------------------------------------------------- #
# Round trip
# --------------------------------------------------------------------------- #


def test_the_content_committed_is_the_content_read_back(store: Store):
    """Byte for byte. The serialiser preserves a hand-written file's formatting
    exactly, and a store that normalises newlines or strips a trailing one throws
    that away and makes every save show a spurious diff.
    """
    content = (
        "---\nid: task-c00001\nkind: task\ntitle: Café — naïve ölschmidt\n---\n"
        "\nBödy\twith\ttabs.\n\n\n"
    )
    result = store.write(
        path=PATH,
        content=content,
        base_commit=store.head(),
        author="ann",
        message="task-c00001: unicode and whitespace",
    )

    assert store.read(result.commit, PATH) == content


def test_a_file_with_no_trailing_newline_keeps_not_having_one(store: Store):
    content = "---\nid: task-c00001\nkind: task\ntitle: No newline\n---\n\nEnds abruptly."
    result = store.write(
        path=PATH,
        content=content,
        base_commit=store.head(),
        author="ann",
        message="task-c00001: no trailing newline",
    )

    assert store.read(result.commit, PATH) == content
