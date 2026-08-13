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
import io
import threading
from difflib import SequenceMatcher
from pathlib import Path
from typing import Literal

import pygit2
from pydantic import BaseModel
from ruamel.yaml import YAML

_BRANCH = "refs/heads/main"
_BOT = pygit2.Signature("openproj-bot", "openproj-bot@example.invalid")
_LOCK = "openproj.lock"


class WriteResult(BaseModel):
    commit: str | None
    outcome: Literal["committed", "retried", "merged", "conflict"]
    conflict: str | None = None


class StoreLocked(RuntimeError):
    """Another process already holds the writer lock on this repository."""


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


class Store:
    """One writer over one bare repository."""

    def __init__(self, repo_path: Path, remote: str | None = None) -> None:
        self._path = Path(repo_path)
        self._repo = pygit2.Repository(str(repo_path))
        self._remote = remote
        self._writing = threading.Lock()
        # An flock, not a flag: a second process must fail loudly rather than
        # interleave writes. Somebody will eventually try --workers 4.
        self._lock = open(self._path / _LOCK, "w")
        try:
            fcntl.flock(self._lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self._lock.close()
            raise StoreLocked(
                f"another openproj writer already holds {self._path}. "
                "Single-writer is a correctness invariant, not a preference."
            ) from exc

    # -- reading, always at an explicit commit ------------------------------

    def head(self) -> str:
        """Read the branch tip from disk, so an outside commit is visible at once."""
        return str(pygit2.Repository(str(self._path)).references[_BRANCH].target)

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
        found: list[str] = []

        def walk(tree, prefix: str) -> None:
            for entry in tree:
                name = f"{prefix}{entry.name}"
                if entry.type_str == "tree":
                    walk(self._repo.get(entry.id), f"{name}/")
                else:
                    found.append(name)

        walk(self._tree(commit), "")
        return sorted(found)

    # -- writing ------------------------------------------------------------

    def write(
        self, path: str, content: str, base_commit: str, author: str, message: str
    ) -> WriteResult:
        with self._writing:
            current = self.head()
            if current == base_commit:
                return WriteResult(commit=self._commit(path, content, author, message),
                                   outcome="committed")

            was = self.read(base_commit, path)
            stored = self.read(current, path)
            if was == stored:
                # Somebody edited a different file. Nobody needs to hear about it.
                return WriteResult(commit=self._commit(path, content, author, message),
                                   outcome="retried")

            merged, conflict = _merge(path, was or "", content, stored or "")
            if conflict is not None:
                return WriteResult(commit=None, outcome="conflict", conflict=conflict)
            return WriteResult(commit=self._commit(path, merged, author, message),
                               outcome="merged")

    def _commit(self, path: str, content: str, author: str, message: str) -> str:
        parent = self.head()
        blob = self._repo.create_blob(content.encode("utf-8"))
        tree = self._insert(self._tree(parent), path.split("/"), blob)
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

    def close(self) -> None:
        fcntl.flock(self._lock, fcntl.LOCK_UN)
        self._lock.close()
