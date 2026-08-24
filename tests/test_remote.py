"""Pushing, because the disk is not where the data lives.

On Cloud Run the container filesystem is ephemeral and the service scales to
zero, so a commit that exists only on that disk exists only until the instance
goes away. The durable copy is the git remote, which makes committing without
pushing indistinguishable from not saving.

Four properties carry this suite, and each is a decision rather than a detail:

* **Local `main` is only ever ahead of the remote, never divergent.** The push
  happens inside the same writer lock as the commit, so there is no window in
  which a second commit can be made before the first has been sent. Every other
  property here is a consequence of that one, and it is asserted directly.
* **A failure to push is reported, never dressed up.** The commit is still made
  locally and `WriteResult.pushed` is `False`. A green tick over an unpushed
  commit is how a team discovers on Monday that Friday is gone.
* **A rejected push leaves no half-state.** The store resets to the remote,
  re-applies the same scoped compare-and-swap against it, and either lands or
  refuses — it never leaves a commit stranded on the branch.
* **Genuine divergence raises.** The plan repository has branch protection
  blocking force-push (§13), so the only two moves available are fast-forward and
  stop. Guessing between them with somebody's writing at stake is not a third.

With no remote configured none of this happens at all: local development is the
primary deployment for most of Phase 1 and it must not require a network.

The remote below is a second bare repository in `tmp_path`, reached over
`file://`. A suite that needs a network is a suite that does not run — not in
CI, not on a plane, not on the afternoon GitHub is down — and every property
being asserted is about git's behaviour, not about TLS.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path

import pygit2
import pytest
from test_store import (  # noqa: F401  — `preempted` is a fixture, requested by name below
    OTHER,
    PATH,
    SEED,
    WRITERS,
    commit_directly,
    history,
    preempted,
    record,
)

from openproj.model import parse_text
from openproj.store import Store, StoreDiverged

BRANCH = "refs/heads/main"


# --------------------------------------------------------------------------- #
# Fixtures
#
# The shape mirrors production: the durable repository lives somewhere else and
# the server is handed a bare clone of it plus a URL. The clone's own `origin` is
# deleted on purpose — the Store is told where the remote is, and a Store that
# quietly works off whatever happens to be in `.git/config` would pass these
# tests while ignoring the argument it was given.
# --------------------------------------------------------------------------- #


@pytest.fixture
def remote_path(tmp_path: Path) -> Path:
    """The durable copy. In production this is the repository in C2SM; here it is
    a second bare repository, because `file://` is a real git transport and a
    fake one would only prove that the fake works."""
    path = tmp_path / "origin.git"
    pygit2.init_repository(str(path), bare=True, initial_head="main")
    commit_directly(path, SEED, "seed the corpus")
    return path


@pytest.fixture
def remote_url(remote_path: Path) -> str:
    return f"file://{remote_path}"


@pytest.fixture
def repo_path(tmp_path: Path, remote_url: str) -> Path:
    """What the server actually holds: a bare clone, no working copy, no index.

    Cloned rather than seeded separately, because two repositories that merely
    contain the same files have unrelated histories and every push between them
    is a divergence. The deployment clones for the same reason.
    """
    path = tmp_path / "plan.git"
    clone = pygit2.clone_repository(remote_url, str(path), bare=True)
    clone.remotes.delete("origin")
    return path


@pytest.fixture
def store(repo_path: Path, remote_url: str):
    store = Store(repo_path, remote=remote_url)
    yield store
    store.close()


@pytest.fixture
def local_only(repo_path: Path):
    """A store with no remote — a laptop, which is where this tool lives first."""
    store = Store(repo_path)
    yield store
    store.close()


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def head(repo_path: Path) -> str:
    """The branch tip, read fresh from disk — the whole point is that somebody
    else moved it."""
    return str(pygit2.Repository(str(repo_path)).references[BRANCH].target)


def parent(repo_path: Path, commit: str) -> str:
    return str(pygit2.Repository(str(repo_path))[commit].parents[0].id)


def contains(repo_path: Path, commit: str) -> bool:
    """Is `commit` reachable from this repository's branch tip? A commit this
    repository has never heard of is not reachable, it is absent."""
    repo = pygit2.Repository(str(repo_path))
    try:
        repo[commit]
    except (KeyError, TypeError, ValueError):
        return False
    tip = str(repo.references[BRANCH].target)
    return tip == commit or repo.descendant_of(tip, commit)


def tree_now(repo_path: Path) -> dict[str, str]:
    """Every file at the branch tip, in `commit_directly`'s whole-tree shape.

    An outside commit has to be laid over what is already there; building one
    from `SEED` alone would silently delete everything committed since, and the
    test would then be measuring a deletion it did not mean to make.
    """
    repo = pygit2.Repository(str(repo_path))
    files: dict[str, str] = {}

    def walk(tree, prefix: str) -> None:
        for entry in tree:
            if entry.type_str == "tree":
                walk(repo.get(entry.id), f"{prefix}{entry.name}/")
            else:
                files[f"{prefix}{entry.name}"] = repo[entry.id].data.decode("utf-8")

    walk(repo[repo.references[BRANCH].target].tree, "")
    return files


def pushed_from_a_terminal(remote_path: Path, files: dict[str, str], message: str) -> str:
    """A commit that arrives in the remote by some route that is not this server.

    Somebody with a checkout and a terminal will do this in week one, and the CLI
    does it by design. It is not privileged and it is not ignored: it is simply
    the other side of the compare-and-swap.
    """
    return commit_directly(remote_path, {**tree_now(remote_path), **files}, message)


@contextmanager
def unplugged(remote_path: Path):
    """Take the remote away for the duration, the way a cold start with no
    network does. Renaming the directory breaks a `file://` URL exactly as DNS
    failing breaks an `https://` one, and it does it without a socket."""
    offline = remote_path.with_name(remote_path.name + ".offline")
    remote_path.rename(offline)
    try:
        yield
    finally:
        offline.rename(remote_path)


# --------------------------------------------------------------------------- #
# 1. No remote: unchanged, and offline
# --------------------------------------------------------------------------- #


def test_with_no_remote_a_write_behaves_exactly_as_it_does_today(
    local_only: Store, repo_path: Path, remote_path: Path
):
    """Local-only is the deployment for most of Phase 1, and it must not acquire
    a network dependency because a remote became possible.

    A remote repository exists on disk here and is deliberately not configured,
    so anything reaching for a default `origin` moves it and fails this.
    """
    untouched = head(remote_path)
    base = local_only.head()

    result = local_only.write(
        path=PATH,
        content=record(status="in_progress"),
        base_commit=base,
        author="ann",
        message="task-c00001: status todo -> wip",
    )

    assert result.outcome == "committed"
    assert result.pushed is False
    assert local_only.head() == result.commit
    assert parent(repo_path, result.commit) == base
    assert head(remote_path) == untouched
    assert not pygit2.Repository(str(repo_path)).remotes  # nothing was configured behind us


def test_with_no_remote_the_scoped_compare_and_swap_is_untouched(local_only: Store):
    """The retry and the refusal are what make thirty concurrent editors work;
    adding a push must not cost them. Same two cases as the store's own suite,
    asserted here so a regression shows up as a remote problem, which is what it
    would be."""
    stale = local_only.head()
    local_only.write(
        path=OTHER,
        content=record(id="task-c00002", title="Downgrade numpy", owner="bo", status="in_progress"),
        base_commit=stale,
        author="bo",
        message="task-c00002: status todo -> wip",
    )

    elsewhere = local_only.write(
        path=PATH,
        content=record(priority="high"),
        base_commit=stale,
        author="ann",
        message="task-c00001: priority 2 -> 1",
    )
    assert (elsewhere.outcome, elsewhere.pushed) == ("retried", False)

    collision = local_only.write(
        path=PATH,
        content=record(priority="low"),
        base_commit=stale,
        author="cy",
        message="task-c00001: priority 2 -> 3",
    )
    assert (collision.outcome, collision.commit, collision.pushed) == ("conflict", None, False)


def test_with_no_remote_push_and_fetch_are_answers_not_errors(local_only: Store):
    """`openproj serve --offline` calls these on the same code path the hosted
    one does. Nothing to push is not a failure to push, and a store with no
    remote that raises turns a laptop into a support ticket."""
    assert local_only.push() is False
    assert local_only.fetch() is None


# --------------------------------------------------------------------------- #
# 2. A write reaches the remote
# --------------------------------------------------------------------------- #


def test_a_write_lands_in_the_remote_and_says_that_it_did(
    store: Store, repo_path: Path, remote_path: Path
):
    """The claim `pushed=True` makes is not about the local repository. Read it
    back out of the remote, because that is the copy that survives the instance."""
    result = store.write(
        path=PATH,
        content=record(status="in_progress"),
        base_commit=store.head(),
        author="ann",
        message="task-c00001: status todo -> wip",
    )

    assert result.outcome == "committed"
    assert result.pushed is True
    assert head(remote_path) == result.commit == head(repo_path)

    remote = pygit2.Repository(str(remote_path))
    stored = remote[result.commit].tree["tasks"]["task-c00001.md"]
    assert parse_text(remote[stored.id].data.decode("utf-8"), PATH).status == "in_progress"


def test_the_audit_trail_survives_the_push_unaltered(store: Store, remote_path: Path):
    """The push moves the object, not a copy of it: the person stays the author
    and the bot stays the committer on the durable side too. A push that rewrote
    anything would also be a push that could not fast-forward."""
    result = store.write(
        path=PATH,
        content=record(status="in_progress"),
        base_commit=store.head(),
        author="ann",
        message="task-c00001: status todo -> wip",
    )

    commit = pygit2.Repository(str(remote_path))[result.commit]
    assert (commit.author.name, commit.committer.name) == ("ann", "openproj-bot")
    assert commit.message == "task-c00001: status todo -> wip"


def test_a_refused_write_pushes_nothing(store: Store, remote_path: Path):
    """A conflict writes nothing, so there is nothing to send. `pushed` follows
    the commit: no commit, no push, and no badge claiming otherwise."""
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

    assert (mine.outcome, mine.commit, mine.pushed) == ("conflict", None, False)
    assert head(remote_path) == theirs.commit


def test_pushing_an_already_pushed_commit_reports_nothing_to_do(store: Store, remote_path: Path):
    """`push()` answers "did anything move", so a background retrier can call it
    on a timer without inventing work or writing a log line every ten seconds."""
    result = store.write(
        path=PATH,
        content=record(status="in_progress"),
        base_commit=store.head(),
        author="ann",
        message="task-c00001: status todo -> wip",
    )

    assert store.push() is False
    assert head(remote_path) == result.commit


# --------------------------------------------------------------------------- #
# 3. The invariant: ahead, never divergent
# --------------------------------------------------------------------------- #


def test_local_main_is_only_ever_ahead_of_the_remote_never_divergent(
    store: Store, repo_path: Path, remote_path: Path
):
    """Asserted directly, after every single write, because this is the property
    the whole design is arranged around.

    "Ahead or equal" is the only relationship allowed to hold. Divergence cannot
    accumulate if it is never allowed to appear once, and the way it is never
    allowed to appear is that the push happens inside the lock that made the
    commit.
    """
    for status in ("in_progress", "done", "shelved"):
        result = store.write(
            path=PATH,
            content=record(status=status),
            base_commit=store.head(),
            author="ann",
            message=f"task-c00001: status -> {status}",
        )

        assert result.pushed is True
        assert contains(repo_path, head(remote_path))  # never divergent
        assert head(repo_path) == head(remote_path)  # and, having pushed, not even ahead

    assert len(history(repo_path)) == len(history(remote_path))


@pytest.mark.usefixtures("preempted")
def test_a_write_that_has_returned_is_already_in_the_remote(
    store: Store, repo_path: Path, remote_path: Path
):
    """Eight writers, and every one of them checks the remote the instant its own
    write returns.

    This is what "inside the lock" means from the outside: pushing after the lock
    is released would let a writer be told its work is saved while the bytes are
    still on their way, and under the preemption `preempted` forces that window
    is wide enough to lose a whole batch to one crash.
    """
    base = store.head()
    barrier = threading.Barrier(WRITERS)

    def write(n: int) -> tuple[bool, bool]:
        barrier.wait()
        result = store.write(
            path=f"tasks/task-{n:06d}.md",
            content=record(id=f"task-{n:06d}", title=f"Concurrent {n}"),
            base_commit=base,
            author=f"user{n}",
            message=f"task-{n:06d}: create",
        )
        return result.pushed, contains(remote_path, result.commit)

    with ThreadPoolExecutor(max_workers=WRITERS) as pool:
        results = list(pool.map(write, range(WRITERS)))

    assert results == [(True, True)] * WRITERS
    assert head(repo_path) == head(remote_path)
    assert len(history(remote_path)) == WRITERS + 1  # the seed, plus one per writer


def test_every_commit_the_remote_receives_has_exactly_one_parent(
    store: Store, remote_path: Path
):
    """Fast-forward only. The plan repository is branch-protected against
    force-push and deletion (§13), which is free precisely because this store
    never needs anything else — a merge commit appearing here means it started
    resolving history on its own, and the next thing it needs is `--force`."""
    for status in ("in_progress", "done"):
        store.write(
            path=PATH,
            content=record(status=status),
            base_commit=store.head(),
            author="ann",
            message=f"task-c00001: status -> {status}",
        )

    assert [len(commit.parents) for commit in history(remote_path)] == [1, 1, 0]


# --------------------------------------------------------------------------- #
# 4. A rejected push leaves no half-state
# --------------------------------------------------------------------------- #


def test_a_push_rejected_by_a_moved_remote_retries_on_top_of_it(
    store: Store, repo_path: Path, remote_path: Path
):
    """The remote moves after the store last looked at it, so the push is refused
    rather than pre-empted — the first write below is what makes the store's view
    of the remote current, and the outside commit lands after it.

    From there it is the ordinary compare-and-swap, run again against the remote:
    a different path was touched, so this is the silent retry, and the outsider's
    commit is the parent rather than a casualty.
    """
    first = store.write(
        path=OTHER,
        content=record(id="task-c00002", title="Downgrade numpy", owner="bo", status="in_progress"),
        base_commit=store.head(),
        author="bo",
        message="task-c00002: status todo -> wip",
    )
    assert first.pushed is True

    stale = store.head()
    outside = pushed_from_a_terminal(
        remote_path,
        {"tasks/task-c00003.md": record(id="task-c00003", title="By hand")},
        "task-c00003: added from a terminal",
    )

    mine = store.write(
        path=PATH,
        content=record(priority="high"),
        base_commit=stale,
        author="ann",
        message="task-c00001: priority 2 -> 1",
    )

    assert mine.outcome == "retried"
    assert mine.pushed is True
    assert head(repo_path) == head(remote_path) == mine.commit
    assert parent(repo_path, mine.commit) == outside
    assert parse_text(store.read(mine.commit, PATH), PATH).priority == "high"
    assert store.read(mine.commit, "tasks/task-c00003.md") is not None  # not clobbered
    # The abandoned first attempt is off the branch entirely, not merged in and
    # not sitting under the new tip.
    assert len(history(repo_path)) == len(history(remote_path)) == 4


def test_a_push_rejected_onto_a_real_collision_refuses_and_leaves_nothing_behind(
    store: Store, repo_path: Path, remote_path: Path
):
    """The other half of the rejection, and the one that can corrupt: the commit
    was already made locally before the push was refused, and re-running the
    compare-and-swap against the remote now says no.

    Nothing of that commit may survive. A store that keeps it has a local branch
    holding an edit nobody was told was accepted, and the next push either fails
    forever or quietly overwrites the person who did land.
    """
    first = store.write(
        path=OTHER,
        content=record(id="task-c00002", title="Downgrade numpy", owner="bo", status="in_progress"),
        base_commit=store.head(),
        author="bo",
        message="task-c00002: status todo -> wip",
    )
    assert first.pushed is True

    stale = store.head()
    outside = pushed_from_a_terminal(
        remote_path, {PATH: record(owner="bo")}, "task-c00001: owner ann -> bo"
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
    assert mine.pushed is False
    assert mine.conflict and "bo" in mine.conflict and "cy" in mine.conflict
    assert head(repo_path) == head(remote_path) == outside
    assert parse_text(store.read(outside, PATH), PATH).owner == "bo"
    assert len(history(repo_path)) == len(history(remote_path)) == 3


# --------------------------------------------------------------------------- #
# 5. An unreachable remote
# --------------------------------------------------------------------------- #


def test_an_unreachable_remote_still_commits_and_admits_it_did_not_push(
    store: Store, repo_path: Path, remote_path: Path
):
    """The one failure mode that must never be rounded up to success.

    The work is kept — throwing away somebody's save because a network was down
    is worse than any badge — but the caller is told, so the editor can show
    "saved locally, not yet pushed" instead of a green tick. A green tick here is
    how a team finds out on Monday that Friday is gone.
    """
    before = head(remote_path)

    with unplugged(remote_path):
        mine = store.write(
            path=PATH,
            content=record(status="in_progress"),
            base_commit=store.head(),
            author="ann",
            message="task-c00001: status todo -> wip",
        )

    assert mine.outcome == "committed"
    assert mine.commit is not None
    assert mine.pushed is False
    assert head(repo_path) == mine.commit
    assert parse_text(store.read(mine.commit, PATH), PATH).status == "in_progress"
    assert head(remote_path) == before


def test_the_commit_the_remote_missed_is_still_there_to_push_afterwards(
    store: Store, repo_path: Path, remote_path: Path
):
    """What makes the honest `pushed=False` survivable: the commit is intact and
    a later push sends it. This is the background retrier's whole job, and it can
    only work if the local branch was left ahead rather than rolled back."""
    with unplugged(remote_path):
        mine = store.write(
            path=PATH,
            content=record(status="in_progress"),
            base_commit=store.head(),
            author="ann",
            message="task-c00001: status todo -> wip",
        )
    assert mine.pushed is False

    assert store.push() is True
    assert head(remote_path) == mine.commit == head(repo_path)
    assert len(history(remote_path)) == len(history(repo_path)) == 2


def test_a_write_while_unreachable_still_lands_on_the_one_before_it(
    store: Store, repo_path: Path, remote_path: Path
):
    """Two saves during an outage are two commits, in order, both waiting. The
    store does not stop working because the remote did; it only stops claiming
    to have pushed."""
    with unplugged(remote_path):
        first = store.write(
            path=PATH,
            content=record(status="in_progress"),
            base_commit=store.head(),
            author="ann",
            message="task-c00001: status todo -> wip",
        )
        second = store.write(
            path=OTHER,
            content=record(id="task-c00002", title="Downgrade numpy", owner="bo",
                status="in_progress"),
            base_commit=store.head(),
            author="bo",
            message="task-c00002: status todo -> wip",
        )

    assert (first.pushed, second.pushed) == (False, False)
    assert parent(repo_path, second.commit) == first.commit
    assert store.push() is True
    assert head(remote_path) == second.commit
    assert contains(remote_path, first.commit)


# --------------------------------------------------------------------------- #
# 6. Somebody else's commit
# --------------------------------------------------------------------------- #


def test_fetch_sees_a_commit_pushed_from_a_terminal(store: Store, remote_path: Path):
    """The CLI writes to this repository and so does anyone with a checkout, so
    "the remote moved" is a normal Tuesday and not an exception.

    Seeing it means having it: the commit has to be readable here afterwards, not
    merely named. A fetch that reported an id this repository cannot resolve
    would leave the compare-and-swap below with nothing to compare against.

    Whether local `main` moves is deliberately not asserted — the fast-forward
    belongs inside the writer lock (§8, step 3), and a fetch that moved the
    branch from a poller thread could do it between a commit's parent lookup and
    its ref update.
    """
    before = store.head()
    outside = pushed_from_a_terminal(
        remote_path,
        {"tasks/task-c00003.md": record(id="task-c00003", title="By hand")},
        "task-c00003: added from a terminal",
    )

    assert store.fetch() == outside != before
    assert store.read(outside, "tasks/task-c00003.md") is not None
    assert parse_text(store.read(outside, PATH), PATH).status == "ready"


def test_fetch_reports_a_commit_once_and_then_stops(store: Store, remote_path: Path):
    """`None` means "nothing new", which is what a poller needs to hear to do
    nothing. A fetch that reported the same commit forever would rebuild the
    index and broadcast an SSE event every fifteen seconds."""
    pushed_from_a_terminal(
        remote_path,
        {"tasks/task-c00003.md": record(id="task-c00003", title="By hand")},
        "task-c00003: added from a terminal",
    )

    assert store.fetch() is not None
    assert store.fetch() is None


def test_the_next_write_lands_on_top_of_a_fetched_commit_not_over_it(
    store: Store, repo_path: Path, remote_path: Path
):
    """The base commit the browser is holding is now two moves old, and the file
    it is editing was not the one that moved — so this is the silent retry again,
    with the outsider's work carried forward rather than reverted."""
    stale = store.head()
    outside = pushed_from_a_terminal(
        remote_path,
        {"tasks/task-c00003.md": record(id="task-c00003", title="By hand")},
        "task-c00003: added from a terminal",
    )
    assert store.fetch() == outside

    mine = store.write(
        path=PATH,
        content=record(status="in_progress"),
        base_commit=stale,
        author="ann",
        message="task-c00001: status todo -> wip",
    )

    assert mine.outcome == "retried"
    assert mine.pushed is True
    assert parent(repo_path, mine.commit) == outside
    assert store.read(mine.commit, "tasks/task-c00003.md") is not None
    assert head(remote_path) == mine.commit


# --------------------------------------------------------------------------- #
# 7. Divergence
# --------------------------------------------------------------------------- #


@pytest.fixture
def diverged(store: Store, repo_path: Path, remote_path: Path) -> tuple[str, str]:
    """Both sides moved from the same commit and neither contains the other.

    The only way to build this is the way it will actually happen: a save during
    an outage that could not be pushed, and then somebody committing from a
    terminal before the network came back. Returns (ours, theirs).
    """
    base = store.head()
    with unplugged(remote_path):
        ours = store.write(
            path=OTHER,
            content=record(id="task-c00002", title="Downgrade numpy", owner="bo",
                status="in_progress"),
            base_commit=base,
            author="bo",
            message="task-c00002: status todo -> wip",
        )
    assert ours.pushed is False

    theirs = pushed_from_a_terminal(
        remote_path,
        {"tasks/task-c00003.md": record(id="task-c00003", title="By hand")},
        "task-c00003: added from a terminal",
    )

    assert parent(repo_path, ours.commit) == parent(remote_path, theirs) == base
    assert ours.commit != theirs
    return ours.commit, theirs


def test_a_genuine_divergence_raises_instead_of_guessing(
    store: Store, repo_path: Path, remote_path: Path, diverged: tuple[str, str]
):
    """Two commits, one shared parent, and no answer the store is entitled to
    pick. Reordering somebody's history to make a push succeed is exactly what
    branch protection exists to prevent, and doing it locally first does not make
    it a different act.

    Nothing is written on either side. The recovery is a person with a terminal,
    which is available precisely because the data is plain files in plain git.
    """
    ours, theirs = diverged

    with pytest.raises(StoreDiverged) as caught:
        store.write(
            path=PATH,
            content=record(status="in_progress"),
            base_commit=store.head(),
            author="ann",
            message="task-c00001: status todo -> wip",
        )

    assert str(caught.value)  # a runbook has to be writable from it
    assert head(repo_path) == ours
    assert head(remote_path) == theirs
    assert len(history(repo_path)) == len(history(remote_path)) == 2


def test_push_refuses_to_resolve_a_divergence_by_itself(
    store: Store, repo_path: Path, remote_path: Path, diverged: tuple[str, str]
):
    """The background retrier calls `push()` on a timer with nobody watching, so
    this is the call that would quietly force-push at three in the morning. It
    raises instead, and the remote keeps the commit it was given."""
    ours, theirs = diverged

    with pytest.raises(StoreDiverged):
        store.push()

    assert head(remote_path) == theirs
    assert head(repo_path) == ours


def test_one_save_talks_to_the_remote_once(tmp_path):
    """It was three: fetch, commit, fetch again inside the push, push. A round
    trip to GitHub is about 600 ms measured from a laptop, so that was most of
    what a save cost.

    The duplicate went first — the push was re-asking what `_absorb_remote` had
    asked milliseconds earlier inside the same lock. Then the pre-fetch went too:
    the write commits against local HEAD and pushes, and the PUSH is the question.
    GitHub refuses a non-fast-forward, and the store rewinds, fetches, and runs
    the same compare-and-swap loop again against what actually landed.

    So the fetch happens when somebody else really did write, rather than on
    every save in the hope that they might have.

    Counted rather than timed, because the point is the number of conversations
    and not how slow the network happened to be.
    """
    upstream = tmp_path / "upstream.git"
    pygit2.init_repository(str(upstream), bare=True, initial_head="main")
    commit_directly(upstream, {"tasks/task-a00001.md": "---\nid: task-a00001\n---\n"}, "seed")
    working = tmp_path / "working.git"
    pygit2.clone_repository(str(upstream), str(working), bare=True)

    said = []
    real_fetch, real_send = Store.fetch, Store._send

    def fetch(self):
        said.append("fetch")
        return real_fetch(self)

    def send(self, refetched=False):
        said.append("push")
        return real_send(self, refetched)

    Store.fetch, Store._send = fetch, send
    try:
        store = Store(working, remote=str(upstream))
        said.clear()
        store.write("tasks/task-a00001.md", "---\nid: task-a00001\ntitle: x\n---\n",
                    store.head(), "ann", "one save")
        store.close()
    finally:
        Store.fetch, Store._send = real_fetch, real_send

    assert said == ["push"], f"one save talked to the remote {len(said)} times: {said}"


def test_a_push_rejected_by_a_moved_remote_is_retried_once(tmp_path):
    """The fetch that was removed from the write path was there to notice a remote
    that had moved. It is still noticed — just when the push is actually rejected,
    rather than on every save in the hope that one day it will be.
    """
    upstream = tmp_path / "upstream.git"
    pygit2.init_repository(str(upstream), bare=True, initial_head="main")
    commit_directly(upstream, {"tasks/task-a00001.md": "---\nid: task-a00001\n---\n"}, "seed")

    ours = tmp_path / "ours.git"
    theirs = tmp_path / "theirs.git"
    pygit2.clone_repository(str(upstream), str(ours), bare=True)
    pygit2.clone_repository(str(upstream), str(theirs), bare=True)

    mine = Store(ours, remote=str(upstream))
    yours = Store(theirs, remote=str(upstream))

    # Somebody else lands a commit on a different file first.
    yours.write("tasks/task-b00002.md", "---\nid: task-b00002\n---\n",
                yours.head(), "bo", "theirs")

    # Ours is now behind, and its tracking ref does not know it. The write still
    # lands: `_absorb_remote` fetches, and the push goes on top.
    written = mine.write("tasks/task-a00001.md", "---\nid: task-a00001\ntitle: mine\n---\n",
                         mine.head(), "ann", "ours")
    assert written.commit, "the write did not land"
    assert written.pushed, "the write did not reach the remote"

    # And the remote holds both.
    landed = Store(upstream)
    paths = landed.paths(landed.head())
    assert "tasks/task-a00001.md" in paths and "tasks/task-b00002.md" in paths
    for one in (mine, yours, landed):
        one.close()


def test_an_upload_reaches_the_remote_like_every_other_commit(tmp_path):
    """`put_asset` took no lock and never pushed, and both were wrong the same way.

    The commit existed only on this disk, so ONE image upload followed by anybody
    pushing to the plan by hand left local and remote genuinely forked — and from
    then on every write raised `StoreDiverged` for the life of the container. Not
    the first write: all of them, for ever, because nothing reconciled. And
    because `WRITE_FAILURES` is consulted at exactly one call site, that reached
    the eleven HTTP routes as a plain-text 500.

    It is also the writer that breaks first now that writes run on a threadpool:
    concurrent with a save, libgit2 refuses the commit outright with "current tip
    is not the first parent".
    """
    upstream = tmp_path / "upstream.git"
    pygit2.init_repository(str(upstream), bare=True, initial_head="main")
    commit_directly(upstream, {"tasks/task-a00001.md": "---\nid: task-a00001\n---\n"}, "seed")

    ours = tmp_path / "ours.git"
    pygit2.clone_repository(str(upstream), str(ours), bare=True)
    store = Store(ours, remote=str(upstream))

    name, fresh = store.put_asset(b"\x89PNG\r\n\x1a\n" + b"0" * 32, ".png", "ann")
    assert fresh and name.startswith("assets/")

    # On the remote, not merely on this disk.
    landed = Store(upstream)
    assert name in landed.paths(landed.head()), "the upload never left the container"

    # And the store is not wedged: a save afterwards still lands.
    written = store.write("tasks/task-a00001.md", "---\nid: task-a00001\ntitle: after\n---\n",
                          store.head(), "ann", "a save after an upload")
    assert written.commit and written.pushed
    for one in (store, landed):
        one.close()


def test_a_write_that_loses_the_race_runs_again_and_lands(tmp_path):
    """The bargain stage 2 makes. There is no fetch before a save any more, so a
    save is committed against a base that may already be stale — and the push is
    what asks. When it is refused, the store rewinds, takes what landed, and runs
    the SAME compare-and-swap loop against it.

    Conflict semantics are therefore unchanged: the retry is the identical loop,
    so two people editing two files still merge silently and two people editing
    one file still get the same refusal. What moves is the tail latency of a
    collision — the rare case now pays the round trip that every save used to.

    Verified against real GitHub over HTTPS before this was built, because
    `file://` and GitHub word the refusal differently and only one of them is
    production: a non-fast-forward push raises `cannot push non-fastforwardable
    reference`. The store tells a refusal from an unreachable host by fetching and
    looking, not by reading that message — the first version matched on the text
    and worked in production and never in these tests.
    """
    upstream = tmp_path / "upstream.git"
    pygit2.init_repository(str(upstream), bare=True, initial_head="main")
    commit_directly(upstream, {"tasks/task-a00001.md": "---\nid: task-a00001\n---\n"}, "seed")

    ours = tmp_path / "ours.git"
    theirs = tmp_path / "theirs.git"
    pygit2.clone_repository(str(upstream), str(ours), bare=True)
    pygit2.clone_repository(str(upstream), str(theirs), bare=True)
    mine, yours = Store(ours, remote=str(upstream)), Store(theirs, remote=str(upstream))

    # They land a commit on a different file. We know nothing about it: no fetch.
    yours.write("tasks/task-b00002.md", "---\nid: task-b00002\n---\n",
                yours.head(), "bo", "theirs")

    written = mine.write("tasks/task-a00001.md", "---\nid: task-a00001\ntitle: mine\n---\n",
                         mine.head(), "ann", "ours")

    assert written.commit, "the write did not land"
    assert written.pushed, "answered as saved without reaching the remote"
    assert written.outcome in ("committed", "retried"), written.outcome

    # Both records are on the remote, and ours is on top of theirs rather than
    # instead of it.
    landed = Store(upstream)
    paths = landed.paths(landed.head())
    assert "tasks/task-a00001.md" in paths and "tasks/task-b00002.md" in paths
    assert "title: mine" in landed.read(landed.head(), "tasks/task-a00001.md")
    for one in (mine, yours, landed):
        one.close()


# --------------------------------------------------------------------------- #
# 8. The write path does not wait for the remote (docs/deferred-push.md)
# --------------------------------------------------------------------------- #


def test_a_write_answers_without_waiting_for_the_remote(
    store: Store, repo_path: Path, remote_path: Path, monkeypatch
):
    """A save answers when the commit lands on this disk, not when GitHub takes it.

    Measured on the deployed service, the push was ~1.5s of a ~2s save — GitHub's
    server-side time, none of it ours to make faster — so the remote here is made
    deliberately slow the same way: every conversation with it costs `delay`
    seconds. The remote stays real and the transport stays git; only its speed is
    injected, at the two methods that hold a conversation at all. The write must
    answer in less than one conversation's time, admit the remote does not hold
    the commit yet, leave it counted in the backlog, and set the poke the
    background pusher wakes on.
    """
    delay = 3.0
    real_fetch, real_send = Store.fetch, Store._send

    def slow_fetch(self):
        time.sleep(delay)
        return real_fetch(self)

    def slow_send(self):
        time.sleep(delay)
        return real_send(self)

    monkeypatch.setattr(Store, "fetch", slow_fetch)
    monkeypatch.setattr(Store, "_send", slow_send)

    untouched = head(remote_path)
    started = time.monotonic()
    result = store.write(
        path=PATH,
        content=record(status="in_progress"),
        base_commit=store.head(),
        author="ann",
        message="task-c00001: status todo -> wip",
    )
    elapsed = time.monotonic() - started

    # Strictly under one delay: a write that held even a single conversation
    # with the remote cannot get here in time, and a local commit is milliseconds.
    assert elapsed < delay, f"the write held a conversation with the remote ({elapsed:.1f}s)"
    assert result.outcome == "committed"
    assert result.commit is not None
    # Honest, not pessimistic: the remote genuinely does not hold it yet.
    assert result.pushed is False
    assert head(repo_path) == result.commit
    assert head(remote_path) == untouched  # the remote's turn is the pusher's, not the save's
    assert store.condition().unpushed == 1
    assert store.dirty.is_set(), "nothing poked the pusher, so the commit would sit for ever"


def test_a_write_answered_200_is_a_write_that_reached_the_remote(tmp_path):
    """The invariant the optimistic push must not spend. `pushed` is what the page
    reports as saved, and a commit that only exists on an ephemeral container is
    not saved — `deploy/boot.py` re-clones the plan on every cold start, so an
    unpushed commit is not a cache entry awaiting sync, it is work that does not
    exist yet."""
    upstream = tmp_path / "upstream.git"
    pygit2.init_repository(str(upstream), bare=True, initial_head="main")
    commit_directly(upstream, {"tasks/task-a00001.md": "---\nid: task-a00001\n---\n"}, "seed")
    ours = tmp_path / "ours.git"
    pygit2.clone_repository(str(upstream), str(ours), bare=True)
    store = Store(ours, remote=str(upstream))

    for n in range(3):
        written = store.write("tasks/task-a00001.md", f"---\nid: task-a00001\ntitle: {n}\n---\n",
                              store.head(), "ann", f"edit {n}")
        assert written.pushed, f"edit {n} answered as saved without reaching the remote"
        landed = Store(upstream)
        assert landed.head() == written.commit, f"edit {n} is not what the remote holds"
        landed.close()
    store.close()


# --------------------------------------------------------------------------- #
# 9. sync(): the pusher lands the backlog (docs/deferred-push.md)
# --------------------------------------------------------------------------- #


def test_the_pusher_lands_the_commits_a_save_did_not_wait_for(
    store: Store, repo_path: Path, remote_path: Path
):
    """The other half of the deferred push's bargain. A save answers with a sha
    the remote does not hold yet, and `sync()` is what makes that answer honest.
    On the quiet day — nobody pushed by hand in between — the commits land with
    their ORIGINAL shas: a client holding an answered sha must find that exact
    sha on the remote, because sha instability is allowed only on the recovery
    path (docs/deferred-push.md).
    """
    first = store.write(
        path=PATH,
        content=record(status="in_progress"),
        base_commit=store.head(),
        author="ann",
        message="task-c00001: status todo -> wip",
    )
    second = store.write(
        path=OTHER,
        content=record(id="task-c00002", title="Downgrade numpy", owner="bo",
            status="in_progress"),
        base_commit=store.head(),
        author="bo",
        message="task-c00002: status todo -> wip",
    )
    assert (first.pushed, second.pushed) == (False, False)
    assert store.condition().unpushed == 2

    outcome = store.sync()

    assert outcome.state == "landed"
    assert outcome.landed == second.commit
    # The original shas, read back out of the remote — the copy that survives
    # the instance. Nothing was in the way, so nothing was re-minted or parked.
    assert head(remote_path) == second.commit
    assert contains(remote_path, first.commit)
    assert outcome.remapped == {}
    assert outcome.parked == []
    assert store.condition().unpushed == 0
    # And the backlog is empty now, which the pusher must be able to hear
    # without holding a conversation with the remote to find out.
    assert store.sync().state == "idle"


def test_an_unreachable_remote_leaves_the_backlog_for_the_next_pass(
    store: Store, repo_path: Path, remote_path: Path
):
    """Unreachable is not a rejection. The backlog is real, local, and worth
    sending unchanged when the network comes back — so `sync()` says which
    failure it was and touches nothing: nothing rewound, nothing re-minted, and
    the same pass run after the outage lands the same commit under the same sha.
    """
    written = store.write(
        path=PATH,
        content=record(status="in_progress"),
        base_commit=store.head(),
        author="ann",
        message="task-c00001: status todo -> wip",
    )

    with unplugged(remote_path):
        outcome = store.sync()

    assert outcome.state == "unreachable"
    assert outcome.landed is None
    assert head(repo_path) == written.commit  # nothing rewound
    assert store.condition().unpushed == 1  # the backlog is intact
    # What makes the honest "unreachable" survivable: the commit kept its sha,
    # so the next pass is the quiet day again.
    assert store.sync().state == "landed"
    assert head(remote_path) == written.commit
