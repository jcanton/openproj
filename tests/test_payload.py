"""What a page carries has to be JSON, and not merely something `json.dumps` wrote.

The two ends of every page here disagreed about what a payload was. Python's
encoder writes `Infinity`, `-Infinity` and `NaN` for the three non-finite floats
— they are JavaScript literals, not JSON — and every block on every page is read
back with `JSON.parse`, which refuses all three. So one `person_weeks: .inf`
edited into a file by hand answered 200 with a complete-looking page whose table
said "The plan could not be loaded. This page arrived without its data", blaming
the network for a number, and `/api/index.json` answered 500 to every reader.

A string search of the served HTML is not enough to see this and is not enough to
prove it fixed: the markup is byte-for-byte a normal page either way, and the
difference is entirely in whether one line of JavaScript threw. So the claim is
asked of Chrome — do the rows appear — and of the JSON route, which is the other
consumer. The unit test underneath them says which characters came out, because
when the browser test fails that is the question you want answered first.

Where a non-finite number comes from: not from the write routes, which refuse
`Infinity` at both doors. From a file somebody edited in git, which the whole
store is built to keep working — `Cycle._last_day` and `within_the_calendar`
already clamp the arithmetic so the pages render. It was only the trip out that
had no way to say it.
"""

from __future__ import annotations

import json
import math
from datetime import date
from pathlib import Path

import pygit2
import pytest
from fastapi.testclient import TestClient
from test_store import commit_directly

from openproj.index import build_index
from openproj.model import (
    CALENDAR_DAYS,
    Config,
    parse_text,
    what_json_can_carry,
    within_the_calendar,
)
from openproj.render import STATIC, render_graph, render_table
from openproj.render.tokens import _percent
from openproj.web import create_app

ORDINARY = (
    "---\nid: task-e00001\nkind: task\ntitle: An ordinary task\n"
    "status: ready\nperson_weeks: 1\nstart_date: 2026-09-01\n---\n\nBody.\n"
)
HAND_EDITED = (
    "---\nid: task-e00002\nkind: task\ntitle: A size somebody typed into a file\n"
    "status: ready\nperson_weeks: {size}\nstart_date: 2026-09-01\n---\n\nBody.\n"
)

# The three spellings YAML has for a number that is not one. `.nan` matters as
# much as `.inf`: it has no nearest representable value at all, so a fix that
# clamped instead of nulling would still have left the page unparseable.
NOT_NUMBERS = (".inf", "-.inf", ".nan")


def index_with(*texts: str):
    records = [parse_text(text, f"tasks/task-{n}.md") for n, text in enumerate(texts)]
    return build_index(records, Config(schema_version=2), date(2026, 8, 17))


def plan_repo(tmp_path: Path, size: str) -> Path:
    path = tmp_path / "plan.git"
    pygit2.init_repository(str(path), bare=True, initial_head="main")
    commit_directly(
        path,
        {
            "config/defaults.yaml": "schema_version: 2\n",
            "tasks/task-e00001.md": ORDINARY,
            "tasks/task-e00002.md": HAND_EDITED.format(size=size),
        },
        "a size somebody edited by hand",
    )
    return path


# --------------------------------------------------------------------------- #
# The unit: what came out
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("value", (math.inf, -math.inf, math.nan))
def test_a_number_json_cannot_hold_leaves_as_null(value: float):
    assert what_json_can_carry({"size": value}) == {"size": None}


def test_a_number_json_can_hold_is_left_exactly_alone():
    """Including the shapes a payload is actually made of, and including zero and
    the negatives — a walk written with a truthiness test drops all three."""
    payload = {"rows": [{"size": 0.0, "cycle": -2, "on": False, "why": None}], "n": 1e308}

    assert what_json_can_carry(payload) == payload


@pytest.mark.parametrize("size", NOT_NUMBERS)
@pytest.mark.parametrize("page", (render_table, render_graph))
def test_no_page_ships_a_data_block_that_is_not_json(page, size: str):
    """Read back with a JSON parser rather than searched for a word.

    Searching for `Infinity` would pass over `NaN`, and both would pass over
    whatever the next non-JSON literal turns out to be. The question is not which
    characters are absent, it is whether a JSON parser accepts the block — which
    is the same question the page's own script asks.
    """
    rendered = page(
        index_with(ORDINARY, HAND_EDITED.format(size=size)), STATIC, base_commit="deadbee"
    )

    blocks = [text for text in rendered.split('type="application/json">')[1:]]
    assert blocks, "the page shipped no data block at all, so this proved nothing"
    for block in blocks:
        # `<` and friends are what `_json` writes for the characters that
        # could end the script element; a JSON parser reads them straight back.
        json.loads(block.split("</script>")[0])


# --------------------------------------------------------------------------- #
# The medium: whether the rows appear in a browser
# --------------------------------------------------------------------------- #


_ROWS = """
  const block = document.getElementById('payload');
  let parses = false;
  try { JSON.parse(block.textContent); parses = true; } catch (e) { parses = false; }
  return {
    parses,
    // Every row but the last one, which is the `+` control rather than a record.
    // `:not(.adder)` and not `tr[data-id]`: a row that lost its id is exactly
    // what this is watching for, and selecting on the attribute would hide it.
    ids: [...document.querySelectorAll('#rows tbody tr:not(.adder)')].map(r => r.dataset.id || ''),
    text: (document.querySelector('#rows') || document.body).innerText,
  };
"""


@pytest.mark.parametrize("size", NOT_NUMBERS)
def test_a_size_somebody_hand_edited_does_not_empty_the_table(size: str, tmp_path: Path):
    """The rows are drawn by the page's own script from the block above it.

    So this cannot be asked of the HTML: the served markup has a full `<thead>`
    and an empty `<tbody>` whether the payload parses or not, and the difference
    only exists after a browser has run the script. When it did not parse the
    page fell to its "arrived without its data" state — which is a true sentence
    about a truncated response and a false one about a plan that is entirely
    present, and the reader is told to check their connection over one character
    in one file.
    """
    from browser import chrome, measured_in

    page = render_table(
        index_with(ORDINARY, HAND_EDITED.format(size=size)),
        STATIC,
        base_commit="deadbee",
        may_write=True,
    )

    got = measured_in(chrome(), page, tmp_path / f"size-{size}.html", 1400, _ROWS)

    assert got["parses"], f"the payload is not JSON with a size of {size}"
    assert sorted(got["ids"]) == ["task-e00001", "task-e00002"], (
        f"with a size of {size} the table drew {got['ids']}, and says: {got['text']!r}"
    )
    assert "could not be loaded" not in got["text"], (
        f"the page blamed the trip for a size of {size}: {got['text']!r}"
    )


# --------------------------------------------------------------------------- #
# The other consumer: the JSON route
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("size", NOT_NUMBERS)
def test_the_index_route_answers_rather_than_faulting_on_such_a_size(size: str, tmp_path: Path):
    """`JSONResponse` encodes with `allow_nan=False`, so this raised inside the
    encoder — after the response object existed, which is a 500 in `text/plain`
    on the one route whose readers are all scripts."""
    with TestClient(create_app(plan_repo(tmp_path, size), auth="dev")) as client:
        got = client.get("/api/index.json")

        assert got.status_code == 200, got.text
        records = got.json()["plan"]
        assert set(records) == {"task-e00001", "task-e00002"}
        # Null, not a clamp: JSON has no way to say this number, and every page
        # already draws an absent one as a dash. A clamp would put a figure
        # nobody wrote into a cell.
        assert records["task-e00002"]["person_weeks"] is None
        assert records["task-e00001"]["person_weeks"] == 1.0


@pytest.mark.parametrize("size", NOT_NUMBERS)
def test_every_page_still_serves_when_a_file_carries_such_a_size(size: str, tmp_path: Path):
    """`-.inf` is the one that was still a 500 on every page, and it is the reason
    this is parametrised rather than written once about `.inf`.

    `within_the_calendar` bounded the top of the range and not the bottom, so a
    negative infinity walked through the guard and reached `math.ceil` — the same
    OverflowError, out of the same function, off the same kind of hand-edited
    file. The value that was found got fixed; the range it was one end of did not.
    """
    with TestClient(create_app(plan_repo(tmp_path, size), auth="dev")) as client:
        for route in (
            "/",
            "/graph",
            "/timeline",
            "/people",
            "/cycles",
            "/detail",
            "/detail/task-e00002",
            "/api/index.json",
        ):
            assert client.get(route).status_code == 200, f"{route} with a size of {size}"


@pytest.mark.parametrize(
    "value,expected",
    (
        (math.inf, CALENDAR_DAYS),
        (-math.inf, -CALENDAR_DAYS),
        # NaN loses every comparison, so it lands wherever the constants are
        # written. What matters is that it lands on a number at all.
        (math.nan, CALENDAR_DAYS),
        (0.0, 0.0),
        (-5.0, -5.0),
        (5.0, 5.0),
    ),
)
def test_the_calendar_bound_holds_at_both_ends(value: float, expected: float):
    assert within_the_calendar(value) == expected
    # The property the callers actually depend on, stated as itself: whatever
    # comes back can be rounded and ceilinged without raising. Asserted as a
    # type rather than as truthiness — a bound of 0 is a legitimate answer and
    # `assert math.ceil(...)` would have called it a failure.
    assert isinstance(math.ceil(round(within_the_calendar(value))), int)


# --------------------------------------------------------------------------- #
# The rest of the sweep: the values that never reached JSON at all
#
# `what_json_can_carry` above is the trip OUT, and it was only ever half of this.
# The other half is the values a page prints, a template rounds and `openproj
# check` is silent about — five of which answered 500 on `main` under a green
# suite of 2400. Three were fixed on the calendar branch; what is below is the
# rest of it, and the corpus it is asked of carries all three kinds at once:
# `.inf` in a config file, `.inf` in a cycle and `.nan` on a task.
# --------------------------------------------------------------------------- #


_SETUP = (
    "---\ncycle: 37\nstarts_on: 2026-08-17\nreviews_on: 2026-09-14\n"
    "availability:\n  ann: {rate}\n  bo: 0.5\n---\n\nThe goal.\n"
)
_PITCH = (
    "---\nid: pitch-e00001\nkind: pitch\ntitle: A pitch with tasks under it\n"
    "status: in_progress\nperson_weeks: 2\ncycle: 37\nassignees: [ann]\n"
    "owner: ann\nreviewers: [bo]\n"
    "start_date: 2026-08-17\n---\n\n## Progress\n\n- [x] one\n- [ ] two\n"
)
_TASK = (
    "---\nid: task-e00003\nkind: task\ntitle: A task under that pitch\n"
    "status: ready\nparent: pitch-e00001\nperson_weeks: {size}\n"
    "owner: ann\nreviewers: [bo]\n"
    "assignees: [ann]\nstart_date: 2026-08-17\n---\n\nBody.\n"
)


def whole_plan(tmp_path: Path, size: str = "1", rate: str = "0.5", cooldown: str = "2.0") -> Path:
    """A plan with a cycle, a pitch, a task under it and a roster.

    Bigger than `plan_repo` above on purpose: the three sites this section is
    about are a cycle page, a record page and a deck, and none of those exists
    for a corpus of two loose tasks. Every one of the three bad values is a
    parameter, so one corpus builder covers the config file, the cycle and the
    record, and a test names which of them it is varying.
    """
    path = tmp_path / "whole.git"
    pygit2.init_repository(str(path), bare=True, initial_head="main")
    commit_directly(
        path,
        {
            "config/defaults.yaml": f"schema_version: 2\ncooldown_weeks: {cooldown}\n",
            "config/people.yaml": "known_people: [ann, bo]\n",
            "cycles/0037.md": _SETUP.format(rate=rate),
            "pitches/pitch-e00001.md": _PITCH,
            "tasks/task-e00003.md": _TASK.format(size=size),
        },
        "a plan somebody hand-edited",
    )
    return path


# --------------------------------------------------------------------------- #
# The unit: the one question, asked once
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "value,expected",
    (
        (math.inf, False),
        (-math.inf, False),
        (math.nan, False),
        (0.0, True),
        (-2.5, True),
        (7, True),
        (None, False),
        ("1.0", False),
        # `bool` is an `int` in Python, so a bare `isinstance(value, int | float)`
        # calls `True` a size of one week. A `person_weeks: yes` in a file is a
        # bool to YAML, and "one week" is not what anybody meant by it.
        (True, False),
        (False, False),
    ),
)
def test_a_number_is_asked_of_the_value_and_never_of_its_type(value: object, expected: bool):
    from openproj.model import a_number

    assert a_number(value) is expected


@pytest.mark.parametrize("size", NOT_NUMBERS)
def test_a_size_that_is_not_a_number_is_no_size_at_all(size: str):
    """`size_weeks` is where the record half of this is closed, and closing it
    there rather than at the fifteen places that print a week is the whole shape
    of the fix.

    None and not a clamp: None is the answer this function already had for a size
    nobody can use, and every caller already handles it — `_weighed` leaves such a
    record OUT of a rollup rather than counting it at zero, so a parent's
    percentage stays a true statement about the children whose weeks are known.
    """
    from openproj.model import size_weeks

    record = parse_text(HAND_EDITED.format(size=size), "tasks/task-e00002.md")

    assert size_weeks(record) is None
    assert size_weeks(parse_text(ORDINARY, "tasks/task-e00001.md")) == 1.0


@pytest.mark.parametrize("rate", NOT_NUMBERS)
def test_a_rate_that_is_not_a_number_falls_back_to_the_nominal_one(rate: str):
    """The cycle half, and the same shape: one place, not the fifteen readouts
    downstream of it.

    The nominal rate and not zero, because that is where this line already sent a
    rate of zero and somebody not on the roster at all — the scheduler cannot fix
    a planning mistake by refusing to produce a date.
    """
    from openproj.model import Config, parse_cycle_text

    cycle = parse_cycle_text(_SETUP.format(rate=rate), "cycles/0037.md")
    config = Config(nominal_availability=0.8)

    assert cycle.rate("ann", config.nominal()) == 0.8
    assert cycle.rate("bo", config.nominal()) == 0.5
    # And somebody nobody has named, which is the case the fallback was written
    # for and the one it must not have stopped answering.
    assert cycle.rate("nobody", config.nominal()) == 0.8
    # **A stated zero stays zero here**, which is the semantics `.get(who,
    # nominal)` had and which a guard written as `stated if a_number(stated) and
    # stated` quietly changes: somebody put in a cycle at no availability would
    # have started drawing a full-time capacity. The scheduler's floor is its
    # own, on top of this, because zero there is a division by zero.
    at_zero = parse_cycle_text(_SETUP.format(rate="0"), "cycles/0037.md")

    assert at_zero.rate("ann", config.nominal()) == 0.0
    assert at_zero.capacity("ann", config.nominal()) == 0.0


@pytest.mark.parametrize("nominal", (math.inf, -math.inf, math.nan, 0.0))
def test_a_nominal_rate_that_is_not_a_number_is_not_a_fallback(nominal: float):
    """A fallback that can itself be `.inf` is not a fallback — and
    `nominal_availability` is a hand-edited config value of exactly the same kind
    as the rates it stands in for.

    The field is left exactly as the file wrote it, because `unusable_numbers`
    has to be able to report it: a value repaired at parse time is a value nobody
    can be told about.
    """
    from openproj.model import Config

    config = Config(nominal_availability=nominal)

    assert config.nominal() == 1.0
    assert config.nominal_availability is nominal or math.isnan(config.nominal_availability)


# --------------------------------------------------------------------------- #
# What `openproj check` says, which used to be nothing at all
# --------------------------------------------------------------------------- #


def test_a_config_setting_that_is_not_a_number_is_named_by_path_and_field(tmp_path: Path):
    """The file, not just the field. The configuration is a merge of up to four
    files and a reader sent to the wrong one is worse off than a reader sent to
    none, which is why `read_config` records where each key came from at the
    moment it accepts it.
    """
    from openproj.model import load_repo, unusable_numbers

    _, config, _ = load_repo(_on_disk(tmp_path, cooldown=".inf"))

    found = unusable_numbers(config)

    assert [(one.path, one.field) for one in found] == [
        ("config/defaults.yaml", "cooldown_weeks")
    ], found
    assert "cool-down" in found[0].why, found[0].why


def test_a_cycles_availability_that_is_not_a_number_is_named_by_file_and_person(tmp_path: Path):
    from openproj.model import load_repo, unusable_numbers

    _, config, _ = load_repo(_on_disk(tmp_path, rate=".nan"))

    found = unusable_numbers(config)

    assert [(one.path, one.field) for one in found] == [("cycles/0037.md", "availability")], found
    assert "ann" in found[0].why and "nominal" in found[0].why, found[0].why


def _on_disk(tmp_path: Path, size: str = "1", rate: str = "0.5", cooldown: str = "2.0") -> Path:
    """The same plan as `whole_plan`, as a directory rather than a repository.

    `load_repo` walks a working tree and the server walks a commit; the values
    this section is about are in the files either way, so the cheaper of the two
    is used wherever the claim is not about serving.
    """
    root = tmp_path / "plan"
    for where, text in {
        "config/defaults.yaml": f"schema_version: 2\ncooldown_weeks: {cooldown}\n",
        "config/people.yaml": "known_people: [ann, bo]\n",
        "cycles/0037.md": _SETUP.format(rate=rate),
        "pitches/pitch-e00001.md": _PITCH,
        "tasks/task-e00003.md": _TASK.format(size=size),
    }.items():
        (root / where).parent.mkdir(parents=True, exist_ok=True)
        (root / where).write_text(text, encoding="utf-8")
    return root


@pytest.mark.parametrize("size", NOT_NUMBERS)
def test_a_size_that_is_not_a_number_is_a_blocker_on_the_record_that_carries_it(
    size: str, tmp_path: Path
):
    """A blocker and not a warning, on a corpus written at schema version 2 — so
    this also holds that the rule is stamped 1 rather than at the current version.

    Grandfathering exists so that a requirement invented today does not turn
    somebody's year-old file red. No file predates arithmetic: `person_weeks:
    .inf` has never been a size anybody could plan against, at any version, and
    it broke pages on the day it was committed. Stamped at the current version
    this would report a warning where it means a blocker, on every record that
    exists today, for ever.
    """
    from openproj.model import load_repo, validate_all

    records, config, _ = load_repo(_on_disk(tmp_path, size=size))

    mine = [
        one
        for one in validate_all(records, config, today=date(2026, 8, 17))
        if one.record_id == "task-e00003" and one.field == "person_weeks"
    ]

    assert [one.severity for one in mine] == ["blocker"], mine
    assert mine[0].rule_version == 1, "stamped later, every existing record is grandfathered"
    # The value said back, because a reader looking for the line they typed needs
    # to be told which one it is rather than which characters to search for.
    said = {".inf": "inf", "-.inf": "-inf", ".nan": "nan"}[size]
    assert said in mine[0].message, mine[0].message


def test_check_counts_a_setting_that_is_not_a_number_and_leaves_with_1(tmp_path, capsys):
    """The whole point of this half. `openproj check` reported byte-identical
    counts on a corpus holding one of these and on a corpus holding none — "0
    blockers, 0 warnings" on a plan whose every date came out of `.inf`, which is
    the failure this repository already has a row in its own table for.

    **The COUNT and not only the exit code.** Written against the exit code alone
    this passed with the count line left as it was, because the status is decided
    by a second expression — so the one number a reader actually sees could go on
    saying zero while the command came back 1. The headline is the thing that
    was wrong; it is the thing asserted.
    """
    from openproj.cli import main

    good = _on_disk(tmp_path / "good")
    bad = _on_disk(tmp_path / "bad", cooldown=".inf", rate=".inf", size=".nan")

    assert main(["check", str(good), "--today", "2026-08-17"]) == 0
    assert capsys.readouterr().out.splitlines()[-1] == "0 blockers, 0 warnings"

    assert main(["check", str(bad), "--today", "2026-08-17"]) == 1
    said = capsys.readouterr().out
    # Three: the config setting, the cycle's availability, and the record's size.
    assert said.splitlines()[-1].startswith("3 blockers,"), said
    assert "config/defaults.yaml" in said and "cycles/0037.md" in said, said


# --------------------------------------------------------------------------- #
# The medium: what a page actually serves, and what it prints
# --------------------------------------------------------------------------- #

# Every route that draws a page, plus the two that answer a script. Written out
# rather than derived from the app's routing table on purpose: the point of the
# list is that somebody adding a route has to think about this, and a list read
# off `app.routes` would grow silently and prove whatever the app happened to do.
_ROUTES = (
    "/",
    "/table",
    "/graph",
    "/timeline",
    "/cycles",
    "/cycle/37",
    "/deck/37",
    "/people",
    "/issues",
    "/notes",
    "/help",
    "/detail",
    "/detail/pitch-e00001",
    "/detail/task-e00003",
    "/new",
    "/api/index.json",
    "/api/health",
)


@pytest.mark.parametrize("value", NOT_NUMBERS)
def test_the_cycle_page_serves_when_somebodys_availability_is_not_a_number(
    value: str, tmp_path: Path
):
    """`/cycle/<n>` answered `OverflowError: cannot convert float infinity to
    integer` out of the roster row's `(row.rate * 100)|round|int` — inside a Jinja
    template, where nothing can guard it, off one line in one cycle file.

    Named as a route rather than as a template expression because that is what
    somebody meets: the page for the cycle they are in the middle of betting.
    """
    with TestClient(create_app(whole_plan(tmp_path, rate=value), auth="dev")) as client:
        got = client.get("/cycle/37")

        assert got.status_code == 200, got.text[:400]


@pytest.mark.parametrize("value", NOT_NUMBERS)
def test_the_record_page_and_the_deck_serve_when_a_size_is_not_a_number(
    value: str, tmp_path: Path
):
    """`round(100 * counted.fraction)` raised in three places, and the third is
    the deck — every record in a cycle, on the screen at the review meeting.

    The PARENT's page, not the child's: `Progress` is a rollup, so a `.nan` on one
    task took down the page of the pitch above it. The task's own page drew fine,
    which is why this was not noticed.
    """
    with TestClient(create_app(whole_plan(tmp_path, size=value), auth="dev")) as client:
        for route in ("/detail/pitch-e00001", "/detail/task-e00003", "/deck/37", "/table"):
            assert client.get(route).status_code == 200, route


def test_no_page_prints_a_number_that_is_not_one(tmp_path: Path):
    """**The tripwire for the whole sweep, and the thing a per-site fix cannot
    give you.** Every route, over a corpus carrying all three kinds at once —
    `.inf` in a config file, `.inf` in a cycle and `.nan` on a task.

    Written this way round because the sweep's finding was that guarding the two
    SOURCES emptied all fifteen readouts downstream of them: a test per readout
    would have to be written once per readout and would say nothing about the
    sixteenth. `staffing_of` was found by exactly this scan, printing "inf
    full-time between them" under a pitch, after four separate greps for
    `round(`, `int(`, `|round` and `Math.round` had each reported the sweep done.

    **Asked of the parsed document and of the payloads, never of the bytes.** A
    byte scan finds `Infinity` in Ace's minified source and `NaN` in the
    datepicker's month parser — both vendored, neither ours — and it finds this
    repository's own comments about the defect, which are written in the words of
    the defect. An allowlist of surrounding phrases was tried first and it is the
    wrong instrument for the same reason a denylist of URL spellings is: it has
    to enumerate an unbounded set, and the one it misses is the one that matters.
    So the question is put where the answer lives — the text a reader sees, and
    the JSON a script reads — and script and style bodies are structurally out.
    """
    import re
    from html.parser import HTMLParser

    class _Readable(HTMLParser):
        """Text a reader sees, and every `application/json` payload, kept apart
        from script and style bodies."""

        def __init__(self) -> None:
            super().__init__(convert_charrefs=True)
            self.said: list[str] = []
            self.payloads: list[str] = []
            self._in = ""

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            kind = dict(attrs).get("type") or ""
            self._in = "json" if tag == "script" and "json" in kind else tag

        def handle_endtag(self, tag: str) -> None:
            self._in = ""

        def handle_data(self, data: str) -> None:
            if self._in == "json":
                self.payloads.append(data)
            elif self._in not in ("script", "style"):
                self.said.append(data)

    bad = re.compile(r"(?<![-A-Za-z])(-?inf|nan|Infinity|NaN)(?![A-Za-z-])")

    def numbers_in(payload: object) -> list[float]:
        """Every non-finite float in a decoded payload, however deep.

        `json.loads` accepts the three JavaScript literals that `json.dumps`
        writes, so a payload can carry one and still decode — which is the whole
        reason `_json` passes `allow_nan=False`. Reading the decoded values says
        which numbers are in there rather than which characters are.
        """
        if isinstance(payload, float):
            return [] if math.isfinite(payload) else [payload]
        if isinstance(payload, dict):
            return [n for value in payload.values() for n in numbers_in(value)]
        if isinstance(payload, list):
            return [n for value in payload for n in numbers_in(value)]
        return []

    repo = whole_plan(tmp_path, size=".nan", rate=".inf", cooldown=".inf")

    with TestClient(create_app(repo, auth="dev")) as client:
        for route in _ROUTES:
            got = client.get(route)
            assert got.status_code == 200, f"{route}: {got.text[:300]}"
            if not got.headers["content-type"].startswith("text/html"):
                assert not numbers_in(got.json()), route
                continue
            page = _Readable()
            page.feed(got.text)
            for said in page.said:
                # The one sentence in the app that prints such a value on
                # purpose: the problem beside the record, which says the value
                # back so a reader knows which line to open.
                if "is not a size anything can be planned against" in said:
                    continue
                assert not bad.search(said), f"{route} shows a reader: {said.strip()[:160]!r}"
            for block in page.payloads:
                carried = json.loads(block)
                assert not numbers_in(carried), route


def test_every_page_says_so_when_a_config_file_holds_a_number_that_is_not_one(tmp_path: Path):
    """The banner is the shell's job for the reason the nav mark is: twelve entry
    points is twelve places to forget, and the one page that forgot would draw a
    date off `.inf` with nothing anywhere saying so.

    Parsed out of the document rather than searched for. The two banners carry the
    same `class="unreadable"` — same weight, and a second colour would be a
    channel carrying nothing — so a substring test cannot tell them apart at all.
    """
    from pages import unusable_banner_says, unusable_in

    repo = whole_plan(tmp_path, cooldown=".inf")

    with TestClient(create_app(repo, auth="dev")) as client:
        for route in _ROUTES:
            got = client.get(route)
            if not got.headers["content-type"].startswith("text/html"):
                continue
            listed = unusable_in(got.text)

            assert len(listed) == 1, f"{route} listed {listed}"
            assert listed[0].startswith("config/defaults.yaml — cooldown_weeks"), listed
            assert "cool-down" in listed[0], listed
            # The headline separately from the list, because an empty list is the
            # answer to two questions — "no banner" and "a banner with nothing in
            # it" — and a red box announcing "0 settings" on every page is the
            # negative case a list-only test cannot see.
            assert "not a number" in unusable_banner_says(got.text), route


def test_a_plan_with_nothing_wrong_draws_no_such_banner(tmp_path: Path):
    """The negative half, and it is the half that catches a banner wired to
    something that is always true — which is how a red strip ends up on every
    page of a plan that is perfectly fine."""
    from pages import banner_says, unusable_banner_says

    with TestClient(create_app(whole_plan(tmp_path), auth="dev")) as client:
        got = client.get("/")

        assert unusable_banner_says(got.text) == ""
        assert banner_says(got.text) == ""


def test_a_rollup_can_never_be_more_than_finished(seed_root: Path):
    """The structural fact the three `_percent` calls rest on, pinned because a
    comment claiming it is not the same as a test holding it.

    `_weighed` (`index.py`) sums the same per-child quantity for both halves of a
    rollup and the done half sums over a subset of the children, so `done` cannot
    exceed `total`. Which means routing the record page's two meters and the
    deck's third through `_percent` moves no number — the clamp is defensive, and
    an earlier version of the comment beside them claimed it fixed a meter
    announcing "120 per cent" over a full bar. It does not, because there is no
    such meter.

    Constructed as well as swept: a bet of 1 holding two done tasks worth 3 and 2
    is the shape that would produce one if anything could, and it reads 5/5. The
    mismatch between a bet and its contents is real and is reported — by
    `_rollup_problems`, in words, on its own line.
    """
    from openproj.index import build_index
    from openproj.model import Config, load_repo

    records, config, unreadable = load_repo(seed_root)
    seed = build_index(records, config, date(2026, 8, 17), unreadable)

    assert seed.progress, "the corpus rolled nothing up, so the sweep proved nothing"
    for record_id, counted in seed.progress.items():
        assert counted.done <= counted.total, f"{record_id}: {counted.text}"

    outrun = build_index(
        [
            parse_text(
                "---\nid: pitch-ee0001\nkind: pitch\ntitle: A small bet\n"
                "status: in_progress\nperson_weeks: 1\n---\n\nB\n",
                "pitches/pitch-ee0001.md",
            ),
            *(
                parse_text(
                    f"---\nid: task-ee000{n}\nkind: task\ntitle: T{n}\nstatus: done\n"
                    f"parent: pitch-ee0001\nperson_weeks: {weeks}\n---\n\nB\n",
                    f"tasks/task-ee000{n}.md",
                )
                for n, weeks in ((1, 3), (2, 2))
            ),
        ],
        Config(schema_version=2),
        date(2026, 8, 17),
    )
    rolled = outrun.progress["pitch-ee0001"]

    assert (rolled.done, rolled.total) == (5.0, 5.0), rolled.text
    assert _percent(rolled.done, rolled.total) == round(100 * rolled.fraction) == 100
