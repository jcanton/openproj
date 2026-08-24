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
import logging
import os
import threading
import time
from difflib import SequenceMatcher
from pathlib import Path
from typing import Literal, NamedTuple

import pygit2
from pydantic import BaseModel
from pygit2.enums import DeltaStatus, RepositoryOpenFlag, SortMode
from ruamel.yaml import YAML

_LOG = logging.getLogger(__name__)

_BRANCH = "refs/heads/main"
_ORIGIN = "origin"
_TRACKING = "refs/remotes/origin/main"
# The newest commit this process has POSITIVELY confirmed the remote holds as
# part of our lineage — seeded the moment the store opens (a bare clone's tip
# came FROM the remote, so the remote demonstrably held it) and moved only by a
# successful push after that. Seeded at open because production boots into a
# fresh clone every time, and a guard armed only by the first push is off for
# exactly that window. Not the tracking ref: a fetch moves that to whatever the
# remote says today, and the whole point of this one is to notice when what the
# remote says today no longer contains what we saw it hold — the force-push
# guard (docs/deferred-push.md, recovery step 2).
_PUSHED = "refs/openproj/pushed"
# The recovery's scratch name for the rebased tip. A push refspec needs a ref on
# the local side, and the tip must reach the remote BEFORE refs/heads/main moves
# — so it cannot be main that names it.
_LANDING = "refs/openproj/landing"
# One local ref per parked commit, `refs/openproj/stranded-<sha>`. It is the
# push source for the branch of the same name on the remote, and it is deleted
# the moment that push is confirmed — so the glob over this prefix counts
# exactly the parked commits this container would still lose, the same
# philosophy as `unpushed`. On Cloud Run every local ref dies with the
# instance; the durable record of a parked commit is the remote branch, never
# this.
_STRANDED = "refs/openproj/stranded-"
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
    # Whether the commit has reached the remote — always False on a fresh write
    # now that the push has left the request path (docs/deferred-push.md); the
    # background pusher lands it and announces the landing itself. The meaning
    # is unchanged on purpose: on an ephemeral filesystem an unpushed commit is
    # a lost commit, and nothing may claim the remote holds one before it does.
    pushed: bool = False


class Condition(BaseModel):
    """Whether this store can write, and how much of it is only on this disk.

    Every field is read from refs on the local filesystem. Nothing here talks to
    the network, which is the whole point: a health answer that fetches is slow,
    fails when GitHub is slow, and answers a different question every time it is
    asked.
    """

    head: str
    # The newest commit this process has reason to believe the remote holds:
    # `refs/remotes/origin/main`, which libgit2 moves on a fetch AND on a
    # successful push. None when no remote is configured, or before anything has
    # fetched or pushed.
    remote: str | None
    # The tracking ref no longer contains `refs/openproj/pushed` — the remote
    # LOST a commit this process positively confirmed it held. Not
    # both-sides-moved: with the push off the request path that is the ordinary
    # recoverable race, and a flag that goes red on every hand-push is a flag
    # people learn to ignore (docs/deferred-push.md, "Health").
    diverged: bool
    # Commits on local `main` that `remote` does not hold: what this container
    # loses if it is replaced. `pushed: false` tells one caller about one write;
    # this is the same fact for the whole store, and the number a monitor watches.
    unpushed: int
    # Seconds since the oldest of those commits was written; None when nothing
    # is waiting. `unpushed` alone stopped meaning "at risk" the day saves
    # stopped pushing — it is briefly non-zero after EVERY save — so the alarm
    # is "non-zero and not draining", and this is the number that says so.
    oldest_unpushed_age: float | None
    # Parked commits whose branch has not yet been confirmed on the remote —
    # the glob over `refs/openproj/stranded-*`, see the note at `_STRANDED`.
    parked: int
    # The sentence, when there is one to say. Built by `_forked_message`, the
    # same wording for the same condition wherever it is met.
    refusal: str | None


class SyncOutcome(NamedTuple):
    """One pass of the background pusher, and everything a page needs to hear.

    Announced whole rather than as an event per commit, because confirmation
    cannot be "my sha is on main": recovery re-mints shas, so a client waiting
    to see its own answered sha on the branch would wait forever after any
    rejection (docs/deferred-push.md). One outcome names the tip that landed,
    every sha that changed name on the way, and every sha that could not land
    and where it went instead.
    """

    # The tip local main and the remote share after this pass — the "everything
    # up to X has landed" a page's mark-clearing needs. None when the pass did
    # not finish: unreachable, diverged, or nothing to do.
    landed: str | None
    # Original sha -> re-minted sha, for commits the recovery had to re-commit
    # onto what the remote actually held. Empty on the quiet day: the original
    # commits go up unchanged, so a client's answered sha is the sha that lands.
    remapped: dict[str, str]
    # (original sha, branch name) for commits that could not be replayed and
    # were parked on a branch on the remote instead of being dropped.
    parked: list[tuple[str, str]]
    # Which day it was. "idle": nothing to send. "landed": the backlog is on the
    # remote. "unreachable": the network failed, the backlog is intact, try
    # later. "diverged": the remote lost a commit we confirmed it held — a
    # genuine fork, never resolved automatically.
    state: Literal["idle", "landed", "unreachable", "diverged"]


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


def _diverged_message(local: str, remote: str) -> str:
    """The wording for `push`'s both-sides-moved refusal.

    It was written out twice — in `push` and in `_absorb_remote`, which the
    deferred push has since deleted. `Store.condition` used to read it too; its
    `refusal` now describes the force-push guard instead (`_forked_message`),
    because both-sides-moved stopped being the condition that wedges a store the
    day the recovery learned to replay through it.
    """
    return (
        f"local {local[:7]} and remote {remote[:7]} have both moved; "
        "refusing to guess which commits to discard"
    )


def _forked_message(confirmed: str, remote: str) -> str:
    """The one wording for the one condition that stops the pusher for good.

    Not `_diverged_message`: that sentence describes both-sides-moved, which the
    recovery now resolves on its own. This one is the force-push guard — the
    remote no longer contains a commit this process confirmed it held — and
    naming the lost commit is what makes a runbook writable from it.
    """
    return (
        f"the remote at {remote[:7]} no longer contains {confirmed[:7]}, which it "
        "was seen to hold; somebody rewrote history — refusing to replay onto it"
    )


def _stranded_refspec(sha: str) -> str:
    """Local parked ref to the remote branch of the same commit, for one push."""
    return f"{_STRANDED}{sha}:refs/heads/openproj/stranded-{sha}"


def _stranded_shas(repo: pygit2.Repository) -> list[str]:
    """Every parked commit whose branch is not yet confirmed on the remote."""
    return [
        name.removeprefix(_STRANDED)
        for name in repo.listall_references()
        if name.startswith(_STRANDED)
    ]


def _blob_at(repo: pygit2.Repository, commit: str, path: str) -> pygit2.Oid | None:
    """The id of the bytes at this path, or None — `Store.read` without the
    decode, because the replay's fast paths compare ids and never look inside."""
    node = repo[commit].tree
    for part in path.split("/"):
        if node.type_str != "tree":
            return None
        try:
            node = node / part
        except KeyError:
            return None
    return node.id if node.type_str == "blob" else None


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
    """Three-way line merge. Overlapping edits are a conflict, never a marker.

    Two edits collide if they overlap OR if they merely BEGIN on the same line,
    and the second half of that is not obvious. An insertion has an EMPTY span —
    `SequenceMatcher` reports inserting before line 3 as `(3, 3)` — so an
    insertion at line N and a replacement starting at line N satisfy neither
    `overlaps` (which needs `other_span[0] < span[1]`, and `3 < 3` is false) nor
    an equality test on the spans. They used to merge, and the assembly below
    could only keep one of them: `{*ours, *yours}` is a SET, both spans start at
    N, and whichever the set yields first sets `cursor` past the other, which is
    then skipped by the `cursor > span[0]` guard.

    Measured before the fix, on 4,000 generated same-start pairs: **48% lost a
    line**, silently, reported as `merged`. Half of those were the line already
    in git — so somebody's committed sentence was reverted by a save that was
    answered with a commit sha and no conflict. It is 2.8% of ALL merges, which
    is how it went unnoticed.

    Widening to "begins at the same line" is a strict superset of the old test,
    so nothing that used to refuse now merges. What changes is that some saves
    which used to merge — the half where the set order happened to keep both —
    are refused instead. That is the right direction and it is the whole trade:
    **a refusal is announced and a drop is not.**

    The same trade, made a second time and for the same reason: the convergence
    clause compared the replacement TEXT and not the span, so two edits that
    overlap, cover different numbers of lines and write the same words skipped
    the check and fell into the assembly loop, where a set decided which of them
    survived. `base a b c d`, mine replacing `b c` with `X` and theirs replacing
    `b c d` with `X`, merged to `a X d` and said nothing: the line theirs
    deleted was back. Identity is now the span and the text together.

    The alternative was to fix the assembly loop to keep both spans, which is
    what you actually want and is not available here: it means deciding an order
    between two edits at one point, which is what a CRDT is for and what a line
    merge cannot do. Getting that silently wrong is worse than refusing, and
    every other write path in this file rests on this function.
    """
    base_lines = base.splitlines(True)
    mine_lines, theirs_lines = mine.splitlines(True), theirs.splitlines(True)
    ours, yours = _changes(base_lines, mine_lines), _changes(base_lines, theirs_lines)

    conflicts = []
    for span, replacement in ours.items():
        for other_span, other_replacement in yours.items():
            overlaps = span[0] < other_span[1] and other_span[0] < span[1]
            # Not `span == other_span`: an insertion's span is empty, so an
            # insertion and a replacement that begin on one line are a collision
            # the equality missed. See the docstring.
            same_start = span[0] == other_span[0]
            # `(span, replacement)` and not `replacement` alone. The clause is
            # here so two people who made the IDENTICAL edit converge instead of
            # colliding, and identity is the span as well as the text: two edits
            # that overlap, cover different numbers of lines and happen to write
            # the same words are not one edit, and skipping them dropped one of
            # them. `base a b c d`, mine replacing `b c` with `X` and theirs
            # replacing `b c d` with `X`, answered `a X d` with no conflicts —
            # the line theirs deleted, back, reported as merged and committed
            # with a sha. Which is the failure this whole function was rewritten
            # for, arriving through the one door the guard left open.
            same_edit = (span, replacement) == (other_span, other_replacement)
            if (overlaps or same_start) and not same_edit:
                stored_text = "".join(other_replacement).strip()
                yours_text = "".join(replacement).strip()
                # An empty span is an insertion BEFORE a line, and rendering it
                # as a range printed `lines 4-3` — a span that reads backwards,
                # in the one sentence somebody gets when their save is refused.
                where = (
                    f"before line {span[0] + 1}"
                    if span[0] == span[1]
                    else f"lines {span[0] + 1}-{span[1]}"
                )
                conflicts.append(
                    f"  {where}: stored {stored_text!r} · yours {yours_text!r}"
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

    Its own type and not a bare `Exception`, because the two ways a push fails
    want opposite answers. An unreachable remote is a commit that is real and
    local and still in the backlog, worth sending unchanged when the network
    comes back. A rejection means somebody else's commit is on the remote and
    ours is not a descendant of it — recoverable only by replaying the backlog
    onto what actually landed (docs/deferred-push.md), which is the pusher's
    job and never the request's.
    """


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
    """Structured merge of one record file. Returns (merged_text, conflict_report)."""
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


def _verdict(
    path: str, was: str | None, mine: str | None, stored: str | None
) -> tuple[str | None, str | None]:
    """One path's fate against the tip: (resolved_text, conflict_sentence).

    `was` is the file at the caller's base, `mine` what the caller wants it to
    say — None to remove it — and `stored` what the tip holds now. At most one
    side of the answer is not None; a resolved text of None with no conflict
    means the proposal stands exactly as proposed, which for a removal is the
    drop going ahead.

    Extracted from `_attempt`'s loop so the deferred-push replay can re-drive a
    commit's per-path delta through the SAME decision a save makes. Two copies
    of this ladder would let write-time and replay-time conflict semantics
    drift apart, and an invariant written twice will be guarded once. What does
    NOT live here is the write path's wording around the result — the outcome
    labels, the already-gone courtesy, the fresh-base fast path — because the
    replay has nobody to say any of it to.
    """
    if was == stored:
        # Somebody edited a different file. Nobody needs to hear.
        return mine, None
    # A removal has no third text to fall back on. `_merge` exists because two
    # edits to one file can often both be kept; a delete and an edit cannot.
    # Refused rather than merged, and refused rather than quietly winning: the
    # edit would otherwise be committed and then thrown away without anybody
    # reading it.
    if mine is None:
        return None, _changed_under_delete(path)
    # Deleted under us, and it must not come back. `_merge` is handed
    # `stored or ""`, so a deletion arrives looking exactly like an empty
    # frontmatter: every key nobody touched reads as "only they moved it" and
    # drops, the one key this write touched reads as "only we moved it" and
    # stays. A drag onto a record somebody had just deleted therefore recreated
    # it as a file holding nothing but `parent:`, and answered 200. Parsing
    # would not have caught it — every field here is optional by design.
    if was is not None and stored is None:
        return None, _deleted(path)
    merged, conflict = _merge(path, was or "", mine, stored or "")
    if conflict is not None:
        return None, conflict
    return merged, None


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
        which is every test and every development run. One that also has an
        `offer_pull_request` — `GitHubApp` does — is how a parked branch becomes
        a pull request; without it the branch simply goes unannounced."""
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
        # The background pusher's poke, set by every commit. An Event and not a
        # queue: the pusher reads the whole backlog from refs each time it runs,
        # so a burst of saves coalesces into one wake and there is nothing to
        # drain, replay or lose when wakes overlap.
        self.dirty = threading.Event()
        # Why each parked commit could not replay, by sha — the sentences that
        # become its pull request's body once the branch is confirmed on the
        # remote. In memory only, on purpose: the local stranded refs die with
        # the instance anyway (see `_STRANDED`), and an offer for a branch a
        # previous life parked falls back to pointing at that pass's log.
        self._parked_reasons: dict[str, list[str]] = {}
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
        # Where the branch stood when this process took it over — read after the
        # flock, so it is the tip nobody else can be moving. It is the floor
        # `condition` counts unpushed commits from when there is no tracking ref
        # to count from: a bare clone's tip came FROM the remote, so counting the
        # history behind it as "at risk" would answer `unpushed: 347` on a healthy
        # cold start and teach everybody to ignore the number. It also bounds that
        # revwalk to the commits this process made rather than to the size of the
        # plan's history, which is what keeps a health check cheap.
        # `.get`, not `head()`, because a plan repository that has never been
        # committed to has no `refs/heads/main` at all and `head()` raises a
        # `KeyError` on it. That is not an error state: `pygit2.init_repository`
        # gives an unborn branch, which is what a brand-new plan and every
        # `create_app` against a fresh bare repo start from. `condition` treats
        # `None` as "no floor to count from", which is the truth — there are no
        # commits to be at risk.
        opened = pygit2.Repository(str(self._path))
        born = opened.references.get(_BRANCH)
        self._opened_at = str(born.target) if born else None
        # The force-push guard is armed HERE, not by the first successful push.
        # Armed only then, it was off in exactly the state every production
        # instance boots into — `deploy/boot.py` clones the plan fresh onto an
        # in-memory disk on every cold start — and in that window a force-pushed
        # remote was silently healed: the backlog replayed onto the rewritten
        # history, local main swapped onto it, and a commit the remote provably
        # held gone from every main with health still green. The seed is sound
        # by the same argument the `unpushed` floor makes above: a bare clone's
        # tip came FROM the remote, so the remote demonstrably held it. The
        # tracking ref, when it exists, is the same confirmation made later — a
        # fetch or push moved it to what the remote said — so it wins over the
        # older opening tip. An existing guard ref is a previous life's positive
        # confirmation and is never overwritten by inference.
        if remote and opened.references.get(_PUSHED) is None:
            tracking = opened.references.get(_TRACKING)
            confirmed = str(tracking.target) if tracking else self._opened_at
            if confirmed is not None:
                opened.references.create(_PUSHED, confirmed)

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
        the record save: a restored draft carries the commit it was drafted
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
        their cached stamp. When it is NOT an ancestor — which stays routine,
        not a force-push story: a rejected push is recovered by replaying
        local-only commits onto what the remote holds and swapping the branch
        to the re-minted tip (docs/deferred-push.md), and the old tip is no
        ancestor of the new one — the map is discarded and rebuilt from
        scratch. Retract-by-rebuild is the whole correctness story: there is no
        retraction logic to get wrong, it
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
    # exist. The push is the background pusher's job, off the request path:
    # nothing inside `_writing` touches the network at all, because a save that
    # waits for GitHub costs GitHub's latency — measured at ~1.5s of a ~2s
    # request (docs/deferred-push.md).

    def _remote_head(self) -> str | None:
        repo = pygit2.Repository(str(self._path))
        reference = repo.references.get(_TRACKING)
        return str(reference.target) if reference else None

    def condition(self) -> Condition:
        """Can this store write, and how much of it is only on this disk.

        **Two local refs and no network.** `refs/heads/main` against
        `refs/remotes/origin/main` is the same comparison `push` makes before
        it refuses, so this is not a second opinion about the wedge — it is
        that opinion, read from outside the lock. Adding a fetch here would
        make the answer slow, make it fail when GitHub does, and make it a
        different question every time somebody asked it.

        **It reports the condition as of the last push or fetch, and that is
        the right window.** The tracking ref only moves when something fetches
        or pushes, so a fork that happened thirty seconds ago is invisible
        until the pusher next tries to land the backlog. That is not a gap to
        close: "can this service push" is answerable only by having tried, and
        the alternative is a health route that goes red because somebody else's
        push is in flight.

        **There is nothing to clear, which is the point.** This is a reading of
        the world, not a memory of an event. It goes false the moment a fetch
        teaches the process the histories forked, and true again the moment a
        fetch or a push teaches it they no longer have, because both answers
        ask these same two refs. A recorded flag cleared by "a successful write"
        would have to decide what counts as one: `PUT /api/icon` answers 200 for
        an icon that is already set without ever reaching the store, and clearing
        on that would report health in the middle of a total outage. A flag never
        cleared is worse still — it is cleared by restarting the container, and
        on Cloud Run a restart clears this by discarding the very commits
        `unpushed` is counting.

        No lock, and a fresh `Repository`: this is read while a save holds
        `_writing`, and a health check that waits behind a 600 ms push is a
        health check that reports the push.
        """
        repo = pygit2.Repository(str(self._path))
        parked = len(_stranded_shas(repo))
        born = repo.references.get(_BRANCH)
        if born is None:
            # A plan with no commits yet. `pygit2.init_repository` leaves
            # `refs/heads/main` absent until the first one, so this is what every
            # brand-new plan is for as long as it takes somebody to write a
            # record — and `references[...]` raises `KeyError` on it, which made
            # `/api/health` answer 500 on exactly the plan a first-time reader
            # points the tool at.
            #
            # Healthy, and honest: there is nothing committed, so there is
            # nothing unpushed and nothing to have diverged. `head` is empty
            # rather than invented, which is the same answer `store.head()`
            # would give if it could.
            return Condition(
                head="",
                remote=None,
                diverged=False,
                unpushed=0,
                oldest_unpushed_age=None,
                parked=parked,
                refusal=None,
            )
        local = str(born.target)
        if not self._remote:
            # A laptop. There is no remote to be ahead of, behind or beside, so
            # nothing is waiting to be pushed — `unpushed: 0` rather than the
            # whole history, which is what "not known to be on the remote" would
            # otherwise mean here.
            return Condition(
                head=local,
                remote=None,
                diverged=False,
                unpushed=0,
                oldest_unpushed_age=None,
                parked=parked,
                refusal=None,
            )
        reference = repo.references.get(_TRACKING)
        remote = str(reference.target) if reference else None
        # Not both-sides-moved: that is now the ordinary race the recovery
        # resolves, and it would go red on every hand-push. The wedge is the
        # remote no longer containing what this process CONFIRMED it held —
        # `refs/openproj/pushed`, seeded when the store opened and moved by each
        # successful push — the same comparison the recovery's force-push guard
        # makes, so the flag and the refusal cannot disagree about the same
        # repository. Absent only when nothing was ever confirmed (no remote, or
        # a branch unborn at open), which is the one state where False is the
        # honest answer rather than a blind spot: before the seed existed, this
        # read False for every fresh clone too — the whole boot-to-first-push
        # window in production — and health could not go red during precisely
        # the window the guard was needed.
        held = repo.references.get(_PUSHED)
        confirmed = str(held.target) if held else None
        diverged = (
            remote is not None
            and confirmed is not None
            and remote != confirmed
            and not repo.descendant_of(remote, confirmed)
        )
        walk = repo.walk(local, SortMode.NONE)
        floor = remote or self._opened_at
        if floor is not None:
            walk.hide(floor)
        unpushed, oldest = 0, None
        for commit in walk:
            unpushed += 1
            # The author's clock and not the committer's: the committer is
            # `_BOT`, one Signature minted at import, so its time is the
            # process's birth. The author Signature is minted per save, and the
            # age of the WORK is what the alarm is about — a replayed commit
            # keeps its author verbatim, so the age survives a re-mint too.
            when = commit.author.time
            oldest = when if oldest is None or when < oldest else oldest
        return Condition(
            head=local,
            remote=remote,
            diverged=diverged,
            unpushed=unpushed,
            oldest_unpushed_age=None if oldest is None else max(0.0, time.time() - oldest),
            parked=parked,
            refusal=(
                _forked_message(confirmed, remote) if diverged and confirmed and remote else None
            ),
        )

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
        # that can tell a genuine fork from a race. `_send` alone cannot: without
        # a fresh fetch, "local is not on top of the remote" is the ordinary
        # consequence of the remote having moved since this process last looked.
        # Somebody force-pushed, or a second writer existed, is what this is
        # about, and neither is recoverable by trying again.
        local, remote_head = self.head(), self._remote_head()
        # Equality first: `descendant_of(x, x)` is false — a commit is not its own
        # descendant — so a store with nothing to send looked exactly like a fork.
        if remote_head is not None and remote_head != local:
            if not self._repo.descendant_of(local, remote_head):
                raise StoreDiverged(_diverged_message(local, remote_head))
        return self._send()

    def _send(self) -> bool:
        """Push what the tracking ref already says is ahead.

        Split out of `push` when the write path still pushed: a save had just
        fetched, milliseconds earlier and inside the same lock, and then fetched
        again on the way out — THREE round trips to GitHub at about 600 ms each.
        The split survives the write path's departure because the pusher wants
        exactly this half: push without fetching, and let the rejection be the
        freshness question.

        Divergence is still caught, and caught properly; it is just not paid
        for on every push. If the remote moved, the push is rejected, and this
        fetches once and looks — so the fetch happens when it is needed rather
        than in the hope that it will be.
        """
        local, remote_head = self.head(), self._remote_head()
        if remote_head == local:
            return False
        # Not a fork — a race, and the difference decides whether anything can be
        # done about it. Without a pre-fetch, "local is not on top of the remote"
        # is the ORDINARY case: somebody pushed to the plan by hand since this
        # process last looked. Raising `StoreDiverged` here called that
        # unrecoverable, and it is the exact case the pusher's replay recovers
        # from (docs/deferred-push.md).
        #
        # A genuine fork — somebody force-pushed, or two writers existed — is
        # still caught where a fresh fetch exists to catch it: `push` checks
        # before sending, and the recovery guards before replaying. So the hard
        # answer is given by code that has fetched, rather than guessed here
        # from a tracking ref that is stale by design.
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
            # want opposite answers: one is recoverable by replaying the backlog
            # onto what actually landed, the other is a commit that is real and
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

    def sync(self) -> SyncOutcome:
        """The background pusher's one entry point: land local main on the remote.

        Runs on the pusher's thread with no lock held and works on a FRESH
        `pygit2.Repository`, never `self._repo` — pygit2 objects are not safe to
        share between threads, and a fresh handle per cross-thread reader is
        this file's own pattern.

        The quiet day: local level with the tracking ref means nothing to say,
        and local ahead means one push, sending the original commits under
        their original shas — a client's answered sha is the sha that lands,
        and sha instability exists only on the recovery path
        (docs/deferred-push.md). No fetch first: the rejection IS the freshness
        question, so a round trip to predict it would be the write path's old
        pre-fetch moved into the pusher, paid on every pass whether or not
        anybody else wrote. A rejected push goes to `_recover`; leftover parked
        refs — a branch whose push failed on an earlier pass — ride along on
        whatever push happens next, because re-sending a branch the remote
        already holds is a no-op and NOT re-sending one it lost is a commit
        gone for good.
        """
        quiet = SyncOutcome(landed=None, remapped={}, parked=[], state="idle")
        if not self._remote:
            return quiet
        repo = pygit2.Repository(str(self._path))
        born = repo.references.get(_BRANCH)
        if born is None:
            # An unborn branch has no commits to be at risk — the same answer
            # `condition` gives for the same repository.
            return quiet
        local = str(born.target)
        tracking = repo.references.get(_TRACKING)
        level = tracking is not None and str(tracking.target) == local
        leftovers = _stranded_shas(repo)
        if level and not leftovers:
            return quiet
        refspecs = [_stranded_refspec(sha) for sha in leftovers]
        if not level:
            refspecs.append(f"{_BRANCH}:{_BRANCH}")
        try:
            # A success moves the tracking ref too, which is what lets
            # `condition` answer `unpushed: 0` and the next pass answer "idle"
            # without holding a conversation with the remote.
            repo.remotes[_ORIGIN].push(refspecs, callbacks=self._callbacks())
        except Exception:
            # A refusal and an unreachable host arrive as the same class, and
            # they want opposite answers — told apart by asking git, never by
            # reading the message, for `_send`'s reason: `file://` and HTTPS
            # word the refusal differently.
            try:
                repo.remotes[_ORIGIN].fetch(callbacks=self._callbacks())
            except Exception:
                # The backlog is real, local, and worth sending unchanged when
                # the network comes back — nothing rewound, nothing re-minted,
                # the pusher backs off and asks again.
                return SyncOutcome(landed=None, remapped={}, parked=[], state="unreachable")
            moved = repo.references.get(_TRACKING)
            if (
                moved is None
                or str(moved.target) == local
                or repo.descendant_of(local, str(moved.target))
            ):
                # The remote is reachable and NOT ahead, so the failure was not
                # a rejection — a hiccup worth the same patient retry.
                return SyncOutcome(landed=None, remapped={}, parked=[], state="unreachable")
            return self._recover(repo, local, str(moved.target))
        self._settle(repo, leftovers)
        repo.references.create(_PUSHED, local, force=True)
        return SyncOutcome(
            landed=local,
            remapped={},
            parked=[(sha, f"openproj/stranded-{sha}") for sha in leftovers],
            state="landed",
        )

    def _recover(self, repo: pygit2.Repository, local: str, remote_tip: str) -> SyncOutcome:
        """The push was rejected: replay the backlog onto what the remote holds.

        The seven steps of docs/deferred-push.md's "Recovery, when the push is
        rejected", in order. Everything here runs WITHOUT `_writing` except the
        swap at the end, and the swap does no network — the lock is never held
        across a conversation with the remote.
        """
        nothing = SyncOutcome(landed=None, remapped={}, parked=[], state="unreachable")
        # Step 2, the force-push guard, before anything is replayed. A remote
        # that no longer contains what this process confirmed it held did not
        # merely move — it LOST a commit, and replaying onto rewritten history
        # would launder the rewrite into ordinary-looking commits. Genuine
        # forks are a person's to resolve, never resolved automatically.
        # `__init__` seeds the ref whenever a remote is configured, so absent
        # here means the branch was unborn when the store opened: the remote
        # never held any of our lineage, everything local is this process's own
        # re-drivable work, and replaying it onto whatever the remote grew is
        # the ordinary recovery, not a laundered rewrite.
        confirmed = repo.references.get(_PUSHED)
        if confirmed is not None:
            held = str(confirmed.target)
            if held != remote_tip and not repo.descendant_of(remote_tip, held):
                return SyncOutcome(landed=None, remapped={}, parked=[], state="diverged")
        # Steps 3-5: oldest first, each commit's own delta re-driven onto the
        # growing tip. A parked commit never joins the tip, so the commits
        # behind it replay against a tree that LACKS it — overlapping edits
        # park in turn rather than silently reintroducing the refused change.
        remapped: dict[str, str] = {}
        parked: list[tuple[str, str]] = []
        tip = remote_tip
        for commit in self._local_only(repo, local, remote_tip):
            advanced, refusals = self._replay_one(repo, commit, tip)
            if refusals:
                parked.append((str(commit.id), self._park(repo, commit, refusals)))
                continue
            if advanced != tip:
                remapped[str(commit.id)] = advanced
                tip = advanced
        # Step 6: the rebased tip and every parked branch, in ONE push, BEFORE
        # local main moves. The person's content is durable on GitHub before
        # anything claims otherwise — a crash after this push loses nothing.
        # `carrying` re-reads the refs rather than using this pass's parked
        # list, so a branch stranded by an earlier failed pass rides along too.
        carrying = _stranded_shas(repo)
        refspecs = [_stranded_refspec(sha) for sha in carrying]
        if tip != remote_tip:
            repo.references.create(_LANDING, tip, force=True)
            refspecs.append(f"{_LANDING}:{_BRANCH}")
        if refspecs:
            try:
                self._land(repo, refspecs)
            except Exception:
                # Unreachable mid-recovery, or a hand-push won another race: the
                # next pass simply recovers again, and it converges — replaying
                # an already-applied delta is a no-op, and hand-pushes arrive at
                # human rate. Local main was never touched, so nothing is lost.
                return nothing
        self._settle(repo, carrying)
        repo.references.create(_PUSHED, tip, force=True)
        if repo.references.get(_LANDING) is not None:
            repo.references.delete(_LANDING)
        durable = tip
        # Step 7: only now take the lock, replay the stragglers — commits made
        # while the recovery ran, pure local tree work — and move the branch.
        # This is the arm the adversary attacked: a straggler that conflicts
        # here parks exactly like the main loop's, because nothing may be
        # dropped merely because it arrived late.
        late: list[str] = []
        with self._writing:
            for straggler in self._local_only(repo, self.head(), local):
                advanced, refusals = self._replay_one(repo, straggler, tip)
                if refusals:
                    parked.append((str(straggler.id), self._park(repo, straggler, refusals)))
                    late.append(str(straggler.id))
                    continue
                if advanced != tip:
                    remapped[str(straggler.id)] = advanced
                    tip = advanced
            # The swap. Not a rewind: every commit leaving main is re-minted on
            # the new tip, convergent with it, or parked on a branch the remote
            # holds — and the stragglers were replayed under this same lock, so
            # nothing can have landed between the walk above and this move.
            repo.references[_BRANCH].set_target(tip)
        # Push again if the swap added anything — replayed stragglers ride on
        # main now, parked ones on their branches. A failure here is the one
        # place the outcome is mixed: the first batch IS durable, so `landed`
        # says so, and "unreachable" is what sends the pusher back to retry the
        # remainder, which the leftover-carrying above then heals.
        refspecs = [_stranded_refspec(sha) for sha in late]
        if tip != durable:
            refspecs.append(f"{_BRANCH}:{_BRANCH}")
        if refspecs:
            try:
                self._land(repo, refspecs)
            except Exception:
                return SyncOutcome(
                    landed=durable, remapped=remapped, parked=parked, state="unreachable"
                )
            self._settle(repo, late)
            repo.references.create(_PUSHED, tip, force=True)
        return SyncOutcome(landed=tip, remapped=remapped, parked=parked, state="landed")

    def _local_only(
        self, repo: pygit2.Repository, tip: str, floor: str
    ) -> list[pygit2.Commit]:
        """The commits reachable from `tip` and not from `floor`, oldest first.

        Oldest first because each replay's delta is against its own parent, so a
        commit must find its predecessors' work already folded into the tip it
        lands on — the same order the branch itself tells the story in.
        """
        walker = repo.walk(repo[tip].id, SortMode.TOPOLOGICAL | SortMode.REVERSE)
        walker.hide(repo[floor].id)
        return list(walker)

    def _replay_one(
        self, repo: pygit2.Repository, commit: pygit2.Commit, onto: str
    ) -> tuple[str, list[str]]:
        """Re-drive one commit's per-path delta onto `onto`: (tip, refusals).

        The delta is the commit against ITS OWN PARENT, never its whole tree: a
        whole tree carries every earlier commit's content with it, and if one of
        those was just parked, replaying the tree would silently reintroduce the
        refused edit under somebody else's sha.

        Blob ids settle the cheap cases without decoding — identical means a
        convergent edit and is skipped, unchanged-since-base takes ours, and
        both are what let a binary asset replay at all. Everything else decodes
        and goes through `_verdict`, the SAME ladder a save uses, so write-time
        and replay-time conflict semantics cannot drift.

        A non-empty refusal list means the WHOLE commit parks: `write_all` is
        atomic — a conflict on any path writes nothing — and a partial replay
        would be the half-done promotion arriving through yet another door. An
        identical resulting tree mints nothing, because an empty commit on the
        decision log says a decision was made when none was.
        """
        if commit.parents:
            base_tree = commit.parents[0].tree
        else:
            base_tree = repo[repo.TreeBuilder().write()]
        resolved: dict[str, pygit2.Oid | None] = {}
        refusals: list[str] = []
        for delta in base_tree.diff_to_tree(commit.tree).deltas:
            path = delta.new_file.path or delta.old_file.path
            was_oid = None if delta.status == DeltaStatus.ADDED else delta.old_file.id
            mine_oid = None if delta.status == DeltaStatus.DELETED else delta.new_file.id
            stored_oid = _blob_at(repo, onto, path)
            if mine_oid == stored_oid:
                # Convergent: the tip already says what this commit wanted —
                # including a file both sides deleted. Nothing to mint.
                continue
            if was_oid == stored_oid:
                # Untouched since our base: take ours, bytes for bytes.
                resolved[path] = mine_oid
                continue
            try:
                was = repo[was_oid].data.decode("utf-8") if was_oid is not None else None
                mine = repo[mine_oid].data.decode("utf-8") if mine_oid is not None else None
                stored = (
                    repo[stored_oid].data.decode("utf-8") if stored_oid is not None else None
                )
            except UnicodeDecodeError:
                # Three genuinely different byte states and at least one is not
                # text: there is no line merge to run. Content-addressed assets
                # cannot get here — same bytes are the same path — so this is a
                # hand-committed binary, and it parks rather than crashing the
                # pusher's thread.
                refusals.append(
                    f"{path} — changed on both sides and not text, so there is no merge to run."
                )
                continue
            text, refusal = _verdict(path, was, mine, stored)
            if refusal is not None:
                refusals.append(refusal)
                continue
            resolved[path] = (
                repo.create_blob(text.encode("utf-8")) if text is not None else None
            )
        if refusals or not resolved:
            return onto, refusals
        tree = repo[onto].tree.id
        for path, blob in resolved.items():
            root = repo[tree]
            if blob is None:
                tree = self._drop(repo, root, path.split("/"))
            else:
                tree = self._insert(repo, root, path.split("/"), blob)
        if tree == repo[onto].tree.id:
            return onto, []
        # `ref=None`, so no branch moves until the swap. The original author
        # signature verbatim — person, clock and all — the bot as committer,
        # the message unchanged: `git log --format='%an'` stays a per-person
        # audit trail across a re-mint (invariant 4).
        minted = repo.create_commit(
            None, commit.author, _BOT, commit.message, tree, [repo[onto].id]
        )
        return str(minted), []

    def _park(self, repo: pygit2.Repository, commit: pygit2.Commit, refusals: list[str]) -> str:
        """A commit that cannot replay goes to a branch, never away.

        The conflict has no user attached — the 200 went out long ago — so the
        original commit is named by a local `refs/openproj/stranded-<sha>` ref,
        pushed to the branch of the same name on the remote, which cannot be
        rejected because the ref does not exist there yet. The refusals are
        logged for the operator now and become the pull request's body later;
        the branch is the durability and the PR is only the visibility.
        """
        sha = str(commit.id)
        repo.references.create(f"{_STRANDED}{sha}", sha, force=True)
        # Kept by sha for the pull request's body: the offer happens only once
        # the branch push is confirmed, and by then the sentences naming the
        # disagreement exist nowhere else.
        self._parked_reasons[sha] = refusals
        _LOG.warning(
            "parked %s on openproj/stranded-%s — it could not be replayed:\n%s",
            sha[:7],
            sha,
            "\n".join(refusals),
        )
        return f"openproj/stranded-{sha}"

    def _settle(self, repo: pygit2.Repository, shas: list[str]) -> None:
        """These parked commits' branches are on the remote now: drop the local
        refs, then offer each branch as a pull request.

        Deleting is what keeps `condition().parked` honest — the count is "what
        this container would still lose", and a branch the remote holds is not
        that — and it is what lets `sync` know, without a conversation with the
        remote, that a would-be-idle pass still has parked branches to send:
        any ref under the prefix IS one.

        The offer rides in the same function because it and the deletion are
        one transition — "confirmed durable" — and a push path that settled in
        one place and announced in another would eventually do only half.
        Every caller is on the pusher's thread with `_writing` NOT held, which
        is where a conversation with the network belongs.
        """
        for sha in shas:
            name = f"{_STRANDED}{sha}"
            if repo.references.get(name) is not None:
                repo.references.delete(name)
        self._offer_pull_requests(repo, shas)

    def _offer_pull_requests(self, repo: pygit2.Repository, shas: list[str]) -> None:
        """Best-effort visibility for branches that are already durable.

        The credentials object may not know how to open one — None on a
        laptop, a plain callbacks-only stub in a test — and that is silence,
        not an error: a branch nobody can announce is still a branch. A
        refusal from GitHub — the 403 of a revoked `pull_requests: write`, an
        outage — is logged and swallowed, per branch so one failure does not
        silence the next: the branch is the durability and the PR is only the
        visibility (docs/deferred-push.md), and a pusher thread that dies over
        an announcement stops landing everybody's commits.
        """
        offer = getattr(self._credentials, "offer_pull_request", None)
        for sha in shas:
            # Popped even when nobody can be told: a settled branch is never
            # offered again, and a dict that only grows is a leak.
            reasons = self._parked_reasons.pop(sha, None)
            if offer is None:
                continue
            commit = repo[sha]
            message = commit.message.strip()
            summary = message.splitlines()[0] if message else sha[:7]
            why = "\n".join(
                reasons
                or [
                    "It could not be replayed onto what the remote holds; the exact "
                    "refusals were logged by the pass that parked it."
                ]
            )
            body = (
                f"{commit.author.name}'s commit {sha} could not be replayed onto what "
                "the remote holds, so it is parked here rather than lost.\n\n"
                f"Why it could not be replayed:\n\n{why}\n\n"
                "Merge this branch once the disagreement is resolved, or close it if "
                "what the plan now says should stand."
            )
            try:
                offer(
                    branch=f"openproj/stranded-{sha}",
                    title=f"Stranded: {summary}",
                    body=body,
                )
            except Exception:
                _LOG.warning(
                    "could not open a pull request for openproj/stranded-%s — the commit "
                    "is safe on that branch; only the announcement failed",
                    sha,
                    exc_info=True,
                )

    def _land(self, repo: pygit2.Repository, refspecs: list[str]) -> None:
        """Everything a recovery sends, in one push.

        The recovery's only conversation with the remote, and one call rather
        than one per ref on purpose: the parked branches and the rebased tip
        must be durable on GitHub together, BEFORE local main moves — a crash
        between two pushes would leave an acknowledged commit reachable from no
        ref the remote holds.
        """
        repo.remotes[_ORIGIN].push(refspecs, callbacks=self._callbacks())

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

        It needs the lock. This once took none, and concurrent with a save on
        the threadpool libgit2 refuses the commit outright with "current tip is
        not the first parent". The `_absorb_remote()` that used to open this
        block went with the deferred push: it existed because an unpushed asset
        commit had nothing else to reconcile it — one upload plus one hand-push
        to the plan left the histories forked for the life of the container —
        and the pusher now reconciles every commit, this one included. Nothing
        inside `_writing` touches the network any more, anywhere in this file.
        """
        name = f"assets/{hashlib.sha256(data).hexdigest()[:16]}{suffix}"
        with self._writing:
            if self.read_asset(self.head(), name) is not None:
                return name, False
            blob = self._repo.create_blob(data)
            parent = self.head()
            tree = self._insert(self._repo, self._tree(parent), name.split("/"), blob)
            who = pygit2.Signature(author, f"{author}@users.noreply.github.com")
            self._repo.create_commit(_BRANCH, who, _BOT, f"upload {name}", tree, [parent])
            # Through `_finish`, so an upload pokes the pusher and joins the
            # same backlog as every other commit. The name and "it is new" are
            # what the caller wants; the result `_finish` builds is discarded —
            # an upload the remote does not hold yet is a broken image on one
            # page, not a lost record.
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
            # NO NETWORK IN HERE. The pre-fetch went first — it cost a round
            # trip on every save whether or not the remote had moved, about
            # 600 ms from a laptop — and the push has now followed it out
            # (docs/deferred-push.md): a save commits against local HEAD and
            # answers, and the background pusher lands the branch on its own
            # clock. Remote staleness is the pusher's problem; the
            # compare-and-swap below keeps handling browser-side staleness — a
            # `base_commit` older than HEAD — exactly as it always has.
            return self._attempt(files, base_commit, author, message)

    def _attempt(
        self,
        files: dict[str, str | None],
        base_commit: str,
        author: str,
        message: str,
    ) -> WriteResult:
        """One pass of the compare-and-swap, against the local tip.

        Called with `self._writing` already held, and nothing in here may take
        it again — the lock is deliberately non-reentrant. The `_Rejected` retry
        that used to live here — rewind to the head captured before the commit,
        absorb the remote, run again — went with the push itself: a rewind was
        sound only while the lock spanned both the commit and the push, and once
        the push is deferred, `set_target(before)` would discard commits other
        people made after the one being retried. Nothing rewinds
        `refs/heads/main` any more; a rejected push is the pusher's to recover,
        by replay (docs/deferred-push.md).
        """
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
            text, refusal = _verdict(path, was, content, stored)
            if refusal is not None:
                conflicts.append(refusal)
                continue
            resolved[path] = text
            # The label repeats the ladder's first comparison rather than
            # coming back with the verdict, because it is wording and not a
            # guard: nothing is decided by it, and `_verdict`'s other
            # caller, the replay, has no outcome to report to anybody.
            outcomes.append("retried" if was == stored else "merged")
        if conflicts:
            return WriteResult(
                commit=None, outcome="conflict", conflict="\n".join(conflicts)
            )
        # The most eventful thing that happened to any of them. A caller shown
        # "committed" for a set in which one file had to be merged has been
        # told the quiet half of what happened.
        worst = max(outcomes, key=_OUTCOMES.index, default="committed")
        made = self._commit(resolved, author, message)
        return self._finish(made, worst)

    def _finish(self, commit: str, outcome: str) -> WriteResult:
        """Commit made; answer now, and poke the pusher.

        The push that lived here was ~1.5s of a ~2s save — GitHub's server-side
        time, none of it ours to make faster (docs/deferred-push.md) — so the
        request stops paying for it. `pushed=False` is the truth at this moment,
        not pessimism: the commit is real, local, and in the pusher's backlog,
        and nothing may say the remote holds it before the remote does.
        """
        self.dirty.set()
        return WriteResult(commit=commit, outcome=outcome, pushed=False)

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
                tree = self._drop(self._repo, root, path.split("/"))
                continue
            blob = self._repo.create_blob(content.encode("utf-8"))
            tree = self._insert(self._repo, root, path.split("/"), blob)
        # Author is the person, committer is the bot: `git log --format='%an'` is
        # then a per-person audit trail for free, while a future push credential
        # stays a bot that no human's departure invalidates.
        who = pygit2.Signature(author, f"{author}@users.noreply.github.com")
        oid = self._repo.create_commit(_BRANCH, who, _BOT, message, tree, [parent])
        return str(oid)

    def _insert(self, repo: pygit2.Repository, tree, parts: list[str], blob) -> pygit2.Oid:
        """Rebuild the path's spine. TreeBuilder writes one tree, so nested paths
        have to be walked and rewritten from the bottom up.

        `repo` is a parameter and not `self._repo` because the replay builds
        trees on the pusher's own fresh handle (invariant: the pusher never
        touches the shared one), while the write path passes the shared handle
        it has always used."""
        builder = repo.TreeBuilder(tree) if tree is not None else repo.TreeBuilder()
        name, rest = parts[0], parts[1:]
        if not rest:
            builder.insert(name, blob, pygit2.enums.FileMode.BLOB)
        else:
            child = None
            if tree is not None and name in [entry.name for entry in tree]:
                entry = tree[name]
                if entry.type_str == "tree":
                    child = repo.get(entry.id)
            builder.insert(name, self._insert(repo, child, rest, blob), pygit2.enums.FileMode.TREE)
        return builder.write()

    def _drop(self, repo: pygit2.Repository, tree, parts: list[str]) -> pygit2.Oid:
        """The same spine, rebuilt without this entry.

        Git has no empty directory: a tree with no entries is not something a
        commit can point a name at, and writing one produces a repository that
        `git fsck` complains about and that some clients refuse to read. So when
        removing the last record from `tasks/` empties it, the directory goes too
        — which is also what `git rm` does, and what a plan with no tasks in it
        should look like.
        """
        builder = repo.TreeBuilder(tree)
        name, rest = parts[0], parts[1:]
        if not rest:
            builder.remove(name)
            return builder.write()
        entry = tree[name] if name in [item.name for item in tree] else None
        child = repo.get(entry.id) if entry is not None and entry.type_str == "tree" else None
        if child is None:
            return builder.write()
        inner = self._drop(repo, child, rest)
        if len(repo[inner]) == 0:
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
