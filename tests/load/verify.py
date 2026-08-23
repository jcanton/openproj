"""What the repository says happened, judged against what the run actually did.

This is the half of the harness that matters. A latency table says a service was
slow; this says whether it lost somebody's writing, and it answers that against
git rather than against the responses — because the whole class of defect this
audit is about is a response that says one thing and a repository that says
another.

Six questions, in the order they are worth asking:

1. **Is every character every co-editor typed in the final committed body?**
   Each co-editor owns a contiguous run behind its own anchor, so this is a
   substring test and not a guess. A run that is short is reported with how many
   characters landed and how many did not.
2. **Is every form writer's change committed, or was it explicitly refused?** A
   save answered 200 whose marker is not in the tree is LOST DATA and is
   reported as such. A 409 is not a loss — it is the compare-and-swap doing its
   job — and is counted separately. Anything else (a 5xx, a timeout, a dropped
   connection) is AMBIGUOUS and is reported with whether the marker landed
   anyway, because "the browser was shown a failure for a commit that is in git"
   and "the browser was shown a success for a commit that is not" are the two
   halves of the same defect and only the repository can tell them apart.
3. **Does any committed file contain a conflict marker?** In the final tree, and
   in every blob any commit in the run changed.
4. **Does local HEAD equal the bare origin's HEAD?** A commit that never pushed
   is a commit that dies with the instance — Cloud Run's filesystem is in memory
   and `--min-instances 0` tears the instance down when the service goes quiet.
   Divergence (neither head an ancestor of the other) is worse and is reported
   separately.
5. **Does `git fsck` pass**, on the plan and on the origin?
6. **Does the corpus still load through `model.load_repo` with zero
   `Unreadable`?** Against a real clone of the plan, because that is the
   question `openproj check` asks and the one a person with a terminal asks.

And two cheap self-checks of the harness itself, because a checker that passes
vacuously is worse than no checker: no commit may be authored by the `unsigned`
login (that would mean the cookies never verified and everybody was one person),
and every final `person_weeks` must be a value somebody actually sent (a merge
that invents one is a defect no marker would catch).
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

import harness

# Severities, ordered worst first. `LOST` is the only one that should ever stop a
# reader — everything else is a fact about the run.
LOST = "LOST DATA"
DIVERGED = "REPO DIVERGED"
BROKEN = "BROKEN"
AMBIGUOUS = "AMBIGUOUS"
NOTE = "note"
ORDER = {LOST: 0, DIVERGED: 1, BROKEN: 2, AMBIGUOUS: 3, NOTE: 4}


@dataclass
class Finding:
    severity: str
    what: str
    detail: object = None


@dataclass
class Verdict:
    findings: list[Finding] = field(default_factory=list)
    checks: dict = field(default_factory=dict)

    def say(self, severity: str, what: str, detail: object = None) -> None:
        self.findings.append(Finding(severity, what, detail))

    @property
    def lost(self) -> bool:
        return any(f.severity in (LOST, DIVERGED) for f in self.findings)

    @property
    def ok(self) -> bool:
        return not any(f.severity in (LOST, DIVERGED, BROKEN) for f in self.findings)

    def as_dict(self) -> dict:
        ordered = sorted(self.findings, key=lambda f: ORDER.get(f.severity, 9))
        return {
            "ok": self.ok,
            "lost_data": self.lost,
            "findings": [asdict(f) for f in ordered],
            "checks": self.checks,
        }


# -- the checks --------------------------------------------------------------


def _final_bodies(plan: Path, head: str) -> tuple[dict[str, str], dict[str, str]]:
    """`({id: file text}, {id: path})` at the tip."""
    paths = harness.record_paths(plan, head)
    return {i: (harness.read_blob(plan, head, p) or "") for i, p in paths.items()}, paths


def coedit_characters(verdict: Verdict, plan: Path, head: str, typed: list) -> None:
    files, _ = _final_bodies(plan, head)
    rows = []
    for one in typed:
        text = files.get(one.record, "")
        expected = one.expected
        anchor = one.anchor
        at = text.find(anchor)
        wanted = len(expected) - len(anchor)
        if at < 0:
            landed = 0
        else:
            tail = text[at + len(anchor) :]
            want = expected[len(anchor) :]
            landed = 0
            while landed < len(want) and landed < len(tail) and tail[landed] == want[landed]:
                landed += 1
        rows.append(
            {
                "who": one.who,
                "record": one.record,
                "typed": wanted,
                "committed": landed,
                "anchor_in_tree": at >= 0,
                "saves": one.saves,
                "trouble": one.trouble,
            }
        )
        if wanted and landed < wanted:
            verdict.say(
                LOST,
                f"{one.who} typed {wanted} characters into {one.record} and "
                f"{wanted - landed} of them are not in the plan",
                rows[-1],
            )
        for trouble in one.trouble:
            verdict.say(BROKEN, f"{one.who}: {trouble}")
    verdict.checks["coeditors"] = rows


def form_changes(verdict: Verdict, plan: Path, head: str, sent: list) -> None:
    files, _ = _final_bodies(plan, head)
    counts = {"committed": 0, "refused": 0, "lost": 0, "ambiguous_present": 0,
              "ambiguous_absent": 0, "refused_but_present": 0}
    lost, ambiguous = [], []
    for one in sent:
        text = files.get(one.record, "")
        present = one.marker in text
        accepted = one.status == "200" and one.outcome in ("committed", "merged", "retried")
        if accepted:
            if present:
                counts["committed"] += 1
            else:
                counts["lost"] += 1
                lost.append(asdict(one))
        elif one.status == "409":
            counts["refused"] += 1
            if present:
                counts["refused_but_present"] += 1
        else:
            counts["ambiguous_present" if present else "ambiguous_absent"] += 1
            ambiguous.append({**asdict(one), "in_tree": present})
    verdict.checks["form_writes"] = counts
    if lost:
        verdict.say(
            LOST,
            f"{len(lost)} form saves were answered 200 and are not in the plan",
            lost[:10],
        )
    if ambiguous:
        verdict.say(
            AMBIGUOUS,
            f"{len(ambiguous)} form saves were answered neither 200 nor 409; "
            f"{counts['ambiguous_present']} of them landed in git anyway",
            ambiguous[:10],
        )
    if counts["refused_but_present"]:
        verdict.say(
            BROKEN,
            f"{counts['refused_but_present']} saves were refused 409 and their marker "
            "is in the plan anyway",
        )


def conflict_markers(verdict: Verdict, plan: Path) -> None:
    """`<<<<<<<` or `>>>>>>>` anywhere a commit in this run put one.

    The final tree in full, plus every blob any commit changed — a marker that
    was committed and then edited away is still a marker that was committed, and
    the final tree alone cannot see it. `=======` is not looked for: it is a
    setext heading underline and the corpus is full of markdown.
    """
    import pygit2  # noqa: PLC0415

    git = pygit2.Repository(str(plan))
    head = str(git.references["refs/heads/main"].target)
    seen: set[tuple[str, str]] = set()
    found = []
    for path in harness.tree_paths(plan, head):
        text = harness.read_blob(plan, head, path) or ""
        if "<<<<<<<" in text or ">>>>>>>" in text:
            seen.add((head, path))
            found.append({"commit": head[:10], "path": path, "at": "the tip"})
    walked = 0
    for commit in git.walk(git[head].id):
        walked += 1
        if not commit.parents:
            continue
        for delta in git.diff(commit.parents[0], commit).deltas:
            blob = git[commit.tree_id]
            try:
                text = (blob / delta.new_file.path).data.decode("utf-8")
            except (KeyError, UnicodeDecodeError):
                continue
            if ("<<<<<<<" in text or ">>>>>>>" in text) and (
                str(commit.id), delta.new_file.path
            ) not in seen:
                seen.add((str(commit.id), delta.new_file.path))
                found.append({"commit": str(commit.id)[:10], "path": delta.new_file.path,
                              "at": "the commit that wrote it"})
    verdict.checks["conflict_markers"] = {"commits_walked": walked, "found": found}
    if found:
        verdict.say(LOST, f"{len(found)} committed blobs carry a conflict marker", found[:10])


def pushed(verdict: Verdict, plan: Path, origin: Path | None) -> None:
    import pygit2  # noqa: PLC0415

    local = harness.head_of(plan)
    if origin is None or not origin.exists():
        verdict.checks["push"] = {"local": local[:10], "origin": None,
                                  "note": "no remote was configured for this run"}
        return
    remote = harness.head_of(origin)
    git = pygit2.Repository(str(plan))
    unpushed = 0
    if local != remote:
        seen = {str(c.id) for c in git.walk(git[remote].id)} if git.get(remote) else set()
        unpushed = sum(1 for c in git.walk(git[local].id) if str(c.id) not in seen)
    forked = (
        local != remote
        and git.get(remote) is not None
        and not git.descendant_of(local, remote)
    )
    verdict.checks["push"] = {
        "local": local[:10],
        "origin": remote[:10],
        "equal": local == remote,
        "unpushed_commits": unpushed,
        "forked": forked,
    }
    if forked:
        verdict.say(DIVERGED, "local and origin have both moved and neither contains the other")
    elif local != remote:
        verdict.say(
            LOST,
            f"{unpushed} commits are on the instance's disk and not on the remote — on "
            "Cloud Run the filesystem is in memory and those commits die with the instance",
            verdict.checks["push"],
        )


def fsck(verdict: Verdict, plan: Path, origin: Path | None) -> None:
    out = {}
    for name, where in (("plan", plan), ("origin", origin)):
        if where is None or not where.exists():
            continue
        done = subprocess.run(
            ["git", "--git-dir", str(where), "fsck", "--no-progress"],
            capture_output=True,
            text=True,
        )
        out[name] = {"returncode": done.returncode,
                     "output": (done.stdout + done.stderr).strip()[:2000]}
        if done.returncode != 0:
            verdict.say(BROKEN, f"git fsck failed on {name}", out[name])
    verdict.checks["fsck"] = out


def snapshot(plan: Path) -> dict:
    """The plan, cloned out and loaded the way `openproj check` loads it.

    Taken before the load as well as after it. A synthetic corpus arrives with
    validation warnings of its own — a generated plan is not a shaped one — and a
    report that printed the final count alone would read as though the run had
    caused them. What the run caused is the DIFFERENCE.
    """
    from openproj.model import load_repo, validate_all  # noqa: PLC0415

    where = Path(tempfile.mkdtemp(prefix="openproj-verify-"))
    try:
        subprocess.run(
            ["git", "clone", "--quiet", str(plan), str(where / "plan")],
            check=True, capture_output=True,
        )
        records, config, unreadable = load_repo(where / "plan")
        problems = validate_all(records, config)
        blockers = [p for p in problems if p.severity == "blocker"]
        return {
            "records": len(records),
            "unreadable": [{"path": u.path, "why": u.why} for u in unreadable],
            "blockers": len(blockers),
            "warnings": len(problems) - len(blockers),
            "blocker_lines": [f"{p.record_id}: {p.field}: {p.message}" for p in blockers[:10]],
        }
    finally:
        shutil.rmtree(where, ignore_errors=True)


def parses(verdict: Verdict, plan: Path, before: dict | None) -> None:
    after = snapshot(plan)
    was = before or {"records": None, "unreadable": [], "blockers": 0, "warnings": 0}
    verdict.checks["parses"] = {
        "records": after["records"],
        "unreadable": after["unreadable"],
        "blockers": after["blockers"],
        "warnings": after["warnings"],
        "blockers_before": was["blockers"],
        "unreadable_before": len(was["unreadable"]),
    }
    gained = [u for u in after["unreadable"] if u not in was["unreadable"]]
    if gained:
        verdict.say(
            BROKEN,
            f"{len(gained)} files in the plan are no longer records — every page draws a "
            "banner about each of them",
            gained[:10],
        )
    if after["blockers"] > was["blockers"]:
        verdict.say(
            BROKEN,
            f"the run added {after['blockers'] - was['blockers']} validation blockers "
            f"(now {after['blockers']}, was {was['blockers']})",
            after["blocker_lines"],
        )
    elif after["blockers"]:
        verdict.say(
            NOTE,
            f"{after['blockers']} validation blockers, all of them already in the corpus "
            "this run started from",
        )


def authorship(verdict: Verdict, plan: Path, expected: set[str]) -> None:
    """A self-check of the harness, not of the app.

    Under `--auth dev` a cookie that does not verify is not refused — `writer`
    invents `dev_login` and permits the write. So a signing mismatch would run
    twenty people who were all one person, silently, and every attribution
    number in the report would be of the harness. `serve_load.py` sets that
    login to `unsigned` precisely so this can look for it.
    """
    import pygit2  # noqa: PLC0415

    git = pygit2.Repository(str(plan))
    authors: dict[str, int] = {}
    for commit in git.walk(git.references["refs/heads/main"].target):
        authors[commit.author.name] = authors.get(commit.author.name, 0) + 1
    verdict.checks["authors"] = dict(sorted(authors.items(), key=lambda kv: -kv[1]))
    if harness.UNSIGNED in authors:
        verdict.say(
            BROKEN,
            f"{authors[harness.UNSIGNED]} commits are authored by {harness.UNSIGNED!r}: the "
            "harness's session cookies did not verify, so every writer was one person",
        )
    # The bot's own name, read out of `store.py` rather than written down here:
    # it signs the corpus's first commit and every asset upload, so a hardcoded
    # copy would report the harness's own setup as a stranger the day it changed.
    from openproj.store import _BOT  # noqa: PLC0415

    strangers = set(authors) - expected - {_BOT.name}
    if strangers:
        verdict.say(NOTE, "commits by logins this run did not simulate", sorted(strangers))


def fields_are_values_somebody_sent(verdict: Verdict, plan: Path, head: str, sent: list) -> None:
    """No merge may invent a `person_weeks` nobody wrote.

    `_merge_frontmatter` merges per key, which is right for independent fields;
    this is the cheapest possible check that it is not doing something else.
    """
    from openproj.model import parse_text  # noqa: PLC0415

    files, paths = _final_bodies(plan, head)
    wanted: dict[str, set[float]] = {}
    for one in sent:
        wanted.setdefault(one.record, set()).add(one.person_weeks)
    invented = []
    for record, values in wanted.items():
        text = files.get(record)
        if text is None:
            continue
        try:
            record = parse_text(text, paths[record])
        except ValueError as error:
            verdict.say(BROKEN, f"{record} no longer parses: {error}")
            continue
        if record.person_weeks is not None and record.person_weeks not in values:
            invented.append({"record": record, "final": record.person_weeks,
                             "sent": sorted(values)})
    verdict.checks["fields"] = {"checked": len(wanted), "invented": invented}
    if invented:
        verdict.say(BROKEN, "a committed person_weeks is a value nobody sent", invented)


# -- the whole verdict -------------------------------------------------------


def verify(plan: Path, origin: Path | None, typed: list, sent: list,
           logins: set[str] | None = None, before: dict | None = None) -> dict:
    verdict = Verdict()
    head = harness.head_of(plan)
    verdict.checks["head"] = head[:10]
    coedit_characters(verdict, plan, head, typed)
    form_changes(verdict, plan, head, sent)
    conflict_markers(verdict, plan)
    pushed(verdict, plan, origin)
    fsck(verdict, plan, origin)
    parses(verdict, plan, before)
    authorship(verdict, plan, logins or set())
    fields_are_values_somebody_sent(verdict, plan, head, sent)
    return verdict.as_dict()


def summary(result: dict) -> str:
    lines = []
    for finding in result["findings"]:
        lines.append(f"  [{finding['severity']}] {finding['what']}")
    if not lines:
        lines.append("  nothing to report: every write is committed or refused, "
                     "nothing is unpushed, the plan parses")
    return "\n".join(lines)
