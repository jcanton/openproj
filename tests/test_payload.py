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
from openproj.web import create_app

ORDINARY = (
    "---\nid: task-e00001\nkind: task\ntitle: An ordinary task\n"
    "status: ready\nperson_weeks: 1\nassigned_on: 2026-09-01\n---\n\nBody.\n"
)
HAND_EDITED = (
    "---\nid: task-e00002\nkind: task\ntitle: A size somebody typed into a file\n"
    "status: ready\nperson_weeks: {size}\nassigned_on: 2026-09-01\n---\n\nBody.\n"
)

# The three spellings YAML has for a number that is not one. `.nan` matters as
# much as `.inf`: it has no nearest representable value at all, so a fix that
# clamped instead of nulling would still have left the page unparseable.
NOT_NUMBERS = (".inf", "-.inf", ".nan")


def index_with(*texts: str):
    entities = [parse_text(text, f"tasks/task-{n}.md") for n, text in enumerate(texts)]
    return build_index(entities, Config(schema_version=2), date(2026, 8, 17))


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
    rendered = page(index_with(ORDINARY, HAND_EDITED.format(size=size)), STATIC,
                    base_commit="deadbee")

    blocks = [
        text
        for text in rendered.split('type="application/json">')[1:]
    ]
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
        index_with(ORDINARY, HAND_EDITED.format(size=size)), STATIC, base_commit="deadbee"
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
def test_the_index_route_answers_rather_than_faulting_on_such_a_size(
    size: str, tmp_path: Path
):
    """`JSONResponse` encodes with `allow_nan=False`, so this raised inside the
    encoder — after the response object existed, which is a 500 in `text/plain`
    on the one route whose readers are all scripts."""
    with TestClient(create_app(plan_repo(tmp_path, size), auth="dev")) as client:
        got = client.get("/api/index.json")

        assert got.status_code == 200, got.text
        entities = got.json()["entities"]
        assert set(entities) == {"task-e00001", "task-e00002"}
        # Null, not a clamp: JSON has no way to say this number, and every page
        # already draws an absent one as a dash. A clamp would put a figure
        # nobody wrote into a cell.
        assert entities["task-e00002"]["person_weeks"] is None
        assert entities["task-e00001"]["person_weeks"] == 1.0


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
        for route in ("/", "/graph", "/timeline", "/people", "/cycles", "/detail",
                      "/detail/task-e00002", "/api/index.json"):
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
