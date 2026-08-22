# One record, one page — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every record in the plan the same kind of thing, give it the same page, and list them all in one place sorted by last edited.

**Architecture:** `Issue` and `Note` become the fifth and sixth rungs of the ladder `Rung`/`KINDS` already is, so one template serves every record and per-kind differences are data. The invariant they gave up — that a separate type kept them off the table, the graph, the timeline and the people page — is bought back by inverting the index: `Index.entities` narrows to plan kinds only, so every existing consumer stays correct with no edit and a forgotten one fails closed, while a new `Index.records` holds everything and is the greppable opt-in. The editor's three views lose their unnamed fourth state: `view` becomes the sessionless landing view and absorbs the reading view. The landing page becomes a flat list of every record sorted by a last-edited time walked out of git history.

**Tech Stack:** Python 3.12, FastAPI, pydantic v2, ruamel.yaml (round-trip), pygit2 (bare repo, no working tree), Jinja2 autoescape + `Markup(...).format()`, vendored Ace and Yjs (no npm, no build step, no CDN), pytest + a headless-Chrome harness in `tests/browser.py`.

**Spec:** `docs/superpowers/specs/2026-08-22-one-record-one-page-design.md`

## Global Constraints

Every task's requirements implicitly include this section. All of it is from `AGENTS.md` unless marked.

**Where the work happens**
- Work in the worktree `.worktrees/one-record-one-page`, never at the repository root. The root stays on `main` and stays clean — it is where releases are cut and where a deploy builds its image. `pwd` before an edit if a command has just failed.
- This branch's history does not move: no rebase, no amend, no force-push, no squash, ever. Corrections are new commits.

**How it is verified**
- **Do not run pytest on this machine.** Not the whole suite, not one file of it — jcanton, 2026-08-21: *"no running suite locally, commit and run on CI"*. The local loop is `uv sync` then `uv run ruff check .`. Then push and read CI.
- TDD ordering still holds: the test is **written first, in the same commit as the code**. The red/green gate is CI, not the laptop.
- The one exception: running a **single** test function (`-k one_exact_name`) to reproduce a failure CI has already reported. Two of them is a suite, and a suite is CI's.
- Rendering a page and looking at it, or driving one in Chrome to answer a specific question, is not a test run and stays welcome. **Take a screenshot** — if a claim is about pixels, look at the pixels.
- ruff: line length 100, target py312, rules `E,F,I,UP,B`.

**How the code is written**
- One escaping boundary per language: Python through `Markup(...).format()` or the autoescaped Jinja `_ENV`; JavaScript through `esc` or `textContent`.
- **Never assemble a page by substituting into finished markup.** `test_no_page_is_assembled_by_substitution` parses `render.py` and `web.py` as syntax and bans every `.replace(` and `.sub(` attribute call in them — `str.replace` and `datetime.replace` included.
- Allowlists, not denylists.
- A write the model cannot read back must be refused: parse the patched text before writing and answer 422 naming the field and why.
- An invariant written twice will be guarded once. If a guard is the same three lines in two places, it is one helper. Two constants that are the same number are the same defect.
- Empty must not look like broken, and neither must a failure. A filter matching nothing, a plan that failed to load, and a plan with no records are three different sentences.
- Assume the browser refuses: `localStorage` throws on the property itself. Every access goes through `remembered` in the shell.
- Comments say **why** — what went wrong, or what the alternative was and why it lost. Nothing that restates the line beneath it.
- Derived data never reaches frontmatter. `serialise` and `patch_text` round-trip rather than re-serialise.
- Parse permissively, validate strictly. Requiredness lives in `validate_all` and nowhere else.
- When you qualify a selector to win a fight, work out what else it now beats, and say in the comment which way the cascade resolves.
- Copy is design material: a control says exactly what will happen and keeps the same word through the flow.
- Quality floor, met without announcing it: responsive, visible keyboard focus (`:focus-visible` with `outline: 2px solid var(--focus)`), reduced motion respected.
- Look for it before you write it: weigh the library that already does this, and write down what you found and why you chose as you did — in the commit that builds it. `No npm, no build step, no CDN` still decides most of the answer.

**How tests are written**
- A test that would not have caught the defect it is written for is not a test. Delete the fix, watch the test fail, put the fix back.
- Test the behaviour in the medium where it happens. If the claim is about pixels, the test tells painted from unpainted, or says in its own words why it cannot.
- Derive fixtures from the code where the code is what varies — a fixture that restates a rule drifts from it; one that runs the rule *is* it.
- **Type something that is not ASCII.** No test ever drove the editor with anything but ASCII, and that shipped three defects, the last a splice boundary *inside* a surrogate pair under 1160 passing tests.
- Report skips. A skipped test says why it skipped.

**Commits**
- A short imperative subject stating the change as a fact about the product, not as a description of a diff. Then a body saying what was wrong and why this is the fix.
- Every message ends with exactly this line and nothing after it:

  ```
  🤖 Written by an agent on behalf of @jcanton
  ```

  No `Co-Authored-By`, no `Claude-Session` trailers. (User instruction, `~/.claude/CLAUDE.md`.)

## Build order

Nine commits. Each leaves the suite green. Commits 1–4 are invisible to users; 5 and 7 are each independently shippable; 8 is the one that cannot be split, and everything before it exists to make it small.

| # | Task | What it is |
|---|---|---|
| 1 | Rung carries whether a kind is planned and what its statuses are | Pure refactor, four rungs only |
| 2 | The index holds the plan, and records holds everything | The inversion; the exclusion sweep lands armed |
| 3 | A status control takes its ladder, its lock and its hint from the record | Editor pipeline, inert until Task 8 |
| 4 | What may be written is derived from the ladder | `ID_PATTERN` from `KINDS`; the generic status gate |
| 5 | A document is read without opening a session | Goal 2 entire; fixes the seat bug already in the tree |
| 6 | Creating a record is the record page with nothing in it | `_NEW` absorbed into `_DETAIL` |
| 7 | The plan opens on what changed last | Goal 3 entire; the git walk, the cache, `/` and `/table` |
| 8 | An issue is a rung, and a note is a rung | The atomic flip |
| 9 | The second surface is gone | Deletions, README, docs |

---

### Task 1: Rung carries whether a kind is planned and what its statuses are

**Files:**
- Modify: `src/openproj/model.py:906` (add `Entity.state` after `_as_written`, before `class Project` at 909)
- Modify: `src/openproj/model.py:965-992` (the `Rung` NamedTuple and the four `KINDS` entries)
- Modify: `src/openproj/model.py:997-1026` (`_WORK_FIELDS` and `unread_fields`)
- Modify: `src/openproj/model.py:1711-1714` (`STATUS_ORDER` moves above the ladder)
- Modify: `src/openproj/model.py:1973-1981` (`_vocabulary_problems` reads the rung)
- Modify: `src/openproj/model.py:2521-2538` (`validate_all`'s exemption becomes structural, via a new `_parked` helper)
- Test: `tests/test_validate.py` (the chosen file — it already owns the seed-corpus snapshot at line 429 and the vocabulary tests at line 538; the new pins go beside them)

**Interfaces:**
- Consumes: nothing from earlier tasks (this is the first). Everything it touches exists today: `Rung` (`model.py:965`), `KINDS` (`model.py:979`), `unread_fields(kind: str) -> tuple[str, ...]` (`model.py:1009`), `_vocabulary_problems(entity: Entity) -> Iterator[tuple[str, str | None, str, int]]` (`model.py:1973`), `validate_all(entities: list[Entity], config: Config) -> list[Problem]` (`model.py:2521`), `STATUS_ORDER = ("shaping", "ready", "in_progress", "done", "shelved")` (`model.py:1714`), `ISSUE_STATUS = ("ready", "in_progress", "done", "shelved")` (`model.py:154`), `NOTE_STATUS = ("thinking", "dropped")` (`model.py:244`), and `openproj check` (`cli.py:81-104`, `_check`).
- Produces, for later tasks:
  - `Rung.planned: bool` and `Rung.statuses: tuple[str, ...]`, in this order, after `carded` — Task 2's `build_index` filter and validator read `planned`; Task 3's `_control_html` ladder and Task 4's generic status gate read `statuses`.
  - `Entity.state(self, entities: dict[str, Entity]) -> str` returning `self.status` — Task 3's fact rows call it on every record; `Issue.state` (`model.py:195`) and `Note.state` (`model.py:319`) become real overrides of it in commit 8.
  - `_vocabulary_problems` judging `entity.status` against `RUNG[entity.kind].statuses` — what makes the issue/note rungs validatable in commit 8 without three seed files turning into blockers.
  - `_parked(entity: Entity) -> bool` — the structural terminal-state exemption.

**Terminal-word verification, done while writing this plan** (the task said to check and say so loudly if it fails — it does not fail): `STATUS_ORDER` (`model.py:1714`) ends in `"shelved"`, `ISSUE_STATUS` (`model.py:154`) ends in `"shelved"`, `NOTE_STATUS` (`model.py:244`) ends in `"dropped"`. Every ladder ends in its terminal word, so `rung.statuses[-1]` is a correct spelling of "parked" for all six eventual rungs. No alternative needed.

**⚠️ ONE INSTRUCTION IN THE TASK BRIEF CANNOT BE DELIVERED AS WRITTEN, AND HERE IS WHY.** The brief asks for a test pinning "`shaping` is a blocker on a product". It cannot be, in this task or any task, without breaking an existing jcanton-quoted pin: `tests/test_product.py:229-249` (`test_a_container_has_no_work_state_to_gate`) asserts that a product file carrying `status: ready` — a word — produces **exactly** `[("warning", "status")]`: one "not read" warning, no vocabulary blocker. If `_vocabulary_problems` judged a product's status against `statuses=()` unconditionally, `"ready"` (and the model default `"shaping"`, on every product ever parsed) would blocker, that test would break, and the change would stop being the "behaviour identical" refactor commit 1 must be. The spec's own words decide it: `statuses=()` "means status is not read" — and a field a kind does not read has no vocabulary to violate; `unread_fields` already reports it as written-but-not-read. So the guard is `if rung.statuses and entity.status not in rung.statuses`, products get **no** vocabulary check, and the alternative pin below (Step 8) asserts exactly that: a product's carried status is a warning-only "not read", never a vocabulary blocker — plus the fact the brief is really after, "each rung accepts exactly its own words", derived from `KINDS` so the issue rung is covered by the same loop the day commit 8 adds it (at which point `shaping` on an *issue* becomes the blocker the spec promises). Two small behaviour deltas ride along, neither pinned by any test and neither reachable in `seed/` (which contains no `products/` directory at all): (a) a product carrying a garbage status like `banana` loses today's *extra* vocabulary blocker and keeps the "not read" warning; (b) a product carrying `status: shelved` was silently skipped by `validate_all`'s exemption and is now reported — the exemption is for parked *work*, and a kind that reads no status cannot be parked by one. Both are called out in commit-message body and pinned in Step 8.

- [ ] **Step 1: Move `STATUS_ORDER` above the ladder.** The ladder is about to reference it, and today it is defined at `model.py:1714` — 735 lines *after* `KINDS` (`model.py:979`), so `statuses=STATUS_ORDER` would be a `NameError` at import. Delete these four lines at `model.py:1711-1714` (leave `PRIORITY_RANK` and its own comment at 1715-1718 where they are):

```python
# Statuses in the order work moves through them. `shaping` is an idea nobody has
# committed to yet, so it demands nothing — the same reason `shelved` does not.
# The gates are cumulative from `ready` onwards.
STATUS_ORDER = ("shaping", "ready", "in_progress", "done", "shelved")
```

and re-insert them, with one added sentence of WHY-it-moved, immediately before the `# THE LADDER.` comment block at `model.py:955` (i.e. after `class Product(Entity):`'s body ends at 953, separated by two blank lines):

```python
# Statuses in the order work moves through them. `shaping` is an idea nobody has
# committed to yet, so it demands nothing — the same reason `shelved` does not.
# The gates are cumulative from `ready` onwards.
#
# Above the ladder rather than with `PRIORITY_RANK`, because the ladder now
# reads it: a rung carries the status vocabulary its kind reads, and three of
# the four rungs carry this one.
STATUS_ORDER = ("shaping", "ready", "in_progress", "done", "shelved")
```

- [ ] **Step 2: Add the two fields to `Rung`.** In the `Rung` NamedTuple (`model.py:965-976`), after the `carded: bool` line, add — **in this exact order**, because `Rung` is a NamedTuple and field order is construction order, and later tasks and commit 8's two new rungs are written against it:

```python
    carded: bool           # does a hover show its shaping document
    planned: bool          # does it appear in the plan: table, graph, timeline, people, scheduler
    statuses: tuple[str, ...]  # the status vocabulary this kind reads; () means status is not read
```

No defaults, deliberately: `Rung` is constructed in exactly one place (`KINDS` — verified by grep, no test constructs one), and a default here would let a seventh rung be added without anyone deciding whether it is planned, which is the property the field exists to force.

- [ ] **Step 3: Update all four `KINDS` entries** (`model.py:979-992`). Every entry gains `planned=True` (all four current kinds are plan kinds — issue and note arrive in commit 8, NOT here). Product gets `statuses=()`; project, pitch and task get `statuses=STATUS_ORDER`. Keep the existing per-rung comment about `under` exactly where it is. The block becomes:

```python
KINDS: tuple[Rung, ...] = (
    # `statuses=()` — status is one of the nine fields a product does not read
    # (jcanton, 2026-08-20: a codebase is not `in_progress`), and () is how the
    # ladder says so now that the vocabulary is a per-rung fact.
    Rung("product", "prod", "products", Product, under=(),
         schedules=False, depends=False, sized=False, carded=False,
         planned=True, statuses=()),
    Rung("project", "proj", "projects", Project, under=("product",),
         schedules=True, depends=True, sized=False, carded=True,
         planned=True, statuses=STATUS_ORDER),
    Rung("pitch", "pitch", "pitches", Pitch, under=("project",),
         schedules=True, depends=True, sized=True, carded=True,
         planned=True, statuses=STATUS_ORDER),
    # A task may skip the pitch — work that nobody shaped still belongs to a
    # project — which is why `under` is written out per rung rather than derived
    # as "everything coarser". Derived, a task could be filed straight under a
    # product, three rungs up, which is not a thing anybody means.
    Rung("task", "task", "tasks", Task, under=("pitch", "project"),
         schedules=True, depends=True, sized=True, carded=True,
         planned=True, statuses=STATUS_ORDER),
)
```

Every keyword value is copied from the current entries — do not change `sized=False` on project or any other existing flag.

- [ ] **Step 4: Re-cut `_WORK_FIELDS` and `unread_fields`.** At `model.py:997-1006`, remove `"status"` from the tuple and rewrite the comment's last sentence, which currently justifies `status`'s presence there:

```python
# The fields that describe work being done, or evidence that it was: a rung the
# scheduler never sees reads none of them. Nobody is assigned to a codebase, a
# codebase is not in a cycle, and — jcanton, 2026-08-20 — a codebase does not
# have a pull request either. `status` is not in this tuple any more: whether a
# kind reads a status is its own axis (`Rung.statuses`), because a kind can
# read one without ever being scheduled — gated here, giving it a status would
# have dragged in the eight fields that come with being work.
_WORK_FIELDS = (
    "owner", "assignees", "reviewers", "review_waived", "assigned_on",
    "cycle", "priority", "prs",
)
```

Then in `unread_fields` (`model.py:1009-1026`), after the `if not rung.schedules:` branch and before the `return`, append the new gate:

```python
    if not rung.schedules:
        fields.extend(_WORK_FIELDS)
    # `status` on its own gate: a kind with an empty vocabulary reads no status.
    # Today that is only `product`, whose behaviour this preserves exactly —
    # `statuses=()` keeps status unread — but gating on the vocabulary rather
    # than on `schedules` is what lets a rung read a status without inheriting
    # the eight scheduling fields above.
    if not rung.statuses:
        fields.append("status")
    return tuple(fields)
```

Verify by reading, not by running: for `product` (`schedules=False`, `statuses=()`) the result is `depends_on, person_weeks, owner, assignees, reviewers, review_waived, assigned_on, cycle, priority, prs, status` — the same eleven fields as today with `status` moved from tenth to last, and every consumer is membership-based (`field in unread_fields(...)` at `index.py:428`, `render.py:1055`, `render.py:16153`; set logic in `tests/test_product.py:263-268` and `tests/test_table.py:496`), so the order change is invisible. For project/pitch/task (`statuses` truthy) the result is unchanged: `()` for project... — no: project is `depends=True, sized=False` so `("person_weeks",)`; pitch and task `()`. Same as today.

- [ ] **Step 5: Add `Entity.state`.** In `class Entity` (`model.py:827`), immediately after the `_as_written` validator ends at line 906 and before `class Project(Entity):` at 909, add (the file has `from __future__ import annotations` at line 8, so the forward reference in the annotation is fine — `Issue.state` at line 195 already relies on it):

```python
    def state(self, entities: dict[str, Entity]) -> str:
        """What this record actually is — for a plan record, its written status.

        The base of the derivation `Issue.state` and `Note.state` already do:
        one method any page can call on any record, so a read display never has
        to know which kinds derive their state from links and which just have
        one. The argument goes unused here because the derivations need it — a
        state read off a link needs the link's targets to look at.
        """
        return self.status
```

Do NOT touch `Issue` (`model.py:157`) or `Note` (`model.py:270`) — they stay standalone `BaseModel`s in this task; their `state` methods (`model.py:195`, `319`) become real overrides only in commit 8 when the subclassing lands.

- [ ] **Step 6: `_vocabulary_problems` reads the rung.** Replace the status half of the function (currently `model.py:1973-1981`; the `priority` half at 1982-1989 is untouched):

```python
def _vocabulary_problems(entity: Entity) -> Iterator[tuple[str, str | None, str, int]]:
    """A word nobody defined, named where it is rather than as a stack trace."""
    statuses = RUNG[entity.kind].statuses
    # An empty vocabulary means the kind reads no status, so there is no word to
    # judge: `unread_fields` already reports a status written on such a file as
    # "not read", and a blocker on top of that would hold a product to a ladder
    # it was just told it does not have. Judging against `STATUS_ORDER` here is
    # what this replaced, and it was wrong in both directions at once: it would
    # turn every stale note into an ungrandfatherable blocker the day notes
    # become records, and it makes `shaping` silently legal on an issue.
    if statuses and entity.status not in statuses:
        yield (
            "blocker",
            "status",
            f"{entity.status!r} is not a status: expected one of {', '.join(statuses)}",
            1,
        )
    if entity.priority not in PRIORITY_RANK:
        yield (
            "blocker",
            "priority",
            f"{entity.priority!r} is not a priority: expected one of "
            f"{', '.join(PRIORITY_RANK)}",
            1,
        )
```

What it does today, quoted so the diff is checkable: `if entity.status not in STATUS_ORDER:` yields `f"{entity.status!r} is not a status: expected one of {', '.join(STATUS_ORDER)}"` — for project/pitch/task the new code joins `rung.statuses`, which **is** `STATUS_ORDER` (same tuple object), so every message is byte-identical. `RUNG` is defined at module level (`model.py:1027`) before any call reaches this function at validation time, and `entity.kind` is guaranteed in `RUNG` by the `_a_rung_of_the_ladder` field validator (`model.py:881-896`).

- [ ] **Step 7: The exemption becomes structural, guarded once.** The rule "parked work is not broken work" is written twice in `validate_all` — `model.py:2532` (`entity.status != "shelved"` in the children map) and `model.py:2537` (`if entity.status == "shelved": continue`) — and AGENTS.md says an invariant written twice will be guarded once. Add one helper immediately above `validate_all` (`model.py:2521`), and rewrite both sites and the docstring sentence that names "Shelved":

```python
def _parked(entity: Entity) -> bool:
    """Exempt from every rule: parked work is not broken work.

    Structural rather than the word `shelved`: every status ladder ends in its
    kind's terminal state — `STATUS_ORDER` and `ISSUE_STATUS` in `shelved`,
    `NOTE_STATUS` in `dropped` — so "the last word of this rung's own ladder" is
    the rule, and a rung added later is exempt in its own vocabulary with no
    edit here. A kind with no vocabulary is never parked: a product claiming
    `status: shelved` used to buy itself a silent skip with a word it does not
    even read, and now its written-but-unread status is reported instead.
    """
    statuses = RUNG[entity.kind].statuses
    return bool(statuses) and entity.status == statuses[-1]


def validate_all(entities: list[Entity], config: Config) -> list[Problem]:
    """Check every entity against every rule it is old enough to be held to.

    Parked entities — those at their own ladder's terminal status, see
    `_parked` — are exempt from all of them: parked work is not broken work,
    and a validator that nags about it teaches people to ignore the validator.
    """
    by_id = {entity.id: entity for entity in entities}
    parent_cycles = _cyclic_members({e.id: [e.parent] if e.parent else [] for e in entities})
    dep_cycles = _cyclic_members({e.id: list(e.depends_on) for e in entities})
    children: dict[str, list[Entity]] = {}
    for entity in entities:
        if entity.parent in by_id and not _parked(entity):
            children.setdefault(entity.parent, []).append(entity)

    problems: list[Problem] = []
    for entity in entities:
        if _parked(entity):
            continue
```

Everything from `for severity, field, message, rule_version in _problems_for(` (`model.py:2539`) onward is untouched, including the `_identity_problems` extension outside the loop and its comment — a parked record with a stolen id must still be reported, and the new spelling preserves that because `_identity_problems` was never inside the exemption. Behaviour for the four rungs: project/pitch/task park at `"shelved"` (`STATUS_ORDER[-1]`), exactly as today; product never parks — the one delta, argued in the callout above and pinned in Step 8.

- [ ] **Step 8: Write the per-rung vocabulary tests** (same commit as the code — TDD ordering is kept, the red/green gate is CI). In `tests/test_validate.py`, first add `KINDS` to the existing `from openproj.model import (...)` block at lines 16-28 — it slots between `Entity` and `Pitch`, keeping ruff's `I` ordering:

```python
from openproj.model import (
    _ID_PATTERN,
    Config,
    Entity,
    KINDS,
    Pitch,
    Problem,
    Project,
    Task,
    cycle_of,
    load_repo,
    parse_text,
    validate_all,
)
```

Then insert these two tests immediately after `test_a_word_nobody_defined_is_a_problem_and_not_a_crash` (which ends at line 555, before `test_a_stale_vocabulary_still_schedules_and_renders` at 558). The first is derived from `KINDS` on purpose — AGENTS.md: derive fixtures from the code where the code is what varies — so the day commit 8 adds the issue and note rungs, this same loop asserts `shaping` blockers on an issue and `ready` blockers on a note with no edit:

```python
def test_each_rung_accepts_exactly_its_own_status_words():
    """The vocabulary is a per-rung fact now, not one module-level ladder.

    Derived from `KINDS` rather than written out per kind, so a rung added
    later — an issue, whose ladder has no `shaping` — is held to its own words
    by this same loop on the day it lands. Only `p.field == "status"` is
    filtered for, because a valid word can still gate other fields (`ready`
    demands an owner) and those problems are some other test's business.
    """
    for rung in KINDS:
        blank = rung.model(id=f"{rung.prefix}-000000", kind=rung.name, title="T")
        for word in rung.statuses:
            said = check(blank.model_copy(update={"status": word}))
            assert not [p for p in said if p.field == "status"], (rung.name, word)
        if rung.statuses:
            vocab = only(check(blank.model_copy(update={"status": "wip"})), blank.id,
                         field="status")
            assert summary(vocab) == (
                "blocker",
                "status",
                f"'wip' is not a status: expected one of {', '.join(rung.statuses)}",
                1,
            ), rung.name


def test_a_kind_that_reads_no_status_has_no_vocabulary_to_violate():
    """A product's status is unread, so no word on it is a vocabulary blocker —
    the "not read" warning from `unread_fields` is the whole report, whether the
    word is on the work ladder or on no ladder at all. `shelved` is the case
    that changed: it used to buy the file a silent skip through the parked
    exemption, using a word a product does not even read, and now the exemption
    is structural (`_parked`) a product cannot park and the warning appears.
    """
    for word in ("shelved", "banana"):
        written = parse_text(
            f"---\nid: prod-000001\nkind: product\ntitle: gt4py\nstatus: {word}\n---\n\nx\n",
            "products/prod-000001.md",
        )
        said = validate_all([written], Config())
        assert [(p.severity, p.field) for p in said] == [("warning", "status")], (word, said)
        assert "not read" in said[0].message
```

Notes for the implementer, verified against the code: `check`, `only` and `summary` are this file's own helpers (`tests/test_validate.py:132,136,146`). The terminal-word loop iteration (`word = "shelved"` on project/pitch/task) passes trivially because `_parked` skips the entity — no problems at all, so none with `field == "status"`. The `only(...)` call is safe on every rung: with an unknown word no status gate fires (`required_at` is keyed by real words), a task's missing-parent problem lands on `field="parent"`, and `Config()` has an empty roster so people checks are off — exactly one `status` problem remains.

- [ ] **Step 9: Write the seed-check pin** (spec test 3). Chosen file: `tests/test_validate.py` — it already owns the seed section (`# --- the seed corpus ---`, line 426) and the exhaustive snapshot `test_the_seed_corpus_reports_exactly_this_problem_set` (line 429), which pins the *content* of `validate_all` over the real 17 files down to the message and rule version. That snapshot **is** the "identical before and after" guarantee and must not be edited (Step 10 verifies it). What it does not pin is the CLI: `_check` (`src/openproj/cli.py:81-104`) prints unreadable files, then every problem as `f"{problem.severity}: {problem.entity_id}: {problem.field}: {problem.message}"` sorted by `(p.severity, p.entity_id, p.field or "")`, then the count line, and exits 1 on blockers. Retyping the 25-entry set into a second literal would be the same invariant guarded twice, so this test pins the other half — that `openproj check` prints the *whole* of `validate_all`'s answer and nothing else — and the two tests together pin "`openproj check` over `seed/` produces an identical problem list". Add a new import line above the `from openproj.model import (` block (ruff `I`: `openproj.cli` sorts before `openproj.model`):

```python
from openproj.cli import main
```

and insert this test immediately after `test_the_seed_corpus_reports_exactly_this_problem_set` (after line 505):

```python
def test_check_over_the_seed_corpus_prints_exactly_the_validated_problems(
    seed_root: Path, capsys
):
    """The seed-check pin, CLI half. The snapshot test above pins WHAT
    `validate_all` says about the real corpus, entry by entry; this pins that
    `openproj check` relays all of it — every line, the sort, the count, the
    exit code — and adds nothing. Together they freeze the command's output
    over `seed/`, which is what has to survive the `unread_fields` re-cut and
    the per-rung vocabulary unchanged: a problem this pair does not notice
    appearing or vanishing is a validation change that got past the refactor.
    """
    entities, config, unreadable = load_repo(seed_root)
    problems = sorted(
        validate_all(entities, config), key=lambda p: (p.severity, p.entity_id, p.field or "")
    )
    blockers = [p for p in problems if p.severity == "blocker"]

    assert main(["check", str(seed_root)]) == 1
    lines = capsys.readouterr().out.splitlines()

    expected = [
        f"blocker: {one.path}: this file is not a record, so nothing in it is in the plan: "
        f"{one.why}"
        for one in unreadable
    ]
    expected += [f"{p.severity}: {p.entity_id}: {p.field}: {p.message}" for p in problems]
    expected.append(
        f"{len(blockers) + len(unreadable)} blockers, {len(problems) - len(blockers)} warnings"
    )
    assert lines == expected
```

The exit-code assertion is `== 1` because the seed corpus has real blockers — `tests/test_cli.py:14-20` already stakes that.

- [ ] **Step 10: Verify the pins you must NOT have touched.** Run `git diff --stat` from the worktree root and confirm the diff touches exactly two files: `src/openproj/model.py` and `tests/test_validate.py`. Then run `git diff tests/test_validate.py` and confirm `test_the_seed_corpus_reports_exactly_this_problem_set` (line 429) shows zero changed lines — its unmodified body passing on CI after the refactor is the before/after identity — and `git diff tests/test_product.py` is empty, so `test_a_container_has_no_work_state_to_gate`'s `[("warning", "status")]` pin stands as the proof that no vocabulary blocker crept onto products.

- [ ] **Step 11: Lint locally — and nothing else locally.** Do NOT run pytest, not even the one file you just edited; the red/green gate is CI (AGENTS.md, jcanton 2026-08-21: "no running suite locally, commit and run on CI"). The whole local loop is:

```bash
cd /Users/jcanton/projects/openproj/.worktrees/one-record-one-page
uv sync
uv run ruff check .
```

Fix anything ruff reports (line length 100, py312, rules E,F,I,UP,B — the import ordering in Step 8/9 and the 100-column `Rung` entries were written to pass it).

- [ ] **Step 12: Commit and push, then read CI.** From the worktree (branch `one-record-one-page`):

```bash
cd /Users/jcanton/projects/openproj/.worktrees/one-record-one-page
git add src/openproj/model.py tests/test_validate.py
git commit -m "$(cat <<'EOF'
A kind knows whether it is planned and which words its status may be

The ladder is where "everything true of one kind and not of its neighbours"
lives, but three per-kind facts were still written elsewhere as facts about the
one entity ladder: the status vocabulary was validated against STATUS_ORDER for
every record, "status" sat inside the scheduling fields as if reading one and
being scheduled were the same axis, and the parked exemption was the literal
word "shelved". Each was wrong the moment a kind with its own ladder arrives —
a stale note would become an ungrandfatherable blocker, and shaping is silently
legal on an issue today.

Rung gains planned and statuses; product takes statuses=() (status stays one of
the fields a product does not read), the other three take STATUS_ORDER, and all
four are planned. unread_fields gates status on the vocabulary instead of on
schedules, _vocabulary_problems judges each record against its own rung's
words, and the exemption is structural — the last word of the rung's own
ladder — behind one helper, _parked. Entity.state(entities) returns the status,
as the base of the derivation Issue.state and Note.state already do.

Four rungs only; issue and note are not added here. Two deliberate edges, both
unreachable in seed/ and unpinned before now: a product carrying a garbage
status keeps its "not read" warning but loses the extra vocabulary blocker (an
unread field has no vocabulary), and a product claiming status: shelved is
reported instead of buying a silent skip with a word it does not read. The
seed-corpus snapshot plus the new CLI pin freeze `openproj check` over seed/
byte for byte across the change.

🤖 Written by an agent on behalf of @jcanton
EOF
)"
git push -u origin one-record-one-page
```

Then read CI rather than running anything locally — `gh run list --branch one-record-one-page --limit 1` and, once it appears, `gh run watch <run-id> --exit-status` (about thirteen minutes; keep working on the next task while it runs). The commit is done only when CI is green; if it is red, the failure names which pin the refactor bent, and the fix happens on this branch in a follow-up commit with the same footer.

---

### Task 2: The index holds the plan, and records holds everything

**Files:**
- Modify: `src/openproj/index.py:19` (pydantic import), `src/openproj/index.py:21-41` (model import block), `src/openproj/index.py:145-149` (the `Index` fields), `src/openproj/index.py:198-200` (validator insertion point), `src/openproj/index.py:436-512` (`build_index`), `src/openproj/index.py:515-524` (`_is_blocked`), `src/openproj/index.py:527-563` (`_matches_predicate`), `src/openproj/index.py:566-584` (`query_fields`), `src/openproj/index.py:587-611` (`cascade_of`), `src/openproj/index.py:614-654` (`apply_filters`)
- Test: `tests/test_exclusion.py` (new file — the sweep and the machinery tests live here; Task 8 later folds the issue/note page tests into it)

**Interfaces:**
- Consumes (from Task 1): `Rung` carries `planned: bool` and `statuses: tuple[str, ...]` after `carded`, and `RUNG: dict[str, Rung]` (`model.py`) resolves a kind name to its rung. At this commit all four rungs have `planned=True`.
- Produces (for Tasks 7 and 8):
  - `Index.records: dict[str, Entity]` — every parsed record. New required field, right after `entities`.
  - `Index.entities: dict[str, Entity]` — plan kinds only, guarded by a pydantic `model_validator` that raises naming the offending id and kind.
  - `apply_filters(index: Index, filters: dict[str, list[str]], query: str, over: dict[str, Entity] | None = None) -> list[str]` — filters `over`, defaulting to `index.entities` (the plan). The landing page (Task 7) passes `over=index.records`.
  - `index.search_blob`, `index.blocked_by`, `index.blocks`, `index.children` are **total over records** — a fact row, the landing search, and the delete cascade cannot `KeyError` on any kind.
  - `query_fields` and `_matches_predicate` are total (they look records up in `index.records`), which is what makes `apply_filters(..., over=index.records)` legal.

This is the load-bearing commit of spec §2, and it is an **inversion**: the plan is the *filtered* map and keeps the old name, so every one of the sixty-odd existing consumers of `.entities` is correct with no edit at all, and a consumer nobody remembers fails **closed** — it sees fewer records, never a note on the timeline. The superset takes the *new* name, `records`, so reaching for it is a deliberate, greppable act. With only planned kinds existing today, `records == entities`, so the whole commit is green by construction — and the sweep test lands here, armed for Task 8.

- [ ] **Step 1: Widen the imports in `src/openproj/index.py`.**

  Line 19 currently reads `from pydantic import BaseModel`. The model import block at lines 21-41 starts `PRIORITY_RANK, STATUS_ORDER, Config, ...`. Two edits:

  ```python
  from pydantic import BaseModel, model_validator
  ```

  and in the `from .model import (...)` block, insert `RUNG,` between `PRIORITY_RANK,` and `STATUS_ORDER,` (ruff's isort orders the uppercase names alphabetically):

  ```python
  from .model import (
      PRIORITY_RANK,
      RUNG,
      STATUS_ORDER,
      Config,
      Cycle,
      Entity,
      Issue,
      Note,
      Problem,
      Unreadable,
      ancestors,
      checklist,
      cycle_of,
      issue_problems,
      note_problems,
      sections,
      size_weeks,
      under,
      unread_fields,
      validate_all,
  )
  ```

- [ ] **Step 2: `Index` gains `records` and the two fields get comments that say which population is which.**

  At `index.py:145-149` the class currently opens:

  ```python
  class Index(BaseModel):
      entities: dict[str, Entity]
      children: dict[str, list[str]]
  ```

  Replace the first two field lines with:

  ```python
  class Index(BaseModel):
      # THE PLAN, and only the plan: kinds whose rung says `planned`. Narrowed on
      # purpose rather than superseded — every PM surface (table, graph, timeline,
      # people, scheduler, facets, /api/index.json) reads this field, so a consumer
      # nobody edits stays correct, and one that is forgotten fails closed: it sees
      # fewer records, never an unplanned one on the timeline.
      entities: dict[str, Entity]
      # Every record that parsed, whatever its kind. Reaching for this is a
      # deliberate act — the word looks wrong in a function about the timeline,
      # which is the point. The landing list, the detail lookup and the delete
      # cascade are its readers.
      records: dict[str, Entity]
      children: dict[str, list[str]]
  ```

  `records` is deliberately **required, with no default**: a `build_index` that forgets to fill it fails at construction rather than shipping an empty landing page.

- [ ] **Step 3: The validator — the by-construction guarantee, in one place.**

  The field list ends at `index.py:196-198` with:

  ```python
      # Ids whose body keeps a "for later" list — deferred scope, which is the only
      # record the plan has of a bet being trimmed to fit.
      for_later: list[str] = []
  ```

  and `def counts_in(...)` follows at line 200. Insert between them:

  ```python
      @model_validator(mode="after")
      def _the_plan_holds_only_planned_kinds(self) -> "Index":
          """The guarantee the type system gave up when every kind became an Entity.

          `model.py` used to argue that an issue being a separate *type* is what
          kept it off the table by construction. This is that argument's
          replacement: one assertion at the single place an Index is made, instead
          of an exclusion in each of sixty read sites that somebody later forgets.
          """
          for entity in self.entities.values():
              if not RUNG[entity.kind].planned:
                  raise ValueError(
                      f"{entity.id} is a {entity.kind}, and no {entity.kind} belongs in "
                      "the plan: .entities holds planned kinds only — put it in .records"
                  )
          return self
  ```

  The message names the offending id and kind, per the write-refusal rule: whoever meets this error is holding the record that caused it.

- [ ] **Step 4: `build_index` — filter once, in the one comprehension; keep every map total.**

  Replace the whole body of `build_index` (`index.py:442-512`, everything after the `def` at 436-441). The current body opens `by_id = {entity.id: entity for entity in entities}` at line 442; the edge maps are at 443-452; the facet/search loop at 456-481; the `return Index(...)` at 483-512. New body:

  ```python
      records = {entity.id: entity for entity in entities}
      # THE INVERSION (spec §2). Filtered here, once, and nowhere else: the plan
      # keeps the old name so its sixty-odd consumers need no edit, and the
      # superset takes the new one so reading it is visible in review.
      plan = {eid: entity for eid, entity in records.items() if RUNG[entity.kind].planned}
      children: dict[str, list[str]] = {entity_id: [] for entity_id in records}
      blocked_by: dict[str, list[str]] = {}
      # Total over records, not over the plan: the record page draws fact rows for
      # every kind, and a map missing a key there is a KeyError on a page, not a
      # smaller answer.
      blocks: dict[str, list[str]] = {entity_id: [] for entity_id in records}

      for entity in entities:
          if entity.parent in children:
              children[entity.parent].append(entity.id)
          blocked_by[entity.id] = [target for target in entity.depends_on if target in records]
          for target in blocked_by[entity.id]:
              blocks[target].append(entity.id)

      spans, explanations = schedule(entities, config, today)

      facets: dict[str, set[str]] = defaultdict(set)
      search_blob: dict[str, str] = {}
      progress: dict[str, Progress] = {}
      for_later: list[str] = []
      # The blob is total: the landing list searches every record, and a record
      # missing from it is one its own page cannot find. PR references included —
      # "which entity is #1364?" is asked in front of a screen, and the answer was
      # only findable if the number also appeared in the prose. What goes in is
      # `SEARCH_FIELDS`, which is also what a row carries to the browser.
      for entity in records.values():
          search_blob[entity.id] = searchable(entity)
      # Facets, progress and deferred scope are PLAN facts: an unplanned kind in a
      # facet menu is a dead option on the table.
      for entity in plan.values():
          for field in (*_SCALAR_FACETS, *_LIST_FACETS, *_HOLDER_FACETS):
              values = _facet_values(entity, field, records)
              # `NO_VALUE` is offered only where something is actually missing, so
              # a menu never carries an option that can select nothing. Every
              # status has a value, so Status never grows one; Cycle grows one the
              # moment a pitch is written and not yet bet.
              facets[field].update(values or [NO_VALUE])
          # A shelved child is not work anybody is waiting for, so it counts in
          # neither half of the fraction — otherwise parking a task makes a pitch
          # look less finished than it was the day before. Looked up in `plan`,
          # not `records`: an unplanned record with a hand-written `parent` is
          # already a containment problem, and counting it into a pitch's progress
          # would let the bad file move a number on the table.
          kids = [plan[k] for k in children[entity.id] if k in plan and plan[k].status != "shelved"]
          counted = _progress_of(entity, kids, config)
          if counted is not None:
              progress[entity.id] = counted
          if sections(entity.body).get(_FOR_LATER):
              for_later.append(entity.id)

      return Index(
          entities=plan,
          records=records,
          children=children,
          blocked_by=blocked_by,
          blocks=blocks,
          spans=spans,
          explanations=explanations,
          problems=validate_all(entities, config),
          unreadable=list(unreadable),
          facets={field: _ordered(field, values) for field, values in facets.items()}
          | {"predicate": sorted(COMPUTED_PREDICATES)},
          search_blob=search_blob,
          cycles=config.cycles,
          plans=config.plans,
          nominal_availability=config.nominal_availability,
          cooldown_weeks=config.cooldown_weeks,
          known_people=config.known_people,
          icons={
              login: person.icon for login, person in config.people.items() if person.icon
          },
          issues=config.issues,
          issue_problems=issue_problems(config, entities),
          notes=config.notes,
          note_problems=note_problems(config, entities),
          today=today,
          default_task_effort=config.default_task_effort,
          holidays=config.holidays,
          progress=progress,
          for_later=for_later,
      )
  ```

  Notes for the implementer: `schedule(entities, ...)` still gets the full list — the scheduler already filters on `RUNG[e.kind].schedules` and needs nothing (spec §2). `validate_all(entities, ...)` also stays total: every record gets checked. The `issues=`/`notes=` lines are today's parallel readers and are deleted in Task 8, not here.

- [ ] **Step 5: `_is_blocked` reads the total map.**

  At `index.py:515-524`, the lookup `index.entities[blocker].status` would `KeyError` if a hand-written `depends_on` ever named an unplanned record (the edge map is total over records now, so such an edge survives into `blocked_by`). Replace the function body's lookup:

  ```python
  def _is_blocked(index: Index, entity_id: str) -> bool:
      """Blocked means waiting on work that is not over.

      Reading a non-empty `depends_on` as "blocked" would park a live task behind
      something finished months ago. The blocker is looked up in `records`:
      `blocked_by` is total over records, so its targets are there by
      construction, and a hand-written edge to an unplanned kind must not 500 the
      page that draws it.
      """
      return any(
          index.records[blocker].status not in ("done", "shelved")
          for blocker in index.blocked_by[entity_id]
      )
  ```

- [ ] **Step 6: `_matches_predicate` becomes total.**

  Four lookups at `index.py:543`, `545`, `552`, `558` read `index.entities[entity_id]`. Change each to `index.records[entity_id]`, and put one comment above the function rather than four copies beside the lines:

  ```python
  # Looked up in `records`, never `entities`: predicates run over whichever
  # population `apply_filters` was handed, and the landing search hands it the
  # whole one. `entities` ⊂ `records`, so the total map is always the safe door.
  def _matches_predicate(index: Index, entity_id: str, predicate: str) -> bool:
  ```

  The four changed lines, exactly:

  ```python
      if predicate == "review_waived":
          return index.records[entity_id].review_waived
      if predicate == "past_cycle_build":
          entity = index.records[entity_id]
  ```
  ```python
      if predicate == "in_progress_without_prs":
          entity = index.records[entity_id]
  ```
  ```python
      if predicate == "untracked":
          # Live work that says nothing about how far along it is: no tasks under
          # it and no checklist in it. A pitch with tasks is tracked by them.
          return (
              index.records[entity_id].status in ("ready", "in_progress")
              and entity_id not in index.progress
          )
  ```

- [ ] **Step 7: `query_fields` becomes total.**

  At `index.py:573-576` change the two `index.entities` reads to `index.records` (the docstring stays — the browser-parity argument is unchanged):

  ```python
      entity = index.records[entity_id]
      fields = {
          field: [value.lower() for value in _facet_values(entity, field, index.records)]
          for field in (*_SCALAR_FACETS, *_LIST_FACETS, *_HOLDER_FACETS)
      }
  ```

- [ ] **Step 8: `cascade_of` iterates records.**

  At `index.py:606-610` the `edited` comprehension walks `index.entities.items()`. The delete cascade serves every kind (spec §2 puts it on the `records` side), and totality is free:

  ```python
      edited = sorted(
          other
          for other, entity in index.records.items()
          if other not in going and going.intersection(entity.depends_on)
      )
  ```

- [ ] **Step 9: `apply_filters` is parameterised on the population, defaulting to the plan.**

  Replace the signature and loop at `index.py:614-633`. Docstring gains the one sentence that stops a future caller guessing:

  ```python
  def apply_filters(
      index: Index,
      filters: dict[str, list[str]],
      query: str,
      over: dict[str, Entity] | None = None,
  ) -> list[str]:
      """AND across fields, OR within a field, then the query language.

      `over` picks the population and defaults to the plan: every caller that
      existed before the landing page is a PM surface, so a caller that forgets
      to ask for more fails closed. The landing list passes `index.records`.

      An unknown field or predicate matches nothing rather than everything: filter
      state comes from a hand-editable query string, and a typo that silently widens
      the result set is worse than one that visibly empties it.

      A query that cannot be read matches nothing, for the same reason and one
      more: half a query is a query somebody is still typing, and a table that
      widens to everything on the way to `kind:task and (` flickers through the
      whole plan at every keystroke. The sentence is not shown from here — this
      function answers with rows — so the caller that has a reader in front of it
      asks `parse` itself. See `render.py`'s `queryError`.
      """
      try:
          asked = parse(query)
      except QueryError:
          return []
      matched = []
      for entity_id, entity in (index.entities if over is None else over).items():
  ```

  Everything from `fields = query_fields(index, entity_id)` down (lines 634-654) is unchanged — it is already total after steps 6-7.

- [ ] **Step 10: Create `tests/test_exclusion.py` — module docstring, imports, and the KINDS-derived seed helper.**

  This file hosts spec §7 tests 1 and 2. Cross-importing sibling test modules is this suite's established style (`test_web.py` does `from test_store import commit_directly`), so the family constructors, the seed corpus and the bare-repo committer are imported, not restated.

  ```python
  """The exclusion: a kind whose rung says `planned=False` is off every PM surface.

  Spec §2 ("one record, one page"): `Index.entities` is the plan and only the
  plan; `Index.records` is every record that parsed. The inversion makes every
  existing consumer safe — a forgotten one sees fewer records, never more — and
  the validator on `Index` is the by-construction guarantee the type system gave
  up when every kind became an Entity.

  Two layers, on purpose:

  * The KINDS-derived sweep. It iterates the ladder and covers every rung with
    `planned=False`, so a seventh unplanned rung is covered the day it is added
    and the sweep cannot go stale. Until the flip commit lands there is no such
    rung, and the sweep SKIPS WITH A STATED REASON rather than passing vacuously
    — `addopts = -ra` puts that skip in every CI summary, so it is a visible
    countdown, not silence. The flip commit un-skips it by existing: nothing in
    this file needs an edit on that day.
  * The machinery tests. They cannot wait for the flip, so they make an unplanned
    rung out of the ladder itself — `RUNG["task"]._replace(planned=False)` under
    `monkeypatch.setitem` — derived from a real rung rather than invented, so the
    fake cannot drift from the shape of one.
  """

  from __future__ import annotations

  import json
  from pathlib import Path

  import pygit2
  import pytest
  from fastapi.testclient import TestClient
  from pydantic import ValidationError
  from test_index import CONFIG, TODAY, a_family, a_task
  from test_store import commit_directly
  from test_web import SEED

  from openproj.cli import main
  from openproj.index import Index, apply_filters, build_index
  from openproj.model import KINDS, RUNG, Rung, parse_text
  from openproj.web import create_app

  # A word no fixture, template or chrome string contains, so "absent from the
  # rendered page" is a claim about this record and nothing else.
  NEEDLE = "xsweepneedle"

  UNPLANNED = tuple(rung for rung in KINDS if not rung.planned)


  def _armed() -> tuple[Rung, ...]:
      """The rungs the sweep covers, or a REPORTED skip while there are none.

      A skip and not a pass: with zero unplanned rungs every loop below is
      vacuous, and a vacuous green is indistinguishable from a real one. The
      skip shows in CI's `-ra` summary on every run until the flip commit adds
      the issue and note rungs, at which point this returns them and the sweep
      runs for real — no edit here, ever.
      """
      if not UNPLANNED:
          pytest.skip(
              "no rung with planned=False in KINDS yet - the sweep arms itself on "
              "the flip commit that adds the issue and note rungs"
          )
      return UNPLANNED


  def _seed_for(rung: Rung) -> tuple[str, str, str]:
      """(id, path, file text) for one minimal record of `rung`'s kind.

      Derived from the ladder — prefix, directory, status vocabulary — and
      carrying only what every kind has: id, kind, title, and the first word of
      the rung's own ladder. If a future unplanned kind grows a required field,
      `parse_text` refuses this text and the sweep fails LOUDLY, which is the
      correct failure: extend this helper, never skip the kind.
      """
      eid = f"{rung.prefix}-0faded"
      front = [f"id: {eid}", f"kind: {rung.name}", f"title: {NEEDLE} {rung.name}"]
      if rung.statuses:
          front.append(f"status: {rung.statuses[0]}")
      text = "---\n" + "\n".join(front) + "\n---\n\nSeeded by the exclusion sweep.\n"
      return eid, f"{rung.directory}/{eid}.md", text
  ```

- [ ] **Step 11: The green-by-construction pin and the index purity test (spec added-test 2).**

  Append to `tests/test_exclusion.py`. The purity test is the one that runs **today**, not vacuously: it flips the real task rung to `planned=False` and watches `build_index` do the exclusion, keep every total map total, and serve both populations through `apply_filters`.

  ```python
  def test_with_only_planned_kinds_the_records_are_exactly_the_plan():
      """The load-bearing fact of this commit: the inversion lands before any
      unplanned kind exists, so the two populations are equal and every existing
      consumer is untouched by construction."""
      index = build_index(a_family(), CONFIG, TODAY)
      assert index.records == index.entities


  def test_build_index_keeps_an_unplanned_kind_out_of_the_plan(monkeypatch):
      """Index purity, testable before the flip: the fake unplanned rung is the
      real task rung with one field changed, so it cannot drift from the shape
      of a rung. Only `planned` flips — the rest of the rung stays as it is, so
      everything else `build_index` does is undisturbed."""
      monkeypatch.setitem(RUNG, "task", RUNG["task"]._replace(planned=False))
      index = build_index(a_family(), CONFIG, TODAY)

      dropped = sorted(eid for eid in index.records if eid.startswith("task-"))
      assert dropped == ["task-c00001", "task-c00002"], "the family's tasks are the fixture"
      for eid in dropped:
          assert eid not in index.entities, f"{eid} leaked into the plan"
          assert eid in index.records

      # The maps a record page and the landing search read are TOTAL: a fact row
      # cannot KeyError and a record cannot be missing from its own search.
      everyone = set(index.records)
      assert set(index.children) == everyone
      assert set(index.blocked_by) == everyone
      assert set(index.blocks) == everyone
      assert set(index.search_blob) == everyone

      # Facets are plan facts: no dropped id anywhere, and the kind menu does
      # not offer the word — a facet that can only ever match nothing.
      for field, values in index.facets.items():
          for eid in dropped:
              assert eid not in values, f"{eid} appears in the {field} facet"
      assert "task" not in index.facets["kind"]

      # One search, two populations: the default is the plan and fails closed;
      # the landing asks for everything by name.
      assert "task-c00001" not in apply_filters(index, {}, "first")
      assert "task-c00001" in apply_filters(index, {}, "first", over=index.records)
  ```

- [ ] **Step 12: The validator rejection (spec test 2).**

  Append. `dict(good)` iterates a pydantic model as `(field, value)` pairs, so the hand-built `Index` is the good one with exactly one thing wrong — and the constructor's `model_validator` is what must catch it.

  ```python
  def test_a_hand_built_index_smuggling_an_unplanned_kind_is_refused(monkeypatch):
      """`build_index` filtering is one half; the validator is the guarantee that
      no OTHER construction path — a future cache, a test fixture, a refactor —
      can put an unplanned kind in the plan either."""
      monkeypatch.setitem(RUNG, "task", RUNG["task"]._replace(planned=False))
      good = build_index(a_family(), CONFIG, TODAY)
      sneaked = a_task("task-0faded", "Smuggled into the plan")
      with pytest.raises(ValidationError) as refusal:
          Index(**{**dict(good), "entities": {**good.entities, sneaked.id: sneaked}})
      said = str(refusal.value)
      assert "task-0faded is a task" in said, "the refusal names the id and the kind"
      assert ".records" in said, "and says where the record belongs instead"
  ```

- [ ] **Step 13: The sweep, index level (spec test 1, first half).**

  Append. Everything is derived from `_armed()` and `_seed_for`, so the day Task 8 adds the issue and note rungs, this covers both — and a seventh unplanned rung after that — with no edit.

  ```python
  def test_every_unplanned_kind_is_out_of_the_plan_and_in_the_records():
      unplanned = _armed()
      entities = a_family()
      seeded: list[tuple[Rung, str]] = []
      for rung in unplanned:
          eid, path, text = _seed_for(rung)
          entities.append(parse_text(text, path))
          seeded.append((rung, eid))

      index = build_index(entities, CONFIG, TODAY)
      for rung, eid in seeded:
          assert eid not in index.entities, f"a {rung.name} leaked into the plan"
          assert eid in index.records, f"the {rung.name} fell out of the record population"
          # The scheduler never dates it, so no payload built from spans can name it.
          assert eid not in index.spans and eid not in index.explanations
          for field, values in index.facets.items():
              assert eid not in values, f"{eid} appears in the {field} facet"
          assert rung.name not in index.facets["kind"], "a facet that can only match nothing"
          # Total maps: the fact rows and the landing search cannot KeyError.
          assert eid in index.blocked_by and eid in index.blocks
          assert eid in index.search_blob
          # Found by the landing search, invisible to the table's.
          assert eid in apply_filters(index, {}, NEEDLE, over=index.records)
          assert eid not in apply_filters(index, {}, NEEDLE)
  ```

- [ ] **Step 14: The sweep, schedule payload (spec test 1, `schedule --json`).**

  Append. `_schedule` (`cli.py:352`) prints `"entities": sorted(index.entities)` plus spans and explanations — the external contract that must stay unplanned-free **by construction**, which this pins.

  ```python
  def test_the_schedule_payload_never_names_an_unplanned_kind(tmp_path: Path, capsys):
      unplanned = _armed()
      (tmp_path / "config").mkdir()
      (tmp_path / "config" / "defaults.yaml").write_text(
          "schema_version: 2\nnominal_availability: 1.0\ndefault_task_effort: 0.5\n"
      )
      (tmp_path / "tasks").mkdir()
      (tmp_path / "tasks" / "task-c00001.md").write_text(
          "---\nid: task-c00001\nkind: task\ntitle: Planned work\nstatus: ready\n"
          "owner: ann\nreviewers: [bo]\nperson_weeks: 1\n---\n\nA task.\n"
      )
      seeded = []
      for rung in unplanned:
          eid, path, text = _seed_for(rung)
          (tmp_path / rung.directory).mkdir(exist_ok=True)
          (tmp_path / path).write_text(text)
          seeded.append(eid)

      assert main(["schedule", str(tmp_path), "--json", "--today", "2026-08-13"]) == 0
      payload = json.loads(capsys.readouterr().out)
      assert "task-c00001" in payload["entities"], "the planned control is scheduled"
      for eid in seeded:
          assert eid not in payload["entities"]
          assert eid not in payload["spans"] and eid not in payload["explanations"]
  ```

- [ ] **Step 15: The sweep, rendered pages (spec test 1, second half).**

  Append. The server fixture is `test_web.py`'s shape: a bare repository (production serves a bare clone, never a checkout), seeded with the shared `SEED` corpus plus one record of every unplanned kind. Reads are public, so no session cookie is needed. The routes asserted are the **final** map (spec §6): `/` is Records (Task 7), `/table` is the table (Task 7), `/detail/{id}` serves every kind (Task 8) — the skip in `_armed()` keeps this green until all three exist, because the unplanned rungs and those routes land in build order 7→8.

  ```python
  @pytest.fixture
  def sweep_client(tmp_path: Path):
      """The SEED corpus plus one record of every unplanned kind, served."""
      _armed()
      path = tmp_path / "plan.git"
      pygit2.init_repository(str(path), bare=True, initial_head="main")
      seeded = dict(SEED)
      for rung in UNPLANNED:
          _, file_path, text = _seed_for(rung)
          seeded[file_path] = text
      commit_directly(path, seeded, "seed the exclusion sweep corpus")
      with TestClient(create_app(path, auth="dev", secret="a-sweep-signing-secret")) as client:
          yield client


  # Every PM page the spec names. The whole document is one response — rows,
  # embedded payload, facet bar, suggestions datalist — so absence of the id and
  # the title needle from the text is absence from all of them at once.
  PLAN_PAGES = ("/table", "/graph", "/timeline", "/people")


  def test_an_unplanned_record_is_on_its_own_page_and_the_landing_and_nowhere_else(
      sweep_client: TestClient,
  ):
      for rung in _armed():
          eid, _, _ = _seed_for(rung)
          for route in PLAN_PAGES:
              page = sweep_client.get(route)
              assert page.status_code == 200
              assert eid not in page.text, f"{eid} leaked onto {route}"
              assert NEEDLE not in page.text, f"the {rung.name}'s title leaked onto {route}"

          listed = sweep_client.get("/api/index.json").json()
          assert eid not in listed["entities"], "the external contract is plan-only"
          assert eid not in listed["spans"]

          # Present exactly where a record lives: the landing list, and its own page.
          landing = sweep_client.get("/")
          assert landing.status_code == 200 and eid in landing.text
          own = sweep_client.get(f"/detail/{eid}")
          assert own.status_code == 200 and NEEDLE in own.text
  ```

  Why this cannot go stale, and cannot stay vacuous quietly: the population it iterates is `KINDS` itself, so a new unplanned rung is swept the day its `Rung(...)` line lands, with zero edits here. And while the population is empty, every one of the four sweep tests reports `SKIPPED` with the stated reason in CI's summary — the suite's `addopts = "-ra"` exists precisely so a skip is a line somebody reads (AGENTS.md: "Report skips"). Task 8's definition of done includes these four flipping from `s` to `.` in the same CI run that adds the rungs; if Task 8 ever landed without that flip, the skip line naming "the flip commit that adds the issue and note rungs" would still be sitting in the summary of a build that just added them, which is as loud as a skip gets. The two monkeypatch tests (steps 11-12) run non-vacuously from this commit on, so the filtering machinery itself is never unguarded in the meantime.

- [ ] **Step 16: Lint locally — and nothing else locally.**

  ```bash
  cd /Users/jcanton/projects/openproj/.worktrees/one-record-one-page
  uv sync
  uv run ruff check .
  ```

  Fix what ruff reports (line length 100 is the one this task's comprehensions flirt with). **Do not run pytest** — not `tests/test_exclusion.py`, not one function. The red/green gate is CI.

- [ ] **Step 17: Commit and push; CI is the verification.**

  ```bash
  git add src/openproj/index.py tests/test_exclusion.py
  git commit -m "$(cat <<'EOF'
  The plan is the filtered map, and the records are everything

  Every PM surface reads Index.entities, and the first design put issues and
  notes INTO it and asked each surface to filter them out — sixty read sites,
  each failing open. Inverted: build_index filters entities on
  RUNG[kind].planned once, in the one comprehension that builds it, and the
  superset takes the new name, Index.records. A consumer nobody edits stays
  correct; a consumer nobody remembers sees fewer records, never a note on the
  timeline. A model_validator on Index refuses any unplanned kind in the plan,
  naming the id and the kind — the by-construction guarantee the type system
  gave up when every kind became an Entity.

  The maps a record page will read are total over records: blocked_by, blocks,
  children and search_blob carry every kind, so a fact row cannot KeyError and
  the landing search can find what the table must not show. apply_filters is
  parameterised on the population and defaults to the plan, so the table's
  search fails closed and the landing asks for everything by name.

  With only planned kinds on the ladder, records equals entities and this
  commit changes no behaviour. The KINDS-derived exclusion sweep lands here,
  skipping with a stated reason until the flip commit adds an unplanned rung —
  from that day it covers every such rung, present and future, with no edit.

  🤖 Written by an agent on behalf of @jcanton
  EOF
  )"
  git push -u origin one-record-one-page
  ```

  Then read CI on the PR (about thirteen minutes) and keep working on the next task while it runs. Expected CI shape for this commit: everything green, and four `SKIPPED` lines from `tests/test_exclusion.py` in the `-ra` summary, each saying the sweep arms itself on the flip commit. Any other skip or any failure in `test_index.py`, `test_search.py` or `test_facets.py` means the inversion changed behaviour it must not have — fix on the branch and push again.

---

### Task 3: A status control takes its ladder, its lock and its hint from the record

**Files:**
- Modify: `src/openproj/render.py:47-76` (the `from .model import (...)` block)
- Modify: `src/openproj/render.py:11784-11803` (`_CONTROL`)
- Modify: `src/openproj/render.py:12008-12040` (`_control_html`)
- Modify: `src/openproj/render.py:13261-13266` (the `<dd>` row in `_DETAIL`)
- Modify: `src/openproj/render.py:15285` (the hand copy of the status ladder)
- Modify: `src/openproj/render.py:15268-15284` (`EDITABLE`)
- Modify: `src/openproj/render.py:15355-15362` (`HILL_LADDERS`, plus two new maps beside it)
- Modify: `src/openproj/render.py:15449-15453` and `15496-15568` (`_HILL` / `_hill_html`)
- Modify: `src/openproj/render.py:15993-16011` (`LABELS`)
- Modify: `src/openproj/render.py:16117-16125` (`SUGGESTS`)
- Modify: `src/openproj/render.py:16127-16180` (`_editable_for`)
- Modify: `src/openproj/render.py:16181-16286` (`_fact_rows`)
- Test: `tests/test_hill.py` (imports at lines 27-48; new tests appended at the end)

**Interfaces:**
- Consumes (from Task 1): `Entity.state(self, entities: "dict[str, Entity]") -> str` returning `self.status`; `Rung.planned: bool` (used only by a test); `unread_fields(kind) -> tuple[str, ...]` unchanged.
- Consumes (from Task 2): `Index.records: dict[str, Entity]`.
- Consumes (already in tree): `_hill_html(status, ladder="entity", *, live=False, control=False, label="Status", group="hill") -> Markup` (`render.py:15496`); `_editable_for(entity, prefix="field")` (`render.py:16127`); `_fact_rows(index, entity, links)` (`render.py:16181`).
- Produces (Tasks 6 and 8 rely on these exact shapes):
  - `_control_html(field: dict, *, ladder: str = "entity", live: bool = True, shown: str | None = None, describedby: str = "") -> Markup`
  - `_CONTROL` honours optional field keys `f.disabled` and `f.placeholder`
  - `_hill_html(..., describedby: str = "")` — one new keyword-only parameter
  - `HILL_LADDERS["issue"]`; `_LADDER_OF: dict[str, str]`; `_STATE_HINT: dict[str, str]`
  - `_editable_for(entity: Entity, prefix: str = "field", signed_in: str = "") -> list[dict]` — field dicts gain a `"placeholder"` key
  - `_fact_rows(index: Index, entity: Entity, links: Links, signed_in: str = "") -> list[dict]` — the per-field rows gain `"hint"` and `"hint_id"` keys
  - `STATUSES is STATUS_ORDER`
  - `EDITABLE` gains `reported_by`/`written_by` (text) and `pitched_into`/`became` (list); `LABELS` and `SUGGESTS` gain the matching entries

**Everything here is inert until Task 8, and that is deliberate.** `_editable_for` intersects `EDITABLE` with `type(entity).model_fields` (render.py:16150-16153), and no model on any rung carries `reported_by`, `written_by`, `pitched_into`, `became`, `opened_on` or `written_on` until the flip commit makes `Issue` and `Note` entity subclasses. Likewise `Entity.state` returns `self.status` for every planned kind, so the lock condition `state() != status` is false on every record that exists today, and the read display `entity.state(index.records)` renders byte-identically to `entity.status`. This commit changes no rendered byte on any existing page; it builds the pipeline Task 8 switches on. The old `_ISSUE`/`_NOTE` pages and their tests (`tests/test_issues.py:297-309`, `tests/test_notes.py:382-403`) are not touched — they die in Task 8, not here.

**One deliberate divergence from the old pages, to be preserved, not "fixed":** the old issue page locks on `bool(issue.pitched_into) and issue.status != "shelved"` (render.py:19117); the spec's rule is `state() != status`. They differ in two corners, both improvements: a `pitched_into` whose targets are all dangling no longer locks the control (a dangling link should be fixable, and `state()` already falls back to `status` for it), and a stored word that happens to equal the derived one stays editable (editing it away just re-derives). Do not carry the old boolean across.

- [ ] **Step 1: Write the tests that run in this commit — appended to `tests/test_hill.py`.** First widen the two import blocks at the top of the file. The current model import (line 30) is `from openproj.model import NOTE_STATUS, load_repo`; the render import (lines 31-47) already carries `HILL_LADDERS, ROUTES, STATUSES, _hill_html, hill_geometry, render_detail`. Extend both (ruff's `I` rule will tell you the exact ordering it wants — fix to its suggestion, do not fight it):

```python
from openproj.index import Index, build_index
from openproj.model import (
    ISSUE_STATUS,
    KINDS,
    NOTE_STATUS,
    RUNG,
    STATUS_ORDER,
    Config,
    Issue,
    Pitch,
    Task,
    load_repo,
)
from openproj.render import (
    _HILL_ALONG,
    _HILL_BOX,
    _HILL_GROUND,
    _HILL_NORMALS,
    _HILL_OFF_THE_PATH,
    _HILL_STOPS,
    _LADDER_OF,
    _STATE_HINT,
    EDITABLE,
    HILL_LADDERS,
    LABELS,
    ROUTES,
    STATUSES,
    SUGGESTS,
    _control_html,
    _editable_for,
    _fact_rows,
    _hill_at,
    _hill_html,
    _hill_path,
    _human,
    hill_geometry,
    render_detail,
    render_table,
)
```

Then append, at the end of the file:

```python
# ---------------------------------------------------------------------------
# The control takes its ladder, its lock and its hint from the record.
#
# Half of these run today and half are armed. Until the flip commit no kind's
# `state()` disagrees with its `status` — `Entity.state` answers `status`, and
# `Issue` and `Note` are not entities yet — so the lock is exercised through a
# subclass that derives its state, which is also all an Issue will be. The one
# test that needs a real issue on a real index is skipif-armed on the rung and
# starts running, unedited, the moment the flip lands.
# ---------------------------------------------------------------------------


class Handed(Task):
    """A record whose state comes from somewhere else, before any such kind exists.

    Stands in for `Issue` and `Note`: a stored `ready` and a derived `done`, the
    exact disagreement the lock exists for.
    """

    def state(self, entities: dict) -> str:
        return "done"


def test_the_status_ladder_is_the_validator_s_and_not_a_hand_copy() -> None:
    """`STATUSES` was the five words typed out a second time, in the file whose
    own comments record what hand copies of a ladder cost. Aliased, not retyped:
    a word added to `STATUS_ORDER` reaches every chip rule, select and hill here
    without anybody remembering this line exists."""
    assert STATUSES is STATUS_ORDER


def test_every_issue_word_stands_on_the_hill() -> None:
    """All four of `ISSUE_STATUS` already have stops — `ready` at the summit,
    `in_progress` halfway down, `done` at the bottom, `shelved` on the ground
    under the summit — so the issue page gets the hill and the last of #67's
    asymmetry goes with it. Derived from the vocabulary, like the other two
    ladders, so a word added to `ISSUE_STATUS` fails here rather than quietly
    having nowhere to stand."""
    assert HILL_LADDERS["issue"] == tuple(ISSUE_STATUS)
    for word in ISSUE_STATUS:
        assert word in _HILL_STOPS, f"{word} is an issue status with nowhere to stand"
    # And the browser is handed it, so a card can draw an issue the day one exists.
    assert hill_geometry()["ladders"]["issue"] == list(ISSUE_STATUS)


def test_the_lock_hint_keeps_the_two_pages_own_words() -> None:
    """Copy carried verbatim from the issue and note pages it replaces. A changed
    word here is a changed sentence on a page somebody already learned to read."""
    assert _STATE_HINT == {
        "issue": "from the work it was pitched into",
        "note": "from what it became",
    }
    assert _LADDER_OF == {"issue": "issue", "note": "note"}


def test_a_derived_state_locks_the_control_in_the_dom_not_in_paint() -> None:
    """Genuinely disabled: the hidden input carries `disabled`, the hill has no
    radios to press and says so as `role="img"`, and the picture shows the
    derived word — the same ball the read view shows, so pressing Edit moves
    nothing."""
    held = Handed(
        id="task-000001", kind="task", title="Waits on something else",
        status="ready", owner="ann",
    )
    index = build_index([held], Config(), date(2026, 8, 17))
    row = next(r for r in _fact_rows(index, held, ROUTES) if r["label"] == "Status")

    assert "hill-ball hill-done" in str(row["display"]), "the page reads the stored word"
    control = str(row["control"])
    assert re.search(r'<input type="hidden" name="status"[^>]* disabled', control)
    assert 'role="radiogroup"' not in control, "a locked hill is offering stops to press"
    assert 'role="img"' in control
    assert "hill-ball hill-done" in control, "Edit moves the ball, which the row promises not to"


def test_the_locked_control_carries_its_explanation_for_a_screen_reader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Not just a visual grey: the why-sentence is a real element in the row,
    and the control points at it with `aria-describedby`. The sentence is
    patched in because no planned kind has one — the two kinds that do arrive
    in the flip commit, and the armed test below takes over then."""
    import openproj.render as render

    monkeypatch.setitem(render._STATE_HINT, "task", "from what it waits on")
    held = Handed(
        id="task-000001", kind="task", title="Handed on", status="ready", owner="ann",
    )
    index = build_index([held], Config(), date(2026, 8, 17))
    page = render_detail(index, ROUTES, only="task-000001", base_commit=HEAD, may_write=True)

    assert '<span class="hint" id="hint-task-000001-status">from what it waits on</span>' in page
    assert 'aria-describedby="hint-task-000001-status"' in page
    assert re.search(r'<input type="hidden" name="status"[^>]* disabled', page)
    assert 'role="radiogroup"' not in page


def test_a_text_control_can_carry_a_placeholder_and_refuse_the_pen() -> None:
    """The two field-dict keys `_CONTROL` gained. `placeholder` is how
    `reported_by` and `written_by` will say who the server stamps; `disabled`
    is the generic lock for any boxed control."""
    field = {
        "name": "reported_by", "id": "x-reported_by", "type": "text", "value": None,
        "gates": (), "list": "people", "text": "", "placeholder": "ann",
    }
    drawn = str(_control_html(field))
    assert 'placeholder="ann"' in drawn
    assert " disabled" not in drawn
    assert re.search(r"<input[^>]* disabled", str(_control_html({**field, "disabled": True})))


def test_what_a_person_owns_on_an_issue_or_a_note_and_what_the_server_stamps() -> None:
    """The four new editable fields, with their suggestion lists and their
    reader's names — and the two creation stamps deliberately absent, because a
    date the server set is not a thing a form may offer a box for."""
    assert EDITABLE["reported_by"] == "text"
    assert EDITABLE["written_by"] == "text"
    assert EDITABLE["pitched_into"] == "list"
    assert EDITABLE["became"] == "list"
    assert "opened_on" not in EDITABLE
    assert "written_on" not in EDITABLE
    assert SUGGESTS["reported_by"] == "people"
    assert SUGGESTS["written_by"] == "people"
    assert SUGGESTS["pitched_into"] == "entities"
    assert SUGGESTS["became"] == "entities"
    for name in (
        "reported_by", "written_by", "pitched_into", "became", "opened_on", "written_on",
    ):
        assert name in LABELS, f"{name} would reach a reader as an identifier"


def test_no_plan_kind_is_offered_an_issue_s_or_a_note_s_fields() -> None:
    """The new `EDITABLE` entries are inert on every planned kind, today and
    forever: the intersection with `model_fields` is what keeps a pitch from
    being offered a `reported_by` box its validator would then refuse."""
    for rung in KINDS:
        if not rung.planned:
            continue
        blank = rung.model(id=f"{rung.prefix}-000000", kind=rung.name, title="")
        offered = {field["name"] for field in _editable_for(blank)}
        assert not offered & {"reported_by", "written_by", "pitched_into", "became"}, (
            f"{rung.name} is offered a box its validator will refuse"
        )
```

- [ ] **Step 2: Write the armed half of spec test 9, in the same file, directly below.** This is the whole-pipeline test — a real issue, a real done pitch, the derived word, the lock, the hint and the placeholder wiring — and it cannot run before the flip because no `Issue` entity and no `issue` rung exist. It is written now, complete, and armed with `skipif` on the rung, so the day Task 8 adds `Rung("issue", ...)` it starts running with no edit. CI's `-ra` summary will show it as a stated skip until then, which is the honest state.

```python
@pytest.mark.skipif(
    "issue" not in RUNG,
    reason="arms in the flip commit, when the issue rung and the Issue entity land",
)
def test_an_issue_whose_pitch_is_done_reads_done_with_a_locked_hill_and_the_hint() -> None:
    """Spec test 9. The stored word is `ready`; the pitch it was pitched into is
    `done`; the page must read the derived state on a hill with no stops, say
    why in the page's own copy, and stamp the signed-in login as the
    `reported_by` placeholder."""
    pitch = Pitch(
        id="pitch-000001", kind="pitch", title="The fix", status="done",
        owner="ann", person_weeks=1.0,
    )
    noticed = Issue(
        id="issue-000001", kind="issue", title="Something broke",
        status="ready", pitched_into=["pitch-000001"],
    )
    index = build_index([pitch, noticed], Config(), date(2026, 8, 17))
    rows = _fact_rows(index, noticed, ROUTES, signed_in="ann")

    status = next(r for r in rows if r["label"] == "Status")
    assert "hill-ball hill-done" in str(status["display"]), "the page reads the stored word"
    control = str(status["control"])
    assert 'data-hill="issue"' in control
    assert 'role="radiogroup"' not in control
    assert re.search(r'<input type="hidden" name="status"[^>]* disabled', control)
    assert status["hint"] == "from the work it was pitched into"
    assert status["hint_id"] == "hint-issue-000001-status"
    assert f'aria-describedby="{status["hint_id"]}"' in control

    reported = next(r for r in rows if r["label"] == "Reported by")
    assert 'placeholder="ann"' in str(reported["control"])
    opened = next(r for r in rows if r["label"] == "Opened on")
    assert opened["derived"] and opened["control"] == ""
```

- [ ] **Step 3: Retire the hand copy of the status ladder.** In the `from .model import (...)` block at `render.py:47-76`, add `STATUS_ORDER,` on its own line after `RUNG,` (constants group; ruff `I` confirms the slot). Then replace line 15285:

```python
STATUSES = ("shaping", "ready", "in_progress", "done", "shelved")
```

with:

```python
# The validator's own ladder, aliased and not retyped. This line was the five
# words written out a second time — the same defect `PREFIX` below records being
# the third copy of the kind ladder — and the two copies could only ever agree
# by luck. `STATUSES` stays as the name this file reads it by.
STATUSES = STATUS_ORDER
```

Everything downstream (`_status_class` at 264, the CSS loops, `_by_status`, the payload `choices`) reads `STATUSES` and is unchanged.

- [ ] **Step 4: The issue ladder, and the two per-kind maps, at `render.py:15355-15362`.** Replace the `HILL_LADDERS` block (update its comment: the vocabularies are three now, and all imported):

```python
# Which stops a record of each kind may stand on, in ladder order. Derived from
# the vocabularies rather than written out beside them: a status added to one of
# them tomorrow fails `test_every_issue_word_stands_on_the_hill` (or its entity
# and note twins) instead of quietly having nowhere to stand, which on a hill
# means no ball at all.
HILL_LADDERS = {
    "entity": tuple(word for word in STATUSES if word in _HILL_STOPS),
    "issue": tuple(word for word in ISSUE_STATUS if word in _HILL_STOPS),
    "note": tuple(word for word in NOTE_STATUS if word in _HILL_STOPS),
}

# Which ladder each kind's status stands on. Only the two unplanned kinds have
# ladders of their own; every planned kind shares the entity's, and product is
# not here because `statuses=()` keeps status in its `unread_fields` — no status
# row is ever built for it.
_LADDER_OF = {"issue": "issue", "note": "note"}

# Why a status control is locked, per kind — the sentence beside it when the
# state is derived from a link rather than typed. Verbatim from the two pages
# this replaces, because the people reading it already learned these words. No
# planned kind appears: `Entity.state` answers `status`, so a planned kind can
# never satisfy the lock condition and never needs a sentence.
_STATE_HINT = {
    "issue": "from the work it was pitched into",
    "note": "from what it became",
}
```

Facts to rely on, verified against `_HILL_ALONG`/`_HILL_OFF_THE_PATH` (render.py:15348-15351): all four `ISSUE_STATUS` words have stops — `ready` at the summit (`_hill_at(0.5)` = (60, 8)), `in_progress` halfway down ((84, 24)), `done` at the bottom over the hill ((108, 40)), `shelved` on the ground under the summit ((60, 40), off the path, dimmed). So `HILL_LADDERS["issue"]` is exactly `ISSUE_STATUS`, nothing filtered. The note needs nothing new: its ladder has existed since #67, `thinking` stands at the foot ((12, 40)) and `dropped` off the path, and the derived third word `promoted` has no stop by design — `_HILL_HANDED_ON` (15440) parks its ball at `shaping`. No fallback is needed for any word; the `if word in _HILL_STOPS` filters are pure tripwire. `hill_geometry()` (15389) iterates `HILL_LADDERS`, so the browser payload gains the issue ladder with no further edit.

- [ ] **Step 5: `_hill_html` learns to point at its explanation.** At `render.py:15496`, add the keyword-only parameter (after `group`):

```python
def _hill_html(
    status: str,
    ladder: str = "entity",
    *,
    live: bool = False,
    control: bool = False,
    label: str = "Status",
    group: str = "hill",
    describedby: str = "",
) -> Markup:
```

Pass it through in the `_fragment` call at 15545 — add one line after `group=group,`:

```python
        group=group,
        describedby=describedby,
```

And in the `_HILL` template opener (15450-15453), add the attribute before the role split:

```
<span data-hill="{{ ladder }}"
      class="hill{% if control %} hill-control{% endif %}{% if dim %} hill-off{% endif %}"
     {% if describedby %}aria-describedby="{{ describedby }}"{% endif %}
     {% if live %}role="radiogroup" aria-label="{{ label }}"
     {% else %}role="img" aria-label="{{ said }}"{% endif %}>
```

Every existing caller (12038, 16225, 19294-19297) omits it and renders byte-identically.

- [ ] **Step 6: `_CONTROL` gains `disabled` and `placeholder`, and loses its dead status arm.** Replace lines 11785-11803 (through the end of the select branch) — the `{% elif %}` branches below stay, each gaining `{% if f.disabled %}disabled{% endif %}`, and the final text branch also gains the placeholder. The status arm of the select is deleted because it has been unreachable since the hill landed — `_control_html` intercepts `f.type == "status"` before `_CONTROL` is ever rendered — and this file's own note at 12044 says what dead code that still renders becomes. Full new template:

```python
_CONTROL = """
{% if f.type == "priority" %}
<select name="{{ f.name }}" id="{{ f.id }}" data-type="text" class="field"
        {% if f.disabled %}disabled{% endif %}
        {% if f.gates %}data-required-at="{{ f.gates|join(' ') }}"{% endif %}>
  {#- The mark in front of the word, the same one the graph draws on a node and
      the table draws in a cell — jcanton, 2026-08-20: "can we have the status and
      priority icons and colours also in the dropdowns for editing a record".
      Status used to share this branch and left when it became the hill; priority
      keeps the native `<select>`, and the mark-as-text is the honest cost of
      keeping one. -#}
  {% for s in priorities %}
  <option value="{{ s }}" {% if s == f.value %}selected{% endif %}>{{
    mark(f.type, s) }}{{ s|human }}</option>
  {% endfor %}
</select>
{% elif f.type == "bool" %}
<input type="checkbox" name="{{ f.name }}" id="{{ f.id }}" data-type="bool" class="field"
       {% if f.disabled %}disabled{% endif %}
       {% if f.value %}checked{% endif %}>
{% elif f.type == "date" %}
<input type="date" name="{{ f.name }}" id="{{ f.id }}" data-type="date" value="{{ f.text }}"
       class="field"
       {% if f.disabled %}disabled{% endif %}
       {% if f.gates %}data-required-at="{{ f.gates|join(' ') }}"{% endif %}>
{% else %}
<input name="{{ f.name }}" id="{{ f.id }}" data-type="{{ f.type }}" value="{{ f.text }}"
       class="field" autocomplete="off"
       {% if f.placeholder %}placeholder="{{ f.placeholder }}"{% endif %}
       {% if f.disabled %}disabled{% endif %}
       {% if f.list %}data-suggest="{{ f.list }}"{% endif %}
       {% if f.gates %}data-required-at="{{ f.gates|join(' ') }}"{% endif %}>
{% endif %}
"""
```

Keep the comment block that precedes `_CONTROL` (11782-11783, about `<dt>`/`<dd>` and `<label for>`) untouched.

- [ ] **Step 7: `_control_html` takes the ladder, the lock and the shown word as parameters.** Replace the whole function (12008-12040). The first comment paragraph survives; the parameters and the disabled hidden input are new; `statuses=STATUSES` disappears from the `_fragment` call because the branch that read it is gone:

```python
def _control_html(
    field: dict,
    *,
    ladder: str = "entity",
    live: bool = True,
    shown: str | None = None,
    describedby: str = "",
) -> Markup:
    # Status is the one field whose control is not a box. It is the hill, and the
    # `<select>` that was here is gone rather than kept beside it: `render.py`'s
    # header already carries the note about what the same word in the same colour
    # twice costs, and a dropdown under a hill that sets the same field is that
    # note again with an extra control.
    #
    # The hidden input, and not the radios, is what the form serialises. `CONTROLS`
    # is `querySelectorAll('[data-type]')` keyed by `name`, so five radios sharing
    # one name would leave `ORIGINAL` holding a single entry and `changed()`
    # answering for whichever radio it read last. `markRequired` and the create
    # form's refusal both ask `[name=status]` for a value and neither has to know
    # that the thing behind it became a picture.
    #
    # `shown` is the word the picture draws; the input keeps the stored one. They
    # differ only on a locked control, where the state is derived from a link —
    # the read view already shows the derived word, and "pressing Edit moves
    # nothing" is a promise this row makes two comments up.
    if field["type"] == "status":
        return Markup(
            # No `.field`: that class is what `.entity.editing .field { display:
            # block }` switches on, and a hidden input is the one control that must
            # not gain a box when the form opens. `CONTROLS` reads `[data-type]`,
            # which is the attribute that matters here.
            '<input type="hidden" name="{}" id="{}" data-type="text"'
            ' value="{}" data-word="{}"{}>{}'
        ).format(
            field["name"],
            field["id"],
            field["value"],
            _human(field["value"]),
            # `disabled` on the input as well as no stops on the hill. The form's
            # own serialiser never sends an unchanged field, so this submits
            # nothing differently — it is the DOM saying what the page means, so
            # a test can ask the input rather than inferring the lock from an
            # absence of radios.
            Markup(" disabled") if not live else Markup(""),
            # Grouped by the control's own id. The static export puts every entity
            # in one file, and one group name would have made four hundred records
            # share a single radio group — pressing a stop on one moves the ball on
            # all of them.
            _hill_html(
                shown if shown is not None else field["value"],
                ladder,
                live=live,
                control=True,
                group=f"hill-{field['id']}",
                describedby=describedby,
            ),
        )
    return _fragment(_CONTROL, f=field, priorities=PRIORITIES)
```

Two notes for the implementer. `Markup(" disabled")` is a literal constant, not data, so it does not open a second escaping boundary — every value that came from a file still goes through `.format()`'s escaping. And `control=True` is not a behaviour change on the live path: `_hill_html` already computes `control=control or live` (15550), so the emitted class set is identical; it matters only when `live=False`, where the locked hill must still hide in read mode the way the promoted note's does (`render.py:2640-2649`).

- [ ] **Step 8: `EDITABLE`, `LABELS`, `SUGGESTS` gain the new fields.** In `EDITABLE` (15268-15284), insert the two person fields after `"owner"` and the two link lists after `"depends_on"` — the dict's order is the page's order, and this reproduces today's issue page top-to-bottom (title, status, reported_by, pitched_into, tags) and note page (title, status, written_by, became, tags) once the kinds exist:

```python
EDITABLE: dict[str, str] = {
    "title": "text",
    "status": "status",
    "owner": "text",
    # An issue's and a note's "who to ask". Inert on every kind in the tree
    # today — `_editable_for` intersects with `model_fields`, and no model
    # carries these until Issue and Note become entities — which is the point:
    # the pipeline is ready before the kinds arrive, so the flip commit adds
    # rungs and deletes pages without touching a form.
    "reported_by": "text",
    "written_by": "text",
    "assignees": "list",
    "reviewers": "list",
    "review_waived": "bool",
    "assigned_on": "date",
    "priority": "priority",
    "cycle": "number",
    "parent": "text",
    "depends_on": "list",
    # The two one-way edges an inbox record carries; rendered through `_links`
    # like `depends_on`, which is links rather than the bare ids both old pages
    # printed. Inert today, same as the pair above.
    "pitched_into": "list",
    "became": "list",
    "tags": "list",
    "prs": "list",
    "person_weeks": "number",
    "shaped_by": "list",
}
```

In `LABELS` (15993), after the `"shaped_by": "Shaped by",` line, add (the last two are for derived rows, not controls — one map for every word a reader gets, which is this map's charter):

```python
    "reported_by": "Reported by", "written_by": "Written by",
    "pitched_into": "Pitched into", "became": "Became",
    "opened_on": "Opened on", "written_on": "Written on",
```

In `SUGGESTS` (16117), after the `"parent": "entities", "depends_on": "entities",` line, add:

```python
    "reported_by": "people", "written_by": "people",
    "pitched_into": "entities", "became": "entities",
```

Leave `PEOPLE_FIELDS` (16113) alone: it feeds the suggestion pool, and widening that pool over `records` is the inversion commit's listed work, not this one's.

- [ ] **Step 9: `_editable_for` learns whose login fills the stamp fields.** Replace the signature and the dict comprehension's `"list": ...` line region (16127-16160). The whole function with its changes:

```python
# The two fields whose empty box says who the server will write. The placeholder
# is the signed-in login because that is the value `POST /api/entity` stamps when
# the box is left empty — a hint that tells the truth about what will happen.
_LOGIN_PLACEHOLDER = ("reported_by", "written_by")


def _editable_for(entity: Entity, prefix: str = "field", signed_in: str = "") -> list[dict]:
    """The fields this kind actually has, with the type a form must coerce back to.

    The prefix is what makes a control's id unique on the page it lands on: the
    static detail export holds every entity in one file, so `owner` alone would
    be the same id sixteen times over and every `<label for>` on the page would
    point at the first of them.
    """
    return [
        {
            "name": name,
            "id": f"{prefix}-{name}",
            "type": kind,
            "value": getattr(entity, name),
            "gates": REQUIRED_AT.get(name, ()),
            "list": SUGGESTS.get(name),
            "placeholder": signed_in if name in _LOGIN_PLACEHOLDER else "",
            "text": ", ".join(str(v) for v in getattr(entity, name))
            if kind == "list"
            else ("" if getattr(entity, name) is None else getattr(entity, name)),
        }
        for name, kind in EDITABLE.items()
        # What the kind has, minus what its rung does not read. A product
        # inherits every field an entity has and is a container: offering a box
        # for an owner it will then be warned about is the form and the validator
        # disagreeing in the most annoying possible order.
        if name in type(entity).model_fields
        and name not in unread_fields(entity.kind)
        # And nothing to file the top rung under. Not routed through
        # `unread_fields`: a parent written on a product is already reported, by
        # the containment rule that knows what it may be filed under, and two
        # warnings about one field is one of them being noise.
        and not (name == "parent" and not PARENT_KINDS[entity.kind])
    ]
```

The default `signed_in=""` renders no `placeholder` attribute anywhere (Jinja's `{% if f.placeholder %}`), so `_new_rows()` at 16630 and every current caller are unchanged. Threading the real login down from `web.py` is Task 6/8's wiring; the slot exists from here on.

- [ ] **Step 10: `_fact_rows` — the read display is `state()`, the lock is one condition, the hint is one sentence.** Four edits inside 16181-16286. First, the signature and loop head (16181, 16203):

```python
def _fact_rows(index: Index, entity: Entity, links: Links, signed_in: str = "") -> list[dict]:
```

```python
    for field in _editable_for(entity, entity.id, signed_in):
        name = field["name"]
        if name == "title":
            continue
        control = None
        hint = ""
        hint_id = ""
        if name == "depends_on":
```

Second, a new branch for the two link lists, inserted directly after the `parent` branch (after line 16213):

```python
        elif name in ("pitched_into", "became"):
            # Links, not the bare ids the two old pages' edit boxes held: the
            # question a reader asks of this row is "what did it become", and an
            # id is not an answer anybody can press.
            display = _links(getattr(entity, name), index, links) or empty
```

Third, replace the status branch (16218-16225):

```python
        elif name == "status":
            # The ball on the hill, and not the chip the table wears. The chip says
            # the word; the hill says the shape the word means — `shaping` and
            # `in_progress` are one rung apart on a ladder and opposite sides of a
            # hill, which is the distinction the whole method turns on and the one
            # a list cannot draw. Read-only here and live in `control`, the same
            # row and the same picture, so pressing Edit moves nothing.
            #
            # The word is `state()`, never `status`: an issue whose pitch has
            # shipped would otherwise read "ready" on its own page. Over `records`
            # because a derived state may follow a link to any kind. For every
            # planned kind `Entity.state` answers `status`, so no page in the tree
            # changes until a kind that derives exists.
            ladder = _LADDER_OF.get(entity.kind, "entity")
            said = entity.state(index.records)
            display = _hill_html(said, ladder)
            # The lock, expressed once. A derived state cannot also be set by
            # hand — two ways to say one thing disagree the moment one is used —
            # so the control keeps the derived picture, loses its stops, and the
            # hint says where the word comes from. `state() != status` and not
            # the old pages' `bool(pitched_into)`: a link whose targets are all
            # dangling derives nothing and should stay fixable, and a stored
            # word that equals the derived one is harmless to retype.
            if said != entity.status:
                hint = _STATE_HINT.get(entity.kind, "")
                hint_id = f"hint-{field['id']}" if hint else ""
            control = _control_html(
                field,
                ladder=ladder,
                live=said == entity.status,
                shown=said,
                describedby=hint_id,
            )
```

Fourth, the row dict (16276-16285) gains the hint keys, and `control` uses the override:

```python
                "for": "" if name == "status" else field["id"],
                "display": display,
                "control": control if control is not None else _control_html(field),
                "gates": field["gates"],
                "derived": False,
                # Only a locked status row carries these; the other appends in
                # this function omit them, and Jinja reads a missing key as
                # falsy, which is the correct answer for "no hint".
                "hint": hint,
                "hint_id": hint_id,
                # "Review waived: no" is a line that says nothing. The row still
                # exists while editing, because turning the waiver on is the whole
                # point of having it; it just does not clutter the read view.
                "editing_only": name == "review_waived" and not entity.review_waived,
```

Fifth, the two creation stamps as derived rows — insert directly after the `for field ...` loop closes (before the `overrun = (` block at 16287):

```python
    # The server's two creation stamps, shown and never offered. `opened_on` and
    # `written_on` are set by `POST /api/entity` when the record is made; a box
    # for one would invite a hand-typed lie about the file's own history. Guarded
    # on the model rather than the rung, so these lines are inert until the kinds
    # that carry them exist.
    for stamped in ("opened_on", "written_on"):
        if stamped in type(entity).model_fields:
            written = getattr(entity, stamped)
            rows.append(
                {
                    "label": LABELS[stamped],
                    "for": "",
                    "display": escape(_read_date(written.isoformat())) if written else empty,
                    "control": "",
                    "gates": (),
                    "derived": True,
                    "editing_only": False,
                }
            )
```

- [ ] **Step 11: the `<dd>` row in `_DETAIL` gains the hint slot.** At 13261-13266, the row currently reads:

```
        <dd class="{% if row.derived %}derived{% endif %}
                   {% if row.editing_only %}editing-only{% endif %}">
          <span class="read">{{ row.display }}</span>
          {% if editable and row.control %}{{ row.control }}{% endif %}
        </dd>
```

Replace with:

```
        <dd class="{% if row.derived %}derived{% endif %}
                   {% if row.editing_only %}editing-only{% endif %}">
          <span class="read">{{ row.display }}</span>
          {% if editable and row.control %}{{ row.control }}{% endif %}
          {#- Why this value is what it is, when it is derived from a link: "from
              the work it was pitched into", "from what it became". Outside both
              the `.read` span and the control, so it reads in both modes — the
              two pages this copy comes from showed it in both. The id is what
              the locked control's `aria-describedby` points at, so the sentence
              reaches a screen reader as the control's own description and not
              only as nearby text. -#}
          {% if row.hint %}<span class="hint" id="{{ row.hint_id }}">{{ row.hint }}</span>
          {% endif %}
        </dd>
```

No stylesheet work: `.hint { color: var(--muted); font-size: 12px; }` is the shell's (render.py:2626) and every page inherits it — the same rule the issue and note pages' hints wear today.

- [ ] **Step 12: local check, commit, push, read CI.** Do not run pytest — not the new tests, not one of them; the red/green gate is CI (`.github/workflows/ci.yml` runs `uv run pytest -q` with real Chrome and node). Locally:

```bash
cd /Users/jcanton/projects/openproj/.worktrees/one-record-one-page
uv sync
uv run ruff check .
```

Fix anything ruff names (the import orderings in both files are the likely candidates), then:

```bash
git add src/openproj/render.py tests/test_hill.py
git commit -F- <<'MSG'
A status control takes its ladder, its lock and its hint from the record

The entity ladder was hardcoded into the one status control the shared
page has, the five status words were written out a second time eleven
lines from a comment about what hand copies cost, and the lock a derived
state needs lived twice — a disabled <select> on the issue page, a
stopless hill on the note page — with different copy and different rules.

Now the control is parameterised: _control_html takes the ladder, a live
flag and the word to draw; _CONTROL takes disabled and placeholder; the
fact row reads state() over records instead of status, locks the control
when the two words disagree, and says why in the pages' own sentences,
wired to the control with aria-describedby rather than left as nearby
grey text. HILL_LADDERS gains the issue ladder — all four ISSUE_STATUS
words already had stops, so the last of #67's asymmetry goes with it —
and STATUSES becomes an alias of the validator's STATUS_ORDER.

All of it is inert until the flip commit: EDITABLE is intersected with
each model's fields and no model carries the new ones yet, and every
planned kind's state() answers its status, so no rendered byte changes.
The spec's issue-whose-pitch-is-done test is written complete and armed
on the issue rung; the lock, the hint slot and the DOM-level disable are
exercised today through a subclass that derives its state, which is also
all an Issue will be.

🤖 Written by an agent on behalf of @jcanton
MSG
git push -u origin one-record-one-page
gh run list --branch one-record-one-page --limit 1
```

Then read the run (`gh run watch <id>` or `gh run view <id> --log-failed`) and fix on the branch if it is red. While it runs, move on — the answer arrives in about thirteen minutes and watching it is not work.

---

### Task 4: What may be written is derived from the ladder

Spec section 3, the route half (build-order commit 4). Independent of the model flip: `KINDS` still holds four rungs here, so nothing user-visible changes for issues and notes — this commit makes the write path read the ladder instead of three hand-written copies of it, and repairs one real hole doing so. All line numbers below are as the files stand at `bf14b0a`, before this task's own edits shift them.

**Files:**
- Modify: `src/openproj/web.py:71-103` (the `from .model import (…)` block — add `RUNG`)
- Modify: `src/openproj/web.py:137` (`ID_PATTERN`, hand-written today)
- Modify: `src/openproj/web.py:145` (after `PREFIX` — add the inverse map)
- Modify: `src/openproj/web.py:646-664` (`_reject_bad_types` — the new gate goes directly after it)
- Modify: `src/openproj/web.py:815-823` (`_directory_for` — split out `_kind_for`)
- Modify: `src/openproj/web.py:1976-1977` (the PATCH route's field checks)
- Modify: `src/openproj/web.py:2352-2358` (the POST route's field checks)
- Modify: `src/openproj/web.py:3044-3048` (the socket's `save` frame checks)
- Test: `tests/test_web.py` (insert after `test_a_new_entity_is_held_to_the_current_rules`, which ends at line 1070)
- Test: `tests/test_product.py` (append at end of file, line 329)
- Test: `tests/test_coedit.py` (insert after line 517, the end of `test_a_save_the_model_could_not_read_back_is_refused_and_writes_nothing`)

**Interfaces:**
- Consumes: `Rung.statuses: tuple[str, ...]` and `RUNG: dict[str, Rung]` from Task 1 — `product` carries `statuses=()`, `project`/`pitch`/`task` carry `STATUS_ORDER`. Also `KINDS: tuple[Rung, ...]` (`model.py:979`), which `web.py` already imports (line 74) and already derives `DIRECTORY` (140) and `PREFIX` (145) from.
- Produces: `ID_PATTERN` derived from `KINDS` — when Task 8 adds the issue and note rungs, `PATCH`/`DELETE /api/entity/{id}` accept their ids with no edit here. `_kind_for(entity_id: str) -> str` — the id-to-rung lookup Task 8's routes reuse. `_reject_bad_status(kind: str, fields: dict) -> None` — the generic gate that lets Task 8 delete `_reject_bad_issue` (web.py:584) and `_reject_bad_note` (web.py:597) along with their routes. **Do not delete those two here** — `POST /api/issue` (1366) and `POST /api/note` (1476) still call them, and they die together in Task 8.

Background you need before editing, verified against the tree:

`web.py:137` reads, today:

```python
ID_PATTERN = re.compile(r"^(proj|pitch|task)-[0-9a-f]{6}$")
```

Three kinds, hand-written — while three lines below it `DIRECTORY` and `PREFIX` are derived from `KINDS`, and `PREFIX`'s own comment records that this exact split already bit once ("The SEVENTH copy… `POST /api/entity` with `kind: product` got past the models and fell over here instead"). The drift is live and user-visible right now: `prod` is missing from the pattern, `POST /api/entity` happily mints `prod-xxxxxx` ids (it goes through `PREFIX`, which is derived), and then `_directory_for` (web.py:815) answers 400 `"'prod-…' is not an entity id"` to every `PATCH` and `DELETE` on the id it just minted. A product can be created and never edited or removed again. Deriving the pattern repairs that, and the commit message must say so — it is a behavioural fix riding a refactor, and a reviewer has to be told.

The status vocabulary has three doors and three different answers today. `POST /api/entity` refuses an undefined status, but sideways — `validate_all` reports it as a blocker and the route answers a `{"problems": […]}` 422. `PATCH /api/entity/{id}` (web.py:1936) does not refuse it at all: its checks are `_reject_bad_types` (no status check), `parse_text` (whose `_as_written` validator, model.py:897, deliberately accepts any string so a file already in git still loads), and `loop_made` — no `validate_all` — so `{"status": "banana"}` **commits**, and the plan wakes up with a blocker on a protected branch. The socket's `save` frame (web.py:3040-3049) calls only `_reject_bad_types`. One gate, called at all three doors, closes this; the bespoke `_reject_bad_issue`/`_reject_bad_note` keep guarding their own routes until Task 8.

A product is the proof case for `statuses=()`. Today `status: ready` on a product is accepted and *warned about* — `unread_fields` puts `status` in the unread list, model.py's rule at 2221-2245 yields `("warning", "status", "a product is a grouping…")`, and `test_a_container_has_no_work_state_to_gate` (test_product.py:228) pins it at the file level. The API door must keep answering the same: 201, warning beside the record, never a 422 — an unread field is not a wrong field, and hand-written files are first-class here. So the gate is silent when `rung.statuses` is empty.

- [ ] **Step 1: Write the both-doors vocabulary test (spec test 4).** In `tests/test_web.py`, insert after line 1070 (the `assert git_head(repo_path) == base` that ends `test_a_new_entity_is_held_to_the_current_rules`), leaving two blank lines each side. `client`, `repo_path`, `create`, `save`, `git_head`, `TASK` and `VALID_TASK` are all already in this file's scope (fixtures at 187-211, helpers at 237-280, `VALID_TASK` at 973):

```python
def test_a_status_nobody_defined_is_refused_at_both_doors(
    client: TestClient, repo_path: Path
):
    """POST refused it sideways, as a `problems` list out of `validate_all`;
    PATCH did not refuse it at all. `parse_text` deliberately takes any word so
    that a file which arrived in git with one still loads, and the PATCH route
    never asked the vocabulary — so `status: banana` committed, and the plan
    woke up with a blocker about it on a branch where the commit cannot be
    force-pushed away. One gate now, read off the rung, on every door, and its
    answer is one sentence naming the field.
    """
    base = git_head(repo_path)

    made = create(client, {**VALID_TASK, "status": "banana"})
    assert made.status_code == 422
    assert "status" in made.json()["detail"]
    assert "'banana'" in made.json()["detail"]
    assert "expected one of" in made.json()["detail"]

    saved = save(client, TASK, {"status": "banana"})
    assert saved.status_code == 422
    assert "status" in saved.json()["detail"]
    assert "'banana'" in saved.json()["detail"]

    assert git_head(repo_path) == base, "a refusal writes nothing"
```

- [ ] **Step 2: Write the product tests.** Append both to the end of `tests/test_product.py` (after line 329). They follow the file's own pattern — `test_a_product_can_be_made_through_the_api` at line 280 does its imports inside the function and builds its own client — because this file predates the `test_web` fixtures and imports them piecemeal on purpose. First, the `statuses=()` half of the gate — what a status on a product does today, kept:

```python
def test_a_status_on_a_product_still_warns_rather_than_refuses(tmp_path: Path):
    """The `statuses=()` half of the write gate: a kind that does not read the
    field gets no vocabulary check at the door. `status: ready` written into a
    product's file by hand is a warning beside the record, not a refusal
    (`test_a_container_has_no_work_state_to_gate` above), and the API door has
    to answer the same — 201 with the warning — or the two ways of writing a
    record stop being equal, which the README calls first-class on purpose.
    """
    import pygit2
    from fastapi.testclient import TestClient
    from test_store import commit_directly
    from test_web import ANN, SECRET, SEED, SESSION_COOKIE, sign_session

    from openproj.web import create_app

    plan = tmp_path / "plan.git"
    pygit2.init_repository(str(plan), bare=True, initial_head="main")
    commit_directly(plan, SEED, "seed")

    with TestClient(create_app(plan, auth="dev", secret=SECRET)) as client:
        client.cookies.set(SESSION_COOKIE, sign_session(ANN, SECRET))
        head = client.get("/healthz").json()["head"]
        made = client.post(
            "/api/entity",
            json={"base_commit": head,
                  "fields": {"kind": "product", "title": "gt4py", "status": "ready"},
                  "body": "The DSL under icon4py.\n"},
        )
        assert made.status_code == 201, made.json()
        product = made.json()["id"]
        said = [
            (p["severity"], p["field"])
            for p in client.get("/api/index.json").json()["problems"]
            if p["entity_id"] == product
        ]
        assert said == [("warning", "status")], said
```

Then the ride-along fix, driven end to end:

```python
def test_a_product_can_be_patched_and_deleted(tmp_path: Path):
    """`ID_PATTERN` was hand-written as three kinds while `PREFIX` three lines
    under it was derived, so `POST /api/entity` minted `prod-` ids that
    `_directory_for` then answered 400 to: a product could be created and never
    edited or removed again. The pattern is derived from `KINDS` now; this
    drives both doors that opens.
    """
    import pygit2
    from fastapi.testclient import TestClient
    from test_store import commit_directly
    from test_web import ANN, SECRET, SEED, SESSION_COOKIE, sign_session

    from openproj.web import create_app

    plan = tmp_path / "plan.git"
    pygit2.init_repository(str(plan), bare=True, initial_head="main")
    commit_directly(plan, SEED, "seed")

    with TestClient(create_app(plan, auth="dev", secret=SECRET)) as client:
        client.cookies.set(SESSION_COOKIE, sign_session(ANN, SECRET))
        head = client.get("/healthz").json()["head"]
        made = client.post(
            "/api/entity",
            json={"base_commit": head,
                  "fields": {"kind": "product", "title": "gt4py"},
                  "body": "The DSL under icon4py.\n"},
        )
        assert made.status_code == 201, made.json()
        product = made.json()["id"]

        renamed = client.patch(
            f"/api/entity/{product}",
            json={"base_commit": made.json()["commit"],
                  "fields": {"title": "gt4py-next"}, "body": None},
        )
        assert renamed.status_code == 200, renamed.json()
        entities = client.get("/api/index.json").json()["entities"]
        assert entities[product]["title"] == "gt4py-next"

        gone = client.request(
            "DELETE", f"/api/entity/{product}",
            json={"base_commit": renamed.json()["commit"]},
        )
        assert gone.status_code == 200, gone.json()
        assert client.get(f"/detail/{product}").status_code == 404
```

- [ ] **Step 3: Write the socket-door test.** The room writes through the same gate as PATCH — the comment on `writer` inside `coedit_socket` (web.py:2835-2840) says exactly that, and `test_a_save_the_model_could_not_read_back_is_refused_and_writes_nothing` (test_coedit.py:501) already pins it for types. Insert this directly after that test (after line 517, before `test_a_commit_made_in_git_arrives_in_the_room_as_text`); `client`, `plan`, `open_room`, `Session` and `log_of` are the file's own (lines 62-121):

```python
def test_a_status_the_kind_does_not_speak_is_refused_at_the_socket_too(
    client: TestClient, plan: Path
):
    """The vocabulary gate, at the third door. The room's save frame ran only
    `_reject_bad_types`, which does not look at `status`, so the one word the
    PATCH route now refuses could still be committed by whoever had the
    co-editing page open."""
    before = len(log_of(plan))
    with open_room(client, "ann") as one:
        ann = Session(one, "ann")
        ann.hello()
        # Non-ASCII on purpose: the byte-offset splice path is exercised even
        # here, where the claim is about the field gate — ASCII-only corpora are
        # how the last three data-loss defects shipped.
        ann.type(0, "ẞ—")
        ann.save({"status": "banana"})
        refused = ann.take("refused")
        assert "status" in refused["why"]
        assert "'banana'" in refused["why"]
        # Inside the room, because leaving it commits the body — which is the
        # right thing to do with text that is only refused as a *field*.
        assert len(log_of(plan)) == before, "a refusal writes nothing"
```

- [ ] **Step 4: Import `RUNG` into `web.py`.** In the `from .model import (` block (lines 71-103), add one line between `PEOPLE_DIR,` (line 78) and `Config,` (line 79) — ruff's isort sorts uppercase names before classes, so this is where `I` rules want it:

```python
    PEOPLE_DIR,
    RUNG,
    Config,
```

- [ ] **Step 5: Derive `ID_PATTERN` from `KINDS`.** Replace line 137 (quoted above) with:

```python
# Derived from the ladder, like `DIRECTORY` and `PREFIX` below it. Hand-written,
# it was three kinds, and the drift was user-visible: `prod` was missing, so
# `POST /api/entity` minted product ids (that route reads `PREFIX`, which was
# already derived) that `_directory_for` then answered 400 to — a product could
# be created and never patched or deleted. `\A`/`\Z` and not `^`/`$` because in
# Python `$` also matches before a trailing newline, and this pattern is what
# keeps an id out of paths — `task-a1b2c3\n` must not become
# `tasks/task-a1b2c3\n.md`.
ID_PATTERN = re.compile(r"\A(" + "|".join(rung.prefix for rung in KINDS) + r")-[0-9a-f]{6}\Z")
```

(`prod` and `proj` are both followed by a literal `-` in the pattern, so the four-character prefixes cannot shadow one another.)

- [ ] **Step 6: Add the inverse prefix map.** Directly after `PREFIX = {rung.name: rung.prefix for rung in KINDS}` (line 145), add:

```python
# And back again: the rung an id names, read off its prefix. The inverse of
# `PREFIX`, derived beside it, for the two questions a bare id has to answer —
# which directory its file lives in, and which status vocabulary judges a write
# to it.
KIND_OF_PREFIX = {rung.prefix: rung.name for rung in KINDS}
```

- [ ] **Step 7: Split `_kind_for` out of `_directory_for`.** Replace the whole of `_directory_for` (lines 815-823, quoted here so you can match it exactly):

```python
def _directory_for(entity_id: str) -> str:
    """The directory an id belongs in, or a refusal. The one place an id becomes
    part of a path — everything else must come through here."""
    if not ID_PATTERN.match(entity_id):
        raise HTTPException(400, f"{entity_id!r} is not an entity id")
    prefix = entity_id.split("-")[0]
    kind = next(k for k, p in PREFIX.items() if p == prefix)
    return DIRECTORY[kind]
```

with:

```python
def _kind_for(entity_id: str) -> str:
    """The rung an id names, or a refusal. With `_directory_for` under it, the
    one place a bare id is trusted to mean anything."""
    if not ID_PATTERN.match(entity_id):
        raise HTTPException(400, f"{entity_id!r} is not an entity id")
    return KIND_OF_PREFIX[entity_id.split("-")[0]]


def _directory_for(entity_id: str) -> str:
    """The directory an id belongs in, or a refusal. The one place an id becomes
    part of a path — everything else must come through here."""
    return DIRECTORY[_kind_for(entity_id)]
```

This is not a taste call: the PATCH gate in Step 9 needs a kind from an id, `_directory_for` already computed one, and "if a guard is the same three lines in two places, it is one helper" (AGENTS.md, The invariants).

- [ ] **Step 8: Add the generic status gate.** After `_reject_bad_types` (its last line, `raise HTTPException(422, "review_waived must be true or false")`, is line 664), before `async def _sent`, add:

```python
def _reject_bad_status(kind: str, fields: dict) -> None:
    """A status outside this kind's vocabulary, refused before anything commits.

    Off the ladder, which is what makes one gate safe where `_reject_bad_note`
    above argues a shared gate is not: its fear was a parameter, then an `if`,
    then a word admitted to the wrong record — and a vocabulary that travels on
    the rung has no `if` to get wrong. (Those two gates keep standing in front
    of their own routes until the routes go.) A kind with `statuses=()` does
    not read the field at all, so a word there is unread rather than undefined:
    the validator already warns about it beside the record, and refusing it
    here would make the API door stricter than the hand-written file it must
    stay equal to.
    """
    status = fields.get("status")
    if status is None or not RUNG[kind].statuses:
        return
    if status not in RUNG[kind].statuses:
        raise HTTPException(
            422,
            f"status: {status!r} is not a status for a {kind}: expected one of "
            f"{', '.join(RUNG[kind].statuses)}",
        )
```

The wording deliberately matches the validator's (`model.py:2315`: "is not a status for an issue: expected one of") — same refusal, same words, whichever door it comes out of.

- [ ] **Step 9: Call it on the PATCH door.** In `save` (`@app.patch("/api/entity/{entity_id}")`, line 1936), the field checks at 1976-1977 read:

```python
        fields = {k: v for k, v in _fields_in(payload).items() if k != "id"}
        _reject_bad_types(fields)
```

Add directly under them:

```python
        # `parse_text` below deliberately takes any word — a file that arrived
        # in git with one must still load — so without this the PATCH door
        # committed a status nobody defined, and the plan woke up with a
        # blocker about it on a branch where the commit cannot be force-pushed
        # away.
        _reject_bad_status(_kind_for(entity_id), fields)
```

(`entity_id` has already been through `ID_PATTERN` by here — `_path_for` at line 1947 called `_directory_for` — so `_kind_for` cannot 400 at this point; it is just the lookup.)

- [ ] **Step 10: Call it on the POST door.** In `create` (`@app.post("/api/entity")`, line 2345), directly after `_reject_bad_types(fields)` (line 2358; `kind` was validated against `DIRECTORY` four lines up), add:

```python
        # Before `validate_all` gets a say: the vocabulary refusal arrives as
        # one sentence naming the field — the same sentence PATCH and the room
        # give — rather than as a problems list that happens to mention it.
        _reject_bad_status(kind, fields)
```

- [ ] **Step 11: Call it on the socket door.** In `coedit_socket`'s `save` frame handler, lines 3044-3048 read:

```python
                    try:
                        _reject_bad_types(fields)
                    except HTTPException as refused:
                        _to(connection, {"t": "refused", "why": refused.detail})
                        continue
```

Extend the `try` body:

```python
                    try:
                        _reject_bad_types(fields)
                        # The room writes through the same gate as PATCH — the
                        # comment on `writer` above says exactly that — so the
                        # vocabulary stands here too.
                        _reject_bad_status(_kind_for(entity_id), fields)
                    except HTTPException as refused:
                        _to(connection, {"t": "refused", "why": refused.detail})
                        continue
```

(`entity_id` is the route parameter of `coedit_socket` and is in scope; the handshake already refused ids `_path_for` could not place.)

- [ ] **Step 12: Ruff, commit, push, read CI.** No pytest on this machine — not one file. From the worktree:

```bash
cd /Users/jcanton/projects/openproj/.worktrees/one-record-one-page
uv sync
uv run ruff check .
git add src/openproj/web.py tests/test_web.py tests/test_product.py tests/test_coedit.py
git commit -F- <<'MSG'
What may be written is derived from the ladder

Two fixes wearing one refactor, and a reviewer should read them separately.

The first is user-visible and rides along: ID_PATTERN was hand-written as
three kinds while PREFIX three lines under it was derived, so `prod` was
missing — POST /api/entity minted product ids that _directory_for then
answered 400 to, and a product could be created but never patched or deleted.
The pattern is derived from KINDS now (with \A/\Z, so an id with a trailing
newline cannot become a path), and when the issue and note rungs land their
ids are writable with no edit here.

The second is the status vocabulary, which had three doors and three answers.
POST refused an undefined word sideways, as a problems list; the co-editing
save frame checked types only; and PATCH did not refuse it at all —
parse_text deliberately takes any word so a file already in git still loads,
and the route never asked the vocabulary, so `status: banana` committed and
became a blocker on a protected branch. One gate now, _reject_bad_status,
reading RUNG[kind].statuses, called at all three doors before anything is
committed, answering 422 with the validator's own sentence. A kind with
statuses=() keeps today's behaviour exactly: a status on a product is unread,
warned about beside the record, and never refused — the API door stays equal
to the hand-written file. The bespoke issue and note gates keep guarding
their own routes; they are deleted with those routes, not before.

🤖 Written by an agent on behalf of @jcanton
MSG
git push -u origin one-record-one-page
gh run watch --exit-status || gh run view --log-failed
```

If CI is red, fix on the branch and push again; a red CI here is normal process, not failure. The three new tests must be in this commit, not a following one — the red/green gate is CI, but test-first-in-the-same-commit is still the rule.

---

### Task 5: A document is read without opening a session

Spec section 4, entire. Independent of goals 1 and 3 — shippable on its own, as one commit (build-order commit 5). Everything lands together: the machine, the seat fix, the four new spec tests (5–8), and the repointed existing pins, because the suite must be green on CI after this single commit.

**Files:**
- Modify: `src/openproj/render.py:10319-10330` (the `EDITOR.mode` read)
- Modify: `src/openproj/render.py:11637-11653` (`_viewbar`)
- Modify: `src/openproj/render.py:12049-12083` (`_VIEWS` header comment and consts)
- Modify: `src/openproj/render.py:12085-12162` (`showView`)
- Modify: `src/openproj/render.py:12574-12592` (`chooseView` + segment clicks)
- Modify: `src/openproj/render.py:12694-12697` (the chord), `12700-12707` (Escape), `12709-12746` (the load branch), `12748-12778` (the session listener)
- Modify: `src/openproj/render.py:13150-13169` (`_DETAIL` editbar), `13573-13606` (`showEditing`), `13608-13666` (`flipEditing` + bindings)
- Modify: `src/openproj/render.py:14609-14655` (`_COEDIT` connect/disconnect)
- Modify: `src/openproj/render.py:14753-14770` (`.views` CSS)
- Modify: `src/openproj/render.py:16719, 19066, 19311, 19669` (`views=` at the four render functions)
- Test: `tests/test_editor.py` (tests 6–8 + legacy-mode pin + rewritten pins)
- Test: `tests/test_seats.py` (test 5)
- Modify: `tests/test_coedit.py`, `tests/test_hill.py`, `tests/test_delete.py`, `tests/test_issues.py`, `tests/test_editor.py` (repointed pins; mechanical `toggle` migration)

**Interfaces:**
- Consumes: nothing from earlier tasks. Uses what is already in the tree: `showEditing(editing)` / `flipEditing()` (render.py:13573/13611), `_viewbar(switchable: bool, ace: bool) -> Markup` (11637), `_either_editor_possible(base_commit, may_write) -> bool` (760), the `openproj:session` CustomEvent (detail: bool), `remembered.{get,map,set,forget}` (2002), `Room`/`Rooms` in `coedit.py` (unchanged), `render_detail(index, links=STATIC, only=None, base_commit=None, may_write=False, editor="")` (19615).
- Produces: three view states `view | edit | both` where `view` is the sessionless landing; `?view` as a sessionless read link (the landing list task may link `/detail/{id}?view=` but plain `/detail/{id}` now lands sessionless anyway); `EDITOR.mode ∈ {edit, both}` with legacy `view` migrated on read; `connect()` at session start / disconnect at session end in `_COEDIT`; `_viewbar` returning `Markup("")` for non-writers. Commit 8 (the flip) relies on the issue/note redirects landing on this sessionless read page.

**The one deviation to know about before starting:** the `null` state is deleted on record pages but survives, deliberately and only, on the create form. `_NEW` has no stored document — no `.doc.read` — so it has nothing to land on; its way out of full page stays the old surface-off state until commit 6 absorbs `_NEW` into `_DETAIL`. The discriminator is structural: `LANDING = article.querySelector('.doc.read')`, present on `/detail`, `/issue/{id}`, `/note/{id}` (render.py:13297, 20093, 20447), absent on `/new`. Everything below branches on that one fact, and `null` becomes unreachable — greppably — wherever a landing exists. The Edit button (`#toggle`) is removed from `_DETAIL`: the switcher is the only door into a session, and two adjacent doors into one session are two controls nobody can tell apart. `flipEditing` stays — Cancel calls it, and it remains the programmatic door the tests and the room use. The issue and note pages keep their own hand-built toggles untouched; they are deleted whole in commit 8.

---

- [ ] **Step 1: `EDITOR.mode` stores only session modes; a legacy `view` migrates on read**

In `src/openproj/render.py`, line 10329, inside the `EDITOR` IIFE. Replace:

```js
    mode: one(held.mode, ['edit', 'both', 'view'], 'edit'),
```

with:

```js
    // Only the two session modes. `view` stopped being a session shape when
    // the landing state took its name: the same stored word meant "open
    // sessions in preview-only" yesterday and "the sessionless read page"
    // today, and a preference that changes meaning under a stored value is a
    // trap. A legacy `view` reads as `edit` — the nearest session — and is
    // rewritten the first time anything remembers.
    mode: one(held.mode === 'view' ? 'edit' : held.mode, ['edit', 'both'], 'edit'),
```

The long comment above it (10320–10328, jcanton's "select edit as default mode" quote) stays — it is still the reason the fallback is `'edit'`.

- [ ] **Step 2: `_VIEWS` header — three states, and the two structural consts**

Replace the Python comment paragraph at render.py:12058-12064 (the one beginning `# **A fourth state, which HackMD does not have.**`) with:

```python
# **Three states, and the landing one is `view`.** HackMD is always full page;
# here `view` is the ordinary page — the server-rendered document, the facts
# column, the nav alive — and it is where every session ends. `edit` and `both`
# are sessions and go full page. The fourth, unnamed state this used to carry
# is gone from every record page: exactly one segment is always pressed. The
# one exception is the create form, which has no stored document to land on —
# see `LANDING` and `GROUND` in the script below; that exception dies with
# `_NEW` when creating becomes a mode of the record page.
```

Then replace the JS at 12081-12083:

```js
// null is full page off. See the comment on `_VIEWS` in render.py for why there
// are four states here and three in the note this is modelled on.
let VIEW = null;
```

with:

```js
// The server-rendered document, present on every record page and absent on the
// create form — the structural fact the whole machine branches on. A page with
// a landing has a sessionless `view` state to come back to; the create form
// has nothing to read yet, so its way out of full page is the old surface-off
// state (`null`), kept only there and only until `_NEW` is absorbed.
const LANDING = VIEW_ARTICLE.querySelector('.doc.read');
// Where every exit lands: Escape, the pressed segment, the chord, and the end
// of a session all come here.
const GROUND = LANDING ? 'view' : null;
let VIEW = GROUND;
```

- [ ] **Step 3: `showView` — the machine itself**

Replace the whole function at render.py:12085-12162. Keep the long inert-loop comment (12095–12110), the corner-move comment block (12112–12131) and the seat-layer comment (12146–12151) verbatim — they are unchanged findings. The lines that change are marked; the function becomes:

```js
function showView(mode) {
  VIEW = mode;
  for (const name of VIEWS) {
    VIEW_ARTICLE.classList.toggle('view-' + name, mode === name);
    document.getElementById(VIEW_IDS[name]).setAttribute('aria-pressed', String(mode === name));
  }
  // Full page is what a SESSION looks like. On a record page `view` is the
  // landing — the ordinary page, nav alive — and never full; the create form
  // has no landing, so every view there is full and `null` is its off state.
  const full = LANDING ? (mode === 'edit' || mode === 'both') : mode !== null;
  VIEW_ARTICLE.classList.toggle('full', full);
  // The page behind a fixed, viewport-filling article has nothing left to show
  // and a scrollbar that scrolls it anyway is a scrollbar that moves nothing.
  document.body.classList.toggle('fullpage', full);
  /* ...KEEP the existing inert comment block (12095-12110) unchanged... */
  for (const covered of document.querySelectorAll('body > nav, body > a.skip')) {
    covered.inert = full;
  }
  /* ...KEEP the existing corner comment block (12112-12131) unchanged... */
  if (CORNER) (full ? VIEW_BAR : CORNER_HOME).append(CORNER);
  // One mechanism for whether the preview pane is on the page, and it is the
  // `hidden` attribute the pane was drawn with. The landing does not use the
  // pane at all: the server already rendered this document into `.doc.read`
  // through the same `_markdown`, and a pane here would be one `/api/preview`
  // round trip to redraw what is on the screen. The create form has no
  // rendered copy, so its `view` still previews the draft.
  VIEW_PANE.hidden = mode === null || mode === 'edit' || (LANDING && mode === 'view');
  // The machine owns the session on the pages that have both: `edit` and
  // `both` ARE sessions, so entering one opens it, and the landing is
  // sessionless, so landing ends it. `VIEW` is already set above, which is
  // what keeps the `openproj:session` listener below out of the loop. The
  // create form has no `showEditing` and never leaves editing; the issue and
  // note pages bring their own.
  if (LANDING && typeof showEditing === 'function') {
    const editing = VIEW_ARTICLE.classList.contains('editing');
    if (full && !editing) showEditing(true);
    if (mode === 'view' && editing) showEditing(false);
  }
  /* ...KEEP the existing seat-layer comment (12146-12151) unchanged... */
  dispatchEvent(new Event('openproj:editing'));
  // The width handle belongs to the measure, and full page has none. `place`
  // is the detail page's; the create form has no grip and no such function.
  if (typeof place === 'function') place();
  applySplit();
  sourcePoints = null;
  refreshPreview(true);
}
```

What is deliberately gone: the `showEditing(true)`-only block ("A view of the document is a way into editing it") — a view is no longer always a way into editing; and `mode !== null` as the full-page test — `null` no longer exists where a landing does.

- [ ] **Step 4: `chooseView`, the segments, the chord, Escape — every exit lands on `GROUND`**

At render.py:12581-12592 replace:

```js
function chooseView(mode) {
  showView(mode);
  rememberEditor({mode});
}

for (const name of VIEWS) {
  // Pressing the pressed segment is how you come back out with a pointer, which
  // is the same gesture as the chord below and the only one that needs no
  // fourth control on the bar.
  document.getElementById(VIEW_IDS[name]).onclick =
    () => chooseView(VIEW === name ? null : name);
}
```

with:

```js
function chooseView(mode) {
  showView(mode);
  // Only a session mode is a preference. `EDITOR.mode` answers one question —
  // which view a session opens in — and leaving a session is not an answer to
  // it: recording the exit would take the split away from somebody who edits,
  // lands back on the page, and edits again.
  if (mode === 'edit' || mode === 'both') rememberEditor({mode});
}

for (const name of VIEWS) {
  // Pressing the pressed segment is how you come back out with a pointer — to
  // the landing where the page has one, to the old surface-off state on the
  // create form, which has no landing to come back to.
  document.getElementById(VIEW_IDS[name]).onclick =
    () => chooseView(VIEW === name ? GROUND : name);
}
```

At 12697 change the chord's last line from `chooseView(VIEW === mode ? null : mode);` to `chooseView(VIEW === mode ? GROUND : mode);` (the modifier-matching lines above it are untouched).

At 12703-12707 replace the Escape listener with:

```js
// Escape, arbitrated: see the block in `attachEditing` that dispatches this.
// Answered here only when there is a session view to leave, so on the landing
// — and on the create form's ordinary page — the hatch that gives Tab back
// opens on the first press. Leaving lands on `GROUND`: on a record page that
// is the sessionless landing, so Escape ends the session — and ends it
// without discarding anything, because the text stays in the surface and the
// draft store is the body-undo; only Cancel restores fields.
BODY.addEventListener('openproj:escaped', event => {
  if (VIEW === GROUND) return;
  event.preventDefault();
  showView(GROUND);
});
```

- [ ] **Step 5: the load branch and the session listener**

At render.py:12716-12746: keep `VIEW_ASKED` / `VIEW_LINKED` (12714-12715) and the "**A link beats the preference**" paragraph; replace everything from the "**The preference is applied when an editing SESSION starts**" paragraph through the `if (VIEW_LINKED) { ... }` block (12724-12746) with:

```js
// **The preference is applied when a session starts, not when the page
// loads.** Sticky-at-load would mean that after once choosing the split,
// every record anybody opened afterwards opened as a full-screen editor over
// a record they had come to read — and reading is the ordinary case.
if (VIEW_LINKED) {
  // `?view` is a sessionless read link: it lands on the page, not in a
  // session. `?edit` and `?both` are views OF a session and `showView` opens
  // the session they are views of — including for the editor switch, which
  // re-adds the flag when it reloads so the session survives the navigation.
  showView(VIEW_LINKED);
} else if (VIEW_ARTICLE.classList.contains('editing')) {
  // A session that existed before this script ran: a restored draft — the one
  // place where landing does not mean sessionless — or the create form, which
  // is always editing. It lands in the mode a session opens in.
  showView(EDITOR.mode);
} else {
  // The ordinary page IS a state now, with its segment pressed and the
  // switcher on it: the segments are the door into a session, and a door
  // drawn only inside the room it opens is not a door.
  showView('view');
}
```

Then replace the session listener and its comment block (12748-12778) with:

```js
// A session beginning or ending through any door this script did not open —
// the restored draft's `showEditing(true)` runs before this script, Cancel and
// the room's save run after it. One listener on the one event that means "a
// session began or ended", rather than a copy at every call site: an invariant
// written four times is an invariant guarded three. `VIEW` is set before
// `showView` touches the session, which is what keeps this from looping.
addEventListener('openproj:session', event => {
  if (event.detail && VIEW === GROUND) showView(EDITOR.mode);
  if (!event.detail && VIEW !== GROUND) showView(GROUND);
});
```

- [ ] **Step 6: the switcher is visible outside a session, and withheld from non-writers**

CSS at render.py:14753-14770. Replace the comment + two rules:

```css
/* Three states of one thing ... Hidden until the article is editing ... */
.views { display: none; }
/* No `overflow: hidden` ... */
.entity.editing .views {
  display: inline-flex; vertical-align: middle;
  border: 1px solid var(--line-strong); border-radius: 3px;
}
```

with one rule (keep the `overflow: hidden` comment verbatim between the two comment paragraphs):

```css
/* Three states of one thing, drawn as one control: adjacent segments inside a
   single bordered box, the pressed one filled. Visible outside a session as
   well as in one, because the segments ARE the door in: `edit` and `both`
   open the session they are views of, and a door drawn only inside the room
   it opens is not a door. A reader the server would refuse a write from gets
   no bar at all — `_viewbar` decides that — so there is no rule here for a
   page that should not have one. */
/* No `overflow: hidden` ...  (kept verbatim) */
.views {
  display: inline-flex; vertical-align: middle;
  border: 1px solid var(--line-strong); border-radius: 3px;
}
```

`.eswitch { display: none; }` / `.entity.editing .eswitch` (14813) stay as they are: the editor switch configures the session's surface and has nothing to say outside one.

`_viewbar` at 11637-11653 becomes:

```python
def _viewbar(switchable: bool, ace: bool) -> Markup:
    """The bar of controls that says how, and in what, this document is shown.

    The whole bar is withheld from a reader the server would refuse a write
    from. The segments are the only door into an editing session, so for a
    non-writer they would open an editor whose every save is a 403 — and the
    read page is already the whole page they came for. `switchable` carries
    that fact: `_either_editor_possible` is `base_commit and may_write`, and
    every template that renders this bar sits behind `{% if editable %}`, so
    within a rendered page it reduces to `may_write`.

    `ace` is which way the editor switch is set, which is `_ace_wanted`'s own
    answer, so the switch and the bytes cannot disagree.
    """
    if not switchable:
        return Markup("")
    return Markup(_VIEW_SEGMENTS + _EDITOR_SWITCH.format(checked="true" if ace else "false"))
```

And in all four render functions the view machine goes only to writers — at 16719 (`render_new`), 19066 (`render_issue`), 19311 (`render_note`), 19669 (`render_detail`) change:

```python
        views=_VIEWS,
```

to:

```python
        # The machine drives the segments; a non-writer has neither, or the
        # script would throw on `getElementById` of a control `_viewbar`
        # deliberately withheld.
        views=_VIEWS if may_write else Markup(""),
```

(the comment once, at `render_detail`; the bare expression at the other three).

- [ ] **Step 7: `_DETAIL` loses the Edit button — the switcher is the only door**

At render.py:13150-13169 replace the editbar block (both comment paragraphs and the `<p>`):

```
  {% if editable %}
  {#- The switcher is the way in: pressing Write or Write-and-preview opens
      the session it is a view of, so there is no Edit button beside it — two
      adjacent doors into one session are two controls nobody can tell apart.
      Delete is the other thing a writer may do to a record and it leaves the
      moment a session begins. The whole line is a writer's: a reader the
      server would refuse gets no door at all, which makes the read page the
      whole page for them instead of an editor whose every save is a 403. -#}
  {% if may_write %}
  <p class="editbar"><button type="button" class="delete">Delete</button>
    {{ viewbar }}</p>
  {% endif %}
```

(the closing `{% endif %}` of `editable` and everything after the editbar stay put; the old inner `{% if may_write %}` around Delete is folded into the outer one).

In `showEditing` (13573-13606) delete line 13585 and rewrite the comment above `cancel` (13578-13584):

```js
  document.getElementById('save').hidden = !editing;
  // Save and Cancel are the two ways one editing session ends, and they
  // arrive together at the top of the record. The way IN is the view switcher
  // on the editbar; the Edit button that used to be here was a second door
  // into the same session, one control's width from the first.
  document.getElementById('cancel').hidden = !editing;
```

At 13608-13610 replace the `flipEditing` comment:

```js
// Cancel's handler — and still the one programmatic door: called on a page in
// read mode it opens the session instead (the segments do the same through
// `showView`), which is what the tests and the room's plumbing drive it by.
// A second copy of what ending a session means is how two doors come to
// disagree about the draft.
```

and at 13665-13666 replace:

```js
document.getElementById('toggle').onclick = flipEditing;
document.getElementById('cancel').onclick = flipEditing;
```

with:

```js
document.getElementById('cancel').onclick = flipEditing;
```

The issue and note templates (`_ISSUE` 20048, `_NOTE` 20399) keep their own toggles — they are deleted whole in commit 8, not groomed here.

- [ ] **Step 8: the seat fix — `connect()` at session start, disconnect at session end**

In `_COEDIT`. Three edits:

At 14610 change `if (dead) return;` to `if (dead || !wanted) return;`.

In `socket.onclose` (14631-14642): after `if (dead) return;` insert `if (!wanted) return;`, and change the retry line to store its handle:

```js
      if (!arrived && attempts >= 4) return stop('');
      retry = setTimeout(connect, Math.min(30000, 500 * Math.pow(2, attempts++)));
```

Replace the bare `connect();` at 14645 (keep the `return {live, save(fields) {...}}` after it unchanged) with:

```js
  // --- when a seat is taken --------------------------------------------------
  //
  // At session start, never at script load. `connect()` ran right here, at
  // load, and that was a shipped bug with a cost at both ends of the wire: a
  // signed-in person who merely OPENED a record took a co-editing seat, was
  // listed to everyone else as "also editing", and left the server holding a
  // Room, a `_watch` task and an outbox task per record they visited, kept
  // warm for LINGER_SECONDS after they had gone. The landing list is a page
  // whose whole purpose is opening records; it would have multiplied that.
  //
  // Deferring is safe because nothing above keys off "connected at load": the
  // draft-versus-room arbitration in `welcomed` keys off `ORIGINAL_BODY`, a
  // non-writer is refused at the handshake (and no longer even carries this
  // script), and a non-member learns of moves from the shell's events banner.
  let wanted = false;
  let retry = 0;

  addEventListener('openproj:session', event => {
    if (event.detail && !wanted) {
      wanted = true;
      connect();
    }
    if (!event.detail && wanted) {
      wanted = false;
      // A reconnect armed while the session was open would take the seat back.
      clearTimeout(retry);
      settle(null);
      names([]);
      if (socket) socket.close();
    }
  });
  // A session that began before this script ran, whose `openproj:session` had
  // no listener yet: a restored draft — the one place where landing does not
  // mean sessionless — or a `?edit`/`?both` link, which `_VIEWS` (inlined
  // above) answered at load. The ORDER is the load-bearing half: the restore
  // has already spliced the draft into the surface by the time this line
  // runs, so the room is joined by a page that is visibly holding unsent work
  // and `welcomed` can see two histories and refuse to guess. Restored lazily
  // on the Write press instead, the draft would be spliced in AFTER binding,
  // leave as ordinary typing, and bypass that refusal — the exact class of
  // silent overwrite this branch has shipped three times.
  if (FORM.closest('article.entity').classList.contains('editing')) {
    wanted = true;
    connect();
  }
```

Declare `let retry = 0;` here (as shown) rather than beside the other flags at 14048-14055, so the whole seat-timing story reads in one place. Do not touch the draft-restore block at 13973-13988 — it already runs in an earlier `<script>` than `_COEDIT` (13990-13992 order: views, yjs, coedit), which is what "restore before connect" rests on.

- [ ] **Step 9: spec test 5 — a reader holds no seat (`tests/test_seats.py`)**

Append at the end of `tests/test_seats.py`:

```python
# The socket, counted rather than merely replaced: the claim is about how many
# connections a page opens and WHEN, so every construction is kept, and close()
# behaves like a real socket — readyState moves and onclose fires — so a
# reconnect after the session ended would be visible as a second entry.
COUNTING = """
<script>
window.__sockets = [];
class CountingSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;
  constructor(url) {
    window.__sockets.push(this);
    this.url = url;
    this.readyState = 1;
    setTimeout(() => this.onopen && this.onopen(), 0);
  }
  send(data) {}
  close() {
    this.readyState = 3;
    setTimeout(() => this.onclose && this.onclose({}), 0);
  }
  hear(message) { this.onmessage && this.onmessage({data: JSON.stringify(message)}); }
}
window.WebSocket = CountingSocket;
</script>
"""

READING = """
<script>
addEventListener('load', () => setTimeout(() => {
  window.__atLoad = window.__sockets.length;
  flipEditing();
  window.__inSession = window.__sockets.length;
  document.getElementById('cancel').click();
  window.__afterCancel = window.__sockets.map(one => one.readyState);
  // Past the first reconnect backoff (500ms): a machine that reconnects after
  // the session ended shows up as a second socket here.
  setTimeout(() => { window.__later = window.__sockets.length; }, 800);
}, 200));
</script>
"""

_HELD = """
return {atLoad: window.__atLoad, inSession: window.__inSession,
        afterCancel: window.__afterCancel, later: window.__later,
        listed: document.getElementById('together').textContent};
"""


def test_a_reader_holds_no_seat(index: Index, tmp_path: Path):
    """Spec test 5: opening a record is not editing it.

    `connect()` ran at script load, so a signed-in person who merely OPENED a
    record took a co-editing seat: listed to everyone else as "also editing",
    and holding a Room, a git watch and an outbox task on the server per
    record visited, lingering after they left. The seat, the presence entry
    and the Room task are all downstream of the one socket this counts — no
    connection at load means none of them exist, and the last-person-out
    commit never waits on a reader.
    """
    entity_id = a_record_with_a_document(index)
    page = render_detail(
        index, ROUTES, only=entity_id, base_commit=HEAD, may_write=True, editor="plain"
    )
    page = page.replace("<head>", "<head>" + COUNTING, 1).replace("</body>", READING + "</body>")

    got = measured_in(
        chrome(), page, tmp_path / "seatless.html", 1200, _HELD, height=900, patience=2400
    )

    assert got["atLoad"] == 0, "a reader took a seat by opening the page"
    assert got["inSession"] == 1, "and opening a session did not take one"
    assert got["afterCancel"] == [3], "Cancel did not give the seat back"
    assert got["later"] == 1, "the seat was retaken after the session ended"
    assert got["listed"] == "", "somebody is listed as editing a page nobody edited"
```

- [ ] **Step 10: spec tests 6–8 and the legacy-mode pin (`tests/test_editor.py`)**

Insert after `test_a_link_to_the_split_view_opens_in_the_split_view` (currently ends ~line 2048):

```python
# The socket, counted and timestamped: `bodyAtConnect` is what the surface held
# at the instant the room was joined, which is the fact the restore-before-
# connect ordering is pinned by.
_SOCKETS = """
window.__sockets = [];
class CountingSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;
  constructor(url) {
    window.__sockets.push(this);
    this.url = url;
    this.readyState = 1;
    const body = document.querySelector('textarea[name=body]');
    this.bodyAtConnect = body ? body.value : '';
    setTimeout(() => this.onopen && this.onopen(), 0);
  }
  send(data) {}
  close() { this.readyState = 3; setTimeout(() => this.onclose && this.onclose({}), 0); }
  hear(message) { this.onmessage && this.onmessage({data: JSON.stringify(message)}); }
}
window.WebSocket = CountingSocket;
"""

# No `_STUB_PREVIEW` prefix here, deliberately: `measured_in` runs this script
# at SETTLE (1200ms), AFTER the page's load-time behaviour. A fetch counter
# installed here would miss every /api/preview the page asked at load — the
# very thing `asked` pins — so the stub goes into the <head> beside `_SOCKETS`
# and counts from t=0.
_LINKED = """
const article = document.querySelector('article.entity');
const doc = article.querySelector('.doc.read');
return {
  classes: [...article.classList].filter(c => c === 'full' || c.startsWith('view-')).sort(),
  editing: article.classList.contains('editing'),
  pressed: ['view-edit', 'view-both', 'preview'].filter(
    id => document.getElementById(id).getAttribute('aria-pressed') === 'true'),
  fullpage: document.body.classList.contains('fullpage'),
  navInert: !!document.querySelector('body > nav').inert,
  docShown: doc.getClientRects().length > 0,
  paneHidden: document.getElementById('body-preview').hidden,
  sockets: window.__sockets.length,
  asked: window.asked.length,
};
"""


def test_a_view_link_is_sessionless_and_a_both_link_opens_a_session(
    client: TestClient, tmp_path: Path
):
    """Spec test 6, both halves in one place so a regression of either shows.

    `?view` used to open a session — `showView` forced `showEditing(true)` —
    so there was no way to hand somebody a link to LOOK at a rendered record.
    It is the sessionless read page now: no full page, nav alive, the
    server-rendered document on screen, no seat taken, and no `/api/preview`
    round trip for bytes the server already rendered into the page. `?both` is
    unchanged: a view of a session opens the session it is a view of.
    """
    page = client.get(f"/detail/{TASK}{PLAIN}").text.replace(
        "<head>", "<head><script>" + _SOCKETS + _STUB_PREVIEW + "</script>", 1
    )

    viewed = measured_in(chrome(), page, tmp_path / "viewlink.html", 1400, _LINKED,
                         query="?view=")
    assert viewed["classes"] == ["view-view"] and viewed["pressed"] == ["preview"]
    assert not viewed["editing"], "?view opened a session"
    assert not viewed["fullpage"] and not viewed["navInert"]
    assert viewed["docShown"], "the server-rendered document is not on the screen"
    assert viewed["paneHidden"], "the landing is drawn in the preview pane, not the page"
    assert viewed["sockets"] == 0, "?view took a co-editing seat"
    assert viewed["asked"] == 0, (
        "the landing asked /api/preview to redraw bytes the server already rendered"
    )

    both = measured_in(chrome(), page, tmp_path / "bothlink.html", 1400, _LINKED,
                       query="?both=")
    assert both["classes"] == ["full", "view-both"] and both["pressed"] == ["view-both"]
    assert both["editing"], "?both did not open the session it is a view of"
    assert both["fullpage"] and both["navInert"]
    assert both["sockets"] == 1, "a session opened and no seat was taken"
    assert both["asked"] >= 1, "the live pane never asked for its rendering"


# The stub lives in the <head> here too (same reason as `_LINKED`), so the
# input-driven refreshPreview below hits a working fetch from the first event.
_DIVERGED = """
const article = document.querySelector('article.entity');
const area = document.querySelector('textarea[name=body]');
const doc = article.querySelector('.doc.read');
// Non-ASCII on purpose: no test drives this editor with plain ASCII alone —
// the last three shipped defects each hid behind a corpus that did.
const marker = ' — verworfen, aber aufgehoben ✎';
document.getElementById('view-edit').click();
area.value = area.value + marker;
area.dispatchEvent(new Event('input', {bubbles: true}));
await new Promise(go => setTimeout(go, 80));
document.getElementById('cancel').click();
await new Promise(go => setTimeout(go, 80));
return {
  landed: [...article.classList].filter(c => c === 'full' || c.startsWith('view-')).sort(),
  editing: article.classList.contains('editing'),
  docShown: doc.getClientRects().length > 0,
  docHoldsDraft: doc.textContent.includes(marker),
  boxHoldsDraft: area.value.includes(marker),
  paneHidden: document.getElementById('body-preview').hidden,
};
"""


def test_cancel_with_a_divergent_draft_lands_on_the_stored_commit(
    client: TestClient, tmp_path: Path
):
    """Spec test 7: the landing always renders the stored commit, never the
    live surface.

    Cancel deliberately leaves draft text in the box — the three worst rounds
    this repository has had each destroyed somebody's writing without a word —
    so the page Cancel lands on holds two truths at once: the box still has
    the draft, and the document on screen is what git has. A landing wired to
    the live surface would show uncommitted text as though it were the record.
    """
    page = client.get(f"/detail/{TASK}{PLAIN}").text.replace(
        "<head>", "<head><script>" + _SOCKETS + _STUB_PREVIEW + "</script>", 1
    )
    got = measured_in(chrome(), page, tmp_path / "diverged.html", 1400, _DIVERGED,
                      patience=2400)

    assert got["landed"] == ["view-view"] and not got["editing"]
    assert got["docShown"], "no document on the page Cancel landed on"
    assert not got["docHoldsDraft"], (
        "the landing shows the live surface: uncommitted text drawn as the record"
    )
    assert got["boxHoldsDraft"], "Cancel destroyed the draft instead of keeping it in the box"
    assert got["paneHidden"]


def test_a_draft_at_load_forces_a_session_and_the_room_refusal_still_fires(
    client: TestClient, tmp_path: Path
):
    """Spec test 8: the one exception to sessionless landing, and why.

    The stored-draft restore stays at page load and keeps forcing a session.
    Deferred to the Write press, the draft would be spliced in AFTER the room
    has bound, leave as ordinary typing, and bypass the draft-versus-moved-
    room refusal. Restore-before-connect is the ordering that keeps the
    refusal alive: the surface holds the draft when the room is joined, so
    `welcomed` sees two histories and refuses to guess.
    """
    key = f"openproj:draft:2:{TASK}"
    draft = {"base": "1" * 40, "text": "Größer als geplant — ein Entwurf №8\n"}
    seed = (
        f"try {{ localStorage.setItem({json.dumps(key)}, "
        f"{json.dumps(json.dumps(draft))}); }} catch (e) {{}}"
    )
    page = _before_the_page_runs(client.get(f"/detail/{TASK}{PLAIN}").text, seed)
    page = page.replace("<head>", "<head><script>" + _SOCKETS + _STUB_PREVIEW + "</script>", 1)

    got = measured_in(
        chrome(), page, tmp_path / "draftload.html", 1400,
        """
        const article = document.querySelector('article.entity');
        const area = document.querySelector('textarea[name=body]');
        const socket = window.__sockets[0] || null;
        const forced = {editing: article.classList.contains('editing'),
                        connected: window.__sockets.length,
                        heldAtConnect: socket ? socket.bodyAtConnect : '',
                        base: document.querySelector('[name=base_commit]').value};
        // The room answers with a document that is not what this page was
        // rendered from — an empty seed, which is what a moved room looks
        // like to a page holding hour-old text.
        if (socket) socket.hear({t: 'welcome', seed: 'a'.repeat(40),
                                 base: 'a'.repeat(40), you: 'ann', sv: 'AA==',
                                 update: '', people: ['ann']});
        await new Promise(go => setTimeout(go, 80));
        const box = document.getElementById('conflict');
        return {forced, refused: socket ? !box.hidden : null,
                report: box.textContent, boxNow: area.value};
        """,
        patience=2400,
    )

    marker = draft["text"].strip()
    assert got["forced"]["editing"], "a stored draft no longer forces a session at load"
    assert got["forced"]["connected"] == 1, "the forced session joined no room"
    assert got["forced"]["base"] == draft["base"], (
        "the restore did not move base_commit back under the draft"
    )
    assert marker in got["forced"]["heldAtConnect"], (
        "the room was joined before the draft was in the surface — from here "
        "the draft leaves as ordinary typing and the refusal below never fires"
    )
    assert got["refused"], "two histories, no common base, and nothing refused to guess"
    assert marker in got["report"], "the refusal does not carry the draft back to its author"
    assert marker not in got["boxNow"], (
        "the draft is still in the box after the refusal said the room's text is"
    )


def test_a_stored_legacy_view_mode_opens_the_next_session_in_edit(
    client: TestClient, tmp_path: Path
):
    """The stored word `view` meant "open sessions in preview-only" yesterday
    and names the sessionless landing today. A session cannot open
    sessionless, so a legacy value migrates to `edit` on read rather than
    being trusted into a state that no longer exists — risk 5's empty
    full-page grid."""
    got = measured_in(
        chrome(),
        _before_the_page_runs(
            client.get(f"/detail/{TASK}{PLAIN}").text, _SEED % '{"mode": "view"}'
        ),
        tmp_path / "legacy.html", 1400,
        _STUB_PREVIEW + """
        flipEditing();
        const article = document.querySelector('article.entity');
        return {view: VIEW, editing: article.classList.contains('editing'),
                full: article.classList.contains('full')};
        """,
        patience=1800,
    )
    assert got == {"view": "edit", "editing": True, "full": True}, (
        f"a legacy stored mode landed a session somewhere that is not one: {got}"
    )
```

(`json` is already imported in `test_editor.py`; `_SEED` and `_before_the_page_runs` are defined lower in the file at 3798-3810 — Python resolves them at call time, but keep the two legacy/sticky tests below that point if the implementer prefers definition-before-use for readability. `_SEED`/`_before_the_page_runs` are module-level names, so placement is a style choice, not a correctness one.)

- [ ] **Step 11: rewrite `_VIEWING` and its test — the three states**

Replace the whole `_VIEWING` stub (1852-1946) and `test_the_three_views_are_one_of_three_and_each_pane_scrolls_on_its_own` (1949-2018) with:

```python
_VIEWING = _STUB_PREVIEW + """
const article = document.querySelector('article.entity');
const area = document.querySelector('textarea[name=body]');
const pane = document.getElementById('body-preview');
const marks = document.getElementById('marks');
const doc = article.querySelector('.doc.read');
const seg = name => document.getElementById(
  {edit: 'view-edit', both: 'view-both', view: 'preview'}[name]);
const drawn = element => element.getClientRects().length > 0;
const state = () => ({
  classes: [...article.classList].filter(c => c === 'full' || c.startsWith('view-')).sort(),
  pressed: ['edit', 'both', 'view'].filter(
    n => seg(n).getAttribute('aria-pressed') === 'true'),
  editing: article.classList.contains('editing'),
  box: drawn(area),
  pane: drawn(pane),
  marks: drawn(marks),
  doc: drawn(doc),
  position: getComputedStyle(article).position,
});

const atLoad = state();
// The segment IS the door in: there is no Edit button beside a switcher that
// opens the same session.
seg('edit').click();
const editing = state();
// Enough lines that the box has something to scroll — and not ASCII, because
// no test drives this editor with ASCII alone.
area.value = Array.from({length: 200},
  (_, i) => `Zeile ${i + 1} — ` + 'w'.repeat(88)).join('\\n');
area.dispatchEvent(new Event('input', {bubbles: true}));
await new Promise(go => setTimeout(go, 80));

// Every view change has to tell the seat layer the box moved; a change that
// crosses the session boundary says it twice — once from `showEditing`, once
// from `showView` — which the count below spells out.
let told = 0;
addEventListener('openproj:editing', () => { told++; });

seg('both').click();
const both = state();
await new Promise(go => setTimeout(go, 400));
const split = {
  sideBySide: area.getBoundingClientRect().right <= pane.getBoundingClientRect().left + 1,
  inside: area.getBoundingClientRect().bottom <= innerHeight + 1
          && pane.getBoundingClientRect().bottom <= innerHeight + 1,
  boxScrolls: area.scrollHeight > area.clientHeight + 1,
  paneScrolls: pane.scrollHeight > pane.clientHeight + 1,
  pageScrolls: document.documentElement.scrollHeight > innerHeight + 1,
};

seg('view').click();
const viewing = state();
seg('edit').click();
const writing = state();
// Pressing the pressed segment is the way back out with a pointer — to the
// landing, which ends the session.
seg('edit').click();
const out = state();

const chord = code => dispatchEvent(new KeyboardEvent(
  'keydown', {ctrlKey: true, shiftKey: true, code, key: '@', bubbles: true}));
chord('Digit2');
const chorded = state();
chord('Digit2');
const unchorded = state();

// And AltGr does not reach it — the euro sign on the Swiss-German layout half
// this team types on arrives as ctrl+alt, exactly as dispatched here.
dispatchEvent(new KeyboardEvent('keydown', {
  ctrlKey: true, altKey: true, modifierAltGraph: true, code: 'KeyE', key: '€',
  bubbles: true, cancelable: true,
}));
const afterEuro = state();

seg('both').click();
area.focus();
area.dispatchEvent(new KeyboardEvent(
  'keydown', {key: 'Escape', bubbles: true, cancelable: true}));
const escaped = state();

return {atLoad, editing, both, split, viewing, writing, out, chorded, unchorded,
        afterEuro, escaped, told, asked: window.asked.length};
"""


def test_the_three_views_are_one_of_three_and_each_pane_scrolls_on_its_own(
    client: TestClient, tmp_path: Path
):
    """Three states, and the landing one is `view`.

    HackMD is always full page; here `view` is the ordinary page — the
    server-rendered document, the facts column, the nav alive — and it is
    where every session ends. `edit` and `both` are sessions and go full page.
    The fourth, unnamed state is gone: exactly one segment is always pressed,
    the pressed segment and the chord and Escape all land on the landing, and
    landing ends the session — without discarding anything, because the text
    stays in the surface and only Cancel restores fields.
    """
    LANDED = {
        "classes": ["view-view"], "pressed": ["view"], "editing": False,
        "box": False, "pane": False, "marks": False, "doc": True,
        "position": "relative",
    }
    got = measured_in(
        chrome(), client.get(f"/detail/{TASK}{PLAIN}").text, tmp_path / "views.html",
        1400, _VIEWING, patience=4800,
    )

    assert got["atLoad"] == LANDED, f"the page did not load on the landing: {got['atLoad']}"
    assert got["editing"] == {
        "classes": ["full", "view-edit"], "pressed": ["edit"], "editing": True,
        "box": True, "pane": False, "marks": True, "doc": False, "position": "fixed",
    }, "pressing Write did not open a session in the edit view"

    assert got["both"]["classes"] == ["full", "view-both"]
    assert got["both"]["pressed"] == ["both"], "two segments pressed is not a choice of three"
    assert got["both"]["position"] == "fixed" and got["both"]["editing"]
    assert got["both"]["box"] and got["both"]["pane"]

    assert got["split"] == {
        "sideBySide": True, "inside": True,
        "boxScrolls": True, "paneScrolls": True, "pageScrolls": False,
    }, "the two panes do not scroll on their own inside the window"

    assert got["viewing"] == LANDED, (
        "the eye did not land on the sessionless read page — a live pane, a "
        f"surface, or a session survived: {got['viewing']}"
    )
    assert got["writing"]["classes"] == ["full", "view-edit"] and got["writing"]["editing"]
    assert got["out"] == LANDED, "the pressed segment did not land on the landing"

    assert got["chorded"]["pressed"] == ["both"], "Ctrl+Shift+2 was not read off event.code"
    assert got["unchorded"] == LANDED, "the same chord did not come back to the landing"
    assert got["afterEuro"] == LANDED, (
        "AltGr+E moved the view: the chord swallows a character people type"
    )
    assert got["escaped"] == LANDED, "Escape did not land on the landing"

    # One `openproj:editing` per view change, and a second per session
    # boundary (from `showEditing`): both(1) + view(2) + edit(2) + edit(2)
    # + chord(2) + chord(2) + euro(0) + both(2) + escape(2).
    assert got["told"] == 15, f"a view change the seat layer was not told about: {got['told']}"
    assert got["asked"] >= 1, "the preview was never asked for"
```

- [ ] **Step 12: `_DEEP_LINK`'s no-flag half now lands on the landing**

In `test_a_link_to_the_split_view_opens_in_the_split_view` (2032-2047), replace the last three lines:

```python
    plain = measured_in(chrome(), page, tmp_path / "plain.html", 1400, _DEEP_LINK)
    assert plain["classes"] == [] and plain["pressed"] == []
    assert not plain["editing"], "no link, and the page opened in a view anyway"
```

with:

```python
    plain = measured_in(chrome(), page, tmp_path / "plain.html", 1400, _DEEP_LINK)
    assert plain["classes"] == ["view-view"] and plain["pressed"] == ["preview"]
    assert not plain["editing"], "no link, and the page opened a session anyway"
```

- [ ] **Step 13: repoint the way-in pin and the delete-bar pin**

`test_the_way_in_is_at_the_top_and_the_two_ways_out_are_together` (234-268): keep the first three asserts (commitbar position) and replace the `bar`/toggle block (263-268) with:

```python
    bar = re.search(r'<div class="commitbar".*?</div>', page, re.S).group(0)
    assert 'id="save"' in bar and 'id="cancel"' in bar
    # The way in is the view switcher, and it is not one of the ways out: the
    # segments live on the editbar above the commit bar, never inside it.
    assert 'id="views"' not in bar, "the way in is one of the ways out"
    assert page.index('id="views"') < page.index('id="commitbar"')
    assert page.index('id="views"') < page.index('<dl id="facts">')
    assert 'id="toggle"' not in page, (
        "a second door into the session, one control's width from the switcher"
    )
```

`tests/test_delete.py:104` — replace:

```python
    assert 'id="toggle"' in bar and "class=\"delete\"" in bar, bar
```

with:

```python
    assert "class=\"delete\"" in bar and 'id="views"' in bar, bar
```

- [ ] **Step 14: the session-leaving pins — Cancel, the room's door, the corner**

Replace the loop in `_LEAVING` (3237-3249) with (the `shape()` helper above it is unchanged):

```js
const answers = {};
for (const [name, id] of [['edit', 'view-edit'], ['both', 'view-both']]) {
  // The segment is the door: pressing it opens the session in that view.
  document.getElementById(id).click();
  const inside = shape();
  document.getElementById('cancel').click();
  answers[name] = {inside, after: shape()};
}
return answers;
"""
```

and the assertion loop in `test_cancel_leaves_the_surface_it_was_pressed_in` (3273-3283) with:

```python
    for name, answer in got.items():
        assert answer["inside"]["classes"] == ["full", f"view-{name}"], name
        assert answer["inside"]["navInert"], f"{name}: the page behind the surface is not inert"
        assert not answer["inside"]["over"], (
            f"{name}: the surface does not actually cover the nav, so nothing here is proved"
        )
        assert answer["after"] == {
            "classes": ["view-view"], "fullpage": False, "navInert": False, "over": True,
            "switcher": True, "editing": False,
        }, (
            f"Cancel from the {name} view did not land on the landing: {answer['after']}"
        )
```

(`switcher: True` is the point of the whole change: the way back cannot vanish any more, because it is drawn outside the session too. Trim the docstring's "drawn only under `.entity.editing`" clause to past tense.)

Apply exactly the same two edits to `_SAVED_IN_A_ROOM` (3317-3330: loop over `edit`/`both` only, click the segment, call `showEditing(false)`, drop the trailing "back to read mode" cancel — the page is already sessionless) and to `test_ending_a_session_leaves_the_surface_by_every_door` (3392-3402), whose `after` expectation becomes:

```python
        assert answer["after"] == {
            "classes": ["view-view"], "fullpage": False, "navInert": False, "over": True,
            "switcher": True, "editing": False, "cornerInNav": True,
        }, (
            f"a room's save from the {name} view left the reader in the surface: "
            f"{answer['after']}"
        )
```

`test_the_room_s_own_save_ends_the_session_by_leaving_the_page` (source pin) and `_THE_CORNER` / `test_the_theme_toggle_and_the_way_in_come_into_the_surface_with_you` survive unchanged apart from the mechanical toggle sweep in step 18.

- [ ] **Step 15: `_GRIPPING`, `_NUMBERING`, `_STICKY`, the `_TABBING` tail, `_PREVIEW_ONLY_BARS`, the narrow-window read state**

**`_GRIPPING`** (2050-2077) — the "editing, not full" state is gone on record pages. Replace from `const reading = where();` to the `return`:

```js
const reading = where();
document.getElementById('view-edit').click();
const full = {};
for (const name of ['edit', 'both']) { seg(name).click(); full[name] = where(); }
seg('view').click();               // the landing: session over, column back
const back = where();
return {reading, full, back};
"""
```

and the assertions (2091-2102) with:

```python
    for mode in ("reading",):
        assert not got[mode]["hidden"], f"no handle while {mode}"
        assert got[mode]["onEdge"], f"the handle is not on the column's edge while {mode}"
        assert got[mode]["spare"] > 20, f"the handle is against the window edge while {mode}"

    for name in ("edit", "both"):
        assert got["full"][name]["hidden"], f"a width handle in the {name} view"

    assert not got["back"]["hidden"] and got["back"]["onEdge"], (
        "the handle did not come back with the column"
    )
```

Docstring addendum: editing inline in the reading measure no longer exists — a session is full page, so the handle and the box are never on screen together.

**`_NUMBERING`** (3095-3160): replace the two entry lines

```js
document.getElementById('toggle').click();
// Out of full page: a session now starts in the `edit` VIEW, ...
document.getElementById('view-edit').click();
```

with:

```js
flipEditing();
// In the full-page edit view, which is the only place the box exists now:
// editing inline in the reading measure went with the null state. The sweep
// drives the box's own container instead of `--measure`, which full page does
// not read; the mirror-agreement claim is about widths, wherever they come
// from.
const wrap = document.querySelector('.bodywrap');
```

change the sweep's width line from `article.style.setProperty('--measure', measure + 'px');` to `wrap.style.width = measure + 'px';`, and delete the whole grip-drag coda (from `// And the one control whose entire job is...` through `const dragged = {...};`), returning `{answers}` only. In the test function (3161-3207) delete the three `dragged` assertions and change the `where` message to `f"at a pane width of {answer['measure']}px (box {answer['boxWidth']}px)"`. The control-tells-the-layers claim now lives where the control does: `moveSplit` dispatches `openproj:editing` (render.py:12277) and the sweep in `test_a_view_change_tells_the_seat_layer_the_box_moved` still pins the dispatch in `showView`.

**`_STICKY`** (4174-4192) — replace the stub body after `const mode = () => VIEW;` with:

```js
const atLoad = {view: mode(), full: article.classList.contains('full'),
                editing: article.classList.contains('editing')};
flipEditing();
const afterEdit = {view: mode(), full: article.classList.contains('full')};
document.getElementById('cancel').click();
const afterCancel = {view: mode(), stored: JSON.parse(localStorage.getItem('openproj:editor:1'))};
flipEditing();
document.getElementById('view-edit').click();
return {atLoad, afterEdit, afterCancel,
        chosen: JSON.parse(localStorage.getItem('openproj:editor:1')).mode};
"""
```

and the assertions (4212-4224):

```python
    assert got["atLoad"] == {"view": "view", "full": False, "editing": False}, (
        f"a remembered mode opened a record somebody came to read as a "
        f"full-screen editor: {got['atLoad']}"
    )
    assert got["afterEdit"] == {"view": "both", "full": True}, (
        f"starting a session did not restore the remembered view: {got['afterEdit']}"
    )
    assert got["afterCancel"]["view"] == "view"
    assert got["afterCancel"]["stored"]["mode"] == "both", (
        "Cancel was read as a preference for no surface, so using the split once "
        "and cancelling takes it away"
    )
    assert got["chosen"] == "edit", "pressing a segment did not remember it"
```

**`_TABBING`** (1481-1508): in a session Escape now leaves the session, so the hatch is unreachable there and the box is gone afterwards. Delete the Escape/hatch section of the stub (from `// And Escape arms exactly one Tab...` through `const spent = area.value;`), return without `said, passed, untouched, spent`, delete those four assertions from the test — and add this test right below it, on the page where the box lives on the ordinary page:

```python
def test_escape_still_arms_the_tab_hatch_where_the_box_is_on_the_page(
    client: TestClient, tmp_path: Path
):
    """The hatch's home moved with the null state: on a record page Escape now
    leaves the session (taking the box with it), so the place a first press
    has nothing to leave — and must therefore give Tab back — is the create
    form's ordinary page, which has no landing and keeps the surface-off
    state."""
    got = measured_in(
        chrome(), client.get(f"/new{PLAIN}").text, tmp_path / "hatch.html", 1200,
        _STUB_PREVIEW + """
        const area = document.querySelector('textarea[name=body]');
        // Out of the full-page view first: the create form's pressed segment
        // goes to the old surface-off state and the box stays on the page.
        const lit = ['view-edit', 'view-both', 'preview']
          .map(id => document.getElementById(id))
          .find(seg => seg.getAttribute('aria-pressed') === 'true');
        if (lit) lit.click();
        const press = key => { area.focus(); return area.dispatchEvent(new KeyboardEvent(
          'keydown', {key, bubbles: true, cancelable: true})); };
        area.value = 'alpha — β';
        area.dispatchEvent(new Event('input', {bubbles: true}));
        press('Escape');
        const said = document.getElementById('state').textContent;
        const passed = press('Tab');
        return {said, passed, value: area.value};
        """,
        patience=2400,
    )
    assert "Tab" in got["said"], "the hatch opened silently or not at all"
    assert got["passed"], "Escape did not give the next Tab back to the browser"
    assert got["value"] == "alpha — β", "the armed Tab indented instead of leaving"
```

**`_PREVIEW_ONLY_BARS` / `test_preview_only_takes_away_the_controls_and_keeps_the_one_live_fact`** (5227-5317): delete both. The decision it guarded is repealed by the spec: on a record page the eye ends the session and lands on a static, sessionless page — there is no live room under the landing, by design ("the landing pane always renders the stored commit"). The control-hiding half of the CSS is still exercised, on the create form, by the next edit.

**`_NARROW_FULL_PAGE` / `test_the_full_page_surface_is_a_writing_surface_at_a_window_that_is_not_wide`** (4740-4825): the entry lines

```js
const into = document.getElementById('toggle');
if (into) into.click();
```

become

```js
if (typeof flipEditing === 'function') flipEditing();
```

and the `read` block becomes:

```js
press('preview');
const doc = document.querySelector('article.entity .doc.read');
out.read = {
  paneRows: Math.round(
    pane.getBoundingClientRect().height / parseFloat(getComputedStyle(area).lineHeight)),
  landed: doc ? doc.getClientRects().length > 0 : false,
  documentFirst: main.getBoundingClientRect().top < facts.getBoundingClientRect().top,
};
```

with the tail assertions replaced by:

```python
    if where == "new":
        assert got["read"]["paneRows"] >= 12, "the create form's preview is not readable"
        assert got["read"]["documentFirst"]
    else:
        assert got["read"]["landed"], (
            "pressing the eye did not land on the record's own read page"
        )
```

and `assert got["fixed"] == "fixed"` relaxed to be read from the `write` pass (`out.fixed` is captured at the end of the stub today, after `press('preview')` — move the `out.fixed = getComputedStyle(article).position;` line up, directly after `out.split = state();`, so it still measures a full-page view).

- [ ] **Step 16: the issue-page surface test — Escape now ends the session**

In `tests/test_issues.py` `_SURFACE` (407-483): after the `only` block, replace the Escape probe (466-472):

```js
// Escape leaves the surface, which is the arbitration decided in S2 and the one
// this page inherits by having a surface at all.
area.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true, cancelable: true}));
const left = {classes: [...article.classList].sort(),
              editing: article.classList.contains('editing')};
```

with:

```js
// Back into a session first: pressing the eye above ended it, because `view`
// is the sessionless landing now. Escape then ends the session too — and ends
// it without discarding: the text stays in the box, which is the difference
// between this and the key that destroys writing.
seg('both').click();
await new Promise(go => setTimeout(go, 60));
area.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true, cancelable: true}));
const left = {classes: [...article.classList].sort(),
              editing: article.classList.contains('editing'),
              kept: area.value.length > 0};
```

and its assertions (557-563):

```python
    assert "full" not in got["left"]["classes"], (
        f"Escape did not leave the full-page surface: {got['left']['classes']}"
    )
    assert not got["left"]["editing"], (
        "Escape lands on the sessionless read page now — a session it leaves open "
        "is the vanished null state coming back"
    )
    assert got["left"]["kept"], (
        "ending the session by Escape discarded the text — only Cancel restores"
    )
```

The `cancelled` block and its assertions survive unchanged (the issue page's own toggle stays until commit 8). Also update `assert got["before"]["switcher"]` docline if desired — it now holds outside editing too.

- [ ] **Step 17: the node-harness room tests open a session before they open the socket**

In `tests/test_coedit.py`, five `run_js(..., socket=True)` expressions construct no socket until a session exists. Insert `"  flipEditing();"` as the first statement of each expression string — at lines 727, 1380, 2096, 3877, 3922 the pattern is identical; for example at 727:

```python
        "(async () => {"
        "  flipEditing();"
        "  __socket.opened();"
```

and at 1380 / 2096 (the sync `"(() => {"` forms) the same one line after the opening brace. In the draft test at 2065-2102, `flipEditing();` goes first, before `box.value` is set — the welcome still finds the unsent text because `ORIGINAL_BODY` was captured at load.

- [ ] **Step 18: the mechanical toggle sweep**

The Edit button is gone from `_DETAIL`; `flipEditing` is the same handler the click reached. First apply the two spellings the sweep cannot match:

- `tests/test_editor.py:967-968` (inside `test_cancelling_a_restored_draft_keeps_the_commit_it_was_written_against`): replace
  `"(() => { document.getElementById('toggle')"` + `"   .dispatchEvent(new Event('click'));"` with `"(() => { flipEditing();"` (one line).

Then run the sweep — test_issues.py is deliberately excluded, its toggle is the issue page's own and still real:

```bash
perl -pi -e "s/document\\.getElementById\\('toggle'\\)\\.click\\(\\)/flipEditing()/g" \
  tests/test_editor.py tests/test_seats.py tests/test_coedit.py tests/test_hill.py tests/test_delete.py
```

Then verify nothing was missed and nothing was over-reached:

```bash
grep -rn "getElementById('toggle')" tests/ | grep -v test_issues.py
```

must print nothing (the stubs rewritten in steps 11-15 have already lost theirs; if a line still shows, it is a stub this plan rewrote — apply that step's replacement text, which supersedes the sweep). `test_coedit.py:2796`'s embedded guard becomes `"   flipEditing();"` under its existing `if (!one.classList.contains('editing'))` — correct as-is.

- [ ] **Step 19: ruff, then the commit**

```bash
uv sync && uv run ruff check .
```

Fix anything it names (watch the 100-column limit in the edited render.py strings). Do NOT run pytest — not one file. Then:

```bash
git add src/openproj/render.py tests/test_editor.py tests/test_seats.py \
  tests/test_coedit.py tests/test_hill.py tests/test_delete.py tests/test_issues.py
git commit -F- <<'MSG'
A document is read without opening a session

Opening a record used to mean opening an editor. `showView` forced
`showEditing(true)` — "a view of the document is a way into editing it" — so
there was no way to look at a rendered document without a session, and the
landing state was a fourth, unnamed one. There are three states now and the
landing one is `view`: sessionless, no full page, nav alive, showing the
`.doc.read` the server already rendered — so it asks /api/preview for
nothing. `edit` and `both` are sessions and keep everything they had.
Session end, Escape, the pressed segment and the chord all land there; the
switcher is visible outside the session because it is the only door in (the
Edit button was a second door one control's width from the first), and it is
withheld entirely from a reader the server would refuse a write from.
`EDITOR.mode` stores only edit|both; a stored legacy `view` migrates to
`edit` on read. `?view` is a sessionless read link; `?edit` and `?both` are
unchanged.

This also fixes a bug already in the tree: `connect()` ran at script load,
so an idle signed-in reader took a co-editing seat, was listed to everyone
else as "also editing", and held a Room, a git watch and an outbox task on
the server for every record they visited, lingering after they left.
`connect()` now runs at session start and disconnects at session end.

The one exception is the stored-draft restore, which stays at page load and
keeps forcing a session — deliberately. Deferred to the Write press, the
draft would be spliced in after the room has bound, leave as ordinary
typing, and bypass the draft-versus-moved-room refusal: the exact class of
silent overwrite this branch has shipped three times. Restore runs before
connect, so the room is joined by a page already holding the draft. And the
landing always renders the stored commit, never the live surface — Cancel
leaves draft text in the box on purpose, and a pane built from the surface
would show uncommitted text as though it were the record.

🤖 Written by an agent on behalf of @jcanton
MSG
git push -u origin one-record-one-page
```

Then open/refresh the PR and read CI — the red/green gate is CI, not the laptop. While it runs, move on; a red run here is a normal thing to fix on the branch. Expected watch-points if CI comes back red: the `told == 15` count in step 11 (recount against the final `showView` if it is off by the session-boundary doubling), and any `measured_in` stub that still presses a segment expecting the old full-page preview — the failure message will name the state it found, and the landing dict in step 11 (`LANDED`) is the shape to compare against.

---

### Task 6: Creating a record is the record page with nothing in it

**Files:**
- Modify: `src/openproj/render.py:13106-14014` (the `_DETAIL` template — markup and its main script)
- Modify: `src/openproj/render.py:19615-19700` (`render_detail`)
- Modify: `src/openproj/render.py:16513` (`_detail_rows`' row source)
- Delete: `src/openproj/render.py:12783-13105` (`_NEW`), `src/openproj/render.py:16683-16730` (`render_new`)
- Modify: `src/openproj/web.py:1761-1771` (`GET /new`), `src/openproj/web.py:1780` (the detail 404 lookup)
- Test: `tests/test_table.py` (two new tests beside the create suite at 319–650; the whole existing suite survives)
- Test: `tests/test_render.py:2872-2887` (the `server_pages` fixture repoints)
- Test: `tests/test_cascade.py:50-73` and `tests/test_cascade.py:1125-1140` (two fixtures repoint)

Line numbers were verified against the current tree (`b8837a9`); Tasks 1–5 will have shifted them, so locate every edit by the quoted anchor strings, which are unique in each file. In particular Task 5 rewrote the editbar and the view machine and Task 3 rewrote the fact rows — where a step below touches markup those tasks changed, the step quotes their final form, not `b8837a9`'s.

**Interfaces:**
- Consumes: `render_detail(index: Index, links: Links = STATIC, only: str | None = None, base_commit: str | None = None, may_write: bool = False, editor: str = "") -> str` (render.py:19615, plus whatever context keys Task 3 added to its `.render(...)` call — this task only adds keys, never removes one). `_new_rows() -> list[dict]` (render.py:16611) — rows of `{label, for, control, gates, kinds}`; it calls `_control_html` internally with the kind it loops over, so Task 3's ladder rework arrives here for free. `TEMPLATES: dict[str, str]` (render.py:16602). `KINDS = tuple(rung.name for rung in KIND_LADDER)` (render.py:16526). `_viewbar`/`_VIEWS` as Task 5 left them: `LANDING = VIEW_ARTICLE.querySelector('.doc.read')` is the discriminator between a record page (`GROUND === 'view'`) and the create form (`GROUND === null`, the old surface-off state) — Step 4 below keeps `.doc.read` off the creating page precisely so that discriminator keeps holding after the merge; the load branch `else if (VIEW_ARTICLE.classList.contains('editing')) showView(EDITOR.mode)` puts the born-editing article into a session mode, and `showView`'s `if (LANDING && typeof showEditing === 'function')` guard keeps `showEditing` uncalled there, so the view machine itself needs **no edit** in this task. Task 5 also removed the Edit button (`#toggle`) from `_DETAIL` and pinned `'id="toggle"' not in page` — nothing in this task may bring it back.
- Produces: `render_detail(..., creating: str | None = None) -> str` — `creating` is the kind being made, `None` on a stored record's page. Task 7 links the landing page to `/new`; Task 8 adds the issue and note rungs to this same picker (it is derived from `KINDS`, so that is automatic), points `POST /api/entity`'s per-kind stamping at the `createRecord()` JS this task ships, and deletes `/issue/new` and `/note/new`. The JS contract: `const CREATING` (kind string or `null`), `async function createRecord()`, and `save()` opening with `if (CREATING) { await createRecord(); return; }`. Also produced here, closing a spec §2 gap no other task owned: the record page's three reads move to `index.records` (`_detail_rows`' row source, `render_detail`'s per-row lookup, the `GET /detail/{id}` 404 check) — Task 8's flip relies on exactly this ("an issue id resolves the moment the rungs land") and should credit Task 6, not Task 2, for it.

The one-sentence design fact this task turns on, worth keeping in mind while editing: `_NEW`'s union-of-fields mechanic — every kind's rows on the page, `data-kinds` deciding which are hidden, `showKind()` flipping them — **is already exactly the kind switch the merged record page needs**. Nothing new is invented here; the creating mode is absorbed, not rebuilt. The `CREATING` flag plus POST-vs-PATCH branch is also the exact pattern `_ISSUE` and `_NOTE` already run (render.py:20141, 20490: `const CREATING = ...`, `method: CREATING ? 'POST' : 'PATCH'`) — theirs die with those templates in Task 8; `_DETAIL`'s copy becomes the only one.

Do NOT touch `/issue/new` or `/note/new` (web.py:1341, 1451) in this task — they die in Task 8.

- [ ] **Step 1: The article opens in creating mode.** In `_DETAIL` (render.py:13130-13141), the article tag, the eyebrow, the heading and the meta line each grow a `creating` branch. The eyebrow markup is copied byte-for-byte from `_NEW` because `test_editor.py:555` indexes the literal string `<p class="eyebrow"><label class="kindpick">` and asserts back < picker < `<h1>`; the heading must render exactly `<h1>New entity</h1>` because `test_render.py`'s headings test asserts it is the page's only heading.

```jinja
{% for e in entities %}
<article {% if not creating %}id="{{ e.id }}" {% endif %}class="entity{% if creating %} editing{% endif %}">
  <p class="back"><a href="{{ links.table }}">← all entities</a></p>
  {%- if creating %}
  {#- The kind sits where the stored record's kind chip sits: the two are the
      same document in two modes, and this is the control that decides which
      kind the reader will be looking at afterwards. Options come off `KINDS`,
      never written out — a rung added to the ladder is on this menu the day it
      lands. -#}
  <p class="eyebrow"><label class="kindpick">kind
      <select id="kind">
        {% for k in kinds %}<option value="{{ k }}"
          {% if k == creating %}selected{% endif %}>{{ k|human }}</option>{% endfor %}
      </select>
    </label></p>
  {%- else %}
  <p class="eyebrow"><span class="chip kind-{{ e.kind }}">{{ e.kind|human }}</span></p>
  {%- endif %}
  {#- The heading names the page; on the create page the title box below it is
      a control, because a heading whose only content is an empty input is a
      page with no name and a box with no name either. -#}
  <h1>{% if creating %}New entity{% else %}<span class="read">{{ e.title }}</span>{% endif %}</h1>
  {% if creating %}
  <p class="meta">the id and the file are the server's to choose</p>
  {% else %}
  <p class="meta"><code>{{ e.id }}</code>
     {% if e.parent %}· in {{ e.parent_link }}{% endif %}</p>
  {% endif %}
```

Replace the existing four elements (`<article id=...>` through the `</p>` of the meta line) with this block, keeping the existing `{#- ... -#}` comments that precede the back link and the eyebrow in place above it.

- [ ] **Step 2: The editbar and commitbar branch.** At the editbar block **as Task 5 left it** — Task 5 deleted the Edit button (the switcher is the only door) and folded the inner `{% if may_write %}` around Delete into an outer one; do not reintroduce `id="toggle"` (`test_editor.py` and `test_delete.py` pin its absence). Creating has no Delete and no Cancel — the article never leaves edit mode and there is nothing stored to go back to or delete — and its bar is visible from birth with a static sentence, because a form whose only way to commit appears later is a form with no way to commit it. The button says **Create**, and keeps saying it (copy is design material: the same word from the bar to the refusal). The block becomes:

```jinja
  {% if editable %}
  {#- The switcher is the way in: pressing Write or Write-and-preview opens
      the session it is a view of, so there is no Edit button beside it — two
      adjacent doors into one session are two controls nobody can tell apart.
      Delete is the other thing a writer may do to a record and it leaves the
      moment a session begins. The whole line is a writer's: a reader the
      server would refuse gets no door at all, which makes the read page the
      whole page for them instead of an editor whose every save is a 403. -#}
  {% if may_write %}
  <p class="editbar">{% if not creating %}<button type="button" class="delete">Delete</button>
    {% endif %}{{ viewbar }}</p>
  {% endif %}
  <div class="commitbar" id="commitbar"{% if not creating %} hidden{% endif %}>
    {% if creating %}
    <span id="unsaved">Nothing is written until you press Create</span>
    <button type="button" id="save">Create</button>
    <span id="state" role="status"></span>
    {% else %}
    <span id="unsaved">Nothing to save</span>
    <span id="draftsaved" class="hint"></span>
    <button type="button" id="save" hidden>Save</button>
    <button type="button" id="cancel" hidden>Cancel</button>
    <span id="state" role="status"></span>
    {% endif %}
  </div>
```

(Task 5's comment above `{% if may_write %}` is kept verbatim, as shown.) Keep every other existing `{#- -#}` comment around the bar. Then gate the delete confirmation panel one screen below: change `{% if may_write %}` (render.py:13198, the line above `<div class="confirming"`) to `{% if may_write and not creating %}` — a record that does not exist yet cannot be deleted, and `cascade_of` was never asked about it.

- [ ] **Step 3: The facts rows carry `data-kinds` when creating.** At render.py:13254-13266 the row loop renders one shape; give it the `_NEW` shape in the creating branch. Two shapes deliberately, not one merged tag: `test_table.py:485` matches the literal `<dd data-kinds="...">` with the control as the *first* tag inside it (no `<span class="read">` before it), and the stored-record branch's `class=`/read-span contract is pinned by the editor tests — one tag serving both would break one contract or the other. The else branch below is Task 3's final form of the `<dd>` — its hint slot (`row.hint`/`row.hint_id`, the `aria-describedby` target) is part of it and must survive this edit byte for byte:

```jinja
        {% for row in e.rows %}
        {% if creating %}
        {#- The `_NEW` row shape, absorbed: every kind's fields are on the page
            and `data-kinds` says whose each one is — this hide/show IS the kind
            switch. No `for` on the row whose control is a radio group: a label
            can name one element, and naming one stop of a hill would tell a
            screen reader that "Status" is the word for `shaping`. -#}
        <dt data-kinds="{{ row.kinds }}">{% if row.for %}<label for="{{ row.for
          }}">{{ row.label }}</label>{% else %}{{ row.label }}{% endif %}{% if row.gates %}
          <span class="req" hidden>required</span>{% endif %}</dt>
        <dd data-kinds="{{ row.kinds }}">{{ row.control }}</dd>
        {% else %}
        <dt class="{% if row.derived %}derived{% endif %}
                   {% if row.editing_only %}editing-only{% endif %}">{% if
          editable and row.control and row.for %}<label for="{{ row.for
          }}">{{ row.label }}</label>{%
          else %}{{ row.label }}{% endif %}{% if
          editable and row.gates %} <span class="req" hidden>required</span>{% endif %}</dt>
        <dd class="{% if row.derived %}derived{% endif %}
                   {% if row.editing_only %}editing-only{% endif %}">
          <span class="read">{{ row.display }}</span>
          {% if editable and row.control %}{{ row.control }}{% endif %}
          {#- Why this value is what it is, when it is derived from a link: "from
              the work it was pitched into", "from what it became". Outside both
              the `.read` span and the control, so it reads in both modes — the
              two pages this copy comes from showed it in both. The id is what
              the locked control's `aria-describedby` points at, so the sentence
              reaches a screen reader as the control's own description and not
              only as nearby text. -#}
          {% if row.hint %}<span class="hint" id="{{ row.hint_id }}">{{ row.hint }}</span>
          {% endif %}
        </dd>
        {% endif %}
        {% endfor %}
```

Also add `{% if creating %} placeholder="Title"{% endif %}` to the title input at render.py:13234 (`<input name="title" data-type="text" value="{{ e.title }}" aria-label="Title"`) — the visible word is the placeholder on a box that starts empty.

- [ ] **Step 4: The main column gains the refusal list, the template picker, and loses the room furniture.** Five edits inside `<div class="main">` (render.py:13269-13346):

1. The problems list (render.py:13270-13271) — the creating page's is empty markup filled by script, news arriving on a page that is already open; the stored page's is server-rendered:
```jinja
      {% if creating %}
      <ul id="problems" class="problems" role="status" aria-live="polite" hidden></ul>
      {% elif e.problems %}<ul class="problems">
        {% for p in e.problems %}<li>{{ p }}</li>{% endfor %}</ul>{% endif %}
```
2. The rendered document (render.py:13297) is gated — this one gate is load-bearing for Task 5's whole view machine, not cosmetic. `LANDING = VIEW_ARTICLE.querySelector('.doc.read')` is how the script tells a record page (`GROUND === 'view'`, the sessionless landing, preview pane suppressed in `view`) from the create form (`GROUND === null`, the old surface-off state, `view` still previews the draft). An unconditional `.doc.read` on the merged create page would make `LANDING` truthy on `/new` and silently flip all of that — the hatch test and `_NARROW_FULL_PAGE`'s `'new'` branch would go red:
```jinja
      {#- The landing document. Absent when creating, and structurally so: the
          view machine's `LANDING` looks for exactly this element, and the
          create form having nothing to land on is what keeps its `view` a
          draft preview instead of a sessionless page. -#}
      {% if not creating %}<div class="doc read">{{ e.body }}</div>{% endif %}
```
3. The seatbar (render.py:13306-13308) — no room on a record that has no id yet — wrap `<p id="seatbar" ...>...</p>` in `{% if not creating %}...{% endif %}`, and likewise the seats layer at 13331: `{% if not creating %}<div id="seats" class="seats" aria-hidden="true"></div>{% endif %}`.
4. Directly above the markbar `<p class="field bodybar markbar">` (render.py:13314), insert the template row from `_NEW` verbatim, gated:
```jinja
      {% if creating %}
      {#- The template is offered, never imposed: it fills an untouched box and
          refuses to overwrite one somebody has typed in. `template` and not
          `start from`: the label names the control, and the sentence it was
          part of ended in the option list. -#}
      <p class="field bodybar">
        <label class="tplpick">template
          <select id="template">
            <option value="pitch">the shaping template</option>
            <option value="task">a task</option>
            <option value="project">a project</option>
            <option value="product">a product</option>
            <option value="blank">nothing</option>
          </select>
        </label>
        <span class="hint" id="tplstate" role="status" aria-live="polite"></span>
      </p>
      {% endif %}
```
5. The statusbar's draft control and the conflict box (render.py:13342-13345) — there is no draft and no 409-with-a-report on a create; a refused create lands in `#problems`:
```jinja
      <p class="field bodybar statusbar" id="statusbar">
        {% if not creating %}<button type="button" id="draftevery"></button>{% endif %}
      </p>
      {% if not creating %}<div id="conflict" role="status" aria-live="polite" hidden></div>{% endif %}
```
And give the textarea (render.py:13332-13333) its blank-page furniture: `{% if creating %}rows="14" placeholder="The shaping document." {% endif %}` inserted before `aria-label="Shaping document"`. `{{ e.raw_body }}` renders empty for the blank row, correctly.

- [ ] **Step 5: The script learns which mode it is in.** In the main `{% if editable %}<script>` block, directly after `const FORM = document.getElementById('edit');` (render.py:13441), insert:

```js
// Creating or editing: one template, one script, two write paths. `null` on a
// stored record's page; the kind being made on `/new`. This is the same flag
// the issue and note pages grew for their create modes — theirs die with those
// templates, and this copy becomes the only one.
const CREATING = {{ creating|tojson }};
// Create-page furniture: null on a stored record, dereferenced only behind
// `CREATING`.
const KIND = document.getElementById('kind');
const PROBLEMS = document.getElementById('problems');
```

- [ ] **Step 6: `dirty()` and the session machinery stand down when creating.** Three small guards. First line of `dirty()` (render.py:13533):
```js
function dirty() {
  // The create bar's sentence is static — "Nothing is written until you press
  // Create". A counter here would count fields against defaults nobody typed.
  if (CREATING) return;
```
First line of `showEditing(editing)` (render.py:13573, as Task 5 left the function — the Edit-button line is already gone from it):
```js
function showEditing(editing) {
  // Unreachable when creating — `showView` touches the session only where a
  // landing exists and the create page has none, and neither Cancel nor
  // Delete is on the page to reach it through `flipEditing` — and guarded
  // anyway, because the failure if that ordering ever changed is a null deref
  // that takes the whole script.
  if (CREATING) return;
```
And the cancel binding Task 5 left at what was render.py:13665 (Task 5 already deleted the `toggle` line above it — this task must not resurrect it) becomes:
```js
if (!CREATING) {
  document.getElementById('cancel').onclick = flipEditing;
}
```
The delete wiring below it (13672: `for (const article of ...)`) needs no edit — it already `continue`s when the article has no `.editbar button.delete`.

- [ ] **Step 7: The kind switch and the template picker, absorbed.** Directly after `attachHill(FORM);` (render.py:13564), insert the block below. It is `_NEW`'s logic with its functions as block-scoped consts, so this page adds no top-level name the pinned `test_no_page_declares_one_name_twice` could collide (`SURFACE` is already defined above at 13454, which is why the block sits here and not beside Step 5's consts).

```js
// The create mode's two pickers. Everything here exists only on `/new`; a
// stored record has a kind already and a body somebody wrote.
if (CREATING) {
  // Every kind's fields are on the page and the ones this kind does not have
  // are hidden, rather than each kind being its own round trip — switching
  // kind after typing a title used to mean typing it again. This hide/show is
  // the kind switch the merged page runs on.
  const showKind = () => {
    for (const element of FORM.querySelectorAll('[data-kinds]'))
      element.hidden = !element.dataset.kinds.split(' ').includes(KIND.value);
  };
  showKind();

  // The body a new record starts from. Switching kind switches template, but
  // only while the box is still one of ours: once somebody has typed, the box
  // is theirs — the template never changes underneath a sentence, and the
  // picker says so rather than appearing to do nothing.
  const TEMPLATES = {{ templates|tojson }};
  const TPL = document.getElementById('template');
  const TPLSTATE = document.getElementById('tplstate');
  const untouched = () =>
    Object.values(TEMPLATES).some(text => text.trim() === SURFACE.text().trim());
  const applyTemplate = name => {
    if (!untouched()) {
      TPLSTATE.textContent = 'the body has been edited — clear it to start from a template';
      return false;
    }
    // A whole-document replacement, said in those words and made once. `apply`
    // marks it as the page writing rather than a person typing, and the event
    // tells the layers drawn beside the box, because `apply` deliberately
    // fires no `input` — without it, choosing `blank` left twenty-one line
    // numbers down the side of an empty box.
    SURFACE.apply(() => SURFACE.splice(0, SURFACE.text().length, TEMPLATES[name] ?? ''));
    dispatchEvent(new Event('openproj:editing'));
    TPLSTATE.textContent = '';
    return true;
  };
  TPL.onchange = () => { applyTemplate(TPL.value); };
  KIND.onchange = () => {
    showKind();
    if (untouched() && TEMPLATES[KIND.value] !== undefined) {
      TPL.value = KIND.value;
      applyTemplate(KIND.value);
    }
  };
  TPL.value = TEMPLATES[KIND.value] !== undefined ? KIND.value : 'blank';
  applyTemplate(TPL.value);
}
```

- [ ] **Step 8: `save()` gains the POST-vs-PATCH branch.** It is PATCH-only today. Change its opening (render.py:13741-13743) to:

```js
async function save() {
  // One button, two verbs: a record that exists is PATCHed with what changed;
  // a record that does not exist yet is POSTed whole. The branch is the entire
  // difference between the two modes' write paths — everything around it,
  // Cmd+S included, is shared.
  if (CREATING) { await createRecord(); return; }
  let fields;
```

Then insert `createRecord` between the end of `save()` (the `}` at render.py:13807) and `document.getElementById('save').onclick = save;` (13811). This is `_NEW`'s handler body moved, with two mechanical substitutions — `BASE` for `FORM.querySelector('[name=base_commit]')` and `TITLED` for its re-query of `.title-field` — and nothing else changed; `test_table.py:623` and `test_editor.py:833` pin several of its literal lines (`still needed at status`, `PROBLEMS.replaceChildren(`, `item.textContent = text;`), so the body must survive verbatim:

```js
// The create half of Save, from the page this one absorbed: collect every
// visible field, check the gates the labels are marked from, POST once, land
// on the record that now exists.
async function createRecord() {
  const fields = {kind: KIND.value};
  const status = FORM.querySelector('[name=status]')?.value || 'shaping';
  const missing = [];
  for (const control of FORM.querySelectorAll('[data-type]')) {
    // A field this kind does not have is not empty, it is absent — sending it
    // would ask the server to set an attribute the model does not define.
    if (control.closest('[data-kinds]')?.hidden) continue;
    let value;
    try { value = read(control); } catch (error) { announce(error.message); return; }
    const empty = value === null || (Array.isArray(value) && !value.length);
    const waived = control.name === 'reviewers' &&
      FORM.querySelector('[name=review_waived]')?.checked;
    // The same gates the labels are marked from, so what the form refuses and
    // what it warned you about cannot be two different lists.
    const gates = control.dataset.requiredAt;
    if (gates && empty && !waived && gates.split(' ').includes(status))
      missing.push(labelOf(control));
    if (!empty) fields[control.name] = value;
  }
  if (TITLED.value.trim()) fields.title = TITLED.value.trim(); else missing.push('Title');
  if (missing.length) {
    // The words on the page, not the words in the file: `person_weeks` is what
    // git holds, and a refusal that names it sends somebody looking for a
    // field with that label.
    const chosen = FORM.querySelector('[name=status]');
    PROBLEMS.hidden = false;
    // `replaceChildren` with one line of text, not `innerHTML`: every word in
    // this sentence comes off the page, and the page's fields hold whatever
    // the plan holds. There is no markup wanted here at all, so none is built.
    const line = document.createElement('li');
    line.textContent = 'still needed at status '
      + `${chosen?.selectedOptions[0]?.textContent.trim() || status}: `
      + missing.join(', ');
    PROBLEMS.replaceChildren(line);
    return;
  }
  // The shell's banner is told before the request goes and the sha after,
  // because the server announces a commit to the event stream before it
  // answers the request that made it.
  dispatchEvent(new Event('openproj:writing'));
  let committed = null;
  try {
    const response = await fetch('/api/entity', {
      method: 'POST', headers: {'content-type': 'application/json'},
      body: JSON.stringify({
        base_commit: BASE.value, fields,
        body: SURFACE.text() || '',
      }),
    });
    const answer = await answerOf(response);
    if (!response.ok) {
      // The client check is a courtesy; this is the truth, and swallowing it
      // leaves somebody staring at a form that looks fine. Built as text
      // nodes, because `answer.detail` quotes back whatever key was posted.
      PROBLEMS.hidden = false;
      PROBLEMS.replaceChildren(...refusals(answer, response.status).map(text => {
        const item = document.createElement('li');
        item.textContent = text;
        return item;
      }));
      return;
    }
    committed = answer.commit;
    location.href = '/detail/' + answer.id;
  } finally {
    // Announced even when refused, or one rejected form leaves every later
    // event held back and the banner never appears again.
    dispatchEvent(new CustomEvent('openproj:wrote', {detail: committed}));
  }
}
```

- [ ] **Step 9: The draft machinery stands down when creating.** `_NEW` never kept a draft — there is no record id to key one to, and Create is the only door out — and the merged page keeps that. Four guards in the draft section (render.py:13849-13988):

1. `sayDraft` (13870) gets a null guard as its first line: `if (!RECEIPT) return;` — `#draftsaved` is not in the creating commitbar.
2. The throttle registration (13934-13939) is gated:
```js
// No draft on the create page: nothing stored means nothing to restore over a
// room, and no key with no id to hang one on.
if (!CREATING) SURFACE.onInput(() => {
  if (draftTimer) return;
  const wait = draftTried + draftMs - Date.now();
  if (wait <= 0) writeDraft();
  else draftTimer = setTimeout(writeDraft, wait);
});
```
(The `pagehide`/`visibilitychange` flushes below it need no edit — both are guarded by `draftTimer`, which stays 0 when nothing registers the throttle.)
3. The interval picker (13952-13958): wrap the whole `statusPick(document.getElementById('draftevery'), ...)` call in `if (!CREATING) { ... }` — the button it fills is not on the creating page.
4. The restore (13960-13988): wrap everything from `const draft = remembered.map(DRAFT);` through the closing `}` of `if (typeof draft.text === 'string' ...)` in `if (!CREATING) { ... }`. The restore-forces-a-session rule from Task 5 is untouched for stored records — this only keeps a page with no stored record from consulting a draft key built from an empty id.

Also fix the now-false comment above `const TITLED` (render.py:13445-13450): it justifies the class-based query with "on the create page the title sits outside `<form>`", which stops being true the moment the pages merge. Replace the last three lines of that comment with:
```js
// the title cannot suppress it. Found by class: it once had to be, when the
// create page kept this box outside `<form>`, and the class find is the one
// that keeps working wherever the box sits.
```

- [ ] **Step 10: `render_detail` grows the creating mode, the record page reads every kind, and the room scripts stay off it.** Spec §2 puts "the record page and its fact rows" and "the detail 404 lookup" on the `records` side of the inversion, and no other task performs those edits — Task 8's flip *asserts* they already happened ("an issue id resolves the moment the rungs land"). They happen here, in the task that owns this page, and they are green by construction at this commit because `records == entities` until Task 8 adds an unplanned rung; Task 8's armed issue/note detail-page tests are the tests that will actually observe the difference, so this commit adds none for it. Three sites. First, replace the signature and body-building half of `render_detail` (render.py:19615-19643) with:

```python
def render_detail(
    index: Index,
    links: Links = STATIC,
    only: str | None = None,
    base_commit: str | None = None,
    may_write: bool = False,
    editor: str = "",
    creating: str | None = None,
) -> str:
    """Every entity, exactly one — or one that does not exist yet.

    The server serves one per route; the static build serves them all in a page
    that hides everything but the hash. Same markup, so the two cannot drift.

    `creating` is the kind being made. The create page was a forked template
    once (`_NEW`), and a fork is what the issue and note pages proved a fork
    does; it is now this template with a blank record, the union of every
    kind's fields, and `data-kinds` deciding what shows.
    """
    if creating is not None:
        # A blank record through the same row machinery. No id (the server
        # mints it), no cascade (nothing to delete), no problems (nothing has
        # been refused yet).
        rows: list[dict] = [{
            "id": "",
            "title": "",
            "kind": creating,
            "parent": None,
            "parent_link": "",
            "problems": [],
            "hints": [],
            "progress": None,
            "body": Markup(""),
            "rows": _new_rows(),
            "raw_body": "",
            "deletes": [],
            "frees": [],
        }]
    else:
        rows = _detail_rows(index, links)
        if only is not None:
            rows = [row for row in rows if row["id"] == only]
        # Every entity gets its facts, not only the one being served on its own
        # route: the static export renders them all, and it is the same page.
        # `records`, not `entities`: this page is every record's page — spec §2
        # puts it on the total side of the inversion, and the day an unplanned
        # rung lands its records get their pages through this line unchanged.
        for row in rows:
            entity = index.records[row["id"]]
            row["rows"] = _fact_rows(index, entity, links)
            row["raw_body"] = entity.body
            row["deletes"], row["frees"] = cascade_of(index, row["id"])
    body = _ENV.from_string(_DETAIL).render(
        entities=rows,
        groups=[] if creating else _by_status(rows),
        showing=[] if creating else [row["id"] for row in rows],
        single=creating is not None or only is not None,
        creating=creating,
        kinds=KINDS,
        templates=TEMPLATES if creating else {},
```

Keep every existing keyword below that point (`links=`, `editable=`, `may_write=`, `base_commit=`, `statuses=`, `combobox=`, `required=`, `hill=`, `viewbar=`, `views=`, `splitter=`, `ace=`, `acesurface=`, and anything Task 3 added) **except** the last two, which gain the creating gate — a record with no id has no room to join, exactly as `_NEW` never carried these bytes:

```python
        yjs=_yjs() if base_commit is not None and may_write and creating is None else Markup(""),
        coedit=_COEDIT if base_commit is not None and may_write and creating is None else Markup(""),
    )
    if creating is not None:
        # No nav item marked, deliberately: `aria-current="page"` claims a page
        # within the set, and pressing Table from this form abandons it rather
        # than staying put. With nothing lit, the <h1> is what names the page.
        return _page(
            f"openproj — new {creating}", body, _DETAIL_STYLE + _SUGGEST_STYLE, links,
            unreadable=index.unreadable,
        )
    return _page(
        "openproj — detail", body, _DETAIL_STYLE + _SUGGEST_STYLE, links, "detail",
        index.unreadable,
    )
```

The existing comments inside the old `.render(...)` call (on `may_write`, `showing`, `yjs`) stay where they are.

Second, `_detail_rows`' row source (render.py:16513, the closing line of its list comprehension) switches sides:

```python
        for entity_id, entity in sorted(index.records.items())
```

(was `sorted(index.entities.items())`; everything the comprehension reads per row — `index.problems`, `index.children`, `_links`, `_progress_view`, `_body_html` — is already total or takes the entity itself, and Task 2 made the `blocked_by`/`blocks` maps total over `records` precisely so a fact row here cannot `KeyError`). Add one comment directly above the `return [`:

```python
    # Over `records`, not `entities`: the record page is the one page every
    # kind gets (spec §2). Until an unplanned rung exists the two maps are
    # equal, so nothing changes at this commit — the line is here so the flip
    # commit ships pages, not KeyErrors.
```

Third, the detail 404 lookup (web.py:1780, inside `GET /detail/{entity_id}`; the anchor is `raise HTTPException(404, f"no entity {entity_id!r}")` on the next line):

```python
        if entity_id not in index.records:
```

(was `index.entities`; the comment block below it about `base_commit` and `may_write` stays untouched). `render_detail(... only=entity_id ...)` then finds the row because `_detail_rows` walks the same map — the route and the renderer cannot disagree about which records have pages.

- [ ] **Step 11: Delete `_NEW` and `render_new`.** Remove render.py:12783-13105 (the whole `_NEW = """..."""` assignment, up to but not including `_DETAIL = """` at 13106) and render.py:16683-16730 (`def render_new(...)` through its closing `return _page(...)`; `def _pr_sort` at 16732 is the next thing in the file and stays). Fix the one comment that names the dead template, render.py:14660: change `` `_DETAIL` (with `_NEW`) put the mode class on `article.entity`; `` to `` `_DETAIL` puts the mode class on `article.entity`; ``. `_new_rows`, `TEMPLATES` and `KINDS` all stay — they are the creating mode's data. Verify nothing dangles: `grep -n "render_new\|_NEW\b" src/openproj/*.py` must come back empty.

- [ ] **Step 12: `GET /new` serves the merged page.** Replace the route body at web.py:1761-1771. Same path, same `kind` query with the same default, same 422 — the old `/new` and `/new?kind=…` links all keep working; only what is rendered changes. `/issue/new` (web.py:1341) and `/note/new` (web.py:1451) are not touched.

```python
    @app.get("/new", response_class=HTMLResponse)
    def new(request: Request, kind: str = "task") -> HTMLResponse:
        if kind not in DIRECTORY:
            raise HTTPException(422, f"kind must be one of {sorted(DIRECTORY)}")
        commit, index = index_now()
        return page(
            render.render_detail(
                index,
                render.ROUTES,
                base_commit=commit,
                may_write=may_write(request),
                editor=which_editor(request),
                creating=kind,
            )
        )
```

No injection-census edit is needed: the census (tests/test_injection.py:303) registers `"new task": "/new?kind=task", "new pitch": "/new?kind=pitch"` by route, and the routes are unchanged.

- [ ] **Step 13: Repoint the three fixtures that call `render_new` — these are the create-form tests that move.** Everything else survives verbatim; say so in the commit body. The survivors, verified by reading them against the merged markup: the whole `new_page` suite in `tests/test_table.py` (319 fields-a-person-owns, 344 no-id-no-path, 357 kinds-and-422s, 415 gates-on-controls, 447 gates-are-the-validator's, 475 `data-kinds` ownership — the kind-switch test, 506 server-refuses-foreign-field, 522 somewhere-for-the-refusal, 623 gate-before-post, 289 every-status-offered), `tests/test_editor.py` 555 (kindpick eyebrow position), 724 (uploads), 815/833 (live regions, refusals), 2334 (preview title), `tests/test_product.py:305` (product round-trip), `tests/test_gitdoor.py:53` and `tests/test_writes.py:71` (route lists), and `tests/test_web.py:377/403/446` (route sweeps). The movers:

In `tests/test_render.py:2872-2887`, the `server_pages` fixture:
```python
    from openproj.render import ROUTES, render_cycle, render_detail

    one = next(iter(seed_index.entities))
    return {
        "cycle": render_cycle(seed_index, 37, ROUTES, base_commit="deadbee"),
        "new": render_detail(seed_index, ROUTES, base_commit="deadbee", creating="task"),
        "entity": render_detail(seed_index, ROUTES, only=one, base_commit="deadbee"),
    }
```
In `tests/test_cascade.py:50-73`, the `served_pages` fixture: delete `render_new` from the import list and change the `"create"` entry to
```python
        "create": render_detail(index, ROUTES, base_commit=HEAD, may_write=True,
                                creating="task"),
```
(the comment above it about the create page being "the same markup and the same stylesheet with the mode already on" is now literally true — leave it). In `tests/test_cascade.py:1125-1140`: the import becomes `from openproj.render import render_cycle, render_graph` and the `"create"` entry becomes
```python
        "create": (render_detail(index, ROUTES, base_commit=HEAD, may_write=True,
                                 creating="task"),
                   [el("article", "entity editing"), bar]),
```
And in `tests/test_web.py:354`, the docstring line "`render_new`'s docstring is / where that is argued" becomes "`render_detail`'s creating branch is where that is argued" — the assertion beneath it (`/new?kind=task` lights nothing) is unchanged and now holds against the merged page.

- [ ] **Step 14: The two new tests, written in this same commit.** In `tests/test_table.py`, directly after `test_the_create_form_offers_the_three_kinds_and_nothing_else` (line 357) — whose name and body Task 8 will revisit, not this task:

```python
def test_the_kind_picker_offers_every_rung_and_only_rungs(new_page: str):
    """Derived on both sides: `KINDS` draws the options and the route refuses
    the rest, so a rung added to the ladder is creatable the day it lands
    rather than the day somebody remembers this select."""
    pick = re.search(r'<select id="kind">.*?</select>', new_page, re.S)
    assert pick, "the create page must carry the kind picker"
    assert options(pick.group(0)) == set(KIND_NAMES)


def test_the_create_page_is_the_record_page_in_a_mode(client: TestClient):
    """One template, one script, two verbs. The create form was forked markup
    once (`_NEW`), and a fork is what the issue and note pages proved a fork
    does — the note got the hill and the issue did not, in one commit. Which
    verb runs is data (`CREATING`), never a second page."""
    import openproj.render as render

    new = client.get("/new?kind=task").text
    detail = client.get(f"/detail/{TASK}").text

    assert not hasattr(render, "_NEW"), "the forked template is gone"
    assert not hasattr(render, "render_new"), "and so is its renderer"
    for html in (new, detail):
        assert "if (CREATING) { await createRecord(); return; }" in html
        assert "async function createRecord()" in html
    assert 'const CREATING = "task";' in new
    assert "const CREATING = null;" in detail, "a stored record's page creates nothing"


@pytest.mark.parametrize("kind", KIND_NAMES)
def test_a_record_created_from_the_merged_page_round_trips(client: TestClient, kind: str):
    """The whole create flow per kind, through the page's own base commit: the
    page renders, the POST lands, and the record comes back as a page. The
    read-back is the record's own page, never /api/index.json — that map is
    plan-only by design and cannot answer for an unplanned rung. Parametrized
    over the ladder, so the rungs Task 8 adds walk through this door on the
    day they exist — if their server stamping is missing, this is the test
    that says so."""
    page = client.get(f"/new?kind={kind}")
    assert page.status_code == 200
    base = re.search(r'name="base_commit" value="([0-9a-f]{40})"', page.text).group(1)

    made = client.post(
        "/api/entity",
        json={"base_commit": base,
              "fields": {"kind": kind, "title": f"Round trip {kind}"},
              "body": "A record made from the merged page.\n"},
    )
    assert made.status_code == 201, made.json()
    new_id = made.json()["id"]
    own = client.get(f"/detail/{new_id}")
    assert own.status_code == 200
    assert f"Round trip {kind}" in own.text, (
        "the record's own page is the read-back for every kind — "
        "/api/index.json is plan-only by design and cannot answer for an "
        "unplanned rung"
    )
```

`KIND_NAMES`, `TASK`, `options`, `re`, `pytest` are already imported at the top of `tests/test_table.py` (lines 60-100) — no import edits needed.

- [ ] **Step 15: Verify locally (ruff only), commit, push, read CI.** No pytest on this machine — not one file. The red/green gate is CI.

```bash
cd /Users/jcanton/projects/openproj/.worktrees/one-record-one-page
uv sync
uv run ruff check .
git add src/openproj/render.py src/openproj/web.py tests/test_table.py tests/test_render.py tests/test_cascade.py tests/test_web.py
git commit -F- <<'EOF'
Creating a record is the record page with nothing in it

The create form was a forked copy of the record page (`_NEW`, 320 lines of
markup and script beside `_DETAIL`'s), and a fork is what the issue and note
pages already proved a fork does: the two drifted field by field, comment by
comment, from the page they were copied from. The fork also duplicated the one
mechanic the merged page actually needs — every kind's fields on the page with
`data-kinds` hiding the rest IS the kind switch — so absorbing it costs less
than keeping it.

`_DETAIL` now has a creating mode: the kind picker in the eyebrow, the template
picker over the body, the union-of-fields rows, a visible bar whose button says
Create, and no draft, no room, no Delete, no landing document — there is no
stored record for any of them to be about, and the absent landing is what
keeps the view machine's create-form exception structural. save() gains the
POST-vs-PATCH branch the issue and note pages already carry (theirs die with
their templates next); everything around the branch, Cmd+S included, is one
script. `_NEW` and `render_new` are deleted; GET /new?kind=... serves the
merged page and the old /new keeps working. /issue/new and /note/new are
untouched here — they go when their kinds become rungs.

The record page also moves to the total side of the Task 2 inversion, as spec
§2 lists it: _detail_rows walks index.records, render_detail looks its rows up
there, and GET /detail/{id}'s 404 check reads the same map. With no unplanned
rung existing yet the two maps are equal, so nothing observable changes at
this commit; the flip commit's issue and note pages resolve through these
three lines unchanged.

The create-form suite survives against the merged page; the three fixtures that
called render_new now render the detail template in creating mode. New pins:
the picker is derived from the ladder, the create page and a record page are
one template with one script, and a create round-trips per kind through the
page's own base commit.

🤖 Written by an agent on behalf of @jcanton
EOF
git push -u origin one-record-one-page
gh pr checks --watch || gh run list --branch one-record-one-page --limit 1
```

Read the CI result before starting Task 7. The failures worth expecting, and what each means: a `test_table.py:485` regex miss means Step 3's creating `<dd>` grew an attribute before `data-kinds`; a `test_editor.py:555` index error means Step 1 changed a byte of the eyebrow literal; an `'id="toggle"' not in page` failure means Step 2 or Step 6 resurrected the Edit button Task 5 removed; a Task 5 hatch-test or `_NARROW_FULL_PAGE` failure on `/new` means Step 4's `.doc.read` gate was missed and `LANDING` went truthy on the create page; a `ReferenceError` in any JS-driven test on the detail page means a create-only element was dereferenced outside a `CREATING` guard (Steps 6 and 9 are the checklist).


---

### Task 7: The plan opens on what changed last

**Files:**
- Modify: `src/openproj/store.py:32` (imports), `:379-402` (`blobs`), new code after `:402` and after `close()` at `:851-853`
- Modify: `src/openproj/model.py:1036` (after `_ENTITY_DIRS`)
- Modify: `src/openproj/render.py:24` (imports), `:1571-1603` (`Links`), `:1632-1639` (`STATIC`/`ROUTES`), after `:16071` (`_human`), before `:20871` (`render_table`), `:20741-20745` (`_NAV`), `:20983-21012` (`render_static`)
- Modify: `src/openproj/web.py:60-104` (imports), `:1140-1171` (beside the index cache), `:1286-1289` (the `/` route)
- Modify: `src/openproj/cli.py:19-29` (imports), `:104-117` (`_render`), `:245-276` (`_demo`), `:279-302` (`_serve`)
- Test: `tests/test_store.py:98-120` (`commit_directly`) plus new tests appended
- Test: `tests/test_injection.py:84-85`, `:272-318`, plus the census-completeness test
- Test: `tests/test_records.py` (create)
- Test: repoints in `tests/test_render.py`, `tests/test_web.py`, `tests/test_table.py`, `tests/test_gitdoor.py`, `tests/test_editor.py`, `tests/test_writes.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: `Index.records: dict[str, Entity]` and `Index.entities` narrowed to planned kinds (Task 2); `index.search_blob[record_id]` defined over every record (Task 2); `apply_filters(index, filters, query, over=index.records)` — the `over` parameter Task 2 adds, used by the parity test as the server half of the landing's search twin; `Rung.planned` (Task 1); existing `_facets_html(facets, fields=..., search=..., aside=..., titles=...)` (`render.py:19715`), `_FILTER_JS` (`render.py:4192`), `_page(title, content, style, links, current, unreadable)` (`render.py:20762`), `Store.head()`, `Store.blobs(commit)`, `Store.has(commit)` (`store.py:337-402`).
- Produces:
  - `Store.last_edited(self, known: tuple[str, dict[str, int]] | None = None) -> tuple[str, dict[str, int]]`
  - `last_edited_in(repo_path: Path) -> dict[str, int] | None` (module-level, `store.py`)
  - `edited_by_id(stamps: dict[str, int]) -> dict[str, int]` (module-level, `model.py`)
  - `_ago(epoch: int, now: int) -> str` (`render.py`, beside `_human`)
  - `render_records(index, links=STATIC, base_commit=None, edited=None, now=0) -> str`
  - `Links.records` (`"index.html"` static, `"/"` served); `Links.table` becomes `"table.html"` / `"/table"`
  - `GET /` → Records, `GET /table` → the table; nav word **Records**
  - `census_routes(entity_ids)` and `CENSUS_BLIND` in `tests/test_injection.py` (Task 8 retires the two `CENSUS_BLIND` entries when `/issue/{id}` and `/note/{id}` become redirects)

---

- [ ] **Step 1: Import `SortMode` in `store.py`.**

`store.py:32` currently reads `from pygit2.enums import RepositoryOpenFlag`. Change it to:

```python
from pygit2.enums import RepositoryOpenFlag, SortMode
```

- [ ] **Step 2: Extract the tree walk out of `Store.blobs` so a read-only caller can share it.**

`Store.blobs` (`store.py:379-402`) walks a commit's tree into `{path: blob_id}`. The export needs the same walk over a repository no `Store` is open on, and an invariant written twice is guarded once. Replace the body of `blobs` and add a module function directly above the `class Store:` line (`store.py:270`):

```python
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
```

and the method becomes (keep its docstring, delete its old body):

```python
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
```

- [ ] **Step 3: The history walk's helpers, module-level in `store.py`, below `_tree_blobs`.**

```python
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
```

- [ ] **Step 4: `Store.last_edited`, inserted directly after `blobs` (before the `# -- the remote` section at `store.py:404`).**

```python
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
```

- [ ] **Step 5: `last_edited_in`, the read-only door for the export. Add after `Store`'s `close()` (`store.py:853`), above `build_plan_repository`.**

```python
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
```

- [ ] **Step 6: Teach `tests/test_store.py`'s `commit_directly` about time, parents and dangling commits.**

The walk's tests need side branches, merges and committer clocks that mean something. Replace `commit_directly` (`tests/test_store.py:98-120`) with:

```python
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
```

Every existing caller passes positional `(repo_path, files, message)` or `author=` — unchanged behaviour.

- [ ] **Step 7: Spec test 12 — a side-branch edit merged in carries the side commit's time. Append to `tests/test_store.py` with a section banner.**

```python
# --------------------------------------------------------------------------- #
# 6. last_edited: when a commit last touched each path, in git-log semantics
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
    on_main[OTHER] = entity(id="task-c00002", title="Downgrade numpy differently", owner="bo")
    tip = commit_directly(path, on_main, "edit the other task on main", when=1_000_100)

    on_side = dict(SEED)
    on_side[PATH] = entity(title="Reproduce the artefact at the pole")
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
```

- [ ] **Step 8: Spec test 13 — an edit reverted inside one fetch batch is stamped by the revert, and the incremental walk agrees with the full one.**

```python
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
        edited[PATH] = entity(status="in_progress")
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
        changed["tasks/task-c00003.md"] = entity(id="task-c00003", title="A third task")
        commit_directly(path, changed, "add one, delete one", when=1_000_300)

        head, stamps = store.last_edited(known=known)
        assert OTHER not in stamps, "a deleted path must leave the map"
        assert stamps["tasks/task-c00003.md"] == 1_000_300
        assert (head, stamps) == store.last_edited()
    finally:
        store.close()
```

- [ ] **Step 9: Spec test 11 — a rewound ref discards the cache and rebuilds, with no phantom "edited just now".**

The rewind is exactly what `_attempt` does after a lost push race (`store.py:731` and `:738`: `self._repo.references[_BRANCH].set_target(before)`).

```python
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
        doomed_tree[PATH] = entity(title="An edit whose push will lose")
        doomed = commit_directly(path, doomed_tree, "a doomed publish", when=1_000_100)
        known = store.last_edited()
        assert known[0] == doomed
        assert known[1][PATH] == 1_000_100

        # Rewind the way `_attempt` does, then land somebody else's commit.
        pygit2.Repository(str(path)).references["refs/heads/main"].set_target(base)
        winners = dict(SEED)
        winners[OTHER] = entity(id="task-c00002", title="The write that won", owner="bo")
        winner = commit_directly(path, winners, "the winning write", when=1_000_150)

        head, stamps = store.last_edited(known=known)
        assert head == winner
        assert stamps[PATH] == 1_000_000, "the doomed edit's stamp must not survive"
        assert stamps[OTHER] == 1_000_150
        assert 1_000_100 not in stamps.values()
    finally:
        store.close()
```

- [ ] **Step 10: `edited_by_id` in `model.py`, directly after `_ENTITY_DIRS` (`model.py:1036`).**

```python
def edited_by_id(stamps: dict[str, int]) -> dict[str, int]:
    """Per-record last-edited epochs, joined from `Store.last_edited`'s per-path
    map.

    Here rather than in `web.py` or `cli.py` because the layout facts it reads —
    which directories hold records, `<id>--<slug>.md` with a slug that drifts —
    are this module's (`record_paths_in`, `_path_for`'s stem rule), and both the
    server and the export need the join. Two copies is the drift this file bans.

    Two files claiming one id is a blocker the pages already draw; for a time
    column the newest claim wins, because the row exists either way and a wrong
    recency beats a missing row.
    """
    record_paths, _ = record_paths_in(_ENTITY_DIRS, stamps)
    found: dict[str, int] = {}
    for path in record_paths:
        stem = path.rpartition("/")[2].removesuffix(".md")
        record_id = stem.partition("--")[0]
        if stamps[path] > found.get(record_id, 0):
            found[record_id] = stamps[path]
    return found
```

Because it reads `_ENTITY_DIRS`, the Task 8 flip (which widens `_ENTITY_DIRS` to six directories) makes issue and note stamps appear with no edit here — which is the build order's "shows plan records until commit 8, which is exactly right".

- [ ] **Step 11: `_ago` in `render.py`, beside `_human`.**

First widen the import at `render.py:24` from `from datetime import date` to:

```python
from datetime import UTC, date, datetime
```

Then insert directly after `_human` (`render.py:16067-16071`), before the `_ENV.globals["human"]` line:

```python
# Where "how long ago" stops being the useful answer and "when" begins.
# docs/hackmd-observed.md reads the boundary off the pixels: one column runs
# `17 hours ago` … `10 days ago` and then switches to `2026-07-08` (about 43
# days before the shot), so the threshold falls somewhere past ten days and
# before forty-three. Fourteen keeps every relative form the screenshot shows
# and abandons the form at the first round boundary after them — two weeks —
# because the same observation says the relative answer stops being useful
# before the absolute one does, so when in doubt, switch early.
_ABSOLUTE_AFTER = 14 * 24 * 3600


def _ago(epoch: int, now: int) -> str:
    """`17 hours ago`, or `2026-05-26` once "ago" stops meaning anything.

    Past the threshold the relative form is abandoned rather than extended —
    nobody is shown "2 years ago". A stamp ahead of `now` is a wrong clock on
    some committer's machine; "in 3 hours" under a last-edited column reads as
    broken, so the absolute date — which is at least true — is the answer there
    too.

    Arithmetic and f-strings only: this file is AST-banned from every
    `.replace` attribute call (`test_no_page_is_assembled_by_substitution`),
    and `datetime.replace` is spelled exactly like `str.replace` to that test.
    """
    gone = now - epoch
    if gone < 0 or gone >= _ABSOLUTE_AFTER:
        return datetime.fromtimestamp(epoch, tz=UTC).date().isoformat()
    if gone < 60:
        return "just now"
    if gone < 3600:
        minutes = gone // 60
        return "a minute ago" if minutes == 1 else f"{minutes} minutes ago"
    if gone < 86400:
        hours = gone // 3600
        return "an hour ago" if hours == 1 else f"{hours} hours ago"
    days = gone // 86400
    return "a day ago" if days == 1 else f"{days} days ago"
```

- [ ] **Step 12: `Links` gains `records`; the table's URLs move.**

In `Links` (`render.py:1571-1603`), immediately above `table: str = "index.html"`, change the pair to:

```python
    # The landing list — every record, last edited first. It takes the root
    # name in both modes because it is the page the tool opens on.
    records: str = "index.html"
    table: str = "table.html"
```

In `ROUTES` (`render.py:1633-1639`) change the first line of arguments from
`table="/", detail="/detail", ...` to:

```python
ROUTES = Links(
    records="/", table="/table", detail="/detail", graph="/graph", timeline="/timeline",
    entity="/detail/", new="/new", people="/people",
    cycles="/cycles", cycle="/cycle/", issues="/issues", issue="/issue/",
    notes="/notes", note="/note/",
    asset="/assets/", deck="/deck/", body="/api/body/",
)
```

`_page`'s `live=links.table.startswith("/")` (`render.py:20847`) stays correct in both modes (`"/table"` vs `"table.html"`); leave it.

- [ ] **Step 13: The nav word is Records, first in the row.**

`render.py:20741-20745`:

```python
_NAV = (
    ("records", "Records"), ("table", "Table"), ("graph", "Graph"),
    ("timeline", "Timeline"), ("cycles", "Cycles"), ("people", "People"),
    ("issues", "Issues"), ("notes", "Notes"),
)
```

`_NAV_KEYS`, `_OFF_NAV`, `_PAGE_KEYS` need no edit — they derive.

**The hardcoded-`/` grep, run and answered** (`grep -n 'RedirectResponse("/' src/openproj/web.py; grep -n 'links.table' src/openproj/render.py; grep -rn 'href="/"' src`). Every hit, and what happens to it:

| where | what | action |
|---|---|---|
| `web.py:3147` | `/auth/callback` → `RedirectResponse("/", 303)` | **unchanged** — login lands on Records by design (spec §6) |
| `web.py:3162` | `/logout` → `RedirectResponse("/", 303)` | **unchanged**, same row of the routes table |
| `web.py:3113,3155,3157,3167` | cookie `path="/"` | cookie scope, not a link — untouched |
| `render.py:12785` | create form's `← table` back link via `links.table` | follows the field to `/table`; copy stays true |
| `render.py:13136` | detail page's `← all entities` via `links.table` | follows to `/table` (commit 9 may re-word) |
| `render.py:13725` | after Delete, `location.href = links.table` | follows to `/table` — the table is still the working surface |
| `render.py:17718,17745` | people page role links `{{ links.table }}?owner=…` | **must** keep pointing at the table: they carry table filters |
| `tests/test_render.py:1102,1105` | assert `href="index.html?…"` | repointed to `table.html` in Step 22 |

- [ ] **Step 14: The landing template, its stylesheet, and `render_records`. Insert all three directly above `def render_table` (`render.py:20871`).**

```python
_RECORDS = """
{#- Announced, not drawn: the lit nav item already says Records. -#}
<h1 class="sr-only">Records</h1>
{{ facets }}
<ul id="records">
{%- for r in rows %}
  <li data-id="{{ r.id }}">
    <span class="chip kind-{{ r.kind }}">{{ r.kind }}</span>
    <a href="{{ links.entity }}{{ r.id }}">{{ r.title or r.id }}</a>
    {%- if timed %}<span class="when">{{ r.ago }}</span>{% endif %}
  </li>
{%- endfor %}
</ul>
{#- The no-records sentence is server-rendered so it is right before any script
    runs and in an export where none may. The script below redraws the same
    block for the states only the browser can reach. -#}
<div id="records-empty" role="status"{% if rows %} hidden{% endif %}>
  <p class="headline">{% if not rows %}This plan has no records yet.{% endif %}</p>
  <p class="hint">{% if not rows %}Nothing has been written down.{% endif %}</p>
</div>
<script id="landing" type="application/json">{{ payload|tojson }}</script>
{{ filters }}
<script>
// The bar above is `_facets_html`, which renders #q, #query-error and #unfilter
// unconditionally — exactly what `_FILTER_JS` requires, because its listeners
// are unguarded. The rows are server-rendered; this script only hides them, so
// a payload that did not survive the trip degrades to an unfiltered list
// rather than an empty page.
let RECORDS = null;
try {
  RECORDS = JSON.parse(document.getElementById('landing').textContent);
} catch (error) { RECORDS = null; }
const RECORDS_LOADED = RECORDS !== null;
if (!RECORDS_LOADED) RECORDS = {rows: {}};

const recordItems = [...document.querySelectorAll('#records li[data-id]')];
const recordsEmpty = document.getElementById('records-empty');

// Four states, four sentences, and they must not look like each other: a
// payload that did not load, a plan with no records, a query that cannot be
// read (whose parse error `sayQueryError` already puts beside the box — the
// block only points at it), and a search that matched nothing.
function recordsApply() {
  let shown = 0;
  for (const item of recordItems) {
    const row = RECORDS.rows[item.dataset.id];
    const kept = !RECORDS_LOADED || (!!row && matches(row));
    item.hidden = !kept;
    shown += kept ? 1 : 0;
  }
  let headline = '', hint = '';
  if (!RECORDS_LOADED) {
    headline = 'This search cannot run.';
    hint = 'The page arrived without its search data, so the list is shown unfiltered.';
  } else if (!recordItems.length) {
    headline = 'This plan has no records yet.';
    hint = 'Nothing has been written down.';
  } else if (queryError()) {
    headline = 'That search cannot be read.';
    hint = 'What is wrong with it is beside the search box.';
  } else if (!shown) {
    headline = 'No record matches this search.';
    hint = 'Every record is hidden by what is in the box.';
  }
  recordsEmpty.querySelector('.headline').textContent = headline;
  recordsEmpty.querySelector('.hint').textContent = hint;
  recordsEmpty.hidden = !headline;
}
addEventListener('openproj:filter', recordsApply);
recordsApply();
</script>
"""

_RECORDS_STYLE = """
/* One line per record: chip, title, time. The chip rules come from the shell
   (`.chip.kind-…`), so a kind added to the ladder arrives here already drawn. */
#records { list-style: none; margin: 1rem 0 2rem; padding: 0; max-width: 62rem; }
#records li { display: flex; align-items: baseline; gap: .6rem;
              padding: .4rem .25rem; border-bottom: 1px solid var(--line); }
#records li a { min-width: 0; overflow-wrap: anywhere; }
#records .when { margin-left: auto; color: var(--muted); font-size: 12px;
                 white-space: nowrap; font-variant-numeric: tabular-nums; }
#records-empty .headline { font-weight: 600; margin: 1.5rem 0 .25rem; }
#records-empty .hint { color: var(--muted); margin: 0; }
"""


def render_records(
    index: Index,
    links: Links = STATIC,
    base_commit: str | None = None,
    edited: dict[str, int] | None = None,
    now: int = 0,
) -> str:
    """The landing list: every record, sorted by when a commit last touched it.

    One row is a kind badge, a title linking to the record's page, and one
    relative time — the count of what a HackMD card carries. Nothing else: no
    owner, no status, no tags. The table is the filtering surface; this is the
    finding one.

    `edited` is record id -> epoch seconds (`Store.last_edited` joined through
    `edited_by_id`), or None where there is no history to ask — `openproj
    render` over a plain directory. None OMITS the time column rather than
    leaving it blank, because blank looks broken; the list then sorts by id,
    the one order that exists without a clock. File mtimes are never consulted:
    they lie after a fresh clone.

    `base_commit` is accepted for signature parity with every other page
    renderer and unused: the page offers no writes, so there is nothing to
    compare-and-swap against.
    """
    timed = edited is not None
    rows = []
    for record_id, record in index.records.items():
        epoch = (edited or {}).get(record_id, 0)
        rows.append(
            {
                "id": record_id,
                "kind": record.kind,
                "title": record.title,
                "tags": record.tags,
                "epoch": epoch,
                # Empty when the id has no stamp (a path collision the pages
                # already report as a blocker): nothing, not 1970.
                "ago": _ago(epoch, now) if timed and epoch else "",
                "search": index.search_blob[record_id],
            }
        )
    if timed:
        rows.sort(key=lambda row: (-row["epoch"], row["id"]))
    else:
        rows.sort(key=lambda row: row["id"])
    body = _ENV.from_string(_RECORDS).render(
        rows=rows,
        timed=timed,
        links=links,
        # `predicates: []`, literally: `matches()` dereferences it unguarded,
        # and an omitted array plus a `?predicate=` in the URL is a blank page.
        # Empty rather than computed, because predicates are plan diagnostics
        # and the table is where they are drawn and filtered.
        payload={
            "rows": {
                row["id"]: {
                    "id": row["id"], "kind": row["kind"], "title": row["title"],
                    "tags": row["tags"], "search": row["search"], "predicates": [],
                }
                for row in rows
            }
        },
        # No dropdowns: facets are plan vocabulary and this page is the whole
        # record population. The bar still renders #q, #query-error and
        # #unfilter, which is all `_FILTER_JS`'s unguarded listeners need.
        facets=_facets_html(index.facets, fields=()),
        filters=_FILTER_JS,
    )
    return _page(
        "openproj — records", body, _RECORDS_STYLE, links, "records", index.unreadable
    )
```

- [ ] **Step 15: The export writes the landing as `index.html` and the table as `table.html`.**

`render_static` (`render.py:20983`): change the signature and the page list.

```python
def render_static(
    index: Index,
    out_dir: Path,
    repo: Path | None = None,
    edited: dict[str, int] | None = None,
    now: int = 0,
) -> tuple[str, ...]:
```

Extend the docstring's last paragraph with:

```
    `edited` and `now` feed the landing's time column and come from the caller
    (`cli._render`), which is the one that knows whether the directory it was
    pointed at is a repository at all — None omits the column.
```

and change the page tuple's first entry into two:

```python
    for name, html in (
        ("index.html", render_records(index, edited=edited, now=now)),
        ("table.html", render_table(index)),
        ("detail.html", render_detail(index)),
        ("people.html", render_people(index)),
        ("cycles.html", render_cycles(index)),
        ("issues.html", render_issues(index)),
        ("notes.html", render_notes(index)),
        ("graph.html", render_graph(index)),
        ("timeline.html", render_timeline(index)),
    ):
```

- [ ] **Step 16: `web.py` — the walk cache beside `held`, the warm hook, and the two routes.**

Add `edited_by_id` to the existing `from .model import (` block (`web.py:71-103`), keeping the list alphabetical.

Directly after `_build_index_at` ends (`web.py:1171`), insert:

```python
    # The last history walk, and the head it walked TO. Keyed on the commit
    # ALONE — deliberately narrower than the index cache's (commit, today)
    # above: the map is a fact about history, not about the day the plan is
    # drawn around, and an instance living across midnight must not re-walk a
    # second of history to redraw the same answer.
    #
    # One name, swapped atomically, for the reason `held` gives at length: two
    # dozen sync routes run on anyio worker threads, and reading a single name
    # is one atomic load under the GIL.
    edited_held: tuple[str, dict[str, int]] | None = None

    def edited_now() -> tuple[str, dict[str, int]]:
        nonlocal edited_held
        memo = edited_held
        if memo is not None and memo[0] == store.head():
            return memo
        # `known=memo` advances over just the new commits when the cached
        # commit is an ancestor of head; anything else — a rewound ref after a
        # lost push race is ROUTINE here, not a force-push story — discards and
        # re-walks. Retract-by-rebuild: no retraction logic to get wrong, and
        # affordable because the full walk is about a second (measured: ~0.5 ms
        # per commit on a 520-record plan).
        fresh = store.last_edited(known=memo)
        edited_held = fresh
        return fresh

    # Startup owns the first walk: `cli._serve` calls this before uvicorn
    # binds, and the lifespan hook stays empty at startup on purpose. The walk
    # must never ride a request — a second billed to whichever reader loses
    # the race is exactly the cost this cache exists to hide.
    app.state.warm_edited = edited_now
```

Replace the `/` route (`web.py:1286-1289`) with:

```python
    @app.get("/", response_class=HTMLResponse)
    def records() -> HTMLResponse:
        commit, index = index_now()
        # The map may be one commit ahead of `commit` if a write lands between
        # the two reads. The times are display; the rows are the index's; the
        # event stream's reload reconciles them a moment later.
        _, stamps = edited_now()
        return page(
            render.render_records(
                index,
                render.ROUTES,
                base_commit=commit,
                edited=edited_by_id(stamps),
                now=int(time.time()),
            )
        )

    @app.get("/table", response_class=HTMLResponse)
    def table() -> HTMLResponse:
        commit, index = index_now()
        return page(render.render_table(index, render.ROUTES, base_commit=commit))
```

- [ ] **Step 17: `cli.py` — the export's walk, the eager first walk, and its log line.**

Add `import time` to the stdlib imports (`cli.py:21-28`, between `tempfile` and the `from` lines per isort), and add `edited_by_id` to `from .model import Config, load_repo, validate_all` (`cli.py:32`):

```python
from .model import Config, edited_by_id, load_repo, validate_all
```

Replace `_render` (`cli.py:104-117`):

```python
def _render(repo: Path, out_dir: Path, today: date | None) -> int:
    from .render import render_static
    from .store import last_edited_in

    entities, config, unreadable = load_repo(repo)
    # Walk when the directory is a repository; otherwise the landing renders
    # WITHOUT the time column — omitted, not blank, because blank looks broken
    # and file mtimes lie after a fresh clone.
    stamps = last_edited_in(repo)
    written = render_static(
        build_index(entities, config, today or date.today(), unreadable),
        out_dir,
        repo,
        edited=edited_by_id(stamps) if stamps is not None else None,
        now=int(time.time()),
    )
    print(f"wrote {', '.join(written)} to {out_dir}")
    # Said here as well as drawn on the pages: a build log is where somebody
    # notices, and a static export of a plan missing three of its files that
    # announces only success is how it ships.
    for one in unreadable:
        print(f"left out {one.path}: {one.why}")
    return 0
```

In `_serve` (`cli.py:279-302`), between `app = create_app(...)` and the `return`, insert:

```python
    # The first walk runs before uvicorn binds, so it can never ride a request.
    # Logged so the drift is visible long before it hurts: the cost grows with
    # history length (~0.5 ms per commit measured), not with the plan.
    begun = time.perf_counter()
    walked, stamps = app.state.warm_edited()
    print(
        f"walked the plan's history: {len(stamps)} paths at {walked[:7]} "
        f"in {time.perf_counter() - begun:.2f}s",
        file=sys.stderr,
        flush=True,
    )
```

In `_demo` (`cli.py:245-276`), directly after the `app = create_app(...)` call closes at `:260`, insert:

```python
        # Same rule as `_serve`: startup owns the first walk. On a demo corpus
        # it is microseconds, so it earns no log line of its own.
        app.state.warm_edited()
```

- [ ] **Step 18: The injection census gains the landing, the table's new address, and the two create forms — and its route list becomes importable.**

In `tests/test_injection.py:84-85`, add the table's file:

```python
STATIC_PAGES = ("index.html", "table.html", "detail.html", "people.html", "cycles.html",
                "issues.html", "notes.html", "graph.html", "timeline.html")
```

Directly above `def served(` (`tests/test_injection.py:272`), add:

```python
# The two page routes the census cannot open: an individual issue or note is
# addressed by an id this corpus deliberately malforms (see `corpus`), so the
# route refuses the path and the page under test never renders. Held both ways
# by the completeness test below — a route that leaves the app makes this list
# stale and FAILS, so an exemption cannot outlive its excuse. The flip commit
# turns both routes into redirects and retires this set.
CENSUS_BLIND = {"/issue/{issue_id}", "/note/{note_id}"}


def census_routes(entity_ids: tuple[str, ...]) -> dict[str, str]:
    """Every page the census opens, module-level so the completeness test can
    hold it against `app.routes`. Named rather than keyed by URL: the entity
    pages have the payload in their path, so the hostile plan and the benign
    one address different URLs for the same page."""
    return {
        "records": "/", "table": "/table", "graph": "/graph", "timeline": "/timeline",
        "people": "/people", "cycles": "/cycles", "cycle 41": "/cycle/41",
        # The deck was left out of a census that says it covers every page the
        # server draws, and it is the page a field is most likely to leave the
        # building on: a deck is printed and handed to somebody who was not in
        # the room. Same cycle as the one above, so both read the same plan.
        "deck 41": "/deck/41",
        # The two inboxes and their create forms. Individual issue and note
        # pages are the two CENSUS_BLIND routes above.
        "issues": "/issues", "notes": "/notes",
        "issue new": "/issue/new", "note new": "/note/new",
        "new task": "/new?kind=task", "new pitch": "/new?kind=pitch",
        # `/detail` is the whole plan and read-only; an entity's own page is the
        # editable one, and the only one that carries the combobox.
        "every detail": "/detail",
        **{
            f"{ONE_ENTITY} {n}": f"/detail/{quote(entity_id, safe='')}"
            for n, entity_id in enumerate(entity_ids)
        },
    }
```

and inside `served()` delete the inline `routes = { ... }` literal (`:291-311`), replacing it with:

```python
    routes = census_routes(entity_ids)
```

- [ ] **Step 19: Spec test 14 — census completeness, failing CLOSED. Append after `test_no_served_page_lets_a_field_become_markup` in `tests/test_injection.py`.**

```python
def test_every_html_get_route_is_in_the_census(tmp_path: Path):
    """Risk 2 in the design, closed permanently: the census was a hand-written
    list, and a hand-written list fails OPEN — move the table to /table and the
    census stays green while covering the wrong URL. Held against `app.routes`
    it fails CLOSED: an HTML GET route the census does not open is a failure on
    the commit that adds the route, not a hole found later.

    Filtered on `response_class`: JSON routes, redirects and the asset stream
    are not pages, and a census of them would be a different test.
    """
    from fastapi.responses import HTMLResponse
    from fastapi.routing import APIRoute

    path = tmp_path / "census.git"
    pygit2.init_repository(str(path), bare=True, initial_head="main")
    commit_directly(path, corpus(BENIGN), "seed a plan for the route census")
    app = create_app(path, auth="dev", secret="a-signing-secret-for-tests")
    with TestClient(app):
        def is_page(route) -> bool:
            drawn = getattr(route, "response_class", None)
            # FastAPI wraps an undeclared response class in a DefaultPlaceholder.
            drawn = getattr(drawn, "value", drawn)
            return isinstance(drawn, type) and issubclass(drawn, HTMLResponse)

        pages = {
            route
            for route in app.routes
            if isinstance(route, APIRoute) and "GET" in route.methods and is_page(route)
        }
        assert pages, "no HTML GET routes at all, so nothing was checked"

        covered: set[str] = set()
        for url in census_routes(ids(BENIGN)).values():
            where = url.partition("?")[0]
            for route in pages:
                if route.path_regex.match(where):
                    covered.add(route.path)

        templates = {route.path for route in pages}
        missing = templates - covered - CENSUS_BLIND
        assert not missing, (
            "HTML GET routes the injection census never opens — add each to "
            f"census_routes() or, with a reason, to CENSUS_BLIND: {sorted(missing)}"
        )
        stale = CENSUS_BLIND - templates
        assert not stale, f"CENSUS_BLIND names routes that no longer exist: {sorted(stale)}"
```

- [ ] **Step 20: Create `tests/test_records.py` — the landing, the four sentences, `_ago`, the search twin, and the export rule.**

```python
"""The landing list: every record, sorted by when a commit last touched it.

The time comes from a history walk (`Store.last_edited`), never from a field or
an mtime; the search box is the shared control bar over the shared `matches()`;
and there are FOUR ways for the list to be empty, each with its own sentence,
because a filter matching nothing, a plan with nothing in it, a query that
cannot be read and a payload that never arrived are four different things to do
next. The export renders the same page, minus the time column when the
directory it reads has no history to ask.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime
from pathlib import Path

import pygit2
import pytest
from fastapi.testclient import TestClient
from pages import lit, nav_of
from test_injection import run_js
from test_store import commit_directly

from openproj.index import apply_filters, build_index
from openproj.model import edited_by_id, load_repo
from openproj.render import _ago, render_records, render_static
from openproj.web import create_app

PLAN = {
    "config/defaults.yaml": "schema_version: 1\nnominal_availability: 1.0\n",
    "projects/p.md": (
        "---\nid: proj-a10000\nkind: project\ntitle: Tracer engine\n"
        "status: in_progress\nowner: ann\n---\n\nThe project.\n"
    ),
    # A non-ASCII title and tag, because blob drift between the shared search
    # helper and its JS twin is exactly the kind of defect ASCII cannot see.
    "pitches/one.md": (
        "---\nid: pitch-b20000\nkind: pitch\ntitle: \"Traçage à l'équateur\"\n"
        "status: ready\nowner: ann\ntags: [gpu, 平流]\nparent: proj-a10000\n"
        "person_weeks: 2\n---\n\nA pitch.\n"
    ),
    "tasks/two.md": (
        "---\nid: task-c00001\nkind: task\ntitle: Downgrade numpy\nstatus: ready\n"
        "owner: bo\nprs: ['C2SM/icon4py#1223']\nparent: pitch-b20000\n"
        "person_weeks: 1\n---\n\nA task.\n"
    ),
    # An issue and a note ride in the corpus from the first commit, in today's
    # file format (no `kind:` key — the flip's parser resolves the kind from the
    # id prefix, so the format never changes). At THIS commit neither is a
    # record: needles aimed at them must match NOTHING on both sides, which is
    # itself parity. The flip commit widens the ladder, `records` picks both up
    # on both sides at once, and the same needles start matching — no edit here.
    "issues/issue-ab12cd.md": (
        "---\nid: issue-ab12cd\ntitle: \"Renormalisation à l'équateur\"\n"
        "status: ready\nreported_by: ann\ntags: [数值]\n---\n\nSeen near the pole.\n"
    ),
    "notes/note-ef34ab.md": (
        "---\nid: note-ef34ab\ntitle: \"Idée: traceur passif\"\nstatus: thinking\n"
        "written_by: bo\ntags: [gpu]\n---\n\nHalf a thought.\n"
    ),
}


def plan_repo(tmp_path: Path) -> Path:
    path = tmp_path / "plan.git"
    pygit2.init_repository(str(path), bare=True, initial_head="main")
    return path


# --------------------------------------------------------------------------- #
# The list
# --------------------------------------------------------------------------- #


def test_the_landing_lists_every_record_newest_edit_first(tmp_path: Path):
    path = plan_repo(tmp_path)
    commit_directly(path, PLAN, "seed", when=1_000_000)
    edited = dict(PLAN)
    edited["tasks/two.md"] = PLAN["tasks/two.md"].replace(
        "Downgrade numpy", "Downgrade numpy again"
    )
    commit_directly(path, edited, "edit the task", when=1_000_500)

    with TestClient(create_app(path, auth="dev")) as client:
        page = client.get("/").text

    entities, config, _ = load_repo_from_git(path)
    index = build_index(entities, config, date(2026, 8, 17))
    rows = re.findall(r'<li data-id="([\w-]+)"', page)
    # Derived from `index.records`, not written out: at this commit that is the
    # three plan records — the corpus's issue and note are not records until the
    # flip widens the ladder — and on the flip commit the page and the
    # expectation widen together, with no edit here.
    assert set(rows) == set(index.records)
    assert "task-c00001" in rows, "an empty records map would make this pass vacuously"
    assert rows[0] == "task-c00001", "the record edited last is the record listed first"
    assert 'href="/detail/task-c00001"' in page
    assert '<span class="chip kind-task">' in page
    assert '<span class="when">' in page


def test_the_nav_says_records_at_the_root_and_table_at_table(tmp_path: Path):
    path = plan_repo(tmp_path)
    commit_directly(path, PLAN, "seed", when=1_000_000)
    with TestClient(create_app(path, auth="dev")) as client:
        landing = client.get("/").text
        table = client.get("/table").text
    assert lit(landing) == ["Records"]
    assert lit(table) == ["Table"]
    assert [label for label, _, _ in nav_of(landing)][:2] == ["Records", "Table"]


def test_every_row_carries_an_empty_predicates_array(tmp_path: Path):
    """`matches()` dereferences `row.predicates` without a guard, so an omitted
    array plus a `?predicate=` in the URL is a TypeError and a blank page."""
    path = plan_repo(tmp_path)
    commit_directly(path, PLAN, "seed", when=1_000_000)
    with TestClient(create_app(path, auth="dev")) as client:
        page = client.get("/").text
    block = re.search(
        r'<script id="landing" type="application/json">(.*?)</script>', page, re.S
    ).group(1)
    data = json.loads(block)
    assert data["rows"], "an empty payload proves nothing"
    assert all(row["predicates"] == [] for row in data["rows"].values())


def test_a_predicate_in_the_url_is_a_sentence_and_not_a_blank_page(tmp_path: Path):
    path = plan_repo(tmp_path)
    commit_directly(path, PLAN, "seed", when=1_000_000)
    with TestClient(create_app(path, auth="dev")) as client:
        page = client.get("/").text
    answer = run_js(
        page,
        "(() => { params.set('predicate', 'has_blocker'); recordsApply();"
        " return [document.getElementById('records-empty').hidden,"
        "  document.querySelector('#records-empty .headline').textContent,"
        "  [...document.querySelectorAll('#records li[data-id]')]"
        "    .filter(li => !li.hidden).length]; })()",
        page=True,
    )
    assert not [e for e in answer["errors"] if e.startswith("expression:")], answer["errors"]
    hidden, headline, shown = answer["value"]
    assert shown == 0
    assert hidden is False
    assert headline == "No record matches this search."


# --------------------------------------------------------------------------- #
# The four empty states
# --------------------------------------------------------------------------- #


def test_a_plan_with_no_records_says_so_from_the_server(tmp_path: Path):
    root = tmp_path / "empty"
    (root / "config").mkdir(parents=True)
    (root / "config" / "defaults.yaml").write_text(
        "schema_version: 1\nnominal_availability: 1.0\n", encoding="utf-8"
    )
    entities, config, unreadable = load_repo(root)
    page = render_records(build_index(entities, config, date(2026, 8, 17)), edited={}, now=0)
    assert "This plan has no records yet." in page
    assert "Nothing has been written down." in page


def test_an_unreadable_query_goes_to_the_error_region_not_to_a_row(tmp_path: Path):
    path = plan_repo(tmp_path)
    commit_directly(path, PLAN, "seed", when=1_000_000)
    with TestClient(create_app(path, auth="dev")) as client:
        page = client.get("/").text
    answer = run_js(
        page,
        "(() => { params.set('q', 'kind:'); sayQueryError(); recordsApply();"
        " const err = document.getElementById('query-error');"
        " return [err.hidden, err.textContent,"
        "  document.querySelector('#records-empty .headline').textContent]; })()",
        page=True,
    )
    assert not [e for e in answer["errors"] if e.startswith("expression:")], answer["errors"]
    hidden, said, headline = answer["value"]
    assert hidden is False
    assert said, "the parse error must reach #query-error"
    assert headline == "That search cannot be read."


def test_a_search_that_matches_nothing_says_so(tmp_path: Path):
    path = plan_repo(tmp_path)
    commit_directly(path, PLAN, "seed", when=1_000_000)
    with TestClient(create_app(path, auth="dev")) as client:
        page = client.get("/").text
    answer = run_js(
        page,
        "(() => { params.set('q', 'zzyzzx'); recordsApply();"
        " return document.querySelector('#records-empty .headline').textContent; })()",
        page=True,
    )
    assert answer["value"] == "No record matches this search."


def test_a_lost_payload_degrades_to_an_unfiltered_list_and_says_so(tmp_path: Path):
    """The rows are server-rendered, so a payload that did not survive the trip
    must NOT empty the page — the table's fourth emptiness inverted. Driven, not
    grepped: the payload text is corrupted in the page string, so the real
    JSON.parse throws, the real catch runs, and the real recordsApply() decides
    what a reader sees — a regression that keeps the sentence but hides the rows
    fails here, where a source-substring assertion would stay green."""
    path = plan_repo(tmp_path)
    commit_directly(path, PLAN, "seed", when=1_000_000)
    with TestClient(create_app(path, auth="dev")) as client:
        page = client.get("/").text
    total = len(re.findall(r'<li data-id="', page))
    broken = page.replace(
        '<script id="landing" type="application/json">',
        '<script id="landing" type="application/json">not json ', 1,
    )
    answer = run_js(
        broken,
        "(() => [document.querySelector('#records-empty .headline').textContent,"
        " document.querySelector('#records-empty .hint').textContent,"
        " [...document.querySelectorAll('#records li[data-id]')]"
        "   .filter(li => !li.hidden).length])()",
        page=True,
    )
    assert not [e for e in answer["errors"] if e.startswith("expression:")], answer["errors"]
    headline, hint, shown = answer["value"]
    assert headline == "This search cannot run."
    assert hint == "The page arrived without its search data, so the list is shown unfiltered."
    assert total and shown == total, (
        "a lost payload must leave every server-rendered row on the page"
    )


# --------------------------------------------------------------------------- #
# The time string
# --------------------------------------------------------------------------- #


def test_the_time_is_relative_when_recent_and_absolute_past_two_weeks():
    """The shape read off docs/hackmd-observed.md: `17 hours ago` … `10 days
    ago`, then a date. Past the threshold the relative form is abandoned, not
    extended, and a stamp from a clock ahead of ours is a date, never a
    countdown."""
    now = 1_755_600_000
    assert _ago(now - 30, now) == "just now"
    assert _ago(now - 5 * 60, now) == "5 minutes ago"
    assert _ago(now - 3600, now) == "an hour ago"
    assert _ago(now - 17 * 3600, now) == "17 hours ago"
    assert _ago(now - 86400, now) == "a day ago"
    assert _ago(now - 10 * 86400, now) == "10 days ago"
    assert _ago(now - 13 * 86400, now) == "13 days ago"
    fortnight = now - 14 * 86400
    absolute = datetime.fromtimestamp(fortnight, tz=UTC).date().isoformat()
    assert _ago(fortnight, now) == absolute
    ahead = datetime.fromtimestamp(now + 7200, tz=UTC).date().isoformat()
    assert _ago(now + 7200, now) == ahead


# --------------------------------------------------------------------------- #
# Search parity with the JS twin (spec test 15)
# --------------------------------------------------------------------------- #


def test_the_landing_box_and_the_server_find_the_same_records(tmp_path: Path):
    """The landing's `matches()` runs over its own payload, which is a second
    place the search blob travels — so both halves are asked the same
    questions, non-ASCII included. At this commit `records` equals the plan,
    so the issue and note needles below must match NOTHING on either side —
    which is still parity, asked and answered; the flip commit widens
    `records` on both sides at once and the same needles start matching,
    with no edit to this test."""
    path = plan_repo(tmp_path)
    commit_directly(path, PLAN, "seed", when=1_000_000)
    with TestClient(create_app(path, auth="dev")) as client:
        page = client.get("/").text

    entities, config, _ = load_repo_from_git(path)
    index = build_index(entities, config, date(2026, 8, 17))

    needles = ["traçage", "équateur", "Équateur", "平流", "gpu", "ann",
               "task-c00001", "1223", "downgrade", "tag:gpu", "kind:pitch",
               # The issue's and the note's words, non-ASCII where it counts.
               "renormalisation", "数值", "idée", "issue-ab12cd", "note-ef34ab"]
    disagreed = {}
    for needle in needles:
        # Membership is the claim; the two sides answer in different orders
        # (walk order here, sorted in the JS expression), so both are sorted.
        # `over=index.records`, because the JS twin filters RECORDS.rows —
        # the record population, not the plan.
        here = sorted(apply_filters(index, {}, needle, over=index.records))
        answer = run_js(
            page,
            "(() => { params.set('q', " + json.dumps(needle) + ");"
            " return Object.keys(RECORDS.rows)"
            "   .filter(id => matches(RECORDS.rows[id])).sort(); })()",
            page=True,
        )
        assert not [e for e in answer["errors"] if e.startswith("expression:")], (
            needle, answer["errors"],
        )
        if here != answer["value"]:
            disagreed[needle] = (here, answer["value"])
    assert not disagreed, f"the landing box and the server disagree: {disagreed}"


def load_repo_from_git(path: Path):
    """The corpus as the server reads it, via a worktree-free read of head."""
    from openproj.web import _config_at, _entities_at
    from openproj.store import Store

    store = Store(path)
    try:
        head = store.head()
        config, bad_config = _config_at(store, head)
        entities, bad_entities = _entities_at(store, head)
    finally:
        store.close()
    return entities, config, [*bad_config, *bad_entities]


# --------------------------------------------------------------------------- #
# The export
# --------------------------------------------------------------------------- #


def test_an_export_without_git_omits_the_time_column(tmp_path: Path):
    """Omitted, not blank: blank looks broken. And never file mtimes, which
    say "just now" about the whole plan after every fresh clone."""
    from openproj.store import last_edited_in

    root = tmp_path / "plain"
    for name, text in PLAN.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding="utf-8")
    assert last_edited_in(root) is None

    entities, config, unreadable = load_repo(root)
    out = tmp_path / "site"
    written = render_static(build_index(entities, config, date(2026, 8, 17)), out)
    assert written[:2] == ("index.html", "table.html")
    landing = (out / "index.html").read_text(encoding="utf-8")
    assert '<span class="when">' not in landing
    assert '<li data-id="task-c00001">' in landing


def test_an_export_of_a_repository_carries_the_times(tmp_path: Path):
    from openproj.store import last_edited_in

    root = tmp_path / "checkout"
    pygit2.init_repository(str(root), bare=False, initial_head="main")
    for name, text in PLAN.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding="utf-8")
    commit_directly(root, PLAN, "seed", when=1_000_000)
    edited = dict(PLAN)
    edited["tasks/two.md"] = PLAN["tasks/two.md"].replace(
        "Downgrade numpy", "Downgrade numpy again"
    )
    (root / "tasks" / "two.md").write_text(edited["tasks/two.md"], encoding="utf-8")
    commit_directly(root, edited, "edit the task", when=2_000_000)

    stamps = last_edited_in(root)
    assert stamps is not None and stamps["tasks/two.md"] == 2_000_000

    entities, config, unreadable = load_repo(root)
    out = tmp_path / "site"
    render_static(
        build_index(entities, config, date(2026, 8, 17)), out,
        edited=edited_by_id(stamps), now=2_000_000 + 3600,
    )
    landing = (out / "index.html").read_text(encoding="utf-8")
    assert '<span class="when">an hour ago</span>' in landing
    rows = re.findall(r'<li data-id="([\w-]+)"', landing)
    assert rows[0] == "task-c00001", "sorted by last edit in the export too"
```

Note the local `load_repo_from_git` helper exists because `load_repo` reads a worktree and the parity fixture is a bare repository; it reuses `web.py`'s own `_entities_at`/`_config_at` rather than growing a third reader.

- [ ] **Step 21: Repoint `tests/test_web.py`.**

In `test_every_route_says_which_nav_item_it_is` (`tests/test_web.py:344-378`) change the route table's first entry and add the table's:

```python
    for route, item in (
        ("/", "Records"),
        ("/table", "Table"),
        ("/graph", "Graph"),
        ("/timeline", "Timeline"),
        ("/cycles", "Cycles"),
        ("/cycle/37", "Cycles"),
        # A deck is one cycle's handout and deliberately not a seventh tab, so it
        # lights the item that got you there — the same argument `/cycle/37` makes.
        ("/deck/37", "Cycles"),
        ("/people", "People"),
    ):
```

Then the individual `get("/")` sites, each verified above:

| line | change |
|---|---|
| `test_web.py:321` (`test_the_table_renders_the_repository…`) | `client.get("/")` → `client.get("/table")` |
| `test_web.py:1858` (`table-scroll`) | → `client.get("/table")` |
| `test_web.py:3217`, `:3220` (`DONE` in the page) | → `client.get("/table")` |
| `test_web.py:3519`, `:3522` (cache freshness, "the table is showing…") | → `client.get("/table")` |
| `test_web.py:3591`, `:3594` (`zzarple`/`qqundle`) | → `client.get("/table")` |
| `test_web.py:1125`, `:1196`, `:3501`, `:3506`, `:3574`, `:3578`, `:3611`, `:3746` | **keep `"/"`** — they assert reader access, index-cache behaviour, and the unreadable banner, all of which the landing now carries; leaving them on `/` makes them cover the new page |

- [ ] **Step 22: Repoint `tests/test_render.py`.**

1. `PAGES` (`:29-30`):

```python
PAGES = ("index.html", "table.html", "detail.html", "people.html", "cycles.html",
         "issues.html", "notes.html", "graph.html", "timeline.html")
```

2. `PAGE_NAMES` (`:2787-2793`):

```python
PAGE_NAMES = {
    "index.html": "Records",
    "table.html": "Table",
    "graph.html": "Graph",
    "timeline.html": "Timeline",
    "cycles.html": "Cycles",
    "people.html": "People",
}
```

3. Every `read(rendered, "index.html")` that asserts **table** content moves to `"table.html"`. Run `grep -n 'read(rendered, "index.html")' tests/test_render.py` — at the time of writing that is lines 201, 222, 234, 251, 310, 739, 813, 1470, 1532, 1712, 1752, 1831, 1849, 1850 — and replace the filename in each with `"table.html"` (all of them are table assertions: blocker count, columns, chips, styles, tokens; the token/style reads at 1831-1850 work off any page and simply follow along). Do it in one command and eyeball the diff:

```bash
python3 - <<'EOF'
from pathlib import Path
p = Path("tests/test_render.py")
p.write_text(p.read_text().replace('read(rendered, "index.html")',
                                   'read(rendered, "table.html")'))
EOF
```

4. The people-page role links (`:1102`, `:1105`): change `href="index.html?` to `href="table.html?` in both assertions — the links carry table filters and now follow `Links.table`.

- [ ] **Step 23: Repoint the rest, one line each.**

| file:line | change | why |
|---|---|---|
| `tests/test_table.py:135` (the `page` fixture) | `client.get("/")` → `client.get("/table")` | the ~125 surviving table tests all read this fixture — this is the one-line repoint the spec promises |
| `tests/test_table.py:4436` | → `client.get("/table")` | same page, fetched inline |
| `tests/test_table.py:539`, `:2979` | `(tmp_path / "index.html")` → `(tmp_path / "table.html")` | export assertions about the table's editing chrome |
| `tests/test_writes.py:438` (`broken_id_table` fixture) | → `client.get("/table")` | the fixture is the table's rows |
| `tests/test_editor.py:830` | → `client.get("/table")` | `#row-conflict` is table markup |
| `tests/test_gitdoor.py:210` | → `client.get("/table")` | the docstring's claim is about the table |
| `tests/test_gitdoor.py:607`, `:631` | → `client.get("/table")` | "the table's unreadable banner" — keep the words true |
| `tests/test_gitdoor.py:266`, `:330` | **keep `"/"`** | the banner must be on the landing too; these now pin that |
| `tests/test_cli.py:300` | `seen["table"] = client.get("/")` → `seen["table"] = client.get("/table")`, and add the line `seen["records"] = client.get("/")` directly above it | the demo smoke should touch both pages |
| `tests/test_cli.py:176-177` | add `"table.html"` to the file list | the export writes nine files now |
| `tests/test_headers.py:84-85`, `tests/test_editor.py:485`, `tests/test_gitdoor.py:434-441`, `tests/test_notes.py:131` | **keep** | headers, no-EventSource, banner and nav are shell properties the landing must also hold |

- [ ] **Step 24: ruff, locally — the only local command.**

```bash
uv sync
uv run ruff check .
```

Fix anything it names (likely candidates: import order in `cli.py`/`web.py`/`test_records.py`, a line over 100 columns in `_RECORDS`). Do **not** run pytest — not one file. The red/green gate is CI.

- [ ] **Step 25: Commit and push; CI is the verdict.**

```bash
git add -A
git commit -F - <<'MSG'
The plan opens on what changed last

The landing page is a list of every plan record sorted by when a commit
last touched it, HackMD-fashion: a kind badge, a title into the record's
page, one relative time, and the usual search box over the shared filter
script. The table keeps everything it had and moves to /table; the nav
word is Records, which names the population where Table names a
presentation.

There was no such timestamp to draw — no field, no working tree, no
revwalk anywhere in src/ — so Store.last_edited walks history from head
in git-log semantics: a path is stamped by a commit whose blob differs
from ALL parents, which is what keeps a side-branch edit on the side
commit's time instead of the merge's. A cached map advances over
known..head, first touch wins; a cached commit that is not an ancestor
of head — routine after a lost push race rewinds the ref — is discarded
and rebuilt, because retract-by-rebuild has no retraction logic to get
wrong. The map is cached per commit alone, swapped atomically under the
GIL, and the first walk runs in _serve before uvicorn binds, logged, so
it never rides a request.

The injection census now fails closed: every GET route that draws HTML
must be opened by the census, held against app.routes — without that,
moving the table would have left the census green and empty-handed.

The landing has four empty states, each its own sentence: a payload that
did not load (the list stays, unfiltered, and says so), a plan with no
records, a query that cannot be read (the parse error goes beside the
box), and a search that matched nothing. openproj render pointed at a
directory with no git renders the list without the time column —
omitted, not blank — and never reads file mtimes, which lie after a
fresh clone.

🤖 Written by an agent on behalf of @jcanton
MSG
git push -u origin one-record-one-page
```

Then read CI on the pull request (`uv run pytest -q` in `.github/workflows/ci.yml` is the gate). Expected first-run risks, in order of likelihood: a `pages.lit`/nav assertion somewhere this plan's grep missed (fix by repointing, not by widening the nav test), the `test_no_two_scripts_on_a_page_declare_the_same_name` sweep objecting to a landing script name (rename the landing's declaration, never the shared one), and a drive.js shim gap in the four-sentence tests (fall back to asserting the shipped source the way `test_table.py:2250-2255` does). Fix on the branch and push again; a red CI is a normal thing to fix and costs thirteen minutes of nobody's laptop.

---

### Task 8: An issue is a rung, and a note is a rung

**THE ATOMIC COMMIT.** Adding `issues/` and `notes/` to the ladder makes `_ENTITY_DIRS` (derived at `model.py:1036`) include those directories the instant the two `Rung`s land, so `load_repo` and `_entities_at` start reading every issue and note as an entity in that same moment. Any split lands in a state where *both* the old readers (`Config.issues`, `_issues_at`) and the new one walk the same files: every issue double-parsed, double-listed, double-validated. Everything in this task is therefore one commit. Tasks 1–7 exist to make this commit as small as it is; it is still the largest in the branch. Work through the steps in order, run **only** `uv sync && uv run ruff check .` locally, and let CI be the red/green gate — never pytest on the laptop.

**Files:**
- Modify: `src/openproj/model.py:25-28` (dir constants), `:155-345` (Issue/Note classes move + rewrite), `:979-1001` (KINDS), `:1132-1160` (parse fns), `:623-672` (Config), `:1300-1391` (load_repo), `:1685-1712` (id-pattern comment block), `:1992-2006` (`_people_problems`), `:2192-2283` (`_problems_for`), `:2283-2372` (issue_problems/note_problems)
- Modify: `src/openproj/index.py:21-41` (imports), `:145-174` (Index fields + comment rewrite), `:484-509` (build_index kwargs)
- Modify: `src/openproj/web.py:49-103` (imports), `:261-331` (inbox readers), `:366-395` (`_config_at`), `:580-620` (bespoke gates), `:581` (`_LISTS`), `:752-753` (field lists), `:1336-1555` (issue/note routes → redirects), `:1556-1700` (promote), `:1777-1801` (detail route: records lookup + `signed_in`), `:1829-1851` (`/api/body` hover card), `:2002` (loop guard), `:2078` (delete cascade), `:2345-2427` (POST `/api/entity`)
- Modify: `src/openproj/render.py:1571-1603` (Links), `:1636-1640` (ROUTES), `:13106-13355` (`_DETAIL`), `:15046-…` (`_DETAIL_STYLE`), `:16484-16514` (`_detail_rows` → records), `:16739-16780` (`_suggestions` → records), `:19599-19612` (`_by_status` + new `_TOC_LADDER`), `:19615-19700` (`render_detail`), delete `:18953-19164`, `:19207-19384`, `:19764-19972`, `:19974-20033`, `:20035-20279`, `:20329-20388`, `:20390-20630`, trim `:20633-20740` (`_RECORD_STYLE`), `:20741-20745` (`_NAV`), `:20983-21012` (`render_static`)
- Test: `tests/test_issues.py` (full rewrite), `tests/test_notes.py` (rewrite), `tests/test_injection.py:84-167,252-330` and its `CENSUS_BLIND` — plus surgical edits in `tests/test_cascade.py:50-73,925-1080`, `tests/test_facets.py:250-276`, `tests/test_coedit.py:2187`, `tests/test_web.py:695-715,3785-3812`, `tests/test_editor.py:2263,5349`, `tests/test_render.py:29-30,1384-1397,2827,2863`, `tests/test_records.py` (corpus + parity needles), and the seed-check pin from Task 1 and the sweep docstring from Task 2

All line numbers are the pre-branch tree, verified by reading; Tasks 1–7 will have shifted them, so treat them as anchors and locate by the quoted code.

**Interfaces:**
- Consumes (from Tasks 1–7, per the contract):
  - `Rung` fields `planned: bool` and `statuses: tuple[str, ...]` after `carded` (Task 1); `Entity.state(self, entities: "dict[str, Entity]") -> str` returning `self.status` (Task 1); `unread_fields(kind)` gating `status` on `rung.statuses` and the structural terminal-status exemption `rung.statuses and entity.status == rung.statuses[-1]` in `validate_all` (Task 1); `_vocabulary_problems` reading the ladder off the rung (Task 1).
  - `Index.entities: dict[str, Entity]` plan-only, `Index.records: dict[str, Entity]` total, the `model_validator` refusing unplanned kinds in `entities`, `apply_filters(..., over=...)`, and the KINDS-derived exclusion sweep test (Task 2). Task 2 edits **only index.py** — every `index.entities` read in web.py and render.py that must become total is edited HERE (Steps 10 and 12).
  - `_control_html`/`_CONTROL` taking a per-kind ladder, `live` flag, `disabled` and hint slot; `state()` in the fact rows; the hints `"from the work it was pitched into"` / `"from what it became"`; `EDITABLE` entries `reported_by`, `written_by` (text) and `pitched_into`, `became` (id lists via `_links`) — inert until now; and the `signed_in` slots `_editable_for(entity, prefix, signed_in)` / `_fact_rows(index, entity, links, signed_in)`, whose web wiring Task 3 deferred to this task (Task 3).
  - `web.ID_PATTERN` derived from `KINDS` and the generic status gate refusing any `fields["status"]` outside `RUNG[kind].statuses` on both `POST` and `PATCH /api/entity` (Task 4).
  - `/new?kind=…` creating mode inside `_DETAIL` (Task 6); `render_records(index, links=STATIC, base_commit=None, edited=None, now=0)`, `Links.records`, nav word "Records" at `/`, table at `/table`, `CENSUS_BLIND` + `census_routes` in `tests/test_injection.py`, and the census-completeness test over `app.routes` (Task 7).
- Produces (Task 9 relies on):
  - `RUNG["issue"]` and `RUNG["note"]` live: `Issue(Entity)` and `Note(Entity)` with their own fields; `load_repo`/`_entities_at` read all six directories; `Index.records` carries issues and notes; `web.INBOXES: dict[str, Inbox]` (the per-rung stamping table); redirects `/issues → /`, `/notes → /`, `/issue/new → /new?kind=issue`, `/note/new → /new?kind=note`, `/issue/{id}` and `/note/{id} → /detail/{id}`; `render._PROMOTE_HINTS`; the `#promote` CSS in `_DETAIL_STYLE`. `_RECORD_STYLE` is left in place, now unreferenced — Task 9 deletes it.
  - `render_detail(..., signed_in: str = "")` after `creating`, threaded from `viewer(request)` on `/detail/{id}` and `/new` — Task 3's placeholder slot goes live here.
  - `render._TOC_LADDER` and the rewritten `_by_status` land HERE, in the commit whose rows first carry `thinking`/`dropped` (Task 9 deletes its own Step 7, keeps only the back-link half of its Step 8, and reduces its Step 9 to the reconciliation check — the heading edit and the three `tests/test_render.py` repoints happen in this task).
  - `tests/test_injection.py`'s `CENSUS_BLIND` is emptied here (the completeness test keeps the name); `tests/test_render.py`'s `PAGES` is trimmed here.

---

- [ ] **Step 1: model.py — Issue and Note become Entity subclasses, moved below `Entity`, docstrings rewritten**

Delete the module-level constants at `model.py:27-28`:

```python
_ISSUE_DIR = "issues"
_NOTE_DIR = "notes"
```

Delete the whole block from `ISSUE_STATUS = (...)` at line 155 through the end of `class Note` (the line before `class Unreadable(BaseModel):`, currently 345). The classes cannot stay where they are: they now subclass `Entity`, which is defined at line 827, below them.

Insert the following immediately after `class Product(Entity):` (its body ends just before the `# THE LADDER.` comment, currently line 952). This is the rewritten text the task demands — the docstrings carry the *new* argument for the *old* boundary, and say what changed and why:

```python
ISSUE_STATUS = ("ready", "in_progress", "done", "shelved")


class Issue(Entity):
    """Something somebody noticed, before anybody has decided to do it.

    Stored as `issues/<id>.md`, and — since the sixth rung landed — an Entity,
    on a rung with `planned=False`. It used to be a separate type, and the
    argument for that was real: a separate type kept an issue off the table, the
    graph, the people page and the timeline *by construction*, rather than by an
    exclusion in each of them that somebody later forgets. What replaced the
    type is a stronger construction, not a repeal of it. `build_index` filters
    `Index.entities` down to planned rungs in one comprehension; a
    model_validator on `Index` refuses any index holding an unplanned kind
    there; and the KINDS-derived sweep in the tests seeds one record of every
    unplanned rung and asserts its absence from every plan view. The type
    boundary lived in sixty read sites' annotations with no compiler behind
    them and failed OPEN — forget one filter and an issue appears on the
    timeline. A forgotten consumer of the filtered map now fails CLOSED: it
    sees fewer records, never more.

    What the type cost while it lasted was a second copy of every page, and #67
    measured the drift that buys: the note page got the status hill and the
    issue page did not, in one commit, by the same author.

    Its own fields survive the move unchanged. There is no `shaping` in
    `ISSUE_STATUS`: shaping happens in the record an issue is promoted into and
    never in the issue itself, so a status for it here would be a second place
    to say what `pitched_into` already says — and now that the vocabulary is
    read off the rung, `shaping` is *refused* on an issue rather than silently
    legal, which closes a hole the old bespoke validator left open.
    """

    status: str = "ready"
    reported_by: str | None = None
    opened_on: date | None = None
    # The pitches and tasks this was pitched into. One direction only: an entity
    # does not list its issues, because two directions for one edge disagree the
    # first time somebody edits the wrong end.
    pitched_into: list[str] = []

    def state(self, entities: dict[str, Entity]) -> str:
        """What this issue actually is, given what it was pitched into.

        Derived rather than copied. An issue that has been pitched has been
        picked up, and one whose work is finished is finished — writing that
        into the file as well would be a second copy of a fact the link already
        carries, and the two disagree the moment somebody closes the pitch.

        `shelved` is never overridden. "We are not doing this" is a decision,
        and a link somebody adds afterwards does not reverse it.
        """
        if self.status == "shelved":
            return "shelved"
        linked = [entities[i] for i in self.pitched_into if i in entities]
        if not linked:
            return self.status
        if all(entity.status in ("done", "shelved") for entity in linked):
            return "done"
        return "in_progress"


# Two, and the count is the design.
#
# An issue has four because an issue is a piece of work waiting to be scheduled:
# somebody picks it up, somebody finishes it. A note is not work and never
# becomes work — it becomes a *record* that is work, and then the note is over.
# So the only thing a person decides about a note is whether they are still
# thinking about it, and the only two answers are the two below.
#
# What is deliberately absent: no `in_progress` (there is no such thing as
# working on a note — the moment there is work there is a record, which is
# `promoted`, DERIVED from `became` rather than stored); no `ready` ("ready to
# be shaped" is a promise the Promote button keeps in one press); no `done` (a
# note is not finished, it is answered — by a record somewhere else, or by
# `dropped`).
NOTE_STATUS = ("thinking", "dropped")
# Every state a note can be IN, in the order it moves through them: the two
# above that a person sets, plus the one only a promotion can give it.
# `NOTE_STATUS` is what may be written to a file; this is what a page may draw
# and sort by.
NOTE_STATES = ("thinking", "promoted", "dropped")


class Note(Entity):
    """An idea before anybody knows what it is.

    Stored as `notes/<id>.md`. Like the issue above it is an Entity on an
    unplanned rung, and the docstring there carries the argument for the new
    boundary; what this one keeps is the distinction between the two inboxes,
    which the model change did not touch:

        an issue is "we found something existing that is broken";
        a note is "we are thinking of creating something that does not exist
        and our ideas are confused".

    A note is therefore not a pitch in `shaping`, which is the thing it most
    looks like from a distance. A pitch presupposes that you know what you are
    shaping: it has a problem, a solution and an appetite, and it sits on the
    betting table as a bet somebody could take. A note precedes all three, and
    `planned=False` on its rung is what keeps the plan from looking like it
    holds bets nobody has made — enforced in `build_index`, guarded by the
    Index validator, swept by the KINDS-derived test.

    The fields it declares are the ones a confused idea can honestly carry:
    `written_by` is who to ask, not who owns it (an owner is a commitment, and
    the whole claim of this record is that nobody has committed to anything);
    `became` is the records it graduated into, one direction only, exactly as
    `Issue.pitched_into` is. Every work field it inherits from Entity —
    owner, cycle, priority, the lot — is on `unread_fields("note")`, so the
    editors never offer one and the validator reports one that is written in
    by hand.
    """

    status: str = "thinking"
    written_by: str | None = None
    written_on: date | None = None
    # The entities this note graduated into. On the NOTE and not on the entity:
    # a `from_note` field on `Entity` would put a note id into the type every
    # view of the plan is built from. What the promoted record says about where
    # it came from, it says in its own shaping document, in prose. See
    # `shaping_document`.
    became: list[str] = []

    def state(self, entities: dict[str, Entity]) -> str:
        """`dropped` first and unconditionally — "we are not doing this" was
        said by a person, and somebody linking a record afterwards does not
        un-say it (the same rule `Issue.state` gives `shelved`). `promoted`
        when at least one thing it became exists — not all of them, because a
        brainstorm that splits into two pitches is promoted the moment either
        exists. A link whose target is gone falls back to `thinking` rather
        than claiming a promotion nobody can open; the missing id is a warning
        beside the note, where it can be fixed. Nothing here reads the STATUS
        of what it became: whether that pitch ships is the pitch's business.
        """
        if self.status == "dropped":
            return "dropped"
        if any(target in entities for target in self.became):
            return "promoted"
        return self.status
```

Notes for the implementer: the `@field_validator("status", ...)` bodies the old classes carried are **not** reproduced — `Entity._as_written` covers `status` and `priority` for every subclass. `kind` has no default, same as `Project`; every constructor now passes `kind="issue"` / `kind="note"` (the parser always did).

- [ ] **Step 2: model.py — the two rungs join `KINDS`, exactly as the spec writes them**

In the `KINDS` tuple (currently 979-1001, now carrying `planned=`/`statuses=` on all four rungs from Task 1), append after the `task` rung:

```python
    Rung("issue", "issue", "issues", Issue, under=(), schedules=False, depends=False,
         sized=False, carded=False, planned=False, statuses=ISSUE_STATUS),
    Rung("note",  "note",  "notes",  Note,  under=(), schedules=False, depends=False,
         sized=False, carded=False, planned=False, statuses=NOTE_STATUS),
```

Nothing else here: `KIND_NAMES`, `RUNG`, `_MODELS`, `_ID_PREFIXES`, `_ENTITY_DIRS`, `_PREFIX_FOR_KIND`, `PARENT_KINDS`, `unread_fields` and `web.py`'s `DIRECTORY`/`PREFIX`/`MODELS`/`ENTITY_FIELDS`/`ID_PATTERN` are all derived from this tuple and pick the rungs up on this line. That derivation is the whole reason this commit cannot be split.

- [ ] **Step 3: model.py — delete the bespoke parsers and the Config carry**

Delete `parse_issue_text`, `parse_issue_file`, `parse_note_text`, `parse_note_file` (lines 1132-1160). Issue and note files now come through `parse_text`, whose id-prefix fallback (`_ID_PREFIXES`) already resolves `issue-778899` and `note-11aa22` with no `kind:` key in any file — no backfill, nothing stamps one.

In `Config` (623-672): delete the two fields

```python
    issues: dict[str, Issue] = {}
    notes: dict[str, Note] = {}
```

and the whole `with_issues` and `with_notes` methods. Keep `with_people` and `with_plans`.

In `load_repo` (1300-1391): delete the issue walk (the `# Issues through the same door` comment through the `readable(...)` call), the note walk (`# And the notes, through the same door for the third time.` block), and shrink the return: the config expression becomes

```python
        config.with_plans(plans).with_people(people),
```

and remove `*unreadable_issues, *unreadable_notes, *nested_issues, *nested_notes` from the sorted list. Do **not** touch the entity walk — `_plan_files(root, *_ENTITY_DIRS)` at 1318 now walks `issues/` and `notes/` because Step 2 put them on the ladder.

- [ ] **Step 4: model.py — one id pattern, and the rewritten comment (the most important writing in this commit)**

Delete `_ISSUE_ID_PATTERN` and `NOTE_ID_PATTERN` and every comment line attached to them (currently 1688-1712). `_ID_PATTERN` (1685-1687) is already derived from `KINDS` and now matches `issue-` and `note-` ids by construction. Replace the deleted comments with this, directly under `_ID_PATTERN` — it makes the old comment's argument about the new mechanism, and says what changed:

```python
# One pattern for every rung, issues and notes included — where there were
# three. The comments that stood here argued the opposite: the entity pattern
# was what kept `projects|pitches|tasks/<id>.md` the whole writable surface,
# so admitting an inbox id would have widened that surface "by degrees", and
# each inbox therefore kept a pattern of its own. Both halves of that argument
# moved when the ladder did. The writable surface is now DERIVED from `KINDS`
# (`web.ID_PATTERN`, `web.DIRECTORY`), so it widens exactly when a rung is
# added and never otherwise — there is no "by degrees" left to lose. And what
# keeps an issue out of the PLAN is no longer which pattern its id matches but
# `planned=False` on its rung, enforced once in `build_index`, asserted by the
# Index model_validator, and swept by the KINDS-derived exclusion test. A
# pattern was the wrong home for that rule anyway: it could only refuse ids,
# and the leak it guarded against — an issue on the timeline — never travelled
# through an id.
```

- [ ] **Step 5: model.py — fold the inbox rules into `_problems_for`, delete `issue_problems`/`note_problems`**

The old bespoke validators (2283-2372) checked five things. Three are already covered the moment an issue is an entity: id shape and prefix-vs-kind (`_ID_PATTERN` + `_PREFIX_FOR_KIND` at the top of `_problems_for`), empty title, and the status vocabulary (per-rung `_vocabulary_problems`, Task 1). Two must be folded in.

First, extend `_people_problems` (1992-2006): change the field tuple to

```python
    for field in ("owner", "shaped_by", "assignees", "reviewers", "reported_by", "written_by"):
```

`getattr(entity, field, None)` already answers `None` on kinds without the field. The message changes from the inboxes' `"… is not in the roster"` to this function's `"… is not in config/people.yaml"` — one rule, one sentence, per the one-guard rule.

Second, add the promotion-link rule. Above `_problems_for`, add:

```python
# The links a promotion writes on its source, and the phrase each is reported
# with. One direction only — the promoted record does not list its sources — so
# the only thing that can rot is the target going away, and that is a warning,
# not a blocker: an issue outlives the pitch it fed, and a shelved pitch deleted
# later should not turn the record that pointed at it red. `state()` already
# shows the consequence (the claim quietly drops back to the stored status);
# this names WHICH id went, which is the part a person needs to repair it.
_PROMOTION_LINKS = {"pitched_into": "pitched into", "became": "became"}
```

and inside `_problems_for`, after the `yield from _dependency_problems(...)` line (currently 2273):

```python
    for field, phrase in _PROMOTION_LINKS.items():
        for target in getattr(entity, field, []):
            if target not in by_id:
                yield "warning", field, f"{phrase} {target}, which is missing", 1
```

Then delete `issue_problems` and `note_problems` entirely (2283-2372). `validate_all` needs no edit: issues and notes arrive in its `entities` list from `load_repo`, so `openproj check` covers them for the first time — `cli.py:94` only ever called `validate_all`, so the bespoke rules were dead to the CLI from the day they were written. The structural terminal-status exemption from Task 1 (`rung.statuses and entity.status == rung.statuses[-1]`) is what exempts a `dropped` note exactly as it exempts a `shelved` pitch.

- [ ] **Step 6: index.py — the index stops carrying a second population, and the comment argues the new boundary**

In the imports (21-41): remove `Issue`, `Note`, `issue_problems`, `note_problems`.

In `class Index`, delete the four fields and the comment above them (currently 166-174):

```python
    issues: dict[str, Issue] = {}
    issue_problems: list[Problem] = []
    notes: dict[str, Note] = {}
    note_problems: list[Problem] = []
```

That comment — "Nothing else on the index may reach for them: a note that appears in a second view is a note that has become a bet nobody made" — is the one being replaced, not discarded. Append its rewritten form to the comment block Task 2 put on `records` (keep Task 2's text; add this below it):

```python
    # Where the two inboxes went. `issues` and `notes` were separate maps here,
    # with a comment forbidding the rest of the index from reaching for them —
    # "a note that appears in a second view is a note that has become a bet
    # nobody made". That rule is now structural rather than admonitory: an
    # issue is an Entity on an unplanned rung, so it lives in `records`, is
    # filtered out of `entities` by the one comprehension in `build_index`,
    # and the model_validator below refuses any Index built otherwise. A PM
    # view that is forgotten reads `entities` and fails CLOSED — fewer
    # records, never more — where the old type boundary failed open the day
    # somebody passed the wrong dict. What survives of the admonition is one
    # word: reaching for `records` in a function about the plan is a
    # deliberate, greppable act, and the word looks wrong there on purpose.
```

In `build_index` (484-509): delete the four kwargs `issues=config.issues`, `issue_problems=issue_problems(config, entities)`, `notes=config.notes`, `note_problems=note_problems(config, entities)`. `problems=validate_all(entities, config)` now carries the folded rules for every record.

- [ ] **Step 7: web.py — delete the parallel readers and gates, widen the type lists**

Imports (71-103): remove `ISSUE_STATUS`, `NOTE_ID_PATTERN`, `NOTE_STATUS`, `Issue`, `Note`, `parse_issue_text`, `parse_note_text` from the `.model` import. Add two imports this task needs:

```python
from typing import Literal, NamedTuple
```
(extend the existing `from typing import Literal` at line 51) and

```python
from urllib.parse import quote
```

Delete: `ISSUE_DIR`, `ISSUE_ID_PATTERN` (261-262), `_issues_at`, `_issue_path` (295-308), `NOTE_DIR`, `_notes_at`, `_note_path` (311-330). In `_config_at` (366-395) delete the two lines

```python
    issues, refused_issues = _issues_at(store, commit)
    notes, refused_notes = _notes_at(store, commit)
```

and shrink the return to `config.with_plans(plans).with_people(people)` and `[*refused, *refused_plans, *refused_people]`. Issues and notes now arrive through `_entities_at` (482-483), whose `DIRECTORY.values()` gained the two directories in Step 2 — same `_PARSED` cache, same `readable` door.

Delete `_reject_bad_issue` and `_reject_bad_note` (584-620). Their status halves are the generic per-rung gate from Task 4; their unknown-field halves are the create route's `allowed = set(MODELS[kind].model_fields)` check; their list-shape halves move here — extend `_LISTS` (web.py:581):

```python
_LISTS = ("assignees", "reviewers", "tags", "prs", "depends_on", "shaped_by",
          "pitched_into", "became")
```

Delete `ISSUE_FIELDS = _schema_names(Issue)` and `NOTE_FIELDS = _schema_names(Note)` (752-753). `ENTITY_FIELDS` on the line above is derived from `KINDS` and now carries `reported_by`, `opened_on`, `pitched_into`, `written_by`, `written_on`, `became` — so `_named` keeps commit messages allowlisted for issue saves with no new list.

- [ ] **Step 8: web.py — the per-rung stamping table, and `POST /api/entity` stamps it**

Below `PREFIX` (near line 145), add:

```python
class Inbox(NamedTuple):
    """What the server owns when an inbox record is created, and the link a
    promotion writes on it. One row per unplanned rung, because these were the
    defaults of `POST /api/issue` and `POST /api/note` — the routes this table
    replaced — and losing them would make the shortest write paths in the tool
    ask for four fields instead of a title."""

    author: str  # defaults to the signed-in login; the form may say otherwise
    dated: str   # always the server's: when a record was made is not an opinion
    opens: str   # the status a fresh record starts in
    link: str    # what /api/promote appends the new record's id to


INBOXES = {
    "issue": Inbox("reported_by", "opened_on", "ready", "pitched_into"),
    "note": Inbox("written_by", "written_on", "thinking", "became"),
}
```

In `POST /api/entity` (the `create` handler, 2345-2427), directly after `fields["id"] = entity_id` and before the `created_schema_version` line, insert:

```python
        # The defaults the deleted inbox routes used to supply. `author` is a
        # default and not a fact — somebody files what a colleague mentioned in
        # a corridor, so the form can say otherwise — but the date is written
        # last, over anything the client sent, exactly as the old routes
        # stripped it: `opened_on` and `written_on` are derived rows on the
        # page, and a client that sends one is overruled, not obeyed.
        inbox = INBOXES.get(kind)
        if inbox is not None:
            fields.setdefault(inbox.author, user.login)
            fields.setdefault("status", inbox.opens)
            fields[inbox.dated] = date.today().isoformat()
```

Nothing else changes in `create`: the id was already minted server-side, the `allowed` check already refuses unknown fields per kind, Task 4's status gate already refuses a word off the rung's ladder, and the `validate_all` blocker gate already refuses an empty title.

- [ ] **Step 9: web.py — the promote route reads through the one parser**

In `POST /api/promote` (1556-1700), replace the source-discrimination block

```python
        if NOTE_ID_PATTERN.match(source_id):
            inbox, path, link = "note", _note_path(source_id), "became"
        elif ISSUE_ID_PATTERN.match(source_id):
            inbox, path, link = "issue", _issue_path(source_id), "pitched_into"
        else:
            raise HTTPException(400, f"{source_id!r} is not a note or an issue")
        article = "an issue" if inbox == "issue" else "a note"
```

with:

```python
        # The id decides which inbox this is, off the ladder, through the same
        # pattern every entity write uses — the bespoke patterns went with the
        # bespoke routes. A kind that is not an inbox is a 400 like a garbage
        # id, because "promote a task" is not a request this route has ever
        # taken and the tell is the same either way: the source is not a note
        # or an issue.
        prefix = source_id.split("-")[0]
        kind_of_source = next((r.name for r in KINDS if r.prefix == prefix), None)
        if not ID_PATTERN.match(source_id) or kind_of_source not in INBOXES:
            raise HTTPException(400, f"{source_id!r} is not a note or an issue")
        inbox = kind_of_source
        stamp = INBOXES[inbox]
        article = "an issue" if inbox == "issue" else "a note"
```

Then: replace the `original = store.read(base, path)` lookup — there is no `_note_path` any more, and inbox files may carry `--slug` names like every other record — with the finder every entity write uses:

```python
        path = _path_for(store, base, source_id)
        original = store.read(base, path) if path is not None else None
        if original is None:
            raise HTTPException(404, f"no {inbox} {source_id!r}")
```

Replace the parse and the two per-kind reads:

```python
        source = parse_text(original, path)
        who = getattr(source, stamp.author)
        when = getattr(source, stamp.dated)
```

Replace `link` with `stamp.link` in the `marked = _patched(original, {stamp.link: [*getattr(source, stamp.link), entity_id]}, None, path)` line, and replace the read-back

```python
            (parse_note_text if inbox == "note" else parse_issue_text)(marked, path)
```

with `parse_text(marked, path)`. `render.PROMOTABLE` is keyed `"note"`/`"issue"`, which are now kind names, so the `PROMOTABLE[inbox]` check stands unchanged.

- [ ] **Step 10: web.py — the eight issue/note routes become six redirects, and the three plan-only reads go total**

Delete the entire block from `@app.get("/issues", ...)` (1336) through the end of `save_note` (1555): the two list pages, the two `/…/new` pages, the two record pages, `POST /api/issue`, `PATCH /api/issue/{id}`, `POST /api/note`, `PATCH /api/note/{id}`. In their place:

```python
    # The inbox routes, kept as addresses and nothing else. Bookmarks, commit
    # messages and chat scrollback are full of these URLs; a URL that answered
    # 200 last week and 404 this week reads as a deleted record, not a moved
    # page. 301 because the move is permanent, and the ids are percent-encoded
    # on the way through: a path segment out of the wire is not a thing to
    # write into a Location header verbatim. The `new` routes are declared
    # before the `{id}` routes because the router matches in order and `new`
    # would otherwise be a record id.
    @app.get("/issues")
    def issues_moved() -> RedirectResponse:
        return RedirectResponse("/", status_code=301)

    @app.get("/notes")
    def notes_moved() -> RedirectResponse:
        return RedirectResponse("/", status_code=301)

    @app.get("/issue/new")
    def new_issue_moved() -> RedirectResponse:
        return RedirectResponse("/new?kind=issue", status_code=301)

    @app.get("/note/new")
    def new_note_moved() -> RedirectResponse:
        return RedirectResponse("/new?kind=note", status_code=301)

    @app.get("/issue/{issue_id}")
    def issue_moved(issue_id: str) -> RedirectResponse:
        return RedirectResponse(f"/detail/{quote(issue_id, safe='')}", status_code=301)

    @app.get("/note/{note_id}")
    def note_moved(note_id: str) -> RedirectResponse:
        return RedirectResponse(f"/detail/{quote(note_id, safe='')}", status_code=301)
```

(The f-string builds a URL, not markup — the AST ban is on `.replace`/`.sub`, and `quote` is the escaping boundary for a path segment.)

**Auditor note, applied:** an earlier draft of this step claimed `/detail/{id}` "needs no edit: its 404 lookup reads `index.records` since Task 2". That was wrong — Task 2 edits only `index.py`; web.py's plan-only reads stay plan-only until somebody edits them, and nobody else does. Three web.py edits belong to this step:

**(a)** The detail route's 404 gate (web.py:1780). Replace

```python
        if entity_id not in index.entities:
            raise HTTPException(404, f"no entity {entity_id!r}")
```

with

```python
        if entity_id not in index.records:
            raise HTTPException(404, f"no record {entity_id!r}")
```

Without this, every redirect above lands on a 404 and every issue and note page is unreachable forever.

**(b)** The PATCH loop guard (web.py:2002). An issue or note handed to `loop_made` must be checked against the population it actually lives in — a candidate absent from the checked set is a question asked of the wrong world. Replace

```python
        loop = loop_made(candidate, index_now()[1].entities.values())
```

with

```python
        loop = loop_made(candidate, index_now()[1].records.values())
```

**(c)** The DELETE cascade's dependent rewrite (web.py:2078). Task 2 made `cascade_of` iterate `index.records`, so `edited` can name an unplanned record carrying a hand-written `depends_on`; the plan-only lookup then KeyErrors and the DELETE 500s — exactly the failure the totality work exists to prevent. In the `for other in edited:` loop, replace

```python
                for target in index.entities[other].depends_on
```

with

```python
                for target in index.records[other].depends_on
```

**(d)** The hover card's data route, `GET /api/body/{entity_id}` (web.py:1829-1851) — spec §2 lists the hover card on the records side. It reads with `.get`, so it cannot KeyError, but it 404s on every inbox id, and a card that says "no such record" over a link to a record that exists is worse than no card. Replace

```python
        entity = index_now()[1].entities.get(entity_id)
```

with

```python
        entity = index_now()[1].records.get(entity_id)
```

The 404-for-a-typo contract in its docstring is unchanged — an id no record has is still a 404; an id an issue has is no longer one.

- [ ] **Step 11: render.py — delete the two record pages and the two list pages**

Delete, checking each for stray references before removing (Task 7 must not have taken a dependency; if `grep` finds one outside this deletion set, stop and reconcile):

- `render_issues` and `_ISSUES` (18953-19026 and 19974-20033)
- `render_issue`, `_issue_view`, `_blank_issue` (19029-19164) and `_ISSUE` (20035-20279)
- `render_notes` (19207-19267) and `_NOTES` (20329-20388)
- `render_note`, `_note_view`, `_blank_note` (19269-19384) and `_NOTE` (20390-20630)
- `_RECORD_TABLE` (19764-19934) and, if nothing else references them, `_NOTHING`/`_nothing_rows` (19936-19972)

Keep `_PROMOTE` (20280-20327) and `_promote_html`/`PROMOTABLE`/`_ARTICLE` (19167-19205) — they move surface in the next step. Keep `_RECORD_STYLE` (minus the `#promote` rules, next step): it becomes unreferenced and Task 9 deletes it. Drop imports ruff now flags unused — let `ruff check` name them rather than guessing what Tasks 3-7 still use; `NOTE_STATES` stays either way, Step 13's `_TOC_LADDER` reads it.

In `Links` (1571-1603): delete the four fields `issues`, `issue`, `notes`, `note` and their comment lines; in `ROUTES` (1636-1640) delete `issues="/issues", issue="/issue/", notes="/notes", note="/note/"`. In `_NAV` (20741-20745) delete `("issues", "Issues")` and `("notes", "Notes")` — the landing already wears the superset word "Records" (Task 7). In `render_static` (20983-21012) delete the `("issues.html", render_issues(index))` and `("notes.html", render_notes(index))` entries; every issue and note is in `index.html` (the Records landing, Task 7) and `detail.html` (all of `records`).

- [ ] **Step 12: render.py — the shared page reads the total map, the login threads down, and the promote panel moves into `_DETAIL`**

Six edits, all on the one surviving surface. Task 2 never touched render.py, so every widening to `records` here is this task's to make.

**(a)** `_detail_rows` (render.py:16484-16514) iterates the plan. Change its closing comprehension line

```python
        for entity_id, entity in sorted(index.entities.items())
```

to

```python
        for entity_id, entity in sorted(index.records.items())
```

Everything inside the dict is already total-safe: `index.problems` carries every record's problems since Step 6, `index.children` is total (Task 2), and `_progress_view`/`_shaping_hints` take the entity itself. The grouping key stays `entity.status` — the stored word; the fact row is where the derived `state()` shows (Task 3).

**(b)** `_suggestions` (render.py:16739): the people/tags loop and the PR refs widen to records, so `reported_by`/`written_by` names and issue/note tags reach the datalists (spec §2 puts "the people and tag suggestion blobs" on the records side). Change

```python
    for entity in index.records.values():
```

(the loop that fills `people` and `tags`) and

```python
    refs = {ref for entity in index.records.values() for ref in entity.prs}
```

The `"entities"` completion list stays on `sorted(index.entities.items())`, with this comment above it:

```python
        # Still the PLAN, deliberately: these complete `parent` and
        # `depends_on`, and offering an issue or a note there would offer an
        # edge the model refuses.
```

**(c)** `render_detail` gains the login. Task 3 built the `signed_in` slots into `_editable_for` and `_fact_rows` and deferred the wiring here; Task 6's merged signature has no such parameter, so without this edit the reporter placeholder both old pages shipped is silently lost. In the signature Task 6 wrote, add after `creating`:

```python
    signed_in: str = "",
```

and in the per-row loop (the one Task 6 wrote that sets `row["rows"]`, `row["raw_body"]`, `row["deletes"]`), the whole loop becomes — note the total map, which fixes the KeyError an issue row would otherwise hit the moment (a) lands:

```python
        for row in rows:
            entity = index.records[row["id"]]
            row["rows"] = _fact_rows(index, entity, links, signed_in)
            row["raw_body"] = entity.body
            row["deletes"], row["frees"] = cascade_of(index, row["id"])
```

And in Task 6's creating branch, the blank-record dict gains one key after `"frees": []`:

```python
            "promote": Markup(""),
```

— explicit rather than riding Jinja's default Undefined stringifying to `""`: the "never on the creating article" rule below must survive a move to StrictUndefined, not hold by accident. (`_new_rows()` keeps its no-argument signature; the creating form's author placeholder staying empty is fine because Step 8's stamping table defaults the author server-side on the POST anyway.)

**(d)** web.py passes the login through. In the `detail` route (the `render.render_detail(...)` call at web.py:1793-1801), add:

```python
        who = viewer(request)
```

above the `return page(...)` and

```python
                signed_in=who.login if who else "",
```

as the last keyword of the `render_detail` call. Make the identical two-line addition in `GET /new` (Task 6's route — it already takes `request: Request`).

**(e)** The promote panel. Above `_promote_html` (19171), add the per-kind copy the two deleted pages carried inline:

```python
# The sentence above the Promote button, per inbox. Two entries because the two
# records make two different promises about what happens to the source: an
# issue stays OPEN until the work lands (its state derives from the link), a
# note simply stays and points. Same first sentence on purpose — the control
# keeps the same words through the flow.
_PROMOTE_HINTS = {
    "issue": "The new record starts in Shaping, carrying this issue’s title, its "
             "tags and its text, and saying in its own document that it came from "
             "here. Nothing else is carried: an issue has no owner and no size to "
             "give it. The issue stays open until what it became is done.",
    "note": "The new record starts in Shaping, carrying this note’s title, its "
            "tags and its text, and saying in its own document that it came from "
            "here. Nothing else is carried: a note has no owner and no size to "
            "give it. This note stays, and points at what it became.",
}
```

In the per-row loop from (c), append after the `row["deletes"], row["frees"] = ...` line:

```python
            # The promote panel, where the record is. It lived on the two
            # deleted inbox pages; a kind that is not promotable gets an empty
            # Markup, and the static export gets one for everything because
            # there is no server to post to. Never on the creating article:
            # there is nothing to promote yet, and a control whose only answer
            # is a refusal is a dead end a person can only find by pressing it.
            row["promote"] = (
                _promote_html(
                    row["id"], PROMOTABLE[entity.kind], _PROMOTE_HINTS[entity.kind],
                    base_commit or "", links,
                )
                if base_commit is not None and entity.kind in PROMOTABLE
                else Markup("")
            )
```

In the `_DETAIL` template, between the closing of the edit form and `</article>` (currently 13349-13352), insert the panel exactly where `_NOTE` had it (outside the form — it is its own IIFE and fetch):

```
  {% if editable %}
  </form>
  {% endif %}
  {{ e.promote }}
</article>
```

**(f)** Fix the toc heading at 13113, which was written when issues were excluded by type and is false the moment they render here: `<h1>Every entity in this plan except for issues</h1>` becomes `<h1>Every record in this plan</h1>`. (This edit happens HERE, in the commit that makes it false — Task 9's copy of it is deleted; Task 9 keeps only the back-link retarget.)

Move the four `#promote` rules out of `_RECORD_STYLE` (currently 20729-20737) and append them to `_DETAIL_STYLE`, comment included:

```css
/* The promotion bar. Hidden while the record is being edited: promoting carries
   the STORED body across, so offering it over a textarea somebody is halfway
   through is offering to promote a document they cannot see. */
#promote { display: flex; gap: .5rem; align-items: baseline; flex-wrap: wrap;
           border-top: 1px solid var(--line); margin-top: 1.5rem; padding-top: 1rem; }
.entity.editing #promote { display: none; }
#promote select { font: inherit; font-size: 13px; }
#promote .hint { margin: 0; }
```

- [ ] **Step 13: render.py — `_by_status` learns the inbox vocabularies, in the commit whose rows first carry them**

Moved here from Task 9 (which deletes its own copy): `render_detail` iterates `index.records` from Step 12 onward, so the rows reaching `_by_status` (currently `render.py:19599-19612`) carry issue and note words **on this commit**, and leaving the function alone would put `thinking`/`promoted`/`dropped` into the alphabetical unknown-status tail — where `dropped` sorts **above** `thinking`, a note's terminal state above its live one, which is exactly the inversion the docstring exists to prevent (`done` at the top was the original bug). The issue ladder costs nothing: `ISSUE_STATUS` is a subset of `STATUS_ORDER`, so it adds no words.

Replace the whole function with a derived ladder beside it:

```python
# Every word a record's `state()` can answer, in ladder order, kind by kind.
# Derived from the rungs rather than written out: a seventh kind's vocabulary
# joins this list on the commit that adds the rung, instead of tumbling into
# the alphabetical tail below. The note rung contributes `NOTE_STATES` and not
# `rung.statuses`, because `promoted` is derived from `became` and never stored
# — `model.py` says so beside `NOTE_STATES` itself: statuses are what may be
# written, states are what a page may draw and sort by. The issue rung adds no
# new words; `ISSUE_STATUS` is a subset of the plan ladder, and the dedup keeps
# the plan's order for it.
_TOC_LADDER = tuple(dict.fromkeys(
    word
    for rung in KIND_LADDER
    for word in (NOTE_STATES if rung.name == "note" else rung.statuses)
))


def _by_status(rows: list[dict]) -> list[dict]:
    """The index, in the order work moves through: shaping first, dropped last.

    A status nobody uses is left out rather than shown empty, and a status the
    validator does not know still gets a heading — the index is a way in, and a
    record missing from it because its status is misspelt is invisible.
    """
    known = list(_TOC_LADDER)
    seen = sorted({row["status"] for row in rows}, key=lambda s: (s not in known, s))
    order = [s for s in known if s in seen] + [s for s in seen if s not in known]
    return [
        {"status": status, "entities": [r for r in rows if r["status"] == status]}
        for status in order
    ]
```

`KIND_LADDER` is `render.py`'s existing import alias for `model.KINDS` (`render.py:78`); `NOTE_STATES` is already imported (`render.py:50`); `Rung.statuses` is Task 1's field. The resulting order is `shaping, ready, in_progress, done, shelved, thinking, promoted, dropped` — each kind's own ladder in its own order, kinds in `KINDS` order. The unknown-tail behaviour for a misspelt status is unchanged, and the two tests that pin it (`test_a_status_nobody_uses_gets_no_heading`, `test_an_unknown_status_still_reaches_the_index`, `tests/test_render.py:1400-1413`) pass untouched — they feed `_by_status` plan-ladder words only. `STATUSES` itself stays in this commit (other readers survive until Task 9 retires it).

- [ ] **Step 14: rewrite `tests/test_issues.py` in full**

Replace the whole file with:

```python
"""The issue rung: off the plan by data, not by type.

An issue used to be kept off the table, the graph, the timeline and the people
page by being a separate type. It is now an `Entity` on a rung with
`planned=False`, and the exclusion is enforced once — in `build_index`, backed
by the Index validator and the KINDS-derived exclusion sweep, which stops being
vacuous in the commit that adds this rung. What is left for this file is what
is true of issues and of nothing else: the vocabulary, the derived state, the
server's stamping at creation, and the redirects from the retired routes.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pygit2
import pytest
from fastapi.testclient import TestClient
from test_store import commit_directly
from test_web import ANN, SECRET, SEED, file_at, git_head

from openproj.auth import sign_session
from openproj.index import build_index
from openproj.model import (
    ISSUE_STATUS,
    RUNG,
    Config,
    Entity,
    Issue,
    Task,
    load_repo,
    unread_fields,
    validate_all,
)
from openproj.web import ID_PATTERN, SESSION_COOKIE, create_app


@pytest.fixture
def repo_path(tmp_path: Path) -> Path:
    path = tmp_path / "plan.git"
    pygit2.init_repository(str(path), bare=True, initial_head="main")
    commit_directly(path, SEED, "seed the corpus")
    return path


@pytest.fixture
def client(repo_path: Path):
    with TestClient(create_app(repo_path, auth="dev", secret=SECRET)) as client:
        client.cookies.set(SESSION_COOKIE, sign_session(ANN, SECRET))
        yield client


def opened(client: TestClient, title: str, base: str, body: str = "", **fields) -> str:
    """An issue through the one door every record uses now."""
    response = client.post(
        "/api/entity",
        json={"base_commit": base, "body": body,
              "fields": {"kind": "issue", "title": title, **fields}},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def entities(**by_id: str) -> dict[str, Task]:
    return {
        i: Task(id=i, kind="task", title=i, status=status) for i, status in by_id.items()
    }


# --------------------------------------------------------------------------- #
# The rung
# --------------------------------------------------------------------------- #


def test_an_issue_is_a_rung_of_the_ladder():
    """The properties the old separate type carried longhand, now data on the
    one ladder every derivation reads."""
    rung = RUNG["issue"]

    assert issubclass(Issue, Entity)
    assert rung.model is Issue
    assert (rung.prefix, rung.directory) == ("issue", "issues")
    assert rung.planned is False, "off every plan view, enforced in build_index"
    assert rung.statuses == ISSUE_STATUS
    assert not rung.schedules and not rung.depends and not rung.sized and not rung.carded
    for commitment in ("owner", "cycle", "priority", "depends_on", "person_weeks"):
        assert commitment in unread_fields("issue"), commitment
    assert "status" not in unread_fields("issue"), "an issue reads its status"


def test_an_issue_has_no_shaping():
    """A shaped issue is a pitch. Shaping happens in the record an issue is
    promoted into, never in the issue itself — and with the vocabulary on the
    rung, `shaping` is now refused on an issue instead of silently legal."""
    assert ISSUE_STATUS == ("ready", "in_progress", "done", "shelved")


# --------------------------------------------------------------------------- #
# What a link means
# --------------------------------------------------------------------------- #


def test_pitching_an_issue_is_what_closes_it():
    """Derived, never copied. Writing the state into the file as well would be
    a second copy of a fact the link already carries, and the two disagree the
    moment somebody closes the pitch."""
    world = entities(**{"task-aa0001": "done", "task-bb0001": "in_progress"})
    unlinked = Issue(id="issue-000001", kind="issue", title="x")
    picked = Issue(id="issue-000002", kind="issue", title="x", pitched_into=["task-bb0001"])
    finished = Issue(id="issue-000003", kind="issue", title="x", pitched_into=["task-aa0001"])
    partly = Issue(id="issue-000004", kind="issue", title="x",
                   pitched_into=["task-aa0001", "task-bb0001"])

    assert unlinked.state(world) == "ready"
    assert picked.state(world) == "in_progress"
    assert finished.state(world) == "done"
    assert partly.state(world) == "in_progress"


def test_shelved_is_a_decision_a_link_does_not_reverse():
    world = entities(**{"task-aa0001": "done"})
    wont_fix = Issue(id="issue-000001", kind="issue", title="x", status="shelved",
                     pitched_into=["task-aa0001"])

    assert wont_fix.state(world) == "shelved"


def test_a_link_to_something_that_is_gone_leaves_the_stored_state_alone():
    """An issue outlives the pitch it fed. A deleted target is a warning from
    the one validator every record goes through now — `issue_problems` is gone,
    and the rule survives in `_problems_for` keyed by the link field."""
    issue = Issue(id="issue-000001", kind="issue", title="x", pitched_into=["task-zzzzzz"])

    assert issue.state({}) == "ready"
    assert [(p.severity, p.field) for p in validate_all([issue], Config())] == [
        ("warning", "pitched_into")
    ]


# --------------------------------------------------------------------------- #
# Writing — the lost route defaults (spec test 10)
# --------------------------------------------------------------------------- #


def test_creating_an_issue_stamps_the_lost_route_defaults(
    client: TestClient, repo_path: Path
):
    """POST /api/issue is deleted. The generic create stamps what it stamped:
    a minted id (never the browser's), the signed-in reporter, the server's
    date, and the opening status."""
    issue_id = opened(client, "openproj check is slow", git_head(repo_path))
    stored = file_at(repo_path, git_head(repo_path), f"issues/{issue_id}.md")

    assert re.fullmatch(r"issue-[0-9a-f]{6}", issue_id)
    assert "title: openproj check is slow" in stored
    assert "status: ready" in stored
    assert f"reported_by: {ANN.login}" in stored
    assert re.search(r"opened_on: '\d{4}-\d{2}-\d{2}'", stored)


def test_the_reporter_is_a_default_and_the_date_is_not(
    client: TestClient, repo_path: Path
):
    """The session knows who is writing, and that is right almost every time —
    not when somebody files what a colleague mentioned in a corridor, so the
    form can say otherwise. `opened_on` stays the server's: when the record was
    made is not an opinion."""
    theirs = opened(client, "y", git_head(repo_path), reported_by="halungge")
    stamped = opened(client, "z", git_head(repo_path), opened_on="1999-01-01")

    assert "reported_by: halungge" in file_at(
        repo_path, git_head(repo_path), f"issues/{theirs}.md"
    )
    dated = file_at(repo_path, git_head(repo_path), f"issues/{stamped}.md")
    assert "1999" not in dated, "a client-sent creation date is overruled"
    assert re.search(r"opened_on: '\d{4}-\d{2}-\d{2}'", dated)


def test_an_issue_still_needs_a_title(client: TestClient, repo_path: Path):
    before = git_head(repo_path)
    refused = client.post(
        "/api/entity",
        json={"base_commit": before, "fields": {"kind": "issue", "title": "  "}},
    )

    assert refused.status_code == 422
    assert git_head(repo_path) == before, "a refusal writes nothing"


def test_a_word_off_the_issue_ladder_is_refused_at_both_doors(
    client: TestClient, repo_path: Path
):
    """Spec test 4, armed for the rung it was written for: the bespoke gates
    are gone and the generic one must hold the same line, before anything is
    committed."""
    issue_id = opened(client, "x", git_head(repo_path))
    before = git_head(repo_path)

    created = client.post(
        "/api/entity",
        json={"base_commit": before,
              "fields": {"kind": "issue", "title": "y", "status": "shaping"}},
    )
    saved = client.patch(
        f"/api/entity/{issue_id}",
        json={"base_commit": before, "fields": {"status": "shaping"}, "body": None},
    )

    assert created.status_code == 422
    assert saved.status_code == 422
    assert git_head(repo_path) == before, "a refusal writes nothing"


def test_an_issue_id_is_an_entity_id_now(client: TestClient, repo_path: Path):
    """The pattern is derived from KINDS, so the rung brought its prefix on the
    commit that added it — and the whole entity write surface with it."""
    issue_id = opened(client, "x", git_head(repo_path))

    assert ID_PATTERN.match(issue_id)
    saved = client.patch(
        f"/api/entity/{issue_id}",
        json={"base_commit": git_head(repo_path), "fields": {"tags": ["halo"]},
              "body": None},
    )
    assert saved.status_code == 200, saved.text
    assert "- halo" in file_at(repo_path, git_head(repo_path), f"issues/{issue_id}.md")


# --------------------------------------------------------------------------- #
# The shared page, and the retired routes
# --------------------------------------------------------------------------- #


def test_the_retired_issue_routes_redirect_to_the_shared_ones(
    client: TestClient, repo_path: Path
):
    issue_id = opened(client, "x", git_head(repo_path))

    for old, new in (
        ("/issues", "/"),
        ("/issue/new", "/new?kind=issue"),
        (f"/issue/{issue_id}", f"/detail/{issue_id}"),
    ):
        moved = client.get(old, follow_redirects=False)
        assert moved.status_code == 301, old
        assert moved.headers["location"] == new, old


def test_an_issue_renders_on_the_shared_record_page(
    client: TestClient, repo_path: Path
):
    issue_id = opened(client, "Halo exchange drops a rank", git_head(repo_path))
    page = client.get(f"/detail/{issue_id}").text

    assert "Halo exchange drops a rank" in page
    assert 'id="promote-go"' in page, "the promote panel moved here with the record"
    hovered = client.get(f"/api/body/{issue_id}")
    assert hovered.status_code == 200, "the hover card reads records, not the plan"
    # The commitbar arrives with the shared page. Cancel now means what it
    # means everywhere on this page — the text stays in the box and the stored
    # draft is forgotten — a DELIBERATE change from the old restore-the-body.
    assert 'id="save"' in page and 'id="cancel"' in page


def test_a_derived_state_reads_on_the_page_and_locks_the_control(
    client: TestClient, repo_path: Path
):
    """Two ways to say one thing disagree the moment one of them is used, so an
    issue whose links decide its state shows the derived word and a control
    that says why it is off."""
    issue_id = opened(client, "x", git_head(repo_path))
    saved = client.patch(
        f"/api/entity/{issue_id}",
        json={"base_commit": git_head(repo_path),
              "fields": {"pitched_into": ["task-c00001"]}, "body": None},
    )
    assert saved.status_code == 200, saved.text

    assert "from the work it was pitched into" in client.get(f"/detail/{issue_id}").text


# --------------------------------------------------------------------------- #
# The corpus, and the check that finally covers it
# --------------------------------------------------------------------------- #


def test_the_seed_corpus_issues_load_as_records_off_the_plan(demo_root: Path):
    entities_now, config, unreadable = load_repo(demo_root)
    assert not unreadable

    index = build_index(entities_now, config, date(2026, 8, 17))
    issues = {i: r for i, r in index.records.items() if r.kind == "issue"}

    assert issues, "the demo corpus has issues"
    assert not set(issues) & set(index.entities), "and none of them is in the plan"
    assert not [
        p for p in index.problems
        if p.severity == "blocker" and p.entity_id in issues
    ]
    assert {r.state(index.entities) for r in issues.values()} <= set(ISSUE_STATUS)


def test_check_covers_issues_for_the_first_time(tmp_path: Path):
    """`openproj check` runs `validate_all(entities, config)` and nothing else,
    so `issue_problems` was dead to it from the day it was written: an issue
    with a status nobody defined passed check clean while the web banner
    reported it. One reader now — the same walk, the same rules."""
    (tmp_path / "issues").mkdir()
    (tmp_path / "issues" / "issue-bad001.md").write_text(
        "---\nid: issue-bad001\ntitle: an issue\nstatus: open\n---\n\nx\n",
        encoding="utf-8",
    )

    entities_now, config, unreadable = load_repo(tmp_path)

    assert not unreadable
    assert [e.kind for e in entities_now] == ["issue"], "load_repo walks issues/ itself"
    assert [(p.severity, p.field) for p in validate_all(entities_now, config)] == [
        ("blocker", "status")
    ]
```

- [ ] **Step 15: rewrite `tests/test_notes.py` — new head, kept promotion suite**

This file keeps most of its promotion tests, because `/api/promote` survives unchanged in behaviour. Make exactly these changes:

**(a)** Replace the module docstring, imports, fixtures and helpers (lines 1-86) with:

```python
"""Notes, and the promotion that stops them being a second inbox nobody empties.

A note is the record for "we are thinking of creating something that does not
exist and our ideas are confused", where an issue is "we found something
existing that is broken". A note is now an `Entity` on a rung with
`planned=False`: what used to be kept true by a separate type — no place on the
table, the graph, the timeline or the people page — is enforced once in
`build_index`, guarded by the Index validator, and swept by the KINDS-derived
exclusion test. This file keeps what is true of notes and of nothing else: the
two-word vocabulary with its derived third state, the stamping the deleted
POST /api/note used to do, and the promotion trail.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pygit2
import pytest
from fastapi.testclient import TestClient
from test_store import commit_directly
from test_web import ANN, SECRET, SEED, file_at, git_head

from openproj.auth import sign_session
from openproj.index import build_index
from openproj.model import (
    NOTE_STATES,
    NOTE_STATUS,
    Config,
    Note,
    Task,
    is_bettable,
    load_repo,
    promoted_from,
    shaping_document,
    unread_fields,
    validate_all,
)
from openproj.render import PROMOTABLE
from openproj.web import SESSION_COOKIE, create_app


@pytest.fixture
def repo_path(tmp_path: Path) -> Path:
    path = tmp_path / "plan.git"
    pygit2.init_repository(str(path), bare=True, initial_head="main")
    commit_directly(path, SEED, "seed the corpus")
    return path


@pytest.fixture
def client(repo_path: Path):
    with TestClient(create_app(repo_path, auth="dev", secret=SECRET)) as client:
        client.cookies.set(SESSION_COOKIE, sign_session(ANN, SECRET))
        yield client


def written(client: TestClient, title: str, base: str, body: str = "", **fields) -> str:
    """A note through the one door every record uses now."""
    response = client.post(
        "/api/entity",
        json={"base_commit": base, "body": body,
              "fields": {"kind": "note", "title": title, **fields}},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def opened_issue(client: TestClient, title: str, base: str, body: str = "",
                 **fields) -> str:
    response = client.post(
        "/api/entity",
        json={"base_commit": base, "body": body,
              "fields": {"kind": "issue", "title": title, **fields}},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def promote(client: TestClient, source: str, kind: str, base: str):
    return client.post(
        "/api/promote", json={"source": source, "kind": kind, "base_commit": base}
    )


def entities(**by_id: str) -> dict[str, Task]:
    return {
        i: Task(id=i, kind="task", title=i, status=status) for i, status in by_id.items()
    }
```

**(b)** Delete outright (their surfaces are gone; the sweep from Task 2 owns exclusion): `test_a_note_appears_on_no_page_but_its_own`, `test_a_note_is_not_an_entity_and_cannot_become_one_by_being_saved`, `test_the_notes_page_is_its_own_tab_and_lights_it`, `test_writing_one_down_is_the_same_view_as_editing_one`, `test_an_empty_notes_page_says_what_a_note_is_for`, `test_a_note_id_that_is_not_one_never_becomes_a_path`.

**(c)** Keep byte-identical except `kind="note"` added to every bare `Note(...)` constructor: `test_a_note_has_two_statuses_and_the_third_state_is_derived`, `test_a_promoted_note_does_not_track_what_it_became`, `test_dropped_is_a_decision_that_a_link_does_not_reverse`, `test_the_arrival_document_puts_the_note_under_the_first_heading`, `test_the_citation_says_what_it_can_and_no_more`.

**(d)** Replace `test_a_link_to_something_that_is_gone_is_a_warning_and_not_a_promotion` with:

```python
def test_a_link_to_something_that_is_gone_is_a_warning_and_not_a_promotion():
    """A note outlives what it became. `note_problems` is gone; the rule lives
    in `_problems_for` beside every other record's rules, and still names the
    id that went, which is the part a person needs to repair it."""
    note = Note(id="note-000001", kind="note", title="x", became=["pitch-zzzzzz"])

    assert note.state({}) == "thinking"
    assert [(p.severity, p.field) for p in validate_all([note], Config())] == [
        ("warning", "became")
    ]
```

**(e)** Replace `test_a_note_carries_no_field_that_is_a_commitment` (the write path no longer refuses inherited field names — the *form* never offers them and the validator reports them, which is the entity bargain every record now makes):

```python
def test_a_note_reads_no_field_that_is_a_commitment():
    """An owner, a size, an appetite and a cycle are all things somebody agreed
    to, and the claim a note makes is that nobody has agreed to anything. As an
    Entity subclass the note now DECLARES those fields — that is what makes one
    page serve every kind — so the boundary moved from the type to the ladder:
    every one of them is unread on this rung, the editors decline to offer what
    is unread, and a hand edit that writes one in is reported, not obeyed."""
    for field in ("owner", "assignees", "reviewers", "assigned_on", "cycle",
                  "priority", "prs", "depends_on", "person_weeks"):
        assert field in unread_fields("note"), field

    carried = Note(id="note-000001", kind="note", title="x", owner="ann")
    assert any(
        p.field == "owner" and p.severity == "warning"
        for p in validate_all([carried], Config())
    ), "written in by hand, it is reported beside the record"
```

**(f)** Replace `test_a_status_that_is_not_one_is_refused_and_says_which_are`:

```python
def test_a_status_that_is_not_one_is_refused_and_says_which_are(
    client: TestClient, repo_path: Path
):
    """`promoted` is a state the ball may stand at and no stop may set — it is
    derived from `became`, and typing it would be a second copy of the link.
    The refusal is the generic per-rung gate now; the sentence still names the
    ladder."""
    note_id = written(client, "x", git_head(repo_path))
    before = git_head(repo_path)
    refused = client.patch(
        f"/api/entity/{note_id}",
        json={"base_commit": before, "fields": {"status": "promoted"}, "body": None},
    )

    assert refused.status_code == 422
    assert "thinking" in refused.text and "dropped" in refused.text
    assert git_head(repo_path) == before, "a refusal writes nothing"
```

**(g)** Replace `test_writing_a_note_down_asks_for_a_title_and_nothing_else`:

```python
def test_writing_a_note_down_asks_for_a_title_and_nothing_else(
    client: TestClient, repo_path: Path
):
    """Somebody is in the middle of thinking. POST /api/note is deleted; the
    generic create stamps its defaults from the per-rung table, so a title is
    still the only thing a person supplies."""
    note_id = written(client, "Is the grid file the thing we cache?", git_head(repo_path))
    stored = file_at(repo_path, git_head(repo_path), f"notes/{note_id}.md")

    assert re.fullmatch(r"note-[0-9a-f]{6}", note_id)
    assert "title: Is the grid file the thing we cache?" in stored
    assert "status: thinking" in stored
    assert f"written_by: {ANN.login}" in stored
    assert re.search(r"written_on: '\d{4}-\d{2}-\d{2}'", stored)
    assert client.post(
        "/api/entity",
        json={"base_commit": git_head(repo_path),
              "fields": {"kind": "note", "title": "  "}},
    ).status_code == 422
```

**(h)** Replace `test_a_note_the_server_could_not_read_back_is_never_committed`:

```python
def test_a_note_the_server_could_not_read_back_is_never_committed(
    client: TestClient, repo_path: Path
):
    note_id = written(client, "x", git_head(repo_path))
    before = git_head(repo_path)
    refused = client.patch(
        f"/api/entity/{note_id}",
        json={"base_commit": before, "fields": {"tags": "not-a-list"}, "body": None},
    )

    assert refused.status_code == 422
    assert git_head(repo_path) == before
```

**(i)** Add the redirect pin:

```python
def test_the_retired_note_routes_redirect_to_the_shared_ones(
    client: TestClient, repo_path: Path
):
    note_id = written(client, "x", git_head(repo_path))

    for old, new in (
        ("/notes", "/"),
        ("/note/new", "/new?kind=note"),
        (f"/note/{note_id}", f"/detail/{note_id}"),
    ):
        moved = client.get(old, follow_redirects=False)
        assert moved.status_code == 301, old
        assert moved.headers["location"] == new, old
```

**(j)** In the promotion suite, keep every test but make these mechanical substitutions: every `client.post("/api/issue", json={... "title": t, "body": b, "fields": f})` becomes `opened_issue(client, t, base, body=b, **f)`; in `test_the_note_stays_and_points_at_what_it_became`, `client.get(f"/note/{note_id}")` becomes `client.get(f"/detail/{note_id}")` and the three hill assertions (`data-hill="note"`, `role="radiogroup"`, `hill-ball hill-promoted`) are replaced by the derived-ball pin and the lock hint — the shared page renders the same `_hill_html` for the read display, so the exact class is still the assertion that actually fails when `state()` stops reaching the fact row (a bare `page.count("Promoted")` would pass off any label or panel copy while the row wrongly draws the stored Thinking):

```python
    page = client.get(f"/detail/{note_id}").text
    assert "hill-ball hill-promoted" in page, "the read display draws the DERIVED state's ball"
    assert "from what it became" in page, "the lock says why the control is off"
```

In `test_the_trail_survives_a_round_trip_through_git`, replace `note = config.notes[note_id]` with `note = next(e for e in entities_now if e.id == note_id)`. In `test_an_issue_promoted_into_a_task_lands_as_a_task_this_plan_can_read_back`, replace `issue = config.issues[opened]` with `issue = next(e for e in entities_now if e.id == opened)`. In `test_the_promote_control_is_not_offered_where_it_cannot_work`, the two page URLs become `f"/detail/{note_id}"` / `f"/detail/{opened}"` and the "nothing to promote yet" line becomes `assert 'id="promote-go"' not in client.get("/new?kind=note").text`.

**(k)** Replace the two demo tests at the bottom:

```python
def test_the_shipped_demo_carries_notes_that_load(demo_root: Path):
    entities_now, config, unreadable = load_repo(demo_root)
    assert not unreadable

    index = build_index(entities_now, config, date(2026, 8, 17))
    notes = {i: r for i, r in index.records.items() if r.kind == "note"}

    assert notes, "the demo corpus has notes"
    assert not set(notes) & set(index.entities), "and none of them is in the plan"
    assert not [
        p for p in index.problems if p.severity == "blocker" and p.entity_id in notes
    ]
    assert {n.state(index.entities) for n in notes.values()} == set(NOTE_STATES), (
        "all three states, because a demo that shows one teaches one"
    )
    promoted = next(n for n in notes.values() if n.state(index.entities) == "promoted")
    became = index.entities[promoted.became[0]]
    assert promoted.id in became.body, "the trail is drawn at both ends in the demo too"


def test_the_static_export_carries_every_note(demo_root: Path, tmp_path: Path):
    """notes.html is gone; the record is in the export twice over — on the
    Records landing and in detail.html — with no way to write one, because a
    file has nowhere to post to."""
    from openproj.render import render_static

    entities_now, config, _ = load_repo(demo_root)
    written_files = render_static(
        build_index(entities_now, config, date(2026, 8, 17)), tmp_path
    )
    detail = (tmp_path / "detail.html").read_text(encoding="utf-8")

    assert "notes.html" not in written_files and "issues.html" not in written_files
    assert "note-11aa22" in detail
    assert "note-11aa22" in (tmp_path / "index.html").read_text(encoding="utf-8")
    assert "promote-go" not in detail
```

Keep `load_repo_from` at the bottom unchanged.

- [ ] **Step 16: `tests/test_injection.py` — the inbox ids turn hostile-and-served (spec test 16), and the census goes blind-free**

The corpus comment at 149-151 says the inbox ids are deliberately malformed "because those routes never render". They render now, at `/detail/{id}`, so the corpus arms them the way the entity ids are armed. Four edits:

**(a)** Below `ids()` (line 88), add:

```python
def inbox_ids(text: str) -> tuple[str, str]:
    """The issue and the note, each carrying the payload in its id — the same
    shape the three entity ids take. They were deliberately NOT armed while the
    inbox routes refused their paths and the census read only the list pages;
    an issue now renders on /detail/<id> like everything else, so its id is
    free text to exactly the same renderer."""
    return (f"issue-d0000{id_text(text)}", f"note-e0000{id_text(text)}")
```

**(b)** In `corpus()` (149-161), replace the two entries and their comment:

```python
        # Both inbox records armed like the entities above them: a malformed id
        # is a reported blocker rather than a refusal, so the record loads, and
        # /detail/<id> draws it now that an issue is a rung.
        "issues/i.md": (
            f"---\nid: '{text_yaml(issue_id)}'\ntitle: '{quoted}'\n"
            f"status: '{quoted}'\nreported_by: '{quoted}'\nopened_on: 2026-08-11\n"
            f"tags: ['{quoted}']\npitched_into: ['{text_yaml(pitch_id)}']\n---\n{body}"
        ),
        "notes/n.md": (
            f"---\nid: '{text_yaml(note_id)}'\ntitle: '{quoted}'\n"
            f"status: '{quoted}'\nwritten_by: '{quoted}'\nwritten_on: 2026-08-11\n"
            f"tags: ['{quoted}']\nbecame: ['{text_yaml(pitch_id)}']\n---\n{body}"
        ),
```

with `issue_id, note_id = inbox_ids(text)` added beside the existing `pitch_id, first_id, second_id = ids(text)` at the top of `corpus()`.

**(c)** In `served()` (272-330): replace the two list-page entries and their comment

```python
        # The two inboxes. Their list pages only: ...
        "issues": "/issues", "notes": "/notes",
```

with

```python
        # The retired inbox addresses, censused where they land — the redirect
        # is followed, so this renders the Records landing under the hostile
        # plan a second time, which costs nothing and keeps the
        # census-completeness test honest about the routes existing.
        "issues": "/issues", "notes": "/notes",
        "new issue": "/new?kind=issue", "new note": "/new?kind=note",
```

and update the two fixtures to open the inbox records' own pages:

```python
@pytest.fixture
def hostile_served(tmp_path: Path) -> dict[str, str]:
    return served(tmp_path, corpus(PAYLOAD), "hostile",
                  (*ids(PAYLOAD), *inbox_ids(PAYLOAD)))


@pytest.fixture
def benign_served(tmp_path: Path) -> dict[str, str]:
    return served(tmp_path, corpus(BENIGN), "benign",
                  (*ids(BENIGN), *inbox_ids(BENIGN)))
```

(The `ONE_ENTITY {n}` loop in `served()` already percent-encodes each id into `/detail/…` — the two new ids ride it with no further change.) Also remove `"issues.html", "notes.html"` from `STATIC_PAGES` (84-85; Task 7 will already have it as `index.html`/`table.html`/…).

**(d)** Empty `CENSUS_BLIND`. Task 7's completeness test filters `app.routes` on `HTMLResponse` and asserts both `missing = templates - covered - CENSUS_BLIND` and `stale = CENSUS_BLIND - templates` are empty; this commit turns `/issue/{issue_id}` and `/note/{note_id}` into `RedirectResponse` routes, which drop out of `templates` — leaving the two entries in place makes the set stale and the completeness test RED on the flip commit. Replace the `CENSUS_BLIND = {"/issue/{issue_id}", "/note/{note_id}"}` definition and its comment (the one ending "The flip commit turns both routes into redirects and retires this set.") with — keeping the name, because the completeness test imports it:

```python
# Emptied on the flip commit: /issue/{id} and /note/{id} became 301 redirects,
# so they are no longer HTML GET routes and the census reaches every page again.
# The set stays so the completeness test keeps failing closed if a route ever
# needs an exemption with a reason.
CENSUS_BLIND: set[str] = set()
```

- [ ] **Step 17: collateral test edits — every reader of the deleted surface**

Work through this list; after the source steps, `grep -rn "render_issue\|render_note\|/api/issue\|/api/note\|/issues\|/notes\b" tests/` must come back with only redirect tests and comments.

**`tests/test_cascade.py`** — in `served_pages` (50-73): delete the `render_issues`/`render_notes` imports and the `"issues":`/`"notes":` dict entries. Repoint the `record` fixture (925-937) at the surviving surface — the two-stylesheet duplication these tests policed is what this commit deletes, and the assertions that still describe the one surface keep running against it:

```python
@pytest.fixture
def record(index: Index) -> Sheet:
    """The one record page there is now. This fixture used to be the issue
    page, kept as a second sample of the same editing surface so the two
    stylesheets could not drift; the second stylesheet is gone with the page,
    and what these tests still pin is true of the survivor."""
    return sheet_of(
        render_detail(index, ROUTES, only=sorted(index.records)[0], base_commit=HEAD,
                      may_write=True)
    )
```

In `test_the_box_stays_readable_…` / the two tests at 1035 and 1057 that loop `for name, sheet in (("issue", record), ("detail", detail)):`, drop the `("issue", record)` pair and the loop with it — one sheet, asserted directly.

**`tests/test_facets.py`** — in `every_page` (250-276): delete the `render_issues`/`render_notes` imports and the `"issues":`/`"notes":` entries.

**`tests/test_coedit.py:2187`** — remove `"/issues"` from the route tuple (the redirect lands on `/`, which the tuple already covers).

**`tests/test_web.py:695-715`** — delete the issue and note stanzas of the forged-trailer test (the ones POSTing `/api/issue` and `/api/note`). The bespoke routes refused an unknown field outright; the generic route sanitises the commit message through `_named` instead, and *that* behaviour is already pinned by the entity half of the same test directly above. Leave a line in the surviving test's docstring: `"The issue and note routes went through this same gate when they were folded into /api/entity."`

**`tests/test_web.py:3785-3812`** (the `_PARSED` cache census) — the fixture files stand (they parse through `parse_text` by prefix); change the route list `("/", "/notes", "/issues", "/cycles", "/people")` to `("/", "/cycles", "/people")` — the landing now reads every kind, which is exactly what the `held` assertion checks, and the closing loop `for kind in ("tasks", "notes", "issues", "people", "cycles"):` is unchanged and now proves issues and notes come through the shared blob cache.

**`tests/test_editor.py:2263`** — the parametrize list `["/detail/{task}", "/new", "/issue/new", "/note/new"]` becomes `["/detail/{task}", "/new?kind=issue", "/new?kind=note", "/new"]` (same surfaces, through the door that now serves them). At `:5349`, `client.get("/note/new")` becomes `client.get("/new?kind=note")`.

**`tests/test_render.py`** — four edits, all forced by this commit (leaving any of them to Task 9 turns this commit's CI red):

1. `PAGES` (`:29-30`, as Task 7 Step 22 leaves it — still carrying the two inbox files): `render_static` stops writing `issues.html` and `notes.html` in Step 11, so every `PAGES` loop dies on a missing file. It becomes:

```python
PAGES = ("index.html", "table.html", "detail.html", "people.html", "cycles.html",
         "graph.html", "timeline.html")
```

2. `test_the_detail_page_names_each_document_it_holds` (currently `:2827`) pins the heading Step 12(f) rewrites:

```python
    assert "<h1>Every record in this plan</h1>" in body
```

3. `test_a_heading_that_repeats_the_nav_is_announced_and_not_drawn` (currently `:2863`):

```python
    listing = "Every record in this plan"
```

4. `test_the_index_is_grouped_in_the_order_work_moves` (currently `:1384-1397`) derives its expected headings from `STATUSES` over `index.entities` — with detail.html now carrying `thinking`/`dropped` groups it breaks on this commit. It becomes:

```python
def test_the_index_is_grouped_in_the_order_work_moves(rendered: Path, seed_index: Index):
    """shaping first, dropped last. Alphabetical put `done` at the top, which is
    the one group nobody opens the index looking for — and, once notes arrived,
    put a note's terminal state above its live one."""
    from openproj.render import _TOC_LADDER, _human

    body = read(rendered, "detail.html")
    headings = re.findall(r'<h2 class="tocgroup">\s*([^<]+?)\s*<span', body)
    shown = {r.status for r in seed_index.records.values()}
    present = [s for s in _TOC_LADDER if s in shown]

    assert headings == [_human(s) for s in present]
    assert set(headings) == {_human(r.status) for r in seed_index.records.values()}
    # The heading was the last place a status was still spelled the way the file
    # spells it, two lines above a kind that already read as a word.
    assert not [h for h in headings if "_" in h]
```

(`r.status`, not `r.state(...)`: Step 12(a) keeps the STORED word as the grouping key — the derived state lives on the fact row — so the test measures the same value the page groups by. `_TOC_LADDER` covers a future switch to `state()` regardless; that is what `promoted` is in it for.)

**`tests/test_records.py`** (Task 7's file; its parity docstring defers to this commit by name — "the flip commit adds issue and note needles to this corpus"). Three edits:

1. Extend `PLAN` with two records, non-ASCII titles per the corpus rule:

```python
    "issues/i.md": (
        "---\nid: issue-aa0001\ntitle: \"L'équateur fuit\"\nstatus: ready\n"
        "reported_by: halungge\ntags: [容器]\npitched_into: [pitch-b20000]\n---\n\nAn issue.\n"
    ),
    "notes/n.md": (
        "---\nid: note-bb0001\ntitle: Καταγραφή of a half-idea\nstatus: thinking\n"
        "written_by: bo\n---\n\nA note.\n"
    ),
```

2. In `test_the_landing_box_and_the_server_find_the_same_records`: the server half must search the same population the landing's payload carries, or any issue-matching needle disagrees with the JS twin by construction —

```python
        here = apply_filters(index, {}, needle, over=index.records)
```

— the needles list becomes

```python
    needles = ["traçage", "équateur", "Équateur", "平流", "gpu", "ann",
               "task-c00001", "1223", "downgrade", "tag:gpu", "kind:pitch",
               "fuit", "容器", "καταγραφή", "issue-aa0001", "note-bb0001",
               "kind:issue", "kind:note"]
```

and the docstring's closing sentence "At this commit `records` equals the plan; the flip commit adds issue and note needles to this corpus." becomes "The corpus carries an issue and a note, so parity is asked about the very records where `records` is more than `entities`."

3. In `test_the_landing_lists_every_record_newest_edit_first`, the expected set grows:

```python
    assert set(rows) == {"proj-a10000", "pitch-b20000", "task-c00001",
                         "issue-aa0001", "note-bb0001"}
```

(the ordering assertion `rows[0] == "task-c00001"` still holds — the task carries the newest `when=1_000_500` stamp).

**The seed-check pin (Task 1's test, spec test 3)** — `openproj check seed/` gains exactly one line in this commit: `warning: note-55cc66: written_by: dastrm is not in config/people.yaml`. (`note-33bb44`'s unknown author is exempt — `dropped` is its rung's terminal status; `issue-778899` is `shelved`, likewise.) Update the pin's expected list by adding that one tuple, with this comment beside it: `# Added by the commit that made a note a rung: issues and notes acquired 'openproj check' coverage they never had, and this warning is the coverage arriving — the web banner said it all along.`

**The exclusion sweep (Task 2's test, spec test 1)** — no code change: it derives its cases from `KINDS`, so the two rungs armed it on Step 2. Amend its module docstring with one sentence so a reader knows when it stopped being vacuous: `"Vacuous until the commit that put issue and note on the ladder; from that commit it seeds one issue and one note and asserts each is absent from /table, /graph, /timeline, /people, the schedule payload, /api/index.json, every facet and the suggestions blob's entity completions, present on / and its own /detail page, and refused by the Index validator."` (The suggestions blob's *people and tag* lists deliberately DO carry unplanned records since Step 12(b) — the entity completions are the plan-only part.)

- [ ] **Step 18: lint, commit, push, read CI**

Run the only local commands this project allows:

```bash
uv sync && uv run ruff check .
```

Fix what ruff names (it will catch any import Steps 3-11 left dangling). Then commit everything from Steps 1-17 as **one commit** — the tests land in the same commit as the code, TDD ordering kept with CI as the red/green gate — push, and read CI:

```bash
git add -A
git commit -F - <<'MSG'
An issue is a rung, and a note is a rung

Issues and notes were kept off the plan by being separate types, and the
type boundary was paid for with a second copy of every surface: two record
pages forked from the entity page that drifted on every feature since (#67
gave the note a hill and the issue a select in one commit), two list pages,
two POST routes, two PATCH routes, two id patterns, two bespoke validators
that `openproj check` never ran, and a Cancel that meant something different
from every other Cancel in the tool.

Both records are now Entity subclasses on unplanned rungs. What the type
enforced, the ladder enforces closed instead of open: `build_index` filters
`Index.entities` on `planned`, the Index validator refuses an unplanned kind
there, and the KINDS-derived exclusion sweep — vacuous until this commit —
now seeds an issue and a note and walks every plan view. Everything parallel
is deleted: the readers, the parsers, the Config carry, the routes, the
templates, the gates. The old addresses 301 to the shared ones. POST
/api/entity stamps the deleted routes' defaults from a per-rung table:
minted id, signed-in author, server's date, opening status. The shared
detail page reads the total record map, the toc ladder derives every kind's
vocabulary from the rungs, and `openproj check` covers issues and notes for
the first time; the seed pin gains the one warning that coverage surfaces.

This commit is atomic on purpose: putting the rungs in KINDS makes
`_ENTITY_DIRS` include issues/ and notes/ the moment it lands, so any split
double-reads every inbox record.

One deliberate behaviour change: Cancel on an issue or a note now means
what it means on every record — the text stays in the box and the stored
draft is forgotten — instead of the old restore-the-body. The draft store
is the body-undo now, and one Cancel that means one thing beats two that
mean two.

🤖 Written by an agent on behalf of @jcanton
MSG
git push
```

Then watch CI (do not run pytest locally). Expected failure modes worth knowing before reading the log: a leaked issue on a plan view means a consumer still reads `records` where it should read `entities` (the sweep names the page); a 404 on `/detail/<issue-id>` means Step 10(a)'s records lookup was missed; a KeyError from `render_detail` means Step 12(a) landed without Step 12(c)'s loop edit (or vice versa) — the two widen the same population and go together; a 422 on `POST /api/entity` for a plain issue means the Task 4 status gate ran before the stamping table set `status` — the stamp in Step 8 must execute before that gate reads `fields`; move the inserted block above it if Task 4 placed the gate earlier in the handler.


---

### Task 9: The second surface is gone

Spec §9 commit 9. Everything before this commit made the merge real; this commit is the proof — the fork's stylesheet, its hand-copied ladder, and every sentence of prose that still describes the two-page world are removed or corrected. Nine of the nine build-order commits leave the suite green; this one also leaves the *documentation* true. (The toc ladder, the toc heading and their three test repoints moved into Task 8, the commit whose rows first made them necessary — Steps 1, 9 and 14 below verify that work rather than redo it.)

All line numbers below were verified against the pre-Task-1 tree and **will have shifted by the time you run this** — Tasks 3, 6, 7 and 8 all edit `render.py` above these points. Anchor every edit by the quoted text, never by the number. Several steps are written as "if Tasks 3–8 left it": run the grep first; an old-string that no longer matches means an earlier task already did that piece, and you skip the step. The closing grep in each case must come back empty either way — that is the deliverable, not the individual edit.

**Files:**
- Modify: `src/openproj/render.py:20628-20738` (delete `_RECORD_STYLE` and its header comment — Task 8 Step 12 already trimmed its `#promote` rules into `_DETAIL_STYLE`)
- Modify: `src/openproj/render.py:11699-11706, 11753-11759, 14658-14674, 14999-15008, 15207-15213` (five comments that name `_RECORD_STYLE` or the dead pages)
- Modify: `src/openproj/render.py:15285` (the `STATUSES` hand copy, if Task 3 left it)
- Modify: `src/openproj/render.py:13131-13136` (the back link)
- Modify: `tests/test_editor.py:5335-5347` and `tests/test_cascade.py:946-954, 1033-1043, 1057-1065` (docstrings that name `_RECORD_STYLE` or argue from the two-stylesheet world — Task 8 edits those tests' bodies, not their prose)
- Modify: `README.md:22-28, 38-44`
- Modify: `AGENTS.md:3-4`
- Modify: `docs/architecture.md:5-21`
- Modify: `docs/data-model.md:3-12, 54-61, 73-75, 92-99`
- Test: none new; `tests/test_render.py` only if Step 9's reconciliation check finds a mismatch

**Interfaces:**
- Consumes: `STATUS_ORDER` from `model.py` (exists today at `model.py:1714`) for Step 7's unification; `Links.records` (Task 7) for the back link. From Task 8, as preconditions to verify rather than work to redo: the deletion of `render_issues` / `render_issue` / `render_notes` / `render_note` and the `_ISSUE` / `_NOTE` templates (Step 1's gate), the `#promote` trim of `_RECORD_STYLE` (Task 8 Step 12), `_TOC_LADDER` and the rewritten `_by_status` (Task 8 Step 13), the toc heading fix (Task 8 Step 12(f)), and the three `tests/test_render.py` repoints (Task 8 Step 17).
- Produces: nothing — this is the last commit of the branch, and its deliverable is an absence: no `_RECORD_STYLE`, no second ladder copy, no back link to a page two kinds never reach, no prose describing the two-page world.

---

- [ ] **Step 1: Prove nothing loads `_RECORD_STYLE`, and write down what used to.**

Run:

```bash
grep -rn "_RECORD_STYLE" src/ tests/
```

The **only acceptable hits are prose** — comments and docstrings, which Steps 3–6 rewrite. Before Task 8, the loaders were exactly four `_page(...)` calls, all deleted with their functions in Task 8 Step 11:

- `render_issues` — `_page("Issues", body, _RECORD_STYLE + _SUGGEST_STYLE, ...)` at `render.py:19024`
- `render_issue` — `_page(title, body, _RECORD_STYLE + _SUGGEST_STYLE, ...)` at `render.py:19098`
- `render_notes` — `_page("Notes", body, _RECORD_STYLE + _SUGGEST_STYLE, ...)` at `render.py:19264`
- `render_note` — `_page(title, body, _RECORD_STYLE + _SUGGEST_STYLE, ...)` at `render.py:19338`

and one test consumer, the `record` fixture in `tests/test_cascade.py:931-937` ("One editing surface, two stylesheets" section), which called `render_issue` and was repointed at `render_detail` in Task 8 Step 17. The prose hits you should expect are the five `render.py` comments (Steps 3–5) and four test docstrings (Step 6): `tests/test_editor.py:5344`, `tests/test_cascade.py:952`, `:1039`, `:1059` — pre-branch numbers, anchor by the quoted text. If the grep shows any surviving *code* reference, **stop** — Task 8 is not finished, and deleting the stylesheet now would turn a working page into an unstyled one. Do not proceed past this step until the only hits are prose.

- [ ] **Step 2: Delete `_RECORD_STYLE` and the comment above it.**

In `src/openproj/render.py`, delete the whole block from the comment that begins

```python
# One stylesheet for both inboxes, for the reason `attachRecordTable` is one
# script: the issues table and the notes table are the same table over two kinds
# of record. `.records` and not `#issues, #notes`, so a third one costs a class
# on a `<table>` rather than an edit to fourteen selectors — which is how a rule
# comes to be right for two tables and missing on the third.
_RECORD_STYLE = """
```

(pre-branch `render.py:20628-20633`) down to and including its closing line

```python
""" + _EDITING_STYLE
```

(pre-branch `render.py:20738` — the next non-blank line after it is `_NAV = (`, as Task 8 Step 11 leaves that tuple). The comment goes with the tuple: it argues for a stylesheet shared by two tables that no longer exist. Deleting the trailing `+ _EDITING_STYLE` is safe — `_EDITING_STYLE`'s load-bearing concatenation is the one at the end of `_DETAIL_STYLE` (`""" + _EDITING_STYLE` at `render.py:15261`), which stays. The ~100 deleted lines include the `.records` table rules, the `.state-*` badge colours, and a second copy of `.doc`, `#facts` and `.field` rules — every one of them either styles a deleted page or duplicates a rule `_DETAIL_STYLE` already carries. The four `#promote` rules the block held pre-branch are **not** among them: Task 8 Step 12 moved those into `_DETAIL_STYLE` where the panel now lives; if you still find a `#promote` selector inside this block, stop and reconcile with Task 8 before deleting.

- [ ] **Step 3: Rewrite the two comments in `_SUGGEST_STYLE` that name it.**

First, the 40rem toolbar media query (pre-branch `render.py:11699-11706`). Replace:

```
   `@media` and not `@container`, and that is not a style preference: the only
   `container-type: inline-size` in this file is on `article.entity` inside
   `_DETAIL_STYLE`, and the note and issue pages ship `_RECORD_STYLE +
   _SUGGEST_STYLE` and never load it. A container query here was patched in and
   measured byte-identical to no fix at all on /note/new, because
   `getComputedStyle(article).containerType` is "normal" there.
```

with:

```
   `@media` and not `@container`, and that is measurement rather than taste: this
   rule was proved at eight widths as a media query, in the days when the issue
   and note pages loaded a stylesheet with no `container-type` in it and a
   container query measured byte-identical to no fix at all on /note/new. Those
   pages are gone and every editor now sits in `article.entity`, which IS a
   container — but re-cutting this as a container query is a re-measurement at
   eight widths on the merged page, not an edit.
```

Second, the `.doc table` comment (pre-branch `render.py:11753-11759`). Replace:

```
   Here and not beside the other `.doc` rules because those are written twice,
   once in `_DETAIL_STYLE` and once in `_RECORD_STYLE`, and a third copy of a
   border is a third place for two pages to disagree about what a table is. This
   stylesheet is loaded by every page that shows a document.
```

with:

```
   Here and not beside `_DETAIL_STYLE`'s other `.doc` rules because this
   stylesheet is loaded by every page that shows a document — which is what kept
   this at one copy while the record pages still carried a `.doc` sheet of their
   own, and is still the reason a second copy would be a place for two pages to
   disagree about what a table is.
```

- [ ] **Step 4: Rewrite the `_EDITING_STYLE` header and its full-page media query comment.**

The header (pre-branch `render.py:14658-14680`) argues in the present tense about `_ISSUE`, `_NOTE` and `_RECORD_STYLE`, and says "both stylesheets" when only one now exists. Replace its first two paragraphs and the first line of the third:

```python
# The editing surface, in one place, because two pages draw it and it was drawn
# twice. `_DETAIL` (with `_NEW`) put the mode class on `article.entity`; `_ISSUE`
# and `_NOTE` put it on `<body>` and kept their own copies of `.bodybar` and
# `.body-field` in `_RECORD_STYLE` — so the toolbar, the box and the two bars
# either side of it were two declarations of one thing, and only one of them ever
# got a fix. `tests/test_issues.py` exists because one of those copies once lost
# a specificity fight `.field` against `.bodybar` and put the textarea on the same
# line as the buttons.
#
# **Which way the unification goes is decided by a structural fact, not a
# preference.** The detail template is rendered once per entity and the static
# export puts every entity in ONE document, so "is this being edited" is a
# property of an article and cannot be a class on `<body>`; a record page holds
# exactly one record, so it can be either. So the record pages move to the
# article and this block is written against `.entity.editing` once.
#
# Concatenated at the END of both stylesheets, and that is load-bearing rather
```

with:

```python
# The editing surface, in one place, because it was once drawn twice. Before the
# record pages folded into `_DETAIL`, `_ISSUE` and `_NOTE` put the mode class on
# `<body>` and kept their own copies of `.bodybar` and `.body-field` — so the
# toolbar, the box and the two bars either side of it were two declarations of
# one thing, and only one of them ever got a fix: the note page had the hill and
# the issue page a bare `<select>`, in the same commit, by the same author. That
# is what a second surface does, and it is why there is no second surface.
#
# **Which way the unification went was decided by a structural fact, not a
# preference.** The detail template is rendered once per record and the static
# export puts every record in ONE document, so "is this being edited" is a
# property of an article and cannot be a class on `<body>`. This block is
# written against `.entity.editing` once.
#
# Concatenated at the END of the stylesheet, and that is load-bearing rather
```

(The rest of the third paragraph — the `(0,1,1)` tie argument through "Resolved with `tests/cascade.py` rather than guessed at." — is still true and stays. If Task 8's test rewrite kept a renamed descendant of `tests/test_issues.py`, you may cite it in the first paragraph instead of the #67 sentence; do not cite a file that no longer exists.)

Then the full-page media query comment inside the same block (pre-branch `render.py:14999-15008`). Replace:

```
   `@media` and not `@container`, for the reason the `.marks` block gives at
   length: the only `container-type: inline-size` in this file is in
   `_DETAIL_STYLE`, and the note and issue pages ship `_RECORD_STYLE` and never
   load it — a container query here would never match on two of the four pages
   that draw this surface. On this element the viewport is not a proxy for the
   container anyway: the surface IS the window.
```

with:

```
   `@media` and not `@container`, and on this element that is not even a proxy
   argument: the surface is `position: fixed; inset: 0`, so the viewport IS the
   window this rule is about. (It also predates the merged record page — the
   issue and note pages once shipped a stylesheet with no `container-type` in
   it, and a container query here would never have matched there.)
```

- [ ] **Step 5: Rewrite the `.doc blockquote` comment in `_DETAIL_STYLE`.**

Pre-branch `render.py:15207-15213`. Replace:

```
/* Where a promoted record says where it came from. It is the first thing in the
   document and it is not part of the problem statement, so it is set apart
   rather than left as an indented paragraph that reads like one. Here as well as
   in `_RECORD_STYLE`: this is the page those lines are mostly read on, and a
   rule in the other file is a rule this page never loads. The two are the same
   declaration on the same selector, so there is no cascade to resolve — no page
   loads both. */
```

with:

```
/* Where a promoted record says where it came from. It is the first thing in the
   document and it is not part of the problem statement, so it is set apart
   rather than left as an indented paragraph that reads like one. One copy now:
   the record pages kept a second, identical declaration for as long as they had
   a stylesheet of their own, and it went with the stylesheet. */
```

- [ ] **Step 6: Rewrite the four test docstrings still arguing the two-page world.**

Task 8 edits these tests' bodies — the URLs, the fixtures, the loops — and leaves their prose; without this step the Step 14 sweep can never come back empty. Same rule as Steps 3–5: past tense, and never as a claim about a live symbol.

**(a)** `tests/test_editor.py` — the toolbar-at-a-width test whose body Task 8 Step 17 repointed from `/note/new` to `/new?kind=note` (pre-branch `:5349`). Its docstring's final paragraph (pre-branch `:5342-5347`) reads:

```
    A media query and not a container query. The file's only
    `container-type: inline-size` is on `article.entity` inside `_DETAIL_STYLE`,
    and the note and issue pages ship `_RECORD_STYLE + _SUGGEST_STYLE` and never
    load it — which is why this is parametrised over both surfaces. A container
    query was patched in and measured byte-identical to no fix at all here.
    """
```

Replace with:

```
    A media query and not a container query, proved in the days when the note
    and issue pages shipped a stylesheet with no `container-type` in it — a
    container query was patched in and measured byte-identical to no fix at all
    there. Both parametrised URLs now draw the one merged surface, so the
    parametrisation survives as reading against creating rather than page
    against page.
    """
```

**(b)** `tests/test_cascade.py`, `test_the_record_pages_bar_still_beats_the_field_rule_it_once_lost_to` (pre-branch `:946-954`). Its `record` fixture is the merged page since Task 8, so "concatenated after `_RECORD_STYLE`" names the wrong file. Replace the docstring with:

```
    """The fight the old issue-page suite was written for, re-resolved after the
    mode class moved off `<body>` and onto the article — and now asked of the
    one stylesheet there is, because the `record` fixture is the merged page.

    `.entity.editing .field` and `.entity.editing .bodybar` are both (0,2,1), so
    the tie is decided by order and nothing else — which is why the answer has to
    be asked rather than assumed. The bar wins because `_EDITING_STYLE` is
    concatenated after `_DETAIL_STYLE`; and the markup carries no `.field` on the
    bar either, so the tie does not arise on the page as it is written. Both
    halves, because either one alone is a guard somebody can remove.
    """
```

**(c)** `tests/test_cascade.py`, `test_a_hidden_control_stays_hidden_on_both_of_the_two_stylesheets` (pre-branch `:1033-1043`; Task 8 Step 17 dropped its `("issue", record)` loop pair). The name and the docstring both claim two stylesheets. Rename it `test_a_hidden_control_stays_hidden_while_editing` and replace the docstring with:

```
    """`[hidden] { display: none }` is the UA sheet's, and an author rule of any
    weight beats it. `_DETAIL_STYLE` carries the guard that puts it back; the
    record pages' own stylesheet once lacked it, so the rendered pane — a
    `.field`, `hidden` until a view asks for it — would have been drawn there
    the moment those pages gained one. The stylesheet went with the pages; one
    guard, one surface, asked directly.
    """
```

**(d)** `tests/test_cascade.py`, `test_the_handle_between_the_panes_is_the_same_control_on_both_stylesheets` (pre-branch `:1056-1065`; same loop drop in Task 8 Step 17). Rename it `test_the_handle_between_the_panes_resolves_on_the_one_stylesheet` and replace the docstring's opening (through "so both halves have to be" and the remainder of that sentence) with:

```
    """The splitter, resolved where it lives now. It used to be resolved against
    `_RECORD_STYLE` as well as `_DETAIL_STYLE`, because `render_issue` and
    `render_note` emitted `_SPLIT_HANDLE` into the same `.bodysplit` the detail
    page does — and a second copy of the editing rules under a different mode
    class is the failure mode this file exists for: a rule that wins on one page
    can lose on the other and nothing between them says so. Those pages and
    their stylesheet are gone; what this keeps is the resolution on the
    survivor.
    """
```

Then re-run the Step 1 grep. It must return nothing. If a further prose mention has appeared somewhere Tasks 3–8 wrote, rewrite it the same way: past tense, and never as a claim about a live symbol.

- [ ] **Step 7: Remove the `STATUSES` hand copy — whichever of three states Tasks 3 and 8 left it in.**

Run:

```bash
grep -rn "STATUSES" src/openproj/ tests/
```

Pre-branch the copy is `render.py:15285`:

```python
STATUSES = ("shaping", "ready", "in_progress", "done", "shelved")
```

with twelve readers in `render.py` pre-branch (`_status_class:264`, the table payload `choices` at `:1212`, the timeline CSS rules at `:9616-9630`, `_control_html:12040`, `HILL_LADDERS:15360`, `_by_status:19606`, and four `statuses=STATUSES` template arguments) plus ~20 test uses (`tests/test_render.py`, `tests/test_hill.py:40,97,99`). Task 3 retires the readers that hardcode the entity ladder; Task 8 Step 13 rewrote `_by_status` to read `_TOC_LADDER`, and Task 8 Step 17 moved the grouping test off the `STATUSES` import. Run the grep and act on what is actually left. Three possible states, one action each:

1. **The definition is gone** — earlier tasks finished the job. Do nothing.
2. **The definition survives with zero readers** — delete the one line. (Ruff will not flag an unused module-level tuple; this step is the only thing that removes it.)
3. **The definition survives with readers** — do not sweep the surviving call sites in a cleanup commit. Replace the literal with the model's tuple so the five words exist **once**:

   ```python
   # The plan ladder, under the name this file and its tests have always read it
   # by. Not a copy: a copy is how a sixth word could exist here and not in
   # `model.py`, or there and not here, with nothing failing either way.
   STATUSES = STATUS_ORDER
   ```

   and add `STATUS_ORDER` to the existing `from .model import (...)` block at `render.py:47-66` (alphabetical, after `RUNG`). The tuples are equal today — `model.py:1714` spells the same five words — so behaviour is identical and every reader, test or code, is untouched.

- [ ] **Step 8: The way back tells the truth.**

The toc heading is already done: Task 8 Step 12(f) rewrote it to `<h1>Every record in this plan</h1>` in the commit that made the old words false — do not touch it here (Step 14's grep verifies it stuck). What is left is the back link four lines down (pre-branch `render.py:13131-13136`), which Task 7's hardcoded-`/` audit left for this commit by name ("commit 9 may re-word") — **if a previous task has not already retargeted it** (grep for `all entities` first; skip if gone). Replace:

```
  {#- Back to the table, which is where you came from and where everything is.
      It pointed at the detail index, which was the same list with none of the
      controls — and that index is no longer in the nav, so a link to it now
      lands somewhere a reader has no other route to. -#}
  <p class="back"><a href="{{ links.table }}">← all entities</a></p>
```

with:

```
  {#- Back to Records, which is where you came from and where every record is.
      It pointed at the table once — a list a note or an issue never appears on,
      so for two of the six kinds "back" led somewhere the record just read
      does not exist. -#}
  <p class="back"><a href="{{ links.records }}">← all records</a></p>
```

`links.records` is Task 7's `Links` attribute. The copy rule holds: the control names the page it goes to, and "Records" is the nav's own word for it. No test pins the old text (`grep -rn "all entities" tests/` is empty pre-branch), so this needs no test edit.

- [ ] **Step 9: Reconcile the grouping key with the test that measures it — a check by reading, not an edit.**

Task 8 Step 17 already repointed the three `tests/test_render.py` assertions this branch changes: the heading pin in `test_the_detail_page_names_each_document_it_holds`, the `listing` string in `test_a_heading_that_repeats_the_nav_is_announced_and_not_drawn`, and the full rewrite of `test_the_index_is_grouped_in_the_order_work_moves` over `_TOC_LADDER`. None of those is this commit's to redo. What this commit owes is one reconciliation, checked against what Task 8 actually shipped rather than what it planned:

Read `_detail_rows` (the `"status":` key in its row dict) and the shipped `test_the_index_is_grouped_in_the_order_work_moves` side by side. Task 8 Step 12(a) keeps the **stored** word — `entity.status` — as the grouping key, with the derived `state()` on the fact row, and its Step 17 test reads `r.status` over `seed_index.records.values()` to match. If both say `status`, or both say `state(...)`, this step is done: the test measures the same value the page groups by. If they disagree — Task 8's implementer switched the grouping key to `entity.state(index.records)` but left the test on `r.status`, or the reverse — fix the **test's two expressions** in this commit to read what the page actually groups by (`r.state(seed_index.records)` in both places, or `r.status` in both), and say so in the commit message. `_TOC_LADDER` covers either choice; that is what `promoted` is in it for.

- [ ] **Step 10: README — the tabs paragraph, in the same voice.**

jcanton asked for this sentence explicitly. In `README.md`, replace the paragraph at lines 22-28:

```markdown
The tabs are the same records seen several ways: **Table** is the one people live in, **Graph** is
the dependency diagram, where dependencies are drawn and removed in a mode of its own, **Timeline** the derived Gantt, **Cycles** one page per cycle with its bets
and its capacity, **People** who is on what and who is full, **Issues** the pile of things somebody
noticed, **Notes** the pile of things somebody is still thinking about. Every filter is in the URL,
so a view is a link, and a field can be asked for more than one value at a time — two statuses means
either of them. Pointing at a row, a node or a bar opens the same card in all three: what the record
is, who is on it, when it runs, and its shaping document under a rule.
```

with:

```markdown
The landing page is **Records** — every record in the plan, one line each, sorted by last edited,
with the search box above it. It is how you get back to the thing you were writing yesterday. The
PM work happens in the tabs, which are the same records seen several ways: **Table** is the one
people live in, **Graph** is the dependency diagram, where dependencies are drawn and removed in a
mode of its own, **Timeline** the derived Gantt, **Cycles** one page per cycle with its bets and
its capacity, **People** who is on what and who is full. Every filter is in the URL, so a view is a
link, and a field can be asked for more than one value at a time — two statuses means either of
them. Pointing at a row, a node or a bar opens the same card in all three: what the record is, who
is on it, when it runs, and its shaping document under a rule.
```

And the inbox paragraph at lines 38-44:

```markdown
The last two are inboxes rather than views of the plan, and they are two because they answer
different questions: an issue is "we found something existing that is broken", a note is "we are
thinking of creating something that does not exist and our ideas are confused". Neither carries an
appetite or an owner and neither appears on the table, the graph or the timeline. **Promote** is
what stops either from being an inbox nobody empties: it turns a note into a project, a pitch or a
task, and an issue into a pitch or a task — in one commit, and the new record says in its own
shaping document where it came from.
```

becomes:

```markdown
The two inboxes — issues and notes — are records like any other now, with the same page and the
same editor, and they are two because they answer different questions: an issue is "we found
something existing that is broken", a note is "we are thinking of creating something that does not
exist and our ideas are confused". Neither carries an appetite or an owner and neither appears on
the table, the graph or the timeline; they live on Records and on their own pages. **Promote** is
what stops either from being an inbox nobody empties: it turns a note into a project, a pitch or a
task, and an issue into a pitch or a task — in one commit, and the new record says in its own
shaping document where it came from.
```

The search-language paragraph between them (lines 30-36) stays word for word: it was already written about "a record's fields" and is now true of two more kinds.

- [ ] **Step 11: AGENTS.md — one word in the intro; the invariants themselves survive.**

Checked "The invariants" line by line against the branch: `depends_on`/`blocks`, derived-data-never-in-frontmatter, parse-permissively, `readable`, `record_paths_in`, grandfathering, `_status_class`, the colour blocks, no-npm, and the bot's `derived/` are all still stated correctly — none of them ever asserted the issue/note exclusion, which lived in `model.py`'s docstring and `docs/data-model.md` (fixed in Task 8 and Step 13 respectively). The one stale word is the intro (line 4). Replace:

```markdown
Git-backed appetite planning for the icon4py team. `README.md` has the shape of the thing: one
markdown file per entity, the shaping document *is* the record, every date derived from one typed
```

with:

```markdown
Git-backed appetite planning for the icon4py team. `README.md` has the shape of the thing: one
markdown file per record, the shaping document *is* the record, every date derived from one typed
```

"Entity" now names the class and, in `Index.entities`, the plan-only subset — a sentence about every file on disk should use the superset word, which is the same argument that named the landing page.

- [ ] **Step 12: docs/architecture.md — "The pages" describes pages that exist.**

Two statements are now false: line 5 ("`index.html` is a filterable, searchable table") — `index.html` is Records and the table is `table.html` since Task 7 — and lines 12-17 ("Neither an issue nor a note is an entity … They share a stylesheet and one `attachRecordTable` … they do not share a template"), whose type, stylesheet, script and templates were all deleted in Task 8, and whose exclusion mechanism is now the planned-kinds inversion. `POST /api/promote` is still the door out; keep that sentence. Replace the first two paragraphs of "The pages" (lines 5-17):

```markdown
`index.html` is a filterable, searchable table and the one people live in. `graph.html` is the
dependency DAG, grouped by project and pitch. `timeline.html` is the derived Gantt. `cycles.html`,
`people.html`, `issues.html` and `notes.html` are the cycle records with their betting tables, who
is on what and who is full, the pile of things somebody noticed and the pile of things somebody is
still thinking about; `detail.html` is one record on its own page, and under the server it is also
where a record is edited.

The last two are inboxes rather than views of the plan. Neither an issue nor a note is an entity, so
neither reaches the table, the graph, the timeline or the people page — by construction, because
nothing there ever sees one. They share a stylesheet and one `attachRecordTable`, because they are
the same table over two kinds of record; they do not share a template, because the records differ
and are meant to. `POST /api/promote` is the door out of both: it writes the entity and marks the
source in one commit.
```

with:

```markdown
`index.html` is **Records**, the landing page — every record in the plan, one line each, sorted by
last edited, with the same search box every view carries. `table.html` is the filterable,
searchable table and the page PM work lives in. `graph.html` is the dependency DAG, grouped by
project and pitch. `timeline.html` is the derived Gantt. `cycles.html` and `people.html` are the
cycle records with their betting tables, and who is on what and who is full; `detail.html` is one
record on its own page — any of the six kinds — and under the server it is also where a record is
edited.

Issues and notes are records whose rung says `planned=False`: they are on Records and on their own
pages, and never in the plan views. The exclusion is not a filter on each page — `Index.entities`
holds planned kinds only, a validator on `Index` refuses anything else, and a page that wants every
kind reaches for `Index.records` by name, a word that looks wrong in a function about the timeline.
`POST /api/promote` is the door out of both inboxes: it writes the entity and marks the source in
one commit.
```

The following paragraph ("They render from one in-memory index…") stays: it is true of all the pages.

- [ ] **Step 13: docs/data-model.md — the statements that are now false, each fixed in place.**

Reading the whole file against the branch, exactly five passages are wrong; everything else (the flat-directory rule, sizes, dependencies, required fields, cycles, people, the shaping document) survives verbatim.

**(a) Lines 3-5** — "Four kinds" and "one markdown file per entity". Replace:

```markdown
One markdown file per entity: YAML frontmatter, then the shaping document as the body. Four kinds —
`product`, `project`, `pitch`, `task` — with ids like `pitch-a3f81c`, where the prefix must agree
with the kind (`prod`, `proj`, `pitch`, `task`).
```

with:

```markdown
One markdown file per record: YAML frontmatter, then the shaping document as the body. Six kinds —
`product`, `project`, `pitch`, `task`, `issue`, `note` — with ids like `pitch-a3f81c`, where the
prefix must agree with the kind (`prod`, `proj`, `pitch`, `task`, `issue`, `note`).
```

**(b) Lines 7-12** — the rung property list gains Task 1's two fields, and "a fifth kind" is arithmetic. Replace:

```markdown
They are one list, in one place: `KINDS` in `model.py`, coarsest first. Each rung says what its ids
start with, where its files live, what it may be filed under, and whether it is scheduled, may
depend on anything, carries an appetite, or has a shaping document to show. Everything else — the
directories the loader walks, the id pattern, the parent rules, the filter menus, the create form —
is derived from that table, so a fifth kind is an entry in it rather than a search for the places
`project` was written down.
```

with:

```markdown
They are one list, in one place: `KINDS` in `model.py`, coarsest first. Each rung says what its ids
start with, where its files live, what it may be filed under, whether it is scheduled, may depend
on anything, carries an appetite, or has a shaping document to show — and whether it appears in the
plan at all, and which words its `status` may take. Everything else — the directories the loader
walks, the id pattern, the parent rules, the filter menus, the create form, the plan's views — is
derived from that table, so a seventh kind is an entry in it rather than a search for the places
`project` was written down.
```

**(c) Lines 54-61** — the separate-type argument, which Task 2 deliberately inverted. Replace:

```markdown
An **issue** is stored beside these and is deliberately not one of them. An entity is a bet: it
carries an appetite, takes a place on the timeline and charges somebody's cycle. An issue is the
opposite — most of them will never be worked on, which is the point of having somewhere to put them.
Keeping it a separate type is what holds it off the table, the graph, the people page and the
timeline by construction, rather than by an exclusion in each of them that somebody later forgets.
It has no `shaping` status, because a shaped issue is a pitch, and that is its whole lifecycle:
somebody reads the open issues at the betting table and writes a pitch for what matters. What it was
pitched into is stored on the issue and in that direction only.
```

with:

```markdown
An **issue** is the fifth rung, and `planned=False` is the whole of what makes it different in
kind. A planned record is a bet: it carries an appetite, takes a place on the timeline and charges
somebody's cycle. An issue is the opposite — most of them will never be worked on, which is the
point of having somewhere to put them. What holds it off the table, the graph, the people page and
the timeline is no longer a separate type: `Index.entities` holds planned kinds only, filtered once
in `build_index` and asserted by a validator on `Index`, so a view that is forgotten sees fewer
records, never more — it fails closed. A view that wants every kind reaches for `Index.records` by
name. An issue has no `shaping` status, because a shaped issue is a pitch, and that is its whole
lifecycle: somebody reads the open issues at the betting table and writes a pitch for what matters.
What it was pitched into is stored on the issue and in that direction only.
```

**(d) Lines 73-75** — "the notes page" no longer exists. Replace:

```markdown
So a note has **no appetite, no owner, no size, no cycle and no dependencies**, and it is on the
notes page and nowhere else. It carries a title, a body, `written_by` — who to ask, not who owns it
— `written_on`, `tags`, and `became`.
```

with:

```markdown
So a note has **no appetite, no owner, no size, no cycle and no dependencies**, and — `planned=False`,
the same exclusion an issue gets — it is on Records and its own page, and nowhere in the plan. It
carries a title, a body, `written_by` — who to ask, not who owns it — `written_on`, `tags`, and
`became`.
```

**(e) Lines 92-97** (in "Promotion") — "keeping notes out of `Entity`" is no longer the mechanism. Replace:

```markdown
- **The new record says where it came from in its own shaping document**, in prose, above
  everything. Not a field: a `from_note` on `Entity` would put a note id into the type every view
  of the plan is built from, and the table, the graph and the detail page would each have to decide
  what to do with it — which is the coupling that keeping notes out of `Entity` exists to prevent.
  So "where did this pitch come from" is answerable from the pitch alone, in `git show`, with no
  index and no server.
```

with:

```markdown
- **The new record says where it came from in its own shaping document**, in prose, above
  everything. Not a field: a `from_note` on every planned kind would put a note id into the rows
  the table, the graph and the timeline are built from, and each would have to decide what to do
  with it — which is the coupling that keeping notes out of the plan exists to prevent. So "where
  did this pitch come from" is answerable from the pitch alone, in `git show`, with no index and no
  server.
```

- [ ] **Step 14: The closing sweep, then lint.**

```bash
grep -rn "_RECORD_STYLE" src/ tests/                      # must be empty
grep -rn "Every entity in this plan" src/ tests/          # must be empty — verifies Task 8's heading edit stuck
grep -rn "issues.html\|notes.html" docs/ README.md        # must be empty
grep -rn "not an Entity\|separate type" docs/ README.md   # must be empty
uv sync
uv run ruff check .
```

The first grep is the deletion's own guard beyond CI: any reference this commit missed is an undefined name, and ruff's F821 reports it here, before anything is pushed. Do **not** run pytest — not one file. The suite is CI's.

- [ ] **Step 15: Commit and push; CI is the red/green gate.**

No new tests, by design, and here is why that is safe. A surviving loader of `_RECORD_STYLE` is caught three times over: ruff F821 in Step 14, an immediate `NameError` importing `openproj.render` (which fails every test at collection), and Step 1's grep having refused to let Step 2 run at all. The style rules it carried are covered by the merged page's own guards — Task 8's rewritten cascade suite resolves `_DETAIL_STYLE + _EDITING_STYLE` on the one surface that exists, and `test_the_app_moves_in_two_places` is unaffected because `_RECORD_STYLE` carried no animation. The toc heading, the toc ladder and their three test pins all landed in Task 8 (Steps 12(f), 13 and 17); this commit does not touch that behaviour, and Step 9's reconciliation is a read, not an edit, unless it found a mismatch. The `STATUSES` unification is covered by every test that imports the ladder, which now resolves to `model.STATUS_ORDER` through one name or none. The back-link retarget is one `href` and one Jinja comment, pinned by no test and needing none — CI renders `detail.html` on every page test, so a bad `links.records` reference fails loudly. README, AGENTS.md and the two docs have no tests — the closing greps in Step 14 are their check.

```bash
git add src/openproj/render.py tests/test_cascade.py tests/test_editor.py \
        README.md AGENTS.md docs/architecture.md docs/data-model.md
# add tests/test_render.py to the list above ONLY if Step 9 found a mismatch and edited it
git commit -m "$(cat <<'EOF'
The second record surface is gone

The merge landed with the fork's leftovers still in the tree: a stylesheet
nothing loads (_RECORD_STYLE dressed the four deleted issue and note pages
and nothing else), five comments and four test docstrings describing those
pages in the present tense, a hand copy of the status ladder, and a
detail-page back link that still pointed at the table — a list a note or an
issue never appears on, so for two of the six kinds "back" led somewhere
the record just read does not exist.

The prose was wrong in the same direction. README and docs/architecture.md
still described Issues and Notes as tabs with hand-built pages, and
docs/data-model.md still argued the exclusion from a separate type, when
what enforces it now is Index.entities holding planned kinds only under a
validator, with Index.records the deliberate, greppable superset.

So: the stylesheet is deleted, the ladder copy resolves to model.py's five
words or is gone, the comments and docstrings say what was true rather than
what is, the back link goes to Records, and the four documents describe the
tool that exists — the landing page is Records, and Table, Graph and
Timeline are where the PM work happens.

🤖 Written by an agent on behalf of @jcanton
EOF
)"
git push -u origin one-record-one-page
gh pr checks --watch   # read CI; a red here is fixed with a new commit, never an amend
```

(Watch the heredoc: the footer line is the last line of the message and sits INSIDE the heredoc — `EOF` closes after it, never before, or the footer becomes a shell command instead of part of the message. No `Co-Authored-By` or `Claude-Session` trailers — if your tooling appends them, strip them before pushing.)


---

🤖 Written by an agent on behalf of @jcanton
