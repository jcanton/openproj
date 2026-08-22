"""The git layer: a bare repository written through one serialised writer.

There is no working copy and no index. Eight concurrent writers sharing one
worktree lost 87.5% of their commits to `index.lock` contention; trees are built
with `TreeBuilder` and commits created directly, so there is nothing to contend
for. A single `repo.index` anywhere in this file gives that back.

Compare-and-swap is scoped to the path being written. A stale base whose file
nobody touched is retried silently — roughly 95% of collisions, and the reason
thirty people can hold editors open at once. Only a genuine overlap is refused,
and a refusal writes nothing and shows no conflict markers: a `<<<<<<<` that
reaches a caller reaches a textarea, and then somebody saves it.

`head`, `read` and `paths` are commit-scoped because a human with a terminal will
commit to this repository in week one, and a cached "current" state cannot be
reasoned about when they do.
"""

from __future__ import annotations

import fcntl
import hashlib
import io
import os
import threading
from difflib import SequenceMatcher
from pathlib import Path
from typing import Literal

import pygit2
from pydantic import BaseModel
from pygit2.enums import RepositoryOpenFlag, SortMode
from ruamel.yaml import YAML

_BRANCH = "refs/heads/main"
_ORIGIN = "origin"
_TRACKING = "refs/remotes/origin/main"
_BOT = pygit2.Signature("openproj-bot", "openproj-bot@example.invalid")
# The writer's flock, named here rather than in two places: `openproj demo`
# builds a plan repository out of a directory that may have had a `Store` opened
# against it, and the one file it must not copy is this one. A caller that spelt
# the name itself would be a second copy of it, and this file's own rule is that
# an invariant written twice is guarded once.
LOCK_FILE = "openproj.lock"
# How much happened to a write, least first. `write_all` reports the furthest one
# any of its files reached, so a set is never described by its quietest member.
_OUTCOMES = ("committed", "retried", "merged")


class WriteResult(BaseModel):
    commit: str | None
    outcome: Literal["committed", "retried", "merged", "conflict"]
    conflict: str | None = None
    # Whether the commit reached the remote. On an ephemeral filesystem an
    # unpushed commit is a lost commit, so a caller that reports success without
    # looking at this is how a team finds out on Monday that Friday is gone.
    pushed: bool = False


class NotAPlanRepository(RuntimeError):
    """The path given is not a git repository, and must not be searched upwards for
    one — see the note in `Store.__init__`."""


class StoreLocked(RuntimeError):
    """Another process already holds the writer lock on this repository."""


class StoreDiverged(RuntimeError):
    """Local and remote have both moved and neither contains the other.

    Never resolved automatically: every automatic answer discards somebody's
    commits, and a tracker that silently drops a commit is worse than one that
    stops and says so.
    """


def _split(text: str) -> tuple[str, str]:
    """Frontmatter block and body, without reformatting either."""
    if not text.startswith("---"):
        return "", text
    _, _, rest = text.partition("---\n")
    front, sep, body = rest.partition("\n---\n")
    return (front, body) if sep else ("", text)


def _yaml() -> YAML:
    yaml = YAML()
    yaml.preserve_quotes = True
    return yaml


def _load(front: str) -> dict:
    return _yaml().load(front) or {}


def _dump(mapping) -> str:
    stream = io.StringIO()
    _yaml().dump(mapping, stream)
    return stream.getvalue()


def _merge_frontmatter(base: str, mine: str, theirs: str) -> tuple[str | None, list[str]]:
    """Per-key three-way merge. Returns (merged, conflicts).

    Field-level rather than file-level: they set the status while I set the
    priority is not a disagreement, and refusing it teaches people to keep their
    editors shut.
    """
    base_map, mine_map, theirs_map = _load(base), _load(mine), _load(theirs)
    merged, conflicts = _load(theirs), []
    for key in {*base_map, *mine_map, *theirs_map}:
        was, ours, yours = base_map.get(key), mine_map.get(key), theirs_map.get(key)
        if ours == yours:
            continue
        if ours == was:  # only they moved it
            continue
        if yours == was:  # only we moved it
            if key in mine_map:
                merged[key] = ours
            else:
                merged.pop(key, None)
            continue
        conflicts.append(f"  {key}: stored {yours!r} · yours {ours!r}")
    return (None if conflicts else _dump(merged)), conflicts


def _changes(base: list[str], other: list[str]) -> dict[tuple[int, int], list[str]]:
    return {
        (i1, i2): other[j1:j2]
        for tag, i1, i2, j1, j2 in SequenceMatcher(None, base, other).get_opcodes()
        if tag != "equal"
    }


def _merge_body(base: str, mine: str, theirs: str) -> tuple[str | None, list[str]]:
    """Three-way line merge. Overlapping edits are a conflict, never a marker."""
    base_lines = base.splitlines(True)
    mine_lines, theirs_lines = mine.splitlines(True), theirs.splitlines(True)
    ours, yours = _changes(base_lines, mine_lines), _changes(base_lines, theirs_lines)

    conflicts = []
    for span, replacement in ours.items():
        for other_span, other_replacement in yours.items():
            overlaps = span[0] < other_span[1] and other_span[0] < span[1]
            touching = span == other_span
            if (overlaps or touching) and replacement != other_replacement:
                stored_text = "".join(other_replacement).strip()
                yours_text = "".join(replacement).strip()
                conflicts.append(
                    f"  lines {span[0] + 1}-{span[1]}: "
                    f"stored {stored_text!r} · yours {yours_text!r}"
                )
    if conflicts:
        return None, conflicts

    merged, cursor = [], 0
    for start in range(len(base_lines) + 1):
        for span in (s for s in {*ours, *yours} if s[0] == start):
            if cursor > span[0]:
                continue
            merged.extend(base_lines[cursor : span[0]])
            merged.extend(ours.get(span) or yours.get(span) or [])
            cursor = span[1]
    merged.extend(base_lines[cursor:])
    return "".join(merged), []


def _deleted(path: str) -> str:
    """What a save is answered with when the file it edits is gone.

    A deletion is not an empty file, and the merge below cannot tell them apart:
    it is handed `theirs or ""`, so a record somebody removed in git arrives as a
    frontmatter with no keys and a body with no lines. Every key the save did not
    touch then reads as "only they moved it" and is dropped, every key it did
    touch reads as "only we moved it" and is kept — and the merge that comes out
    is a *resurrection* of the record with nothing in it but the field that was
    being edited. A drag onto a row deleted under you committed
    `---\\nparent: proj-a10000\\n---\\n` over a task, answered 200, and announced
    the move; the same happened to an `owner`, a `status` or anything else whose
    value was empty before the edit.

    Parsing the result would not have caught it. Every field is optional at the
    type level on purpose, so that file loads perfectly well — it is a record
    with no title and no kind, which `validate_all` reports beside the row it
    ruined, one commit too late to stop.

    So the answer is the one git gives for modify/delete: refuse, and say which
    file and what to do. A person deleting a record and a person editing it have
    genuinely disagreed, and there is no third text that is both of their
    intentions.
    """
    return (
        f"{path} — somebody deleted this while you were editing it.\n"
        "  Nothing was written. Restore it in git if it should not have gone, "
        "or make the record again."
    )


class _Rejected(Exception):
    """The remote refused the push because it had moved.

    Its own type and not a bare `Exception`, because `_finish` deliberately
    swallows everything else a push can fail with — an unreachable remote is a
    commit that is real and local and reported as unpushed, which is not this. A
    rejection means somebody else's commit is on the remote and ours is not a
    descendant of it, and that is recoverable by rewinding and trying again.
    """


def _lost_the_race(paths: list[str]) -> str:
    """What a write is answered with after three attempts have all been outrun.

    Not "the remote is broken" and not silence: the plan is being written to
    faster than one save can land, which is a real thing to be told and a
    different thing from a merge conflict. Nothing was committed.
    """
    return (
        f"{', '.join(paths)} — the plan moved three times while this was being "
        "saved.\n  Nothing was written. Reload and try again."
    )


def _changed_under_delete(path: str) -> str:
    """What a delete is answered with when somebody edited the file first.

    The mirror of `_deleted`, from the other side of the same disagreement. One
    person decided this record should not exist and another decided what it should
    say, and there is no third outcome that is both — least of all the one that
    happens by default, which is that the edit is committed and then thrown away
    without ever being read.
    """
    return (
        f"{path} — somebody edited this while you were deleting it.\n"
        "  Nothing was removed. Read what they wrote, then decide again."
    )


def _already_gone(path: str) -> str:
    """What a delete is answered with when the record has already gone.

    Not silence. Two people deleting one record is not a conflict of intent, but
    it is still a page about to say "deleted" over a commit it did not make, and
    the sha it would report belongs to somebody else's work.
    """
    return (
        f"{path} — somebody deleted this first.\n"
        "  Nothing was written, and the record is already out of the plan."
    )


def _merge(path: str, base: str, mine: str, theirs: str) -> tuple[str | None, str | None]:
    """Structured merge of one entity file. Returns (merged_text, conflict_report)."""
    base_front, base_body = _split(base)
    mine_front, mine_body = _split(mine)
    theirs_front, theirs_body = _split(theirs)

    front, front_conflicts = _merge_frontmatter(base_front, mine_front, theirs_front)
    body, body_conflicts = _merge_body(base_body, mine_body, theirs_body)

    problems = front_conflicts + body_conflicts
    if problems:
        report = "\n".join(
            [f"{path} — somebody changed this before you, in the same places:", *problems]
        )
        return None, report
    return f"---\n{front}---\n{body}", None


def _tree_blobs(repo: pygit2.Repository, commit: str) -> dict[str, str]:
    """Every file at this commit, and the id of the bytes in it.

    Module-level so `last_edited_in` — a read-only walk over a repository no
    Store is open on — shares the one tree walk instead of growing a second.
    See `Store.blobs` for why callers want the whole map at once.
    """
    found: dict[str, str] = {}

    def walk(tree, prefix: str) -> None:
        for entry in tree:
            name = f"{prefix}{entry.name}"
            if entry.type_str == "tree":
                walk(repo.get(entry.id), f"{name}/")
            else:
                found[name] = str(entry.id)

    walk(repo.get(commit).tree, "")
    return found


def _stamp_trie(paths: set[str]) -> dict:
    """The paths as a tree of names, each leaf holding its full path.

    The walk compares whole subtrees by oid before it looks at a single entry,
    and it can only do that if the paths it is still hunting are grouped the way
    the trees are. A flat set would ask every commit about every path.
    """
    trie: dict = {}
    for path in paths:
        node = trie
        *directories, name = path.split("/")
        for part in directories:
            node = node.setdefault(part, {})
        node[name] = path
    return trie


def _entry(tree, name: str):
    if tree is None:
        return None
    try:
        return tree[name]
    except KeyError:
        return None


def _touched(repo: pygit2.Repository, ours, theirs, trie: dict) -> set[str]:
    """Which of the trie's paths hold different bytes between two trees.

    Missing counts as different — that is what stamps an added path with the
    commit that added it. Pruned on tree ids: two trees sharing an id share
    every byte beneath, and almost every commit here touches one subtree of
    five, which is what keeps a walk over thousands of commits near a second.
    """
    if ours is not None and theirs is not None and ours.id == theirs.id:
        return set()
    found: set[str] = set()
    for name, below in trie.items():
        mine, yours = _entry(ours, name), _entry(theirs, name)
        if isinstance(below, dict):
            us = repo.get(mine.id) if mine is not None and mine.type_str == "tree" else None
            them = repo.get(yours.id) if yours is not None and yours.type_str == "tree" else None
            if us is None and them is None:
                continue
            found |= _touched(repo, us, them, below)
        else:
            us = mine.id if mine is not None and mine.type_str == "blob" else None
            them = yours.id if yours is not None and yours.type_str == "blob" else None
            if us != them:
                found.add(below)
    return found


def _stamps(
    repo: pygit2.Repository, head: str, wanted: set[str], hide: str | None = None
) -> dict[str, int]:
    """When a commit last changed each of these paths, in git-log semantics.

    A path is stamped by a commit when its blob differs from the SAME path in
    ALL of the commit's parents. Not first-parent: merges are routine here, not
    exceptional, and a first-parent diff stamps a side-branch edit with the
    merge's time — the merge itself stamps a path only where it resolved to
    bytes neither parent held, which is what a retry landing as a merge is.

    Newest-first over a topological walk, first touch wins, and the walk stops
    the moment every wanted path is settled. With `hide` set only commits in
    hide..head are visited — the incremental advance — and a path no visited
    commit touched is simply absent from the answer, for the caller to fill
    from its cache.
    """
    unsettled = set(wanted)
    stamped: dict[str, int] = {}
    if not unsettled:
        return stamped
    trie = _stamp_trie(unsettled)
    walker = repo.walk(repo[head].id, SortMode.TOPOLOGICAL | SortMode.TIME)
    if hide is not None:
        walker.hide(repo[hide].id)
    for commit in walker:
        if not unsettled:
            break
        if commit.parents:
            touched: set[str] | None = None
            for parent in commit.parents:
                differs = _touched(repo, commit.tree, parent.tree, trie)
                # Intersection: equal to ANY parent means some parent already
                # carried these bytes, and this commit is not the edit.
                touched = differs if touched is None else touched & differs
                if not touched:
                    break
        else:
            touched = _touched(repo, commit.tree, None, trie)
        fresh = (touched or set()) & unsettled
        if fresh:
            for path in fresh:
                stamped[path] = commit.commit_time
            unsettled -= fresh
            # Rebuilt so the subtree pruning keeps biting as paths settle. At
            # most one rebuild per settling event, bounded by the path count.
            trie = _stamp_trie(unsettled)
    return stamped


class Store:
    """One writer over one bare repository."""

    def __init__(
        self,
        repo_path: Path,
        remote: str | None = None,
        credentials: object | None = None,
    ) -> None:
        """`credentials` is anything with a `callbacks()` returning pygit2's, or
        None for a remote that needs none — a `file://` path, or no remote at all,
        which is every test and every development run."""
        self._path = Path(repo_path)
        # NO_SEARCH, because the default is to walk UP until it finds a
        # repository. Pointed at a directory that is not one — `--repo seed`, as
        # the README told people to do — it found the openproj checkout instead,
        # answered 200 on every route, and served an empty plan: 126 paths
        # visible, none of them under `pitches/`, `tasks/` or `projects/`,
        # because those live one directory down. Nothing said so. A tool that
        # draws a plan with nothing in it is indistinguishable from a plan with
        # nothing in it, which is the failure this codebase keeps having to
        # relearn — empty must not look like broken, and broken must not look
        # like empty.
        try:
            self._repo = pygit2.Repository(str(repo_path), RepositoryOpenFlag.NO_SEARCH)
        except pygit2.GitError as exc:
            raise NotAPlanRepository(
                f"{repo_path} is not a git repository. A plan lives in its own "
                "repository, and this is the path to that repository — usually a "
                "bare clone: `git clone --bare <url> plan.git`, then "
                "`--repo plan.git`."
            ) from exc
        self._remote = remote
        self._credentials = credentials
        if remote:
            existing = {r.name for r in self._repo.remotes}
            if _ORIGIN in existing:
                self._repo.remotes.set_url(_ORIGIN, remote)
            else:
                self._repo.remotes.create(_ORIGIN, remote)
        self._writing = threading.Lock()
        # An flock, not a flag: a second process must fail loudly rather than
        # interleave writes. Somebody will eventually try --workers 4.
        # "a+" rather than "w": opening for write truncates, and truncating would
        # erase the holder's pid before we even find out somebody else has the lock.
        self._lock = open(self._path / LOCK_FILE, "a+")
        try:
            fcntl.flock(self._lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self._lock.seek(0)
            holder = self._lock.read().strip() or "unknown"
            self._lock.close()
            raise StoreLocked(
                f"another openproj writer already holds {self._path} (pid {holder}). "
                "Single-writer is a correctness invariant, not a preference. "
                f"If it is a leftover, stop it with `kill {holder}` and give it a "
                "second; use `kill -9` only if that does not take."
            ) from exc
        # Whoever holds it says so, so the next person does not have to go hunting
        # through ps for a process whose name is not what they typed.
        self._lock.seek(0)
        self._lock.truncate()
        self._lock.write(str(os.getpid()))
        self._lock.flush()

    # -- reading, always at an explicit commit ------------------------------

    def head(self) -> str:
        """Read the branch tip from disk, so an outside commit is visible at once."""
        return str(pygit2.Repository(str(self._path)).references[_BRANCH].target)

    def has(self, commit: str) -> bool:
        """Whether this repository holds that commit.

        Everything below reads at an explicit commit and assumes it exists: a sha
        this repository has never seen reaches `_tree` as `None.tree`, and one
        that is not hex reaches it as a ValueError — both of which are a 500 on a
        route whose whole job is to refuse politely. The caller that needs this is
        the entity save: a restored draft carries the commit it was drafted
        against, which is older than HEAD on purpose, and a draft that has sat in
        a browser through a re-clone of the plan is a sha nothing here has.
        """
        try:
            found = self._repo.get(commit)
        except (ValueError, TypeError):
            return False
        return found is not None and found.type_str == "commit"

    def _tree(self, commit: str):
        return self._repo.get(commit).tree

    def read(self, commit: str, path: str) -> str | None:
        """The file's content, or None. A directory is not a file and a path that
        runs through one is not a file either — both answer None rather than
        raising, because a caller asking about a path that is not there is the
        normal case, not an error."""
        node = self._tree(commit)
        for part in path.split("/"):
            if node.type_str != "tree":
                return None
            try:
                node = node / part
            except KeyError:
                return None
        return node.data.decode("utf-8") if node.type_str == "blob" else None

    def paths(self, commit: str) -> list[str]:
        return sorted(self.blobs(commit))

    def blobs(self, commit: str) -> dict[str, str]:
        """Every file at this commit, and the id of the bytes in it.

        A blob id is a hash of the content, so two commits that share one names
        the same bytes — which is what lets a reader parse a file once and reuse
        the answer across every commit that did not touch it. Measured on this
        plan: one edit leaves 519 of 520 blobs untouched, and reading and parsing
        the tree is the largest cost in a request.

        Walked once and handed back whole rather than asked per path: the walk is
        the expensive half, and a caller that wants the ids wants all of them.
        """
        return _tree_blobs(self._repo, commit)

    # -- history ------------------------------------------------------------

    def last_edited(
        self, known: tuple[str, dict[str, int]] | None = None
    ) -> tuple[str, dict[str, int]]:
        """(head commit, {path: epoch seconds a commit last touched it}).

        The sha returned is the one the walk actually ran to, which is what
        makes the pair atomically swappable as a cache entry: a caller that
        stores exactly what came back can never hold one commit's sha over
        another commit's map.

        `known` is a previous answer. When its commit is an ancestor of head the
        walk covers only known..head, first touch wins, and untouched paths keep
        their cached stamp. When it is NOT an ancestor — which is routine, not a
        force-push story: the branch ref is published before the push, and a
        lost race rewinds it (`_attempt`, the `set_target(before)` arm) — the
        map is discarded and rebuilt from scratch. Retract-by-rebuild is the
        whole correctness story: there is no retraction logic to get wrong, it
        is affordable because a full walk is about a second at any size this
        plan will reach for years, and it is what stops a doomed commit's
        "edited just now" outliving the commit.

        Only paths present at head are in the map, so a deleted path drops out
        by construction rather than by bookkeeping.
        """
        head = self.head()
        present = set(_tree_blobs(self._repo, head))
        if known is not None:
            cached, stamps = known
            if cached == head:
                return head, dict(stamps)
            if self.has(cached) and self._repo.descendant_of(head, cached):
                fresh = _stamps(self._repo, head, present, hide=cached)
                settled = {path: fresh.get(path, stamps.get(path)) for path in present}
                if all(when is not None for when in settled.values()):
                    return head, settled
                # A path at head that neither the window nor the cache explains
                # should be impossible; if it ever happens, rebuild rather than
                # publish a hole.
        return head, _stamps(self._repo, head, present)

    # -- the remote ---------------------------------------------------------
    #
    # On Cloud Run the disk is ephemeral and the service scales to zero, so the
    # durable copy is the remote and a commit that has not reached it does not
    # exist. Push happens inside the writer lock, which is what keeps local
    # strictly ahead of the remote rather than divergent.

    def _remote_head(self) -> str | None:
        repo = pygit2.Repository(str(self._path))
        reference = repo.references.get(_TRACKING)
        return str(reference.target) if reference else None

    def fetch(self) -> str | None:
        """Bring the tracking ref up to date. Returns the remote head if it moved."""
        if not self._remote:
            return None
        before = self._remote_head()
        self._repo.remotes[_ORIGIN].fetch(callbacks=self._callbacks())
        after = self._remote_head()
        return after if after != before else None

    def push(self) -> bool:
        """Send local main to the remote. False when there was nothing to send.

        Raises StoreDiverged when the two histories have genuinely forked, which
        can only happen if something force-pushed or a second writer existed.
        """
        if not self._remote:
            return False
        self.fetch()
        # The tracking ref is fresh here, and only here, so this is the one place
        # that can tell a genuine fork from a race. `_send` cannot: the write path
        # calls it without fetching, where "local is not on top of the remote" is
        # the ordinary consequence of having committed on a base that has since
        # moved. Somebody force-pushed, or a second writer existed, is what this
        # is about, and neither is recoverable by trying again.
        local, remote_head = self.head(), self._remote_head()
        # Equality first: `descendant_of(x, x)` is false — a commit is not its own
        # descendant — so a store with nothing to send looked exactly like a fork.
        if remote_head is not None and remote_head != local:
            if not self._repo.descendant_of(local, remote_head):
                raise StoreDiverged(
                    f"local {local[:7]} and remote {remote_head[:7]} have both moved; "
                    "refusing to guess which commits to discard"
                )
        return self._send()

    def _send(self) -> bool:
        """Push what the tracking ref already says is ahead.

        Split out of `push` because a write had just fetched, milliseconds
        earlier and inside the same lock, and then fetched again on the way out:
        one save cost THREE round trips to GitHub — fetch, fetch, push — where a
        round trip is about 600 ms and is most of what a save costs at all.

        Divergence is still caught, and caught properly; it is just no longer
        paid for on every write. If the remote moved inside that window the push
        is rejected, and this fetches once and looks — so the fetch happens when
        it is needed rather than in the hope that it will be.
        """
        local, remote_head = self.head(), self._remote_head()
        if remote_head == local:
            return False
        # Not a fork — a race, and the difference decides whether anything can be
        # done about it. Without a pre-fetch, "local is not on top of the remote"
        # is the ORDINARY case: this process committed on a base that was current
        # when it started and is not now. Raising `StoreDiverged` here called that
        # unrecoverable, and it is the exact case the retry recovers from.
        #
        # A genuine fork — somebody force-pushed, or two writers existed — is
        # still caught, one step later: the retry rewinds and calls
        # `_absorb_remote`, which raises `StoreDiverged` when the two histories
        # really cannot be reconciled. So the hard answer is given by the code
        # that can tell, after fetching, rather than guessed here from a tracking
        # ref that is stale by design.
        if remote_head is not None and not self._repo.descendant_of(local, remote_head):
            raise _Rejected(
                f"the remote is at {remote_head[:7]} and this is not on top of it"
            )
        try:
            self._repo.remotes[_ORIGIN].push(
                [f"{_BRANCH}:{_BRANCH}"], callbacks=self._callbacks()
            )
        except Exception:
            # A refusal and an unreachable host arrive as the same class, and they
            # want opposite answers: one is recoverable by rewinding and running
            # the compare-and-swap again, the other is a commit that is real and
            # local and simply has not landed.
            #
            # Told apart by ASKING GIT rather than by reading the message. The
            # first version matched on the text and was wrong within the hour:
            # real GitHub over HTTPS says "cannot push non-fastforwardable
            # reference" and a `file://` remote says "contains commits that are
            # not present locally", so the retry fired in production and never in
            # the tests. A fetch costs a round trip and this is the path where one
            # is worth paying — a push has already failed.
            try:
                self.fetch()
            except Exception as unreachable:
                # The remote is unreachable, and that is what failed — not the
                # push. Chained deliberately: the push error is the symptom and
                # this is the cause, and a runbook wants both.
                raise unreachable from None
            moved = self._remote_head()
            if moved is not None and not self._repo.descendant_of(self.head(), moved):
                raise _Rejected(
                    f"the remote is at {moved[:7]} and this is not on top of it"
                ) from None
            raise
        return True

    def _callbacks(self):
        """Credentials for the remote, minted per call.

        Per call and not per Store: an installation token lives under an hour and
        a server lives for weeks, so a credential fetched once at startup is a
        credential that stops working on a Tuesday afternoon with no deploy to
        blame. The token itself is cached behind this — see `GitHubApp.token`.
        """
        return self._credentials.callbacks() if self._credentials else None

    # -- writing ------------------------------------------------------------

    def put_asset(self, data: bytes, suffix: str, author: str) -> tuple[str, bool]:
        """Store bytes under a name derived from their content, and return it.

        Content-addressed, so the same file uploaded twice is the same path and
        the second upload writes nothing. An asset is never edited, so there is no
        base to compare against, nothing to merge, and no conflict that can exist
        — which is why this needs none of `write_all`'s compare-and-swap.

        It needs the rest of it. This took no lock and never pushed, and both were
        wrong in the same way: the commit existed only on this disk, so ONE image
        upload followed by anybody pushing to the plan by hand left local and
        remote genuinely forked — and from then on every write raised
        `StoreDiverged` for the life of the container. Not the first write. All of
        them, for ever, because nothing ever reconciled. The lock matters for a
        second reason now that writes run on a threadpool: concurrent with a save,
        libgit2 refuses the commit outright with "current tip is not the first
        parent".
        """
        name = f"assets/{hashlib.sha256(data).hexdigest()[:16]}{suffix}"
        with self._writing:
            if self._remote:
                self._absorb_remote()
            if self.read_asset(self.head(), name) is not None:
                return name, False
            blob = self._repo.create_blob(data)
            parent = self.head()
            tree = self._insert(self._tree(parent), name.split("/"), blob)
            who = pygit2.Signature(author, f"{author}@users.noreply.github.com")
            self._repo.create_commit(_BRANCH, who, _BOT, f"upload {name}", tree, [parent])
            # Through `_finish`, so an upload reaches the remote like every other
            # commit and an unreachable remote is reported rather than pretended
            # away. The name and "it is new" are what the caller wants; whether it
            # pushed is on the result `_finish` builds, which this discards — an
            # asset nobody can see yet is a broken image on one page, not a lost
            # record.
            self._finish(self.head(), "committed")
        return name, True

    def read_asset(self, commit: str, path: str) -> bytes | None:
        """The raw bytes. `read` decodes as UTF-8, which an image is not."""
        try:
            entry = self._repo[commit].tree[path]
        except KeyError:
            return None
        return entry.data if entry.type_str == "blob" else None

    def write(
        self, path: str, content: str, base_commit: str, author: str, message: str
    ) -> WriteResult:
        """One file, one commit. The overwhelming majority of writes here."""
        return self.write_all({path: content}, base_commit, author, message)

    def remove(
        self, path: str, base_commit: str, author: str, message: str
    ) -> WriteResult:
        """Take one file out of the plan, in a commit.

        `None` and not an empty string, which is a real file with nothing in it —
        and which `_merge` would treat as a record whose every field was cleared.
        That distinction is the subject of `_deleted` above; spelling a removal as
        empty content would put the bug it describes into the writer as well as
        into the merger.

        History is not touched. The commit removes the file from the tip, and
        `git log --follow` still has every version of it: deleting a record here
        is deleting it from the *plan*, not from the repository, which is the
        whole reason this tool keeps its data in git.
        """
        return self.write_all({path: None}, base_commit, author, message)

    def write_all(
        self, files: dict[str, str | None], base_commit: str, author: str, message: str
    ) -> WriteResult:
        """Several files in ONE commit, each compared-and-swapped on its own path.

        Written for promotion, which creates a record and marks the record it came
        from. Those are two files and one decision, and two commits would say two
        things that are not true: that somebody minted a pitch out of nowhere, and
        that somebody then separately edited a note. `git log` on a plan is the
        team's record of decisions, and one decision is one line of it.

        It also removes the half-done state. Written as two calls, the second can
        conflict after the first has landed — leaving a pitch in the plan and a
        note that does not know what it became, on a protected branch where the
        first commit cannot be taken back. There is no order of the two that fixes
        that; there is only not having two.

        The compare-and-swap is unchanged and still per path, which is the point:
        a promotion touches one brand-new file that nobody can have edited and one
        existing note, so the usual "somebody saved something else" case still
        retries silently and only a genuine overlap on the note itself refuses.
        A conflict on ANY path writes nothing at all — a partial commit is exactly
        the half-done state above, arriving through the other door.

        `write` is this function with one entry, so the swap logic exists once. It
        was copied in the first draft of promotion, which is how three lines of it
        came to disagree about which commit `stored` is read at.
        """
        with self._writing:
            # NO FETCH BEFORE THE WRITE. It was here so that "current" already
            # included whatever the remote had, and it cost a round trip on every
            # save whether or not the remote had moved — measured at about 600 ms
            # from a laptop, which was half of what a save cost at all.
            #
            # Optimistic instead: commit against local HEAD, push, and let the
            # push be the question. GitHub refuses a non-fast-forward and libgit2
            # raises `cannot push non-fastforwardable reference` — verified
            # against the real remote over HTTPS, not over `file://`, because the
            # two answer differently and only one of them is what runs in
            # production. `_retry` then rewinds, fetches, and runs this same loop
            # again against what actually landed.
            #
            # So the fetch happens when somebody else really did write, rather
            # than in the hope that they might have. Conflict SEMANTICS are
            # unchanged, because the retry re-runs this identical loop: what moves
            # is the tail latency of a collision, to about 1.8 s — which was until
            # today the price of every save, collision or not.
            return self._attempt(files, base_commit, author, message, tries=3)

    def _attempt(
        self,
        files: dict[str, str | None],
        base_commit: str,
        author: str,
        message: str,
        tries: int,
    ) -> WriteResult:
        """One pass of the compare-and-swap, and the retry when the push loses.

        Called with `self._writing` already held, and it calls itself, so the lock
        must stay non-reentrant-safe by never being taken again in here.
        """
        if True:
            current = self.head()
            resolved: dict[str, str] = {}
            outcomes: list[str] = []
            conflicts: list[str] = []
            for path, content in files.items():
                # Asked before the fast paths below, because both of them are
                # about a file that is still there. A removal of something
                # already gone slipped through the `was == stored` path — both
                # sides read `None`, which looks exactly like "somebody edited a
                # different file" — and committed a tree identical to its parent:
                # an empty commit, reported to the person who pressed Delete as
                # the sha that deleted the record.
                if content is None and self.read(current, path) is None:
                    conflicts.append(_already_gone(path))
                    continue
                if current == base_commit:
                    resolved[path] = content
                    outcomes.append("committed")
                    continue
                was, stored = self.read(base_commit, path), self.read(current, path)
                if was == stored:
                    # Somebody edited a different file. Nobody needs to hear.
                    resolved[path] = content
                    outcomes.append("retried")
                    continue
                # Deleted under us, and it must not come back. `_merge` is handed
                # `stored or ""`, so a deletion arrives looking exactly like an
                # empty frontmatter: every key nobody touched reads as "only they
                # moved it" and drops, the one key this write touched reads as
                # "only we moved it" and stays. A drag onto a record somebody had
                # just deleted therefore recreated it as a file holding nothing
                # but `parent:`, and answered 200. Parsing would not have caught
                # it — every field here is optional by design.
                # A removal has no third text to fall back on. `_merge` exists
                # because two edits to one file can often both be kept; a delete
                # and an edit cannot. Refused rather than merged, and refused
                # rather than quietly winning: the edit would otherwise be
                # committed and then thrown away without anybody reading it.
                if content is None:
                    conflicts.append(_changed_under_delete(path))
                    continue
                if was is not None and stored is None:
                    conflicts.append(_deleted(path))
                    continue
                merged, conflict = _merge(path, was or "", content, stored or "")
                if conflict is not None:
                    conflicts.append(conflict)
                    continue
                resolved[path] = merged
                outcomes.append("merged")
            if conflicts:
                return WriteResult(
                    commit=None, outcome="conflict", conflict="\n".join(conflicts)
                )
            # The most eventful thing that happened to any of them. A caller shown
            # "committed" for a set in which one file had to be merged has been
            # told the quiet half of what happened.
            worst = max(outcomes, key=_OUTCOMES.index, default="committed")
            before = self.head()
            made = self._commit(resolved, author, message)
            try:
                return self._finish(made, worst)
            except _Rejected:
                # Somebody else landed a commit between this HEAD and this push.
                # Rewind to where we started, take what they wrote, and run the
                # whole loop again against it — which is the same three-way merge
                # a pre-fetch would have done, arrived at from the other side.
                if tries <= 1:
                    # The same 409 they would have been given anyway. A remote
                    # moving faster than three attempts is not a conflict this can
                    # resolve by trying a fourth time.
                    self._repo.references[_BRANCH].set_target(before)
                    self._absorb_remote()
                    return WriteResult(
                        commit=None,
                        outcome="conflict",
                        conflict=_lost_the_race(sorted(files)),
                    )
                self._repo.references[_BRANCH].set_target(before)
                self._absorb_remote()
                return self._attempt(files, base_commit, author, message, tries - 1)

    def _absorb_remote(self) -> None:
        """Fast-forward onto anything the remote gained since the last write.

        An unreachable remote is not a reason to refuse the write: the commit is
        still made locally and reported as unpushed. Refusing would mean the
        tracker stops working whenever GitHub does.
        """
        try:
            self.fetch()
        except StoreDiverged:
            raise
        except Exception:
            return
        local, remote_head = self.head(), self._remote_head()
        if remote_head is None or remote_head == local:
            return
        if self._repo.descendant_of(remote_head, local):
            self._repo.references[_BRANCH].set_target(remote_head)
        elif not self._repo.descendant_of(local, remote_head):
            raise StoreDiverged(
                f"local {local[:7]} and remote {remote_head[:7]} have both moved; "
                "refusing to guess which commits to discard"
            )

    def _finish(self, commit: str, outcome: str) -> WriteResult:
        """Commit made. Try to push, and never claim success for a commit that is
        still only on this disk."""
        pushed = False
        if self._remote:
            try:
                pushed = self._send()
            except (StoreDiverged, _Rejected):
                # Both are answers about the plan rather than about the network,
                # and the caller has something to do with each: a rejection is
                # recoverable by rewinding and running the compare-and-swap again,
                # and a genuine fork is not recoverable at all. Swallowing either
                # into `pushed = False` would report a commit as merely unpushed
                # when it is in fact about to be retried, or about to be lost.
                raise
            except Exception:
                # The remote is unreachable. The commit is real and local; the
                # caller is told it has not landed rather than told nothing.
                pushed = False
        return WriteResult(commit=commit, outcome=outcome, pushed=pushed)

    def _commit(self, files: dict[str, str], author: str, message: str) -> str:
        parent = self.head()
        tree = self._tree(parent).id
        for path, content in files.items():
            # Read the tree back between files. Each insert rewrites the path's
            # spine from the bottom up and hands back a new root, so the second
            # file has to go into the root the first one produced — inserted into
            # the parent commit's instead, it writes a tree that has silently
            # dropped the first file, and the commit still succeeds.
            root = self._repo[tree].peel(pygit2.Tree)
            if content is None:
                tree = self._drop(root, path.split("/"))
                continue
            blob = self._repo.create_blob(content.encode("utf-8"))
            tree = self._insert(root, path.split("/"), blob)
        # Author is the person, committer is the bot: `git log --format='%an'` is
        # then a per-person audit trail for free, while a future push credential
        # stays a bot that no human's departure invalidates.
        who = pygit2.Signature(author, f"{author}@users.noreply.github.com")
        oid = self._repo.create_commit(_BRANCH, who, _BOT, message, tree, [parent])
        return str(oid)

    def _insert(self, tree, parts: list[str], blob) -> pygit2.Oid:
        """Rebuild the path's spine. TreeBuilder writes one tree, so nested paths
        have to be walked and rewritten from the bottom up."""
        builder = self._repo.TreeBuilder(tree) if tree is not None else self._repo.TreeBuilder()
        name, rest = parts[0], parts[1:]
        if not rest:
            builder.insert(name, blob, pygit2.enums.FileMode.BLOB)
        else:
            child = None
            if tree is not None and name in [entry.name for entry in tree]:
                entry = tree[name]
                if entry.type_str == "tree":
                    child = self._repo.get(entry.id)
            builder.insert(name, self._insert(child, rest, blob), pygit2.enums.FileMode.TREE)
        return builder.write()

    def _drop(self, tree, parts: list[str]) -> pygit2.Oid:
        """The same spine, rebuilt without this entry.

        Git has no empty directory: a tree with no entries is not something a
        commit can point a name at, and writing one produces a repository that
        `git fsck` complains about and that some clients refuse to read. So when
        removing the last record from `tasks/` empties it, the directory goes too
        — which is also what `git rm` does, and what a plan with no tasks in it
        should look like.
        """
        builder = self._repo.TreeBuilder(tree)
        name, rest = parts[0], parts[1:]
        if not rest:
            builder.remove(name)
            return builder.write()
        entry = tree[name] if name in [item.name for item in tree] else None
        child = self._repo.get(entry.id) if entry is not None and entry.type_str == "tree" else None
        if child is None:
            return builder.write()
        inner = self._drop(child, rest)
        if len(self._repo[inner]) == 0:
            builder.remove(name)
        else:
            builder.insert(name, inner, pygit2.enums.FileMode.TREE)
        return builder.write()

    def close(self) -> None:
        fcntl.flock(self._lock, fcntl.LOCK_UN)
        self._lock.close()


def last_edited_in(repo_path: Path) -> dict[str, int] | None:
    """`Store.last_edited`'s map for the repository at this path, or None when
    the path is not a repository at all.

    `openproj render` is documented to accept a plain directory of files, and a
    plan with no history has no last-edited to draw — None is the caller's cue
    to omit the time column entirely. Never file mtimes: they lie after every
    fresh clone.

    Read-only on purpose, not a `Store`: a Store drops `openproj.lock` into a
    directory somebody handed us to read, and refuses to run at all while a
    server holds the plan. HEAD rather than `refs/heads/main`, because an
    export is of whatever is checked out.
    """
    try:
        repo = pygit2.Repository(str(repo_path), RepositoryOpenFlag.NO_SEARCH)
    except pygit2.GitError:
        return None
    if repo.head_is_unborn:
        return None
    head = str(repo.head.target)
    return _stamps(repo, head, set(_tree_blobs(repo, head)))


def build_plan_repository(path: Path, files: dict[str, str], message: str) -> str:
    """A bare repository holding exactly these files, in one commit.

    Here rather than in `cli.py` because it is git, and `store.py` is where this
    application knows how git stores things. `openproj demo` is the only caller
    today; the alternative it replaces is six lines of shell in a README, which
    is a recipe nothing tests and everyone gets wrong once.

    Bare, and built with a `TreeBuilder`: `git init && git add .` needs an index
    and a working copy, and the whole argument of this module is that the server
    must have neither. The author is the bot, because nobody wrote these files
    into this repository — a demo is a copy, and attributing it to whoever ran
    the command would put a person's name on a commit they did not make.
    """
    repo = pygit2.init_repository(str(path), bare=True, initial_head="main")
    root: dict = {}
    for name, content in files.items():
        node = root
        *directories, leaf = name.split("/")
        for directory in directories:
            node = node.setdefault(directory, {})
        node[leaf] = content

    def tree(node: dict) -> pygit2.Oid:
        builder = repo.TreeBuilder()
        for name, value in node.items():
            if isinstance(value, dict):
                builder.insert(name, tree(value), pygit2.enums.FileMode.TREE)
            else:
                builder.insert(
                    name, repo.create_blob(value.encode("utf-8")), pygit2.enums.FileMode.BLOB
                )
        return builder.write()

    return str(repo.create_commit(_BRANCH, _BOT, _BOT, message, tree(root), []))
