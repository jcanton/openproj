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

from openproj.model import parse_person_text, parse_text
from openproj.store import Store, StoreLocked, WriteResult, _merge_body

PATH = "tasks/task-c00001.md"
OTHER = "tasks/task-c00002.md"

BODY = "First line.\nSecond line.\nThird line.\n"

# Eight, because eight is the number of writers that lost 87.5% of their commits
# to index.lock in the measurement this whole design exists to answer.
WRITERS = 8


def record(
    *,
    id: str = "task-c00001",
    title: str = "Reproduce the seam artefact",
    status: str = "ready",
    owner: str = "ann",
    priority: str = "medium",
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
    PATH: record(),
    OTHER: record(id="task-c00002", title="Downgrade numpy", owner="bo"),
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
    repo_path: Path,
    files: dict[str, str],
    message: str,
    author: str = "a human",
    when: int | None = None,
    parents: list | None = None,
    ref: str | None = "refs/heads/main",
) -> str:
    """Commit `files` as the whole tree, the way a person with a terminal would.

    Used both to seed the corpus and to simulate the human of point five, who
    pushes to the same repository the server is serving.

    `when` pins the committer clock, `parents` overrides the branch tip, and
    `ref=None` leaves the commit dangling — together they build the side
    branches and merges the last-edited walk is defined over, with times that
    mean something instead of three commits inside one wall-clock second.
    """
    repo = pygit2.Repository(str(repo_path))
    root: dict = {}
    for path, content in files.items():
        node = root
        *directories, name = path.split("/")
        for directory in directories:
            node = node.setdefault(directory, {})
        node[name] = content

    email = f"{author.replace(' ', '.')}@example.invalid"
    signature = (
        pygit2.Signature(author, email, when, 0)
        if when is not None
        else pygit2.Signature(author, email)
    )
    if parents is None:
        parents = [] if repo.head_is_unborn else [repo.head.target]
    oid = repo.create_commit(
        ref, signature, signature, message, _write_tree(repo, root), parents
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
        content=record(status="in_progress"),
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
        content=record(id="pitch-b00001", title="Halo exchange"),
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
        content=record(status="in_progress"),
        base_commit=base,
        author="ann",
        message="task-c00001: status todo -> wip",
    )

    assert result == WriteResult(commit=result.commit, outcome="committed", conflict=None)
    assert store.head() == result.commit
    assert str(history(repo_path)[0].parents[0].id) == base


def test_a_stale_base_whose_path_nobody_touched_is_retried_silently(store: Store, repo_path: Path):
    """~95% of collisions: two people editing two different records.

    Refusing this pair is what makes a planning tool unusable at thirty people, so
    the retry is invisible — a new commit on the current head, no conflict.
    """
    stale = store.head()
    theirs = store.write(
        path=OTHER,
        content=record(id="task-c00002", title="Downgrade numpy", owner="bo", status="in_progress"),
        base_commit=stale,
        author="bo",
        message="task-c00002: status todo -> wip",
    )

    mine = store.write(
        path=PATH,
        content=record(priority="high"),
        base_commit=stale,
        author="ann",
        message="task-c00001: priority 2 -> 1",
    )

    assert mine.outcome == "retried"
    assert mine.conflict is None
    assert str(history(repo_path)[0].parents[0].id) == theirs.commit
    assert parse_text(store.read(mine.commit, PATH), PATH).priority == "high"
    # not clobbered
    assert parse_text(store.read(mine.commit, OTHER), OTHER).status == "in_progress"


def test_two_edits_to_different_frontmatter_keys_of_one_file_are_merged(store: Store):
    """Field-level merge, not file-level. They set the status while I set the
    priority; a whole-file compare-and-swap would refuse a pair that has no actual
    disagreement in it, and people learn to keep their editors closed."""
    stale = store.head()
    store.write(
        path=PATH,
        content=record(status="in_progress"),
        base_commit=stale,
        author="bo",
        message="task-c00001: status todo -> wip",
    )

    mine = store.write(
        path=PATH,
        content=record(priority="high"),
        base_commit=stale,
        author="ann",
        message="task-c00001: priority 2 -> 1",
    )

    assert mine.outcome == "merged"
    assert mine.conflict is None
    merged = parse_text(store.read(mine.commit, PATH), PATH)
    assert (merged.status, merged.priority) == ("in_progress", "high")
    assert merged.owner == "ann"  # untouched by both, so it survives unchanged


def test_two_edits_to_different_parts_of_the_body_are_merged(store: Store):
    stale = store.head()
    store.write(
        path=PATH,
        content=record(body="Their first line.\nSecond line.\nThird line.\n"),
        base_commit=stale,
        author="bo",
        message="task-c00001: reshape the opening",
    )

    mine = store.write(
        path=PATH,
        content=record(body="First line.\nSecond line.\nMy third line.\n"),
        base_commit=stale,
        author="ann",
        message="task-c00001: reshape the ending",
    )

    assert mine.outcome == "merged"
    body = store.read(mine.commit, PATH)
    assert "Their first line." in body
    assert "My third line." in body


def test_an_insertion_and_a_replacement_on_one_line_are_refused_not_half_kept(store: Store):
    """The drop that answered `merged`.

    `SequenceMatcher` reports an insertion before line 2 as the EMPTY span
    `(1, 1)`, and a replacement of line 2 as `(1, 2)`. They begin at the same
    line and they do not overlap — `other_span[0] < span[1]` is `1 < 1` — so the
    old test called them independent and merged them. The assembly could only
    keep one: `{*ours, *yours}` is a set, both spans start at 1, and whichever
    came out first moved `cursor` past the other, which the `cursor > span[0]`
    guard then skipped.

    Measured on 4,000 generated same-start pairs before the fix: **48% lost a
    line.** Half of those were the line already in git, so a save was answered
    with a commit sha while reverting somebody's committed sentence, and nothing
    anywhere said so. Across all merges it is 2.8%, which is why it survived.

    A refusal is announced and a drop is not, so this asks for the refusal.
    """
    stale = store.head()
    store.write(
        path=PATH,
        content=record(body="alpha\nbeta\ngamma\n"),
        base_commit=stale,
        author="ann",
        message="task-c00001: three lines to collide over",
    )
    settled = store.head()

    store.write(
        path=PATH,
        content=record(body="alpha\nbo squeezed a line in\nbeta\ngamma\n"),
        base_commit=settled,
        author="bo",
        message="task-c00001: insert before beta",
    )

    mine = store.write(
        path=PATH,
        content=record(body="alpha\nann rewrote beta\ngamma\n"),
        base_commit=settled,
        author="ann",
        message="task-c00001: replace beta",
    )

    assert mine.outcome == "conflict", (
        "an insertion and a replacement beginning on one line merged, and a "
        "merge here can only keep one of them"
    )
    assert mine.commit is None
    # The refusal names both sides, so the person refused can see what they are
    # up against rather than only that they lost.
    assert "bo squeezed a line in" in mine.conflict
    assert "ann rewrote beta" in mine.conflict

    # And nothing was written: bo's line is still there, exactly as bo left it.
    body = store.read(store.head(), PATH)
    assert "bo squeezed a line in" in body
    assert "ann rewrote beta" not in body


def test_a_refusal_over_an_insertion_says_before_which_line():
    """Asked of `_merge_body` directly, because the wording only appears when the
    SAVE being made is the insertion — the message is built from the caller's own
    span, and through `Store.write` that is whichever side arrives second.

    An insertion's span is empty, and rendering `(1, 1)` as a range printed
    `lines 2-1`: a span that reads backwards, in the one sentence somebody gets
    when their work is refused.
    """
    merged, conflicts = _merge_body(
        "alpha\nbeta\ngamma\n",
        "alpha\nmine, squeezed in\nbeta\ngamma\n",   # insertion: span (1, 1)
        "alpha\ntheirs, replacing\ngamma\n",          # replacement: span (1, 2)
    )

    assert merged is None
    assert conflicts and "before line 2" in conflicts[0], conflicts
    assert "-" not in conflicts[0].split(":")[0], conflicts[0]


def test_two_people_inserting_at_different_places_still_merge(store: Store):
    """The shape the widened test must NOT catch, and the common one.

    Twelve people writing under twelve different headings is the case the audit
    measured at 116 merges and zero conflicts. Those are insertions at different
    indices, so they do not begin at the same line and nothing here touches them.
    """
    stale = store.head()
    store.write(
        path=PATH,
        content=record(body="alpha\nbeta\ngamma\n"),
        base_commit=stale,
        author="ann",
        message="task-c00001: three lines",
    )
    settled = store.head()

    store.write(
        path=PATH,
        content=record(body="alpha\nbo wrote here\nbeta\ngamma\n"),
        base_commit=settled,
        author="bo",
        message="task-c00001: insert after alpha",
    )

    mine = store.write(
        path=PATH,
        content=record(body="alpha\nbeta\ngamma\nann wrote at the end\n"),
        base_commit=settled,
        author="ann",
        message="task-c00001: insert after gamma",
    )

    assert mine.outcome == "merged", mine.conflict
    body = store.read(mine.commit, PATH)
    assert "bo wrote here" in body
    assert "ann wrote at the end" in body


def test_the_same_edit_made_twice_is_not_a_collision(store: Store):
    """Two people typing the same correction is not a disagreement. The widened
    test still gates on `replacement != other_replacement`, so identical edits at
    one line merge to themselves rather than refusing."""
    stale = store.head()
    store.write(
        path=PATH,
        content=record(body="alpha\nbeta\ngamma\n"),
        base_commit=stale,
        author="ann",
        message="task-c00001: three lines",
    )
    settled = store.head()

    both = "alpha\nBETA\ngamma\n"
    store.write(
        path=PATH, content=record(body=both), base_commit=settled,
        author="bo", message="task-c00001: shout beta",
    )
    mine = store.write(
        path=PATH, content=record(body=both), base_commit=settled,
        author="ann", message="task-c00001: shout beta too",
    )

    assert mine.outcome in ("merged", "retried"), mine.conflict
    assert "BETA" in store.read(store.head(), PATH)


def test_both_changing_one_key_differently_is_a_conflict_that_writes_nothing(store: Store):
    """The genuine collision. Nothing is committed, the refusal carries a rendered
    diff, and the caller is told which of the two values is already stored."""
    stale = store.head()
    theirs = store.write(
        path=PATH,
        content=record(owner="bo"),
        base_commit=stale,
        author="bo",
        message="task-c00001: owner ann -> bo",
    )

    mine = store.write(
        path=PATH,
        content=record(owner="cy"),
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
        content=record(body="First line.\nTheir second line.\nThird line.\n"),
        base_commit=stale,
        author="bo",
        message="task-c00001: rewrite the middle",
    )

    mine = store.write(
        path=PATH,
        content=record(body="First line.\nMy second line.\nThird line.\n"),
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
        content=record(owner="bo", body="First line.\nTheir second line.\nThird line.\n"),
        base_commit=stale,
        author="bo",
        message="task-c00001: theirs",
    )

    mine = store.write(
        path=PATH,
        content=record(owner="cy", body="First line.\nMy second line.\nThird line.\n"),
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
        content=record(status="in_progress"),
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
    for author, status in (("ann", "in_progress"), ("bo", "done"), ("cy", "shelved")):
        store.write(
            path=PATH,
            content=record(status=status),
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
        content=record(id="task-c00002", title="Downgrade numpy", owner="bo", status="in_progress"),
        base_commit=stale,
        author="bo",
        message="task-c00002: status todo -> wip",
    )
    mine = store.write(
        path=PATH,
        content=record(priority="high"),
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
        repo_path, {**SEED, "tasks/task-c00003.md": record(id="task-c00003", title="By hand")},
        "task-c00003: added from a terminal",
    )

    assert store.head() == outside != before


def test_the_next_write_lands_on_top_of_an_external_commit_not_over_it(
    store: Store, repo_path: Path
):
    stale = store.head()
    outside = commit_directly(
        repo_path, {**SEED, "tasks/task-c00003.md": record(id="task-c00003", title="By hand")},
        "task-c00003: added from a terminal",
    )

    mine = store.write(
        path=PATH,
        content=record(status="in_progress"),
        base_commit=stale,
        author="ann",
        message="task-c00001: status todo -> wip",
    )

    assert mine.outcome == "retried"
    assert str(history(repo_path)[0].parents[0].id) == outside
    assert store.read(mine.commit, "tasks/task-c00003.md") is not None
    assert parse_text(store.read(mine.commit, PATH), PATH).status == "in_progress"


def test_a_human_editing_the_same_record_is_merged_or_refused_like_anybody_else(
    store: Store, repo_path: Path
):
    """An external commit is not privileged and is not ignored: it is just the
    other side of the compare-and-swap."""
    stale = store.head()
    commit_directly(repo_path, {**SEED, PATH: record(owner="bo")}, "task-c00001: owner -> bo")

    mine = store.write(
        path=PATH,
        content=record(owner="cy"),
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
    """None, not an exception: "no such record" is a 404 the caller renders, and
    the alternative is a try/except around every read in the index build."""
    assert store.read(store.head(), "tasks/task-ffffff.md") is None
    assert store.read(store.head(), "tasks") is None  # a directory is not a file
    assert store.read(store.head(), PATH) == SEED[PATH]


def test_a_path_is_read_at_the_commit_it_is_asked_for(store: Store):
    before = store.head()
    after = store.write(
        path="tasks/task-c00003.md",
        content=record(id="task-c00003", title="Later"),
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
        content=record(id="pitch-b00001", title="Halo exchange"),
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
            content=record(id=f"task-{n:06d}", title=f"Concurrent {n}"),
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
            content=record(priority=["high", "medium", "low"][n % 3]),
            base_commit=store.head(),
            author=f"user{n}",
            message=f'task-c00001: priority -> {["high", "medium", "low"][n % 3]}',
        )

    with ThreadPoolExecutor(max_workers=WRITERS) as pool:
        results = list(pool.map(write, range(WRITERS)))

    landed = [r.commit for r in results if r.commit is not None]
    assert landed, "somebody has to win"
    assert len(set(landed)) == len(landed)
    assert len(history(repo_path)) == len(landed) + 1
    assert parse_text(store.read(store.head(), PATH), PATH).priority in (
        "high",
        "medium",
        "low",
    )


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


def test_the_refusal_names_the_process_holding_the_lock(store: Store, repo_path: Path):
    """A second writer must fail loudly, and the message has to be actionable.

    The first version stated the invariant and left you to find the process
    yourself — and `pkill openproj` does not match the installed entrypoint, so the
    honest answer to "which process" was a hunt through ps. The suggested command
    is kill -9 rather than kill, because SIGTERM does not reliably end a uvicorn
    started through `uv run` and the lock outlives the attempt.
    """
    import os

    with pytest.raises(StoreLocked) as caught:
        Store(repo_path)

    assert str(os.getpid()) in str(caught.value)


def test_a_second_writer_does_not_erase_the_holders_pid(store: Store, repo_path: Path):
    """Opening the lock file for writing truncates it. A refused second writer
    would therefore wipe the very pid the refusal is supposed to report."""
    import os

    with pytest.raises(StoreLocked):
        Store(repo_path)

    assert (repo_path / "openproj.lock").read_text().strip() == str(os.getpid())


def test_a_path_that_is_not_a_repository_is_refused_rather_than_searched_upwards(tmp_path):
    """pygit2 walks UP by default until it finds a repository, and openproj's own
    checkout is upwards of almost everywhere somebody runs this.

    `--repo seed` — which the README told people to use — therefore opened the
    openproj repository itself: 126 paths visible, none of them under `pitches/`,
    `tasks/` or `projects/`, because the seed corpus lives one directory down.
    Every route answered 200 over an empty plan, and nothing anywhere said so. A
    tool drawing a plan with nothing in it is indistinguishable from a plan with
    nothing in it.
    """
    from openproj.store import NotAPlanRepository

    not_a_repo = tmp_path / "corpus"
    not_a_repo.mkdir()
    (not_a_repo / "tasks").mkdir()

    with pytest.raises(NotAPlanRepository) as refusal:
        Store(not_a_repo)

    assert "not a git repository" in str(refusal.value)
    assert "--bare" in str(refusal.value), "the message has to say what to do instead"


# --------------------------------------------------------------------------- #
# 8. One record per person, which is a decision about this file
#
# The icons feature is the reason `people/<login>.md` exists, and the shape was
# chosen against the merge in this module rather than for tidiness. The version
# that was abandoned kept every icon in `config/people.yaml` — the first writable
# path that would have been YAML end to end — and everything in `_merge` above
# treats a file as frontmatter plus prose: a per-key merge of the map at the top,
# a three-way LINE merge of everything under it. Two edits nobody would call a
# disagreement (they add a name to the roster, I clear my icon) therefore
# line-merged into text that is not YAML, committed as `outcome: "merged"` with a
# 200, and took the roster and every icon down on every page at once, on a branch
# whose protection means the commit cannot be force-pushed away.
#
# So the two tests below are the two halves of the fix, and neither of them
# mocks anything: they are the store, writing the files the endpoint writes.
# --------------------------------------------------------------------------- #

ANN_RECORD = "people/ann.md"
BO_RECORD = "people/bo.md"

ANN_ABOUT = "\nAnn, who works on the core solver.\n"


def person(icon: str, body: str = "") -> str:
    return f"---\nicon: {icon}\n---\n{body}"


def test_two_people_choosing_at_once_write_two_files_and_neither_is_merged(
    store: Store, repo_path: Path
):
    """The collision this feature invents, and the shape that makes it not one.

    Both read the same HEAD and both write. Compare-and-swap here is scoped to
    the path, so the second write finds HEAD moved, finds its OWN path untouched
    by the move, and is retried silently — there is no merge to get right,
    because the two people were never editing the same file. That is the whole
    argument for a record per person: in the arrangement this replaced these two
    writes were two edits of one YAML file, and the merge of them is what could
    not be read back.
    """
    base = store.head()

    first = store.write(
        path=ANN_RECORD, content=person("fox"), base_commit=base,
        author="ann", message="ann: icon fox",
    )
    second = store.write(
        path=BO_RECORD, content=person("owl"), base_commit=base,
        author="bo", message="bo: icon owl",
    )

    assert first.outcome == "committed"
    assert second.outcome == "retried", second.conflict
    head = store.head()
    # Both landed, and both still read. Asked of the parser and not of the bytes:
    # what went wrong last time was a file that still looked like a file.
    assert parse_person_text(store.read(head, ANN_RECORD), ANN_RECORD).icon == "fox"
    assert parse_person_text(store.read(head, BO_RECORD), BO_RECORD).icon == "owl"
    # And bo's write left ann's file exactly as ann wrote it. Nothing merged,
    # nothing re-serialised, nothing to disagree about.
    assert store.read(head, ANN_RECORD) == person("fox")


def test_a_merge_inside_one_persons_record_still_reads_back_as_a_person(
    store: Store, repo_path: Path
):
    """The other half: when a merge does happen here, it happens over frontmatter.

    Two tabs, or a person and an admin with a terminal. One side clears the icon,
    the other rewrites the sentence under the fence — non-overlapping, which is
    exactly the case the old arrangement answered with unparseable YAML. Here the
    map is merged key by key and dumped, and the prose is merged as lines, so the
    merge cannot produce a frontmatter the model will not read.
    """
    started = person("fox", ANN_ABOUT)
    commit_directly(repo_path, {**SEED, ANN_RECORD: started}, "ann writes herself down")
    base = store.head()
    commit_directly(
        repo_path,
        {**SEED, ANN_RECORD: person("fox", "\nAnn, who works on the core solver and the halo.\n")},
        "a longer sentence about ann",
    )

    written = store.write(
        path=ANN_RECORD,
        content=person("null", ANN_ABOUT),
        base_commit=base,
        author="ann",
        message="ann: no icon",
    )

    assert written.outcome == "merged", written.conflict
    landed = store.read(store.head(), ANN_RECORD)
    assert parse_person_text(landed, ANN_RECORD).icon is None
    assert "halo" in landed, "the other side's sentence survived"


# --------------------------------------------------------------------------- #
# 9. last_edited: when a commit last touched each path, in git-log semantics
# --------------------------------------------------------------------------- #


def test_a_side_branch_edit_merged_in_carries_the_side_commits_time(tmp_path: Path):
    """First-parent diffing is the defect this pins: it would stamp the side
    branch's edit with the merge's time, because the file differs across the
    first-parent edge. `git log -- path` says the side commit, and so must this.
    """
    path = tmp_path / "plan.git"
    pygit2.init_repository(str(path), bare=True, initial_head="main")
    base = commit_directly(path, SEED, "seed", when=1_000_000)

    on_main = dict(SEED)
    on_main[OTHER] = record(id="task-c00002", title="Downgrade numpy differently", owner="bo")
    tip = commit_directly(path, on_main, "edit the other task on main", when=1_000_100)

    on_side = dict(SEED)
    on_side[PATH] = record(title="Reproduce the artefact at the pole")
    side = commit_directly(
        path, on_side, "edit on a side branch", when=1_000_200, parents=[base], ref=None
    )

    merged = dict(SEED)
    merged[PATH] = on_side[PATH]
    merged[OTHER] = on_main[OTHER]
    merge = commit_directly(path, merged, "merge the branch", when=1_000_900,
                            parents=[tip, side])

    store = Store(path)
    try:
        head, stamps = store.last_edited()
    finally:
        store.close()

    assert head == merge
    # The merge's blob for each file equals ONE of its parents', so the merge
    # stamps neither; the newest commit that really changed each file does.
    assert stamps[PATH] == 1_000_200, "the side commit's time, never the merge's"
    assert stamps[OTHER] == 1_000_100
    assert stamps["config/defaults.yaml"] == 1_000_000


def test_an_edit_reverted_inside_one_batch_is_stamped_with_the_revert(tmp_path: Path):
    """The endpoint-diff shortcut — one diff between the cached commit and head
    — sees identical blobs at both ends and keeps the stale stamp. The walk
    visits every commit in the window, so the revert is the touch that wins.
    """
    path = tmp_path / "plan.git"
    pygit2.init_repository(str(path), bare=True, initial_head="main")
    commit_directly(path, SEED, "seed", when=1_000_000)

    store = Store(path)
    try:
        known = store.last_edited()

        edited = dict(SEED)
        edited[PATH] = record(status="in_progress")
        commit_directly(path, edited, "edit", when=1_000_100)
        commit_directly(path, SEED, "revert the edit", when=1_000_200)

        head, stamps = store.last_edited(known=known)
        assert stamps[PATH] == 1_000_200, "the revert is the last edit, not the seed"
        # And advancing the cache is the same answer as walking from scratch.
        assert (head, stamps) == store.last_edited()
    finally:
        store.close()


def test_last_edited_drops_a_deleted_path_and_stamps_an_added_one(tmp_path: Path):
    path = tmp_path / "plan.git"
    pygit2.init_repository(str(path), bare=True, initial_head="main")
    commit_directly(path, SEED, "seed", when=1_000_000)

    store = Store(path)
    try:
        known = store.last_edited()
        changed = dict(SEED)
        del changed[OTHER]
        changed["tasks/task-c00003.md"] = record(id="task-c00003", title="A third task")
        commit_directly(path, changed, "add one, delete one", when=1_000_300)

        head, stamps = store.last_edited(known=known)
        assert OTHER not in stamps, "a deleted path must leave the map"
        assert stamps["tasks/task-c00003.md"] == 1_000_300
        assert (head, stamps) == store.last_edited()
    finally:
        store.close()


def test_a_rewound_ref_discards_the_cache_and_rebuilds(tmp_path: Path):
    """The lost-race shape from `store.py`'s `_attempt`: a commit is published
    on the branch ref, the push loses, and the ref is rewound (`set_target`).
    The cached commit is then not an ancestor of the next head. Rule: discard
    and re-walk — retract-by-rebuild, because there is no retraction logic to
    get wrong — so the doomed commit's stamp cannot outlive the commit.
    """
    path = tmp_path / "plan.git"
    pygit2.init_repository(str(path), bare=True, initial_head="main")
    base = commit_directly(path, SEED, "seed", when=1_000_000)

    store = Store(path)
    try:
        doomed_tree = dict(SEED)
        doomed_tree[PATH] = record(title="An edit whose push will lose")
        doomed = commit_directly(path, doomed_tree, "a doomed publish", when=1_000_100)
        known = store.last_edited()
        assert known[0] == doomed
        assert known[1][PATH] == 1_000_100

        # Rewind the way `_attempt` does, then land somebody else's commit.
        pygit2.Repository(str(path)).references["refs/heads/main"].set_target(base)
        winners = dict(SEED)
        winners[OTHER] = record(id="task-c00002", title="The write that won", owner="bo")
        winner = commit_directly(path, winners, "the winning write", when=1_000_150)

        head, stamps = store.last_edited(known=known)
        assert head == winner
        assert stamps[PATH] == 1_000_000, "the doomed edit's stamp must not survive"
        assert stamps[OTHER] == 1_000_150
        assert 1_000_100 not in stamps.values()
    finally:
        store.close()
