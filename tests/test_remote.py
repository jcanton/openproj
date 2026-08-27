"""Pushing, because the disk is not where the data lives.

On Cloud Run the container filesystem is ephemeral and the service scales to
zero, so a commit that exists only on that disk exists only until the instance
goes away. The durable copy is the git remote, which makes committing without
pushing indistinguishable from not saving.

Four properties carry this suite, and each is a decision rather than a detail
(design/deferred-push.md is the reasoning):

* **A save answers when the commit lands on this disk.** The push left the
  request path — it was ~1.5s of a ~2s save, all of it GitHub's — and is the
  background pusher's alone. Nothing inside the writer lock touches the
  network at all.
* **Nothing is reported pushed before the remote holds it.** `pushed` keeps
  meaning exactly what it always meant, which is why it is now `False` on
  every fresh write. A green tick over an unpushed commit is how a team
  discovers on Monday that Friday is gone.
* **An answered sha is never merely gone.** The pusher lands it under its own
  name on the quiet day, re-mints it on top of what the remote actually holds
  when a push is rejected, or parks it on a branch on the remote when it
  cannot be replayed — announced, in every case, in the sync outcome.
* **Only a genuine fork stops the pusher.** Both-sides-moved is the ordinary
  recoverable race now that hand-pushes land beside a backlog; the wedge that
  remains is the remote no longer containing a commit this process confirmed
  it held — a force-push — and that is a person's to resolve, never guessed.

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
from openproj.pusher import Pusher
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
    """The saying is split in two now, and each half must stay honest: the write
    admits the remote does not hold the commit yet, and the pusher's outcome is
    what names it landed. Read back out of the remote, because that is the copy
    that survives the instance."""
    result = store.write(
        path=PATH,
        content=record(status="in_progress"),
        base_commit=store.head(),
        author="ann",
        message="task-c00001: status todo -> wip",
    )

    assert result.outcome == "committed"
    assert result.pushed is False  # true at this moment: the remote has nothing yet

    outcome = store.sync()

    assert outcome.state == "landed"
    assert outcome.landed == result.commit
    assert head(remote_path) == result.commit == head(repo_path)

    remote = pygit2.Repository(str(remote_path))
    stored = remote[result.commit].tree["tasks"]["task-c00001.md"]
    assert parse_text(remote[stored.id].data.decode("utf-8"), PATH).status == "in_progress"


def test_the_audit_trail_survives_the_push_unaltered(store: Store, remote_path: Path):
    """The push moves the object, not a copy of it: the person stays the author
    and the bot stays the committer on the durable side too. On the quiet day
    nothing is re-minted, so the sha the save answered is the object the remote
    ends up holding, signature and all."""
    result = store.write(
        path=PATH,
        content=record(status="in_progress"),
        base_commit=store.head(),
        author="ann",
        message="task-c00001: status todo -> wip",
    )
    assert store.sync().state == "landed"

    commit = pygit2.Repository(str(remote_path))[result.commit]
    assert (commit.author.name, commit.committer.name) == ("ann", "openproj-bot")
    assert commit.message == "task-c00001: status todo -> wip"


def test_a_refused_write_pushes_nothing(store: Store, remote_path: Path):
    """A conflict writes nothing, so there is nothing for the pusher to send.
    `pushed` follows the commit: no commit, no push, and no badge claiming
    otherwise — and the pass that lands the backlog carries only the write
    that was accepted."""
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
    assert store.sync().state == "landed"
    assert head(remote_path) == theirs.commit


def test_pushing_an_already_pushed_commit_reports_nothing_to_do(store: Store, remote_path: Path):
    """The pusher wakes on every poke, so a pass with nothing to send must say
    "idle" from two local refs alone — without inventing work, re-sending a
    commit the remote holds, or holding a conversation to find out. `push()`
    keeps answering "did anything move" for the same reason."""
    result = store.write(
        path=PATH,
        content=record(status="in_progress"),
        base_commit=store.head(),
        author="ann",
        message="task-c00001: status todo -> wip",
    )

    assert store.sync().state == "landed"
    assert store.sync().state == "idle"
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

    "Ahead or equal" is still the only relationship allowed to hold; what moved
    is where it is enforced. The window in which local is ahead now lasts until
    the pusher's next pass instead of closing inside the write lock — and when
    a hand-push does land in that window, the recovery replays the backlog ON
    TOP of the remote rather than ever leaving the two beside each other. Here
    nobody else writes, so every pass levels the two under the original shas.
    """
    for status in ("in_progress", "done", "shelved"):
        result = store.write(
            path=PATH,
            content=record(status=status),
            base_commit=store.head(),
            author="ann",
            message=f"task-c00001: status -> {status}",
        )

        assert result.pushed is False
        assert contains(repo_path, head(remote_path))  # ahead of the remote, never beside it
        assert store.sync().state == "landed"
        assert head(repo_path) == head(remote_path) == result.commit  # level again, same sha

    assert len(history(repo_path)) == len(history(remote_path))


@pytest.mark.usefixtures("preempted")
def test_a_write_that_has_returned_is_in_the_backlog_the_pusher_lands(
    store: Store, repo_path: Path, remote_path: Path
):
    """Eight writers, and every one of them is answered with a commit the remote
    does not hold yet — honestly said, and landed whole by one pass.

    The meaning of this test inverted with the deferred push, on purpose. It
    used to pin "a write that has returned is already in the remote", which was
    the request paying GitHub's ~1.5 seconds inside the writer lock — exactly
    the cost design/deferred-push.md removes. What survives is the half a team
    can lose sleep over: no writer is TOLD the remote holds its commit before
    it does, and every answered commit is in the backlog the pusher lands,
    under the preemption `preempted` forces so the interleaving is real.
    """
    base = store.head()
    barrier = threading.Barrier(WRITERS)

    def write(n: int) -> tuple[bool, str]:
        barrier.wait()
        result = store.write(
            path=f"tasks/task-{n:06d}.md",
            content=record(id=f"task-{n:06d}", title=f"Concurrent {n}"),
            base_commit=base,
            author=f"user{n}",
            message=f"task-{n:06d}: create",
        )
        assert result.commit is not None
        return result.pushed, result.commit

    with ThreadPoolExecutor(max_workers=WRITERS) as pool:
        results = list(pool.map(write, range(WRITERS)))

    assert [pushed for pushed, _ in results] == [False] * WRITERS
    assert store.sync().state == "landed"
    for _, commit in results:
        assert contains(remote_path, commit), "an answered commit never landed"
    assert head(repo_path) == head(remote_path)
    assert len(history(remote_path)) == WRITERS + 1  # the seed, plus one per writer


def test_every_commit_the_remote_receives_has_exactly_one_parent(
    store: Store, remote_path: Path
):
    """Fast-forward only. The plan repository is branch-protected against
    force-push and deletion (§13), which is free precisely because this store
    never needs anything else — a merge commit appearing here means it started
    resolving history on its own, and the next thing it needs is `--force`.
    The recovery keeps this true the hard way, by re-committing rather than
    merging; here the quiet day keeps it true by sending the originals."""
    for status in ("in_progress", "done"):
        store.write(
            path=PATH,
            content=record(status=status),
            base_commit=store.head(),
            author="ann",
            message=f"task-c00001: status -> {status}",
        )
    assert store.sync().state == "landed"

    assert [len(commit.parents) for commit in history(remote_path)] == [1, 1, 0]


# --------------------------------------------------------------------------- #
# 4. A rejected push leaves no half-state
# --------------------------------------------------------------------------- #


def test_a_push_rejected_by_a_moved_remote_is_replayed_on_top_of_it(
    store: Store, repo_path: Path, remote_path: Path
):
    """The remote moves after the store last looked at it, so the pusher's push
    is refused — the first sync below is what makes its view of the remote
    current AND arms the force-push guard with a commit the remote provably
    held, so this is also the pass that proves the guard lets an ordinary
    hand-push through.

    From there it is the same per-path ladder, run at replay time: a different
    path was touched, so the commit re-mints cleanly and the outsider's commit
    is the parent rather than a casualty.
    """
    first = store.write(
        path=OTHER,
        content=record(id="task-c00002", title="Downgrade numpy", owner="bo", status="in_progress"),
        base_commit=store.head(),
        author="bo",
        message="task-c00002: status todo -> wip",
    )
    assert store.sync().state == "landed"  # the remote provably holds `first`

    outside = pushed_from_a_terminal(
        remote_path,
        {"tasks/task-c00003.md": record(id="task-c00003", title="By hand")},
        "task-c00003: added from a terminal",
    )

    mine = store.write(
        path=PATH,
        content=record(priority="high"),
        base_commit=store.head(),
        author="ann",
        message="task-c00001: priority 2 -> 1",
    )
    assert mine.pushed is False

    outcome = store.sync()

    assert outcome.state == "landed"
    minted = outcome.remapped.get(mine.commit)
    assert minted is not None and minted != mine.commit
    assert head(repo_path) == head(remote_path) == minted == outcome.landed
    assert parent(repo_path, minted) == outside
    assert parse_text(store.read(minted, PATH), PATH).priority == "high"
    assert store.read(minted, "tasks/task-c00003.md") is not None  # not clobbered
    # The doomed original is off the branch entirely, not merged in and not
    # sitting under the new tip.
    assert not contains(remote_path, mine.commit)
    assert len(history(repo_path)) == len(history(remote_path)) == 4
    assert contains(remote_path, first.commit)  # still under its own sha


def test_a_push_rejected_onto_a_real_collision_parks_the_commit_on_a_branch(
    store: Store, repo_path: Path, remote_path: Path
):
    """The other half of the rejection, and the one whose answer had to change:
    the commit was already made AND answered — the 200 went out — before the
    push was refused, and the replay's ladder now says no.

    The old store could refuse the write while somebody was still there to read
    the refusal; the pusher cannot, so "leaves nothing behind" splits in two.
    Main, on both sides, carries no trace of the doomed commit — nothing half
    applied, nothing quietly overwriting the person who landed. And the commit
    itself goes to a branch on the remote rather than away, because dropping an
    acknowledged save is the one thing worse than refusing it.
    """
    first = store.write(
        path=OTHER,
        content=record(id="task-c00002", title="Downgrade numpy", owner="bo", status="in_progress"),
        base_commit=store.head(),
        author="bo",
        message="task-c00002: status todo -> wip",
    )
    assert store.sync().state == "landed"  # the guard has a confirmed commit to check

    outside = pushed_from_a_terminal(
        remote_path, {PATH: record(owner="bo")}, "task-c00001: owner ann -> bo"
    )

    mine = store.write(
        path=PATH,
        content=record(owner="cy"),
        base_commit=store.head(),
        author="ann",
        message="task-c00001: owner ann -> cy",
    )
    assert mine.commit is not None and mine.pushed is False  # answered, not yet durable

    outcome = store.sync()

    assert outcome.state == "landed"
    branch = f"openproj/stranded-{mine.commit}"
    assert outcome.parked == [(mine.commit, branch)]
    assert stranded_branch(remote_path, mine.commit) == mine.commit  # durable, on the remote
    assert head(repo_path) == head(remote_path) == outside
    assert not contains(remote_path, mine.commit)
    assert parse_text(store.read(outside, PATH), PATH).owner == "bo"
    assert len(history(repo_path)) == len(history(remote_path)) == 3
    assert contains(remote_path, first.commit)


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
    with the outsider's work carried forward rather than reverted.

    The meaning here changed with the deferred push, and not just the wording:
    the fast-forward that used to absorb a fetched commit on the write path —
    `_absorb_remote`, inside the writer lock — is gone, so a fetch alone moves
    only the tracking ref and the branch holds still under every reader's
    feet. It is `sync()` that folds the fetched commit in, with the lock held
    for exactly the swap; the write then lands on top of it in the ordinary
    way, and the whole exchange is asserted in that order below.
    """
    stale = store.head()
    outside = pushed_from_a_terminal(
        remote_path,
        {"tasks/task-c00003.md": record(id="task-c00003", title="By hand")},
        "task-c00003: added from a terminal",
    )
    assert store.fetch() == outside
    assert store.head() == stale  # a fetch is news, never a branch move

    absorbed = store.sync()
    assert absorbed.state == "landed"
    assert (absorbed.remapped, absorbed.parked) == ({}, [])  # nothing of ours in play
    assert store.head() == outside  # the fast-forward, where the lock is

    mine = store.write(
        path=PATH,
        content=record(status="in_progress"),
        base_commit=stale,
        author="ann",
        message="task-c00001: status todo -> wip",
    )

    assert mine.outcome == "retried"
    assert mine.pushed is False
    assert parent(repo_path, mine.commit) == outside
    assert store.read(mine.commit, "tasks/task-c00003.md") is not None
    assert store.sync().state == "landed"
    assert head(remote_path) == mine.commit  # the original sha: nothing was in the way


# --------------------------------------------------------------------------- #
# 7. Divergence
# --------------------------------------------------------------------------- #


@pytest.fixture
def diverged(store: Store, repo_path: Path, remote_path: Path) -> tuple[str, str]:
    """Both sides moved from the same commit and neither contains the other.

    The only way to build this is the way it will actually happen: a save during
    an outage that could not be pushed, and then somebody committing from a
    terminal before the network came back. Returns (ours, theirs).

    Since the deferred push this shape is the ORDINARY recoverable race rather
    than a wedge — every save now widens exactly this window — which is what
    the first test below pins. `push()`, the manual door, still refuses it.
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


def test_a_divergence_nobody_forced_is_replayed_not_raised(
    store: Store, repo_path: Path, remote_path: Path, diverged: tuple[str, str]
):
    """The meaning of this test inverted with the deferred push, and saying so
    is the point: it used to be `test_a_genuine_divergence_raises_instead_of_
    guessing`, and this exact shape — a stranded save, then a hand-push — made
    every later write raise `StoreDiverged` for the life of the container.

    That refusal was right when the alternative was guessing which history to
    discard. The recovery discards neither: it re-commits ours on top of
    theirs, authors and messages verbatim, so both people's commits survive on
    one linear branch. "Genuine" divergence — history REWRITTEN under the
    store, not merely grown — still stops everything, and is pinned by
    `test_a_force_pushed_remote_is_a_fork_and_nothing_is_replayed_onto_it`.
    """
    ours, theirs = diverged

    written = store.write(
        path=PATH,
        content=record(status="in_progress"),
        base_commit=store.head(),
        author="ann",
        message="task-c00001: status todo -> wip",
    )
    assert written.commit is not None and written.pushed is False  # answered, not refused

    outcome = store.sync()

    assert outcome.state == "landed"
    assert contains(remote_path, theirs)  # the hand-push is the new ground, not a casualty
    assert set(outcome.remapped) == {ours, written.commit}  # both of ours re-minted on top
    assert head(repo_path) == head(remote_path) == outcome.landed
    assert store.condition().unpushed == 0
    # Linear, single-parent, both people's work under their own names.
    assert [len(commit.parents) for commit in history(remote_path)] == [1, 1, 1, 0]


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


def test_a_save_talks_to_the_remote_never_and_the_pusher_once(tmp_path):
    """It was three conversations, then one, and the deferred push makes it
    none: a round trip to GitHub is about 600 ms measured from a laptop, the
    push itself ~1.5s of server-side time, and the request now pays for
    neither. The pusher's quiet day is exactly one push — no fetch, because
    the rejection IS the freshness question and a round trip to predict it
    would be the old pre-fetch moved one thread over.

    Counted rather than timed, because the point is the number of conversations
    and not how slow the network happened to be. Counted at `pygit2.Remote` —
    the seam every conversation crosses — because the previous counter wrapped
    `Store._send` with a signature it no longer had (`send(self, refetched)`
    over `_send(self)`), and the TypeError that raised was swallowed by the old
    `_finish` into `pushed=False`: a green test that counted nothing. The
    transport's own methods cannot drift away from the store that calls them.
    """
    upstream = tmp_path / "upstream.git"
    pygit2.init_repository(str(upstream), bare=True, initial_head="main")
    commit_directly(upstream, {"tasks/task-a00001.md": "---\nid: task-a00001\n---\n"}, "seed")
    working = tmp_path / "working.git"
    pygit2.clone_repository(str(upstream), str(working), bare=True)

    said = []
    real_fetch, real_push = pygit2.Remote.fetch, pygit2.Remote.push

    def fetch(remote, *args, **kwargs):
        said.append("fetch")
        return real_fetch(remote, *args, **kwargs)

    def push(remote, *args, **kwargs):
        said.append("push")
        return real_push(remote, *args, **kwargs)

    pygit2.Remote.fetch, pygit2.Remote.push = fetch, push
    try:
        store = Store(working, remote=str(upstream))
        said.clear()
        store.write("tasks/task-a00001.md", "---\nid: task-a00001\ntitle: x\n---\n",
                    store.head(), "ann", "one save")
        assert said == [], f"the save itself held a conversation: {said}"
        assert store.sync().state == "landed"
        assert said == ["push"], f"the pusher's quiet day held: {said}"
        store.close()
    finally:
        pygit2.Remote.fetch, pygit2.Remote.push = real_fetch, real_push


def test_a_push_rejected_by_a_moved_remote_is_recovered_in_one_pass(tmp_path):
    """The fetch that was removed from the write path was there to notice a remote
    that had moved. It is still noticed — inside the pusher's pass, when a push
    is actually rejected, rather than on every save in the hope that one day it
    will be — and one pass is enough to land on top of what it finds.
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
    assert yours.sync().state == "landed"

    # Ours is now behind, and its tracking ref does not know it. The write
    # lands locally all the same; the pusher's push is refused, and ONE
    # recovery replays it on top of theirs.
    written = mine.write("tasks/task-a00001.md", "---\nid: task-a00001\ntitle: mine\n---\n",
                         mine.head(), "ann", "ours")
    assert written.commit, "the write did not land"
    assert written.pushed is False
    assert mine.sync().state == "landed"

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
    the first write: all of them, for ever, because nothing reconciled.

    Reconciliation is the pusher's now, so the claim to hold is that an upload
    joins the same backlog as every other commit: it pokes, it counts as
    unpushed, and the next pass lands it. An upload that bypassed `_finish`
    would sit on this disk until an unrelated save happened to poke — or for
    ever, on the afternoon nobody saves.
    """
    upstream = tmp_path / "upstream.git"
    pygit2.init_repository(str(upstream), bare=True, initial_head="main")
    commit_directly(upstream, {"tasks/task-a00001.md": "---\nid: task-a00001\n---\n"}, "seed")

    ours = tmp_path / "ours.git"
    pygit2.clone_repository(str(upstream), str(ours), bare=True)
    store = Store(ours, remote=str(upstream))

    name, fresh = store.put_asset(b"\x89PNG\r\n\x1a\n" + b"0" * 32, ".png", "ann")
    assert fresh and name.startswith("assets/")
    assert store.dirty.is_set(), "the upload never poked the pusher"
    assert store.condition().unpushed == 1
    assert store.sync().state == "landed"

    # On the remote, not merely on this disk.
    landed = Store(upstream)
    assert name in landed.paths(landed.head()), "the upload never left the container"

    # And the store is not wedged: a save afterwards still lands.
    written = store.write("tasks/task-a00001.md", "---\nid: task-a00001\ntitle: after\n---\n",
                          store.head(), "ann", "a save after an upload")
    assert written.commit is not None
    assert store.sync().state == "landed"
    for one in (store, landed):
        one.close()


def test_a_write_that_loses_the_race_runs_again_and_lands(tmp_path):
    """The bargain the deferred push makes. There is no fetch before a save and
    no push after it, so a save is committed against a base that may already be
    stale — and the pusher's push is what asks. When it is refused, the
    recovery takes what landed and re-drives our commit's delta through the
    SAME per-path ladder against it.

    Conflict semantics are therefore unchanged: the replay is the identical
    ladder, so two people editing two files still merge silently and two people
    editing one file still get the same refusal — parked now, since there is
    nobody left to answer. What moves is who pays the round trip: the pusher's
    thread, never the person.

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
    assert yours.sync().state == "landed"

    written = mine.write("tasks/task-a00001.md", "---\nid: task-a00001\ntitle: mine\n---\n",
                         mine.head(), "ann", "ours")

    assert written.commit, "the write did not land"
    assert written.outcome == "committed", written.outcome  # the base was locally current
    outcome = mine.sync()
    assert outcome.state == "landed"
    assert set(outcome.remapped) == {written.commit}  # re-minted on top, not discarded

    # Both records are on the remote, and ours is on top of theirs rather than
    # instead of it.
    landed = Store(upstream)
    paths = landed.paths(landed.head())
    assert "tasks/task-a00001.md" in paths and "tasks/task-b00002.md" in paths
    assert "title: mine" in landed.read(landed.head(), "tasks/task-a00001.md")
    for one in (mine, yours, landed):
        one.close()


# --------------------------------------------------------------------------- #
# 8. The write path does not wait for the remote (design/deferred-push.md)
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


def test_nothing_says_pushed_before_the_remote_actually_holds_the_commit(tmp_path):
    """The invariant the deferred push must not spend, and the test whose old
    name — `test_a_write_answered_200_is_a_write_that_reached_the_remote` —
    now names the exact behaviour the design removed. `pushed` keeps meaning
    what it always meant, which is WHY it is `False` at answer time: the
    remote genuinely does not hold the commit yet. What the design owes in
    exchange, pinned here per edit: the store admits the gap while it exists
    (`unpushed` counts it), the pass that closes it lands the very sha the
    save answered with, and only then does anything read as pushed —
    `deploy/boot.py` re-clones the plan on every cold start, so an unpushed
    commit is not a cache entry awaiting sync, it is work that does not exist
    yet."""
    upstream = tmp_path / "upstream.git"
    pygit2.init_repository(str(upstream), bare=True, initial_head="main")
    commit_directly(upstream, {"tasks/task-a00001.md": "---\nid: task-a00001\n---\n"}, "seed")
    ours = tmp_path / "ours.git"
    pygit2.clone_repository(str(upstream), str(ours), bare=True)
    store = Store(ours, remote=str(upstream))

    for n in range(3):
        written = store.write("tasks/task-a00001.md", f"---\nid: task-a00001\ntitle: {n}\n---\n",
                              store.head(), "ann", f"edit {n}")
        assert written.pushed is False, f"edit {n} claimed a remote that holds nothing"
        assert store.condition().unpushed == 1, f"edit {n} is at risk and uncounted"
        landed = Store(upstream)
        assert landed.head() != written.commit, f"edit {n}: the claim would have been true"
        landed.close()
        assert store.sync().state == "landed"
        assert store.condition().unpushed == 0
        landed = Store(upstream)
        assert landed.head() == written.commit, f"edit {n} is not what the remote holds"
        landed.close()
    store.close()


# --------------------------------------------------------------------------- #
# 9. sync(): the pusher lands the backlog (design/deferred-push.md)
# --------------------------------------------------------------------------- #


def test_the_pusher_lands_the_commits_a_save_did_not_wait_for(
    store: Store, repo_path: Path, remote_path: Path
):
    """The other half of the deferred push's bargain. A save answers with a sha
    the remote does not hold yet, and `sync()` is what makes that answer honest.
    On the quiet day — nobody pushed by hand in between — the commits land with
    their ORIGINAL shas: a client holding an answered sha must find that exact
    sha on the remote, because sha instability is allowed only on the recovery
    path (design/deferred-push.md).
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


# --------------------------------------------------------------------------- #
# 10. Recovery: a rejected push replays onto what the remote actually holds
# (design/deferred-push.md, "Recovery, when the push is rejected")
# --------------------------------------------------------------------------- #


def stranded_branch(remote_path: Path, sha: str) -> str | None:
    """What the remote's parked branch for this commit points at, or None when
    the branch never arrived. Asked of the remote, because the branch IS the
    durability claim — a local ref proves nothing about what survives the
    instance."""
    repo = pygit2.Repository(str(remote_path))
    reference = repo.references.get(f"refs/heads/openproj/stranded-{sha}")
    return str(reference.target) if reference else None


def test_a_hand_push_between_the_commit_and_the_push_is_replayed_onto(
    store: Store, repo_path: Path, remote_path: Path
):
    """The ordinary race, now that saves answer before pushing: somebody lands a
    commit from a terminal in the window between our commit and the pusher's
    push. The old answer rewound `refs/heads/main` and would have discarded the
    hand-push; the recovery must instead re-commit our work ON TOP of it — the
    original author and message, a new sha, and the old-to-new pair announced in
    `remapped` so a page waiting on the answered sha can stop waiting.
    """
    ours = store.write(
        path=PATH,
        content=record(status="in_progress"),
        base_commit=store.head(),
        author="ann",
        message="task-c00001: status todo -> wip",
    )
    assert ours.pushed is False
    outside = pushed_from_a_terminal(
        remote_path,
        {"tasks/task-c00003.md": record(id="task-c00003", title="By hand")},
        "task-c00003: added from a terminal",
    )
    before = store.condition()
    assert before.unpushed == 1
    assert before.oldest_unpushed_age is not None and before.oldest_unpushed_age >= 0

    outcome = store.sync()

    assert outcome.state == "landed"
    assert contains(remote_path, outside), "the hand-push was discarded"
    minted = outcome.remapped.get(ours.commit)
    assert minted is not None and minted != ours.commit
    assert outcome.landed == minted == head(remote_path) == head(repo_path)
    assert parent(remote_path, minted) == outside  # on top of it, not instead of it
    replayed = pygit2.Repository(str(remote_path))[minted]
    assert (replayed.author.name, replayed.committer.name) == ("ann", "openproj-bot")
    assert replayed.message == "task-c00001: status todo -> wip"
    assert not contains(remote_path, ours.commit)  # the doomed sha was never sent
    assert parse_text(store.read(minted, PATH), PATH).status == "in_progress"
    assert store.read(minted, "tasks/task-c00003.md") is not None
    assert outcome.parked == []
    after = store.condition()
    assert (after.unpushed, after.parked, after.oldest_unpushed_age) == (0, 0, None)


def test_a_commit_that_cannot_be_replayed_is_parked_on_a_branch_before_main_moves(
    store: Store, repo_path: Path, remote_path: Path
):
    """A conflict discovered at replay time has no user attached — the 200 went
    out long ago — so the commit is neither dropped nor retried forever: it goes
    to `openproj/stranded-<sha>` ON THE REMOTE, and only then does local main
    move onto what the remote holds. Branch first, swap second, because the
    moment main stops containing the commit, the branch is the only copy that
    survives the instance.
    """
    ours = store.write(
        path=PATH,
        content=record(owner="cy"),
        base_commit=store.head(),
        author="ann",
        message="task-c00001: owner ann -> cy",
    )
    outside = pushed_from_a_terminal(
        remote_path, {PATH: record(owner="bo")}, "task-c00001: owner ann -> bo"
    )

    outcome = store.sync()

    assert outcome.state == "landed"
    assert outcome.remapped == {}
    branch = f"openproj/stranded-{ours.commit}"
    assert outcome.parked == [(ours.commit, branch)]
    # Durable: the branch on the REMOTE holds the original commit, untouched.
    assert stranded_branch(remote_path, ours.commit) == ours.commit
    parked = pygit2.Repository(str(remote_path))[ours.commit]
    assert (parked.author.name, parked.message) == ("ann", "task-c00001: owner ann -> cy")
    # Main does not contain it, on either side — parked, not merged and not lost.
    assert head(remote_path) == outside
    assert not contains(remote_path, ours.commit)
    assert head(repo_path) == outside  # swapped onto what the remote actually holds
    assert parse_text(store.read(outside, PATH), PATH).owner == "bo"
    assert outcome.landed == outside
    after = store.condition()
    # `parked` counts the stranded commits THIS container would still lose — the
    # branch is on the remote now, so the honest count is zero, same philosophy
    # as `unpushed`.
    assert (after.unpushed, after.parked, after.diverged) == (0, 0, False)


def test_a_commit_that_cannot_replay_one_of_its_paths_parks_whole(
    store: Store, repo_path: Path, remote_path: Path
):
    """Invariant 8 has two doors. `write_all`'s comment promises that a conflict
    on ANY path writes nothing — and the replay must keep the same promise,
    because a promotion is one decision in one commit: a brand-new pitch plus
    the note saying what it became. A replay that landed the resolvable pitch
    and dropped the refused note would be exactly the half-done state that
    comment exists to prevent, arriving through the recovery door — the pitch
    on main under a fresh sha, the note's edit nowhere, no branch, no report.
    Every other recovery test drives single-path commits, where a refusal
    always leaves nothing resolvable and the partial-replay hole cannot open;
    this one holds it shut.
    """
    pitch_path = "tasks/task-c00005.md"
    pitch = record(id="task-c00005", title="Promoted pitch", owner="ann")
    note = record(owner="cy")
    ours = store.write_all(
        files={pitch_path: pitch, PATH: note},
        base_commit=store.head(),
        author="ann",
        message="task-c00005: promoted from task-c00001",
    )
    # The hand-push conflicts ONE of the two paths: the note. The pitch is
    # brand-new and nobody else can have touched it — the easiest half to
    # replay, which is what makes it the half a partial replay would land.
    outside = pushed_from_a_terminal(
        remote_path, {PATH: record(owner="bo")}, "task-c00001: owner ann -> bo"
    )

    outcome = store.sync()

    assert outcome.state == "landed"
    branch = f"openproj/stranded-{ours.commit}"
    assert outcome.parked == [(ours.commit, branch)], "the WHOLE commit parks"
    assert outcome.remapped == {}, "no half of it was re-minted onto main"
    # The branch on the remote holds the original commit, and that commit
    # carries BOTH paths, byte for byte — the decision travels whole.
    assert stranded_branch(remote_path, ours.commit) == ours.commit
    remote_repo = pygit2.Repository(str(remote_path))
    stranded = remote_repo[ours.commit].tree
    assert remote_repo[stranded[pitch_path].id].data.decode("utf-8") == pitch
    assert remote_repo[stranded[PATH].id].data.decode("utf-8") == note
    # NEITHER path reached main: no pitch, and the note still says what the
    # hand-push made it say.
    assert head(remote_path) == outside == head(repo_path)
    assert pitch_path not in tree_now(remote_path)
    assert parse_text(store.read(outside, PATH), PATH).owner == "bo"
    assert not contains(remote_path, ours.commit)
    after = store.condition()
    assert (after.unpushed, after.parked, after.diverged) == (0, 0, False)


def test_a_force_pushed_remote_is_a_fork_and_nothing_is_replayed_onto_it(
    store: Store, repo_path: Path, remote_path: Path
):
    """The force-push guard. The store keeps `refs/openproj/pushed` — the newest
    commit it has positively confirmed the remote holds. A fetched remote that no
    longer contains it did not merely move: it LOST a commit we saw it hold, and
    replaying the backlog onto rewritten history would launder the rewrite into
    ordinary-looking commits. So the pusher stops — no replay, no rewind, no
    parked branches — and the condition is a person's to resolve.
    """
    confirmed = store.write(
        path=PATH,
        content=record(status="in_progress"),
        base_commit=store.head(),
        author="ann",
        message="task-c00001: status todo -> wip",
    )
    assert store.sync().state == "landed"  # the remote provably held this commit

    # History rewritten under us: remote main rewound past the confirmed commit
    # and moved somewhere else, the way a hard reset plus a force-push does it.
    seed = parent(remote_path, confirmed.commit)
    rewritten = commit_directly(
        remote_path,
        {**tree_now(remote_path), "notes.md": "history rewritten\n"},
        "history rewritten",
        parents=[seed],
        ref=None,
    )
    remote = pygit2.Repository(str(remote_path))
    remote.references["refs/heads/main"].set_target(rewritten)

    ours = store.write(
        path=OTHER,
        content=record(id="task-c00002", title="Downgrade numpy", owner="bo",
            status="in_progress"),
        base_commit=store.head(),
        author="bo",
        message="task-c00002: status todo -> wip",
    )

    outcome = store.sync()

    assert outcome.state == "diverged"
    assert (outcome.landed, outcome.remapped, outcome.parked) == (None, {}, [])
    assert head(repo_path) == ours.commit  # nothing rewound
    assert head(remote_path) == rewritten  # nothing replayed onto the fork
    assert stranded_branch(remote_path, ours.commit) is None  # and nothing parked
    after = store.condition()
    assert after.diverged is True
    assert after.refusal, "a runbook has to be writable from the condition"
    # Both commits are at risk now: the one the remote lost and the one behind it.
    assert after.unpushed == 2


def test_the_force_push_guard_is_armed_before_the_first_push_ever_succeeds(
    store: Store, repo_path: Path, remote_path: Path
):
    """The guard must not depend on this process having pushed. It used to:
    `refs/openproj/pushed` was written only by a successful push, and
    `deploy/boot.py` clones the plan fresh onto an in-memory disk on every cold
    start — so every production instance booted into the one state where the
    guard did nothing. In that window a force-pushed remote was silently HEALED:
    the backlog replayed onto the rewritten history, local main swapped onto it,
    health green, and a commit the remote provably held on main gone from every
    main with nothing said anywhere. The clone's tip came FROM the remote, which
    is positive confirmation the remote held it — the same argument the
    `unpushed` floor already makes — so the store must open with the guard set
    to that tip.
    """
    carried = store.head()  # the clone's tip: the remote demonstrably held this
    ours = store.write(
        path=PATH,
        content=record(status="in_progress"),
        base_commit=carried,
        author="ann",
        message="task-c00001: status todo -> wip",
    )
    # History rewritten under us before we ever pushed: remote main replaced by
    # a new root that drops the very commit our clone was cut from.
    rewritten = commit_directly(
        remote_path,
        {**tree_now(remote_path), "notes.md": "history rewritten\n"},
        "history rewritten",
        parents=[],
        ref=None,
    )
    remote = pygit2.Repository(str(remote_path))
    remote.references["refs/heads/main"].set_target(rewritten)

    outcome = store.sync()

    assert outcome.state == "diverged"
    assert (outcome.landed, outcome.remapped, outcome.parked) == (None, {}, [])
    assert head(repo_path) == ours.commit  # nothing rewound, nothing re-minted
    assert contains(repo_path, carried)  # the dropped commit survives on our main
    assert head(remote_path) == rewritten  # nothing replayed onto the fork
    assert stranded_branch(remote_path, ours.commit) is None
    after = store.condition()
    assert after.diverged is True
    assert after.refusal, "a runbook has to be writable from the condition"
    assert after.unpushed == 2  # the commit the remote lost, and ours behind it


def test_a_write_on_a_forked_store_is_refused_and_still_pokes_the_pusher(
    store: Store, repo_path: Path, remote_path: Path
):
    """The write gate and its poke, pinned together because each keeps the other
    honest.

    Refusing: `sync()` parks on a fork and only a person can move the remote, so
    every commit accepted past the guard joins a backlog with no way off this
    disk — on Cloud Run the disk is memory, and an idle recycle discards the
    lot, each commit accepted with a green answer. The deleted-push branch
    shipped exactly that for a while: writes kept answering while the pusher
    was parked for good.

    Poking: the gate reads the tracking ref, which only a fetch moves, and a
    refusal makes no commit — so a gate that refused WITHOUT poking would stay
    shut forever after a person heals the remote, because nothing else on the
    write path or the health route ever fetches. The poke keeps the discovery
    loop alive, and the tail of this test walks it: heal, one pass, and the
    same save goes through.
    """
    confirmed = store.write(
        path=PATH,
        content=record(status="in_progress"),
        base_commit=store.head(),
        author="ann",
        message="task-c00001: status todo -> wip",
    )
    assert store.sync().state == "landed"  # the remote provably held this commit

    seed = parent(remote_path, confirmed.commit)
    rewritten = commit_directly(
        remote_path,
        {**tree_now(remote_path), "notes.md": "history rewritten\n"},
        "history rewritten",
        parents=[seed],
        ref=None,
    )
    remote = pygit2.Repository(str(remote_path))
    remote.references["refs/heads/main"].set_target(rewritten)
    ours = store.write(
        path=OTHER,
        content=record(id="task-c00002", title="Downgrade numpy", owner="bo",
            status="in_progress"),
        base_commit=store.head(),
        author="bo",
        message="task-c00002: status todo -> wip",
    )
    assert store.sync().state == "diverged"

    store.dirty.clear()
    with pytest.raises(StoreDiverged) as refused:
        store.write(
            path=PATH,
            content=record(status="done"),
            base_commit=store.head(),
            author="ann",
            message="task-c00001: status wip -> done",
        )

    assert head(repo_path) == ours.commit, "refused, but committed anyway"
    assert "no longer contains" in str(refused.value), (
        "the refusal must speak in the force-push guard's words, not invent its own"
    )
    assert store.dirty.is_set(), (
        "refused without poking: nothing fetches on the write path or in health, "
        "so the store would stay wedged forever after a person heals the remote"
    )

    # The loop the poke keeps alive. A person puts the remote back onto the
    # history it rewrote away; the pass the poke asked for discovers it and
    # lands the stranded backlog; the gate opens on its own — no restart.
    remote.references["refs/heads/main"].set_target(confirmed.commit)
    assert store.sync().state == "landed"
    healed = store.write(
        path=PATH,
        content=record(status="done"),
        base_commit=store.head(),
        author="ann",
        message="task-c00001: status wip -> done",
    )
    assert healed.commit is not None
    assert store.condition().diverged is False


def test_both_sides_moved_reads_healthy_while_the_remote_still_holds_what_it_held(
    repo_path: Path, remote_path: Path, remote_url: str
):
    """The health rescope, pinned in the one state where its two readings disagree.

    `condition().diverged` used to mean "local and remote have both moved and
    neither contains the other". The deferred push made that the ORDINARY
    recoverable race — a hand-push in the window between a commit and the
    pusher's pass — so the meaning was rescoped to the force-push guard's: the
    tracking ref no longer contains `refs/openproj/pushed`. Every other test
    agrees under both readings, because it looks before anything has raced or
    after everything has landed — a revert to the old comparison passed the
    whole suite. So this one parks the store in the disagreeing state and holds
    it there with an outage. Under the old reading `/api/health` answers 503
    for the entire outage-plus-race window, on every ordinary hand-push — the
    alarm fatigue the spec forbids (design/deferred-push.md, "Health"), because a
    flag that goes red on the recoverable case has been learned and ignored by
    the day the remote really loses a commit.
    """
    store = Store(repo_path, remote=remote_url)
    try:
        ours = store.write(
            path=PATH,
            content=record(status="in_progress"),
            base_commit=store.head(),
            author="ann",
            message="task-c00001: status todo -> wip",
        )
        outside = pushed_from_a_terminal(
            remote_path,
            {"tasks/task-c00003.md": record(id="task-c00003", title="By hand")},
            "task-c00003: added from a terminal",
        )
        # The fetch is what puts the race onto the two refs `condition` reads;
        # nothing on the health path fetches for itself, so without it both
        # readings would still agree and the test would pin nothing.
        assert store.fetch() == outside
        assert ours.commit is not None
        repo = pygit2.Repository(str(repo_path))
        # The disagreement, proved rather than assumed: neither tip contains
        # the other — the old definition's "diverged" — while the tracking ref
        # still descends from everything the remote was seen to hold.
        assert not repo.descendant_of(ours.commit, outside)
        assert not repo.descendant_of(outside, ours.commit)
        state = store.condition()
        assert state.diverged is False
        assert state.refusal is None
        assert state.unpushed == 1
    finally:
        store.close()

    # The same repository behind `/api/health`, during the outage that keeps
    # the race standing: unreachable is not a rejection, so the pusher backs
    # off and the refs hold this exact state however long GitHub is away —
    # which makes the 200 below deterministic, not a race against the pusher.
    # Imported here because this is the one place this Store-level suite
    # crosses into the web layer: the regression being pinned is a 503.
    from fastapi.testclient import TestClient

    from openproj.web import create_app

    # Not `unplugged`: the outage has to end BEFORE the app shuts down, so the
    # drain lands the backlog instead of running out its grace clock, and a
    # context manager can only end it after.
    offline = remote_path.with_name(remote_path.name + ".offline")
    remote_path.rename(offline)
    try:
        with TestClient(create_app(repo_path, remote=remote_url)) as client:
            answer = client.get("/api/health")
            assert answer.status_code == 200
            body = answer.json()
            assert body["ok"] is True
            assert body["detail"] is None
            # The backlog is still here and still counted — proof the pusher
            # did not quietly resolve the race before the route answered.
            assert body["unpushed"] == 1
            assert body["head"] == ours.commit
            offline.rename(remote_path)
    finally:
        if offline.exists():
            offline.rename(remote_path)


def test_a_conflict_in_the_middle_of_a_batch_parks_alone_and_the_rest_land(
    store: Store, repo_path: Path, remote_path: Path
):
    """The judge's finding: later commits must replay against a tip that LACKS the
    parked one. A replay that carried the parked commit's tree forward would
    reintroduce the refused edit silently, one commit later, under somebody
    else's sha — so the delta is per commit against its own parent, and a parked
    commit simply never joins the growing tip.
    """
    first = store.write(
        path=OTHER,
        content=record(id="task-c00002", title="Downgrade numpy", owner="bo",
            status="in_progress"),
        base_commit=store.head(),
        author="bo",
        message="task-c00002: status todo -> wip",
    )
    second = store.write(
        path=PATH,
        content=record(owner="cy"),
        base_commit=store.head(),
        author="ann",
        message="task-c00001: owner ann -> cy",
    )
    third = store.write(
        path="tasks/task-c00004.md",
        content=record(id="task-c00004", title="Late arrival", owner="dee"),
        base_commit=store.head(),
        author="dee",
        message="task-c00004: create",
    )
    outside = pushed_from_a_terminal(
        remote_path, {PATH: record(owner="bo")}, "task-c00001: owner ann -> bo"
    )

    outcome = store.sync()

    assert outcome.state == "landed"
    assert set(outcome.remapped) == {first.commit, third.commit}
    assert outcome.parked == [(second.commit, f"openproj/stranded-{second.commit}")]
    tip = head(remote_path)
    assert tip == outcome.remapped[third.commit] == head(repo_path) == outcome.landed
    # The chain proves the tip the third commit grew on lacks the second: its
    # replay sits directly on the first's, which sits on the hand-push.
    assert parent(remote_path, tip) == outcome.remapped[first.commit]
    assert parent(remote_path, outcome.remapped[first.commit]) == outside
    # The parked edit is NOT silently reintroduced by the commits behind it.
    assert parse_text(store.read(tip, PATH), PATH).owner == "bo"
    assert parse_text(store.read(tip, OTHER), OTHER).status == "in_progress"
    assert store.read(tip, "tasks/task-c00004.md") is not None
    assert stranded_branch(remote_path, second.commit) == second.commit
    # Linear, single-parent, authors verbatim — the audit trail survives the
    # replay exactly as it survived the push (invariant 4).
    assert [len(commit.parents) for commit in history(remote_path)] == [1, 1, 1, 0]
    assert [commit.author.name for commit in history(remote_path)] == [
        "dee", "bo", "a human", "a human",
    ]


def test_a_commit_made_during_the_recovery_is_parked_at_the_swap_not_dropped(
    store: Store, repo_path: Path, remote_path: Path, monkeypatch
):
    """The fatal flaw the adversary found in this design. Commits made DURING a
    recovery are replayed at the swap, under the lock — and that replay had no
    conflict arm, so a straggler that conflicted there was silently dropped: the
    swap moved main to a tip that did not contain it, and nothing said so.
    Nothing may be dropped merely because it arrived late: the straggler parks,
    its branch reaches the remote, and the outcome names it.
    """
    backlog = store.write(
        path=OTHER,
        content=record(id="task-c00002", title="Downgrade numpy", owner="bo",
            status="in_progress"),
        base_commit=store.head(),
        author="bo",
        message="task-c00002: status todo -> wip",
    )
    pushed_from_a_terminal(
        remote_path, {PATH: record(owner="bo")}, "task-c00001: owner ann -> bo"
    )

    straggler: dict = {}
    real_land = Store._land

    def landing(self, repo, refspecs):
        # The interleaving, made deterministic: the recovery's first push is the
        # last thing before the swap, so a save arriving exactly now is the
        # straggler — committed on local main after the backlog walk, replayed
        # only under the lock. The lock is free here, so the save answers the
        # way any save does.
        if not straggler:
            straggler["written"] = store.write(
                path=PATH,
                content=record(owner="cy"),
                base_commit=store.head(),
                author="cy",
                message="task-c00001: owner ann -> cy",
            )
        return real_land(self, repo, refspecs)

    monkeypatch.setattr(Store, "_land", landing)

    outcome = store.sync()

    written = straggler["written"]
    assert written.commit is not None, "the straggler save never answered"
    assert parent(repo_path, written.commit) == backlog.commit  # made during recovery

    assert outcome.state == "landed"
    assert set(outcome.remapped) == {backlog.commit}
    branch = f"openproj/stranded-{written.commit}"
    assert outcome.parked == [(written.commit, branch)], "the straggler vanished"
    # Durable on the remote, not merely noted locally.
    assert stranded_branch(remote_path, written.commit) == written.commit
    assert not contains(remote_path, written.commit)
    assert not contains(repo_path, written.commit)  # off main — parked, not hidden
    landed_tip = outcome.remapped[backlog.commit]
    assert head(remote_path) == head(repo_path) == landed_tip == outcome.landed
    assert parse_text(store.read(landed_tip, OTHER), OTHER).status == "in_progress"
    assert parse_text(store.read(landed_tip, PATH), PATH).owner == "bo"
    after = store.condition()
    assert (after.unpushed, after.parked) == (0, 0)


# --------------------------------------------------------------------------- #
# 11. The thread, and shutdown (design/deferred-push.md, "The pusher")
# --------------------------------------------------------------------------- #


def drained(store: Store, seconds: float = 30.0) -> None:
    """Wait until the pusher has nothing left to send, or fail saying what is left.

    Read off `condition()` and the poke, never off the pusher's internals: the
    claim is that the backlog empties, and the backlog is refs on disk.
    """
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        state = store.condition()
        if state.unpushed == 0 and state.parked == 0 and not store.dirty.is_set():
            return
        time.sleep(0.05)
    state = store.condition()
    raise AssertionError(
        f"the pusher never drained: unpushed={state.unpushed} parked={state.parked}"
    )


def test_several_writers_at_once_all_reach_the_remote(
    store: Store, repo_path: Path, remote_path: Path
):
    """The claim jcanton asked about, asked of real threads: several writers
    saving at once while the pusher runs, with hand-pushes landing in the middle
    of it. Every answered sha must end up landed under its own name,
    re-minted-and-landed with the old-to-new pair announced, or parked on a
    branch that exists on the remote — and NEVER merely gone. A sha that
    answered 200 and then cannot be accounted for is somebody's Friday.

    One writer and one hand-push deliberately edit the same record, so the run
    crosses the conflict arm when the timing falls that way; the property holds
    on either side of the race, which is why it is stated as a property.

    The gate below gives the `file://` remote the one property of GitHub this
    test needs and libgit2's local transport lacks: receive-pack holds the ref
    lock ACROSS its not-a-fast-forward check and the update, while the local
    transport checks and then updates in two steps. Ungated, a hand-push landed
    on the remote and a racing push then replaced `main` with a non-descendant
    — with no force anywhere in this code — which is a loss the production
    transport refuses by construction, manufactured by the harness. Only the
    remote's ref movement is serialised: fetches, replays and rejections still
    interleave freely, which is where the claims under test live.
    """
    gate = threading.Lock()
    real_push = pygit2.Remote.push

    def serial_push(remote, *args, **kwargs):
        with gate:
            return real_push(remote, *args, **kwargs)

    pygit2.Remote.push = serial_push
    outcomes: list = []
    pusher = Pusher(store, deliver=outcomes.append)
    barrier = threading.Barrier(WRITERS + 1)

    def write(n: int) -> str:
        barrier.wait()
        if n == 0:
            # The overlap: the hand-push below edits the same record.
            result = store.write(
                path=PATH,
                content=record(owner="cy"),
                base_commit=store.head(),
                author="cy",
                message="task-c00001: owner ann -> cy",
            )
        else:
            result = store.write(
                path=f"tasks/task-t{n:05d}.md",
                content=record(id=f"task-t{n:05d}", title=f"Concurrent {n}"),
                base_commit=store.head(),
                author=f"user{n}",
                message=f"task-t{n:05d}: create",
            )
        assert result.commit is not None, f"writer {n} was refused"
        return result.commit

    def hand_pushes() -> list[str]:
        barrier.wait()
        made = []
        for n in range(3):
            files = (
                {PATH: record(owner="bo")}
                if n == 0
                else {f"tasks/task-h{n:05d}.md": record(id=f"task-h{n:05d}", title=f"By hand {n}")}
            )
            # Under the gate, tree and commit together — the atomic unit a real
            # remote gives a push. Between two hand-pushes the pusher runs free.
            with gate:
                made.append(
                    commit_directly(remote_path, {**tree_now(remote_path), **files}, f"hand {n}")
                )
            time.sleep(0.02)
        return made

    try:
        pusher.start()
        with ThreadPoolExecutor(max_workers=WRITERS + 1) as pool:
            handed = pool.submit(hand_pushes)
            answered = list(pool.map(write, range(WRITERS)))
            outside = handed.result()
        drained(store)
    finally:
        pusher.close()
        pygit2.Remote.push = real_push

    remapped: dict[str, str] = {}
    parked: dict[str, str] = {}
    for outcome in outcomes:
        remapped.update(outcome.remapped)
        parked.update(dict(outcome.parked))

    def account_for(sha: str) -> str:
        """landed, re-minted, or parked — the three fates the design allows."""
        seen = set()
        while sha in remapped and sha not in seen:
            # A re-mint can itself be re-minted by a later recovery.
            seen.add(sha)
            sha = remapped[sha]
        if contains(remote_path, sha):
            return "landed"
        if stranded_branch(remote_path, sha) == sha:
            return "parked"
        return "gone"

    fates = {sha: account_for(sha) for sha in answered}
    assert "gone" not in fates.values(), f"an answered commit is merely gone: {fates}"
    # Nobody's hand-push was discarded to make room for ours.
    for commit in outside:
        assert contains(remote_path, commit), "a hand-push was discarded"
    # Local main ended up on, or behind, the remote — never beside it.
    assert contains(remote_path, head(repo_path))
    # Linear and single-parent throughout: the audit trail survived the traffic.
    parents = [len(commit.parents) for commit in history(remote_path)]
    assert parents[-1] == 0 and set(parents[:-1]) == {1}


def test_a_shutdown_lands_what_is_still_in_the_backlog(
    store: Store, repo_path: Path, remote_path: Path
):
    """A save answers before the push, so a shutdown can arrive with commits on
    no origin — and on Cloud Run the disk dies with the instance, so the drain
    in the pusher's close IS the last copy leaving the building. This depends on
    `deploy/boot.py`'s execv fix (v0.19.2): SIGTERM now actually reaches the
    server, so lifespan shutdown runs and the drain has its window.

    The backoff is set longer than the test lives, and the write happens while
    the remote is away — so the ordinary retry provably cannot be what lands the
    commit. Only the shutdown can.
    """
    said: list = []
    pusher = Pusher(store, deliver=said.append, backoff=300.0)
    pusher.start()

    with unplugged(remote_path):
        written = store.write(
            path=PATH,
            content=record(status="in_progress"),
            base_commit=store.head(),
            author="ann",
            message="task-c00001: status todo -> wip",
        )
        assert written.pushed is False
        # Wait for the ordinary pass to have tried and failed, so the pusher is
        # provably inside its 300-second wait when the plug goes back in.
        deadline = time.monotonic() + 10
        while not any(one.state == "unreachable" for one in said):
            assert time.monotonic() < deadline, "the pusher never tried at all"
            time.sleep(0.01)

    assert head(remote_path) != written.commit  # still only on this disk
    started = time.monotonic()
    pusher.close()

    assert time.monotonic() - started < 10, "the shutdown drain hung"
    assert head(remote_path) == written.commit, "the backlog died with the process"
    assert store.condition().unpushed == 0


# --------------------------------------------------------------------------- #
# 12. The poll: a hand-push reaches a server nobody saved on
#
# `sync()` answers "is there anything of OURS to send", and answers it without a
# round trip when the tracking ref says no. That is right, and it is why a warm
# instance nobody saves on never notices a hand-push: nothing on the read path
# fetches, so the tracking ref stays where the boot clone left it, `level` is
# true against a stale ref, and the pusher — which only ever wakes on a local
# commit — is never asked. Measured in production on 2026-08-27: a commit pushed
# from a terminal was on GitHub and `/api/health` still named its parent hours
# later, while `/detail/<the new record>` answered 404.
#
# `catch_up()` asks the other question, and the pusher asks it on a timer.
# --------------------------------------------------------------------------- #


def test_a_hand_push_reaches_a_store_that_has_written_nothing(store: Store, remote_path: Path):
    """The bug, as one call. Nothing local has changed, so every existing route
    into the remote declines to look — and the commit is on the remote."""
    outside = pushed_from_a_terminal(
        remote_path,
        {"tasks/task-c00003.md": record(id="task-c00003", title="By hand")},
        "task-c00003: added from a terminal",
    )
    assert store.head() != outside

    assert store.catch_up().state == "landed"

    assert store.head() == outside
    assert store.read(store.head(), "tasks/task-c00003.md") is not None


def test_a_poll_that_finds_nothing_is_idle_and_moves_nothing(store: Store):
    """The overwhelmingly common pass. `idle` is what stops the caller announcing
    a landing to every open tab once a minute forever."""
    before = store.head()

    assert store.catch_up().state == "idle"

    assert store.head() == before


def test_the_poll_carries_the_backlog_up_with_it(store: Store, remote_path: Path):
    """A poll is not a read-only errand: a store with unpushed commits and a
    remote that moved is exactly the recovery case, and the poll must land the
    backlog rather than fast-forward over it."""
    outside = pushed_from_a_terminal(
        remote_path,
        {"tasks/task-c00003.md": record(id="task-c00003", title="By hand")},
        "task-c00003: added from a terminal",
    )
    mine = store.write(
        path=PATH,
        content=record(status="in_progress"),
        base_commit=store.head(),
        author="ann",
        message="task-c00001: status todo -> wip",
    )
    assert mine.pushed is False

    outcome = store.catch_up()

    assert outcome.state == "landed"
    assert contains(remote_path, outside), "the outsider's commit was rewound"
    assert store.read(store.head(), "tasks/task-c00003.md") is not None
    assert parse_text(store.read(store.head(), PATH), PATH).status == "in_progress"
    assert store.condition().unpushed == 0


def test_a_poll_at_an_unreachable_remote_says_so_and_changes_nothing(
    store: Store, remote_path: Path
):
    """Same answer the push path gives, so the caller's backoff is one branch and
    not two."""
    before = store.head()

    with unplugged(remote_path):
        assert store.catch_up().state == "unreachable"

    assert store.head() == before


def test_a_store_with_no_remote_polls_without_a_network(local_only: Store):
    """Local development is the primary deployment for most of Phase 1, and a
    timer that fires there must cost nothing at all."""
    before = local_only.head()

    assert local_only.catch_up().state == "idle"

    assert local_only.head() == before


def test_the_pusher_notices_a_hand_push_with_no_save_to_wake_it(
    store: Store, remote_path: Path
):
    """The end-to-end property, and the one the production incident is about: a
    commit arrives on the remote and NOBODY touches the server."""
    pusher = Pusher(store, idle=0.05)
    pusher.start()
    try:
        outside = pushed_from_a_terminal(
            remote_path,
            {"tasks/task-c00003.md": record(id="task-c00003", title="By hand")},
            "task-c00003: added from a terminal",
        )
        deadline = time.monotonic() + 10
        while store.head() != outside:
            assert time.monotonic() < deadline, "the poll never ran"
            time.sleep(0.01)
    finally:
        pusher.close()

    assert store.read(store.head(), "tasks/task-c00003.md") is not None


def test_the_poll_leaves_a_forked_store_alone(store: Store, remote_path: Path):
    """A FORK — history rewritten, not merely grown — is a person's to resolve,
    and until they do there is nothing a round trip can learn. The pass that
    meets it is the one that discovers it; every timer tick after that must be
    free, or the poll becomes exactly the backoff loop `_pass` was written not to
    be, hammering a remote once a minute for as long as the instance lives.

    Not the `diverged` fixture, which is the ORDINARY recoverable race: both
    sides grew from one commit, `_recover` replays ours onto theirs and answers
    `landed`. Only a remote that lost a commit this store confirmed it held
    parks the pusher, so only that shape tests this.
    """
    confirmed = store.write(
        path=PATH,
        content=record(status="in_progress"),
        base_commit=store.head(),
        author="ann",
        message="task-c00001: status todo -> wip",
    )
    assert store.sync().state == "landed"  # the remote provably held it
    seed = parent(remote_path, confirmed.commit)
    rewritten = commit_directly(
        remote_path,
        {**tree_now(remote_path), "notes.md": "history rewritten\n"},
        "history rewritten",
        parents=[seed],
        ref=None,
    )
    pygit2.Repository(str(remote_path)).references[BRANCH].set_target(rewritten)

    said: list = []
    pusher = Pusher(store, deliver=said.append, idle=0.02)
    pusher.start()
    try:
        deadline = time.monotonic() + 10
        while not any(one.state == "diverged" for one in said):
            assert time.monotonic() < deadline, "the pusher never met the fork"
            time.sleep(0.01)
        seen = len(said)
        time.sleep(0.5)  # twenty-five ticks' worth of timer
    finally:
        pusher.close()

    assert len(said) == seen, "the poll kept asking a remote only a person can fix"
    assert head(remote_path) == rewritten  # and nothing was replayed onto it
