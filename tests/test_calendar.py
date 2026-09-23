"""The calendar popup, asked of the document rather than of a string.

The native calendar an `<input type="date">` opens is browser chrome: no
stylesheet here can reach a day in it. So this is a widget, and everything a
widget owes a reader — a name, a keyboard, an announcement — is ours.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import pytest
from cascade import El, Sheet, el

import openproj.render.calendar as calendar_module
from openproj.index import Index, build_index
from openproj.model import load_repo
from openproj.render.calendar import _calendar_js
from openproj.vendor import _static_dir
from tests.pages import render_paths, tags

# The corpus's own today, which `cycle_windows` does not read: a cycle's three
# dates come from `config.cycles` and the cool-down and from nothing else, so
# this fixture is its own rather than shared with `test_index.py` — whose
# `TODAY` is pinned to the date its hand-derived goldens were checked against
# and is not free to move for a calendar's convenience.
TODAY = date(2026, 8, 13)


@pytest.fixture
def seed_index(seed_root: Path) -> Index:
    records, config, _ = load_repo(seed_root)
    return build_index(records, config, TODAY)


def windows_in(block: str) -> list[dict]:
    """The cycle array the page actually carries, parsed rather than searched for."""
    found = re.search(r"const CYCLE_WINDOWS = (\[.*?\]);", block, re.S)
    assert found, "the page carries no cycle windows at all"
    return json.loads(found.group(1))


def test_the_page_carries_every_dated_cycle_as_its_three_dates(seed_index: Index):
    block = _calendar_js(seed_index)
    carried = windows_in(block)

    assert [w["n"] for w in carried] == sorted(seed_index.cycles)
    for entry, window in zip(carried, seed_index.cycle_windows(), strict=True):
        assert entry == {
            "n": window.number,
            "opens": window.opens.isoformat(),
            "builds": window.builds_until.isoformat(),
            "closes": window.closes.isoformat(),
        }


def test_a_plan_with_no_dated_cycle_still_gets_a_calendar(seed_root: Path):
    """Empty must not look like broken. No bands is a plain calendar, not a
    missing one — and not a page that threw on the way to drawing it."""
    records, config, _ = load_repo(seed_root)
    index = build_index(records, config.model_copy(update={"cycles": {}}), TODAY)
    block = _calendar_js(index)

    assert windows_in(block) == []
    # Two claims and two tools. That the block is script elements and nothing
    # else is a question about markup, so it goes to the parser — `"<script>" in
    # block` was true of the library's own text long before it was true of an
    # element. That the library is IN one of them is a question about the text
    # of a script, which is the one thing a substring is the right tool for.
    assert tags(block) == {"script"}
    assert "window.Datepicker" in block


def test_the_cycle_json_is_a_value_and_not_a_substitution():
    """A title that merely equalled `BARS_JSON` put a live handler on every bar
    link on the timeline. Nothing in this module may rebuild a rendered page.

    The repository-wide sweep asks this of every renderer as SYNTAX, which is the
    stronger question — so the claim worth making here is that this module is
    inside it. A new module in the package has to be swept the day it lands, and
    the way that goes wrong is a list somebody has to remember to add a name to.
    """
    import inspect

    import openproj.render.calendar as module

    swept = {path.name for path in render_paths()}
    assert "calendar.py" in swept, "the renderer's own sweeps do not see this module"

    source = inspect.getsource(module)
    assert ".replace(" not in source
    assert "re.sub(" not in source


# The four places a colour token is defined in `shell.py`, in the order they are
# written. The fourth is the one that keeps being forgotten: `:root[data-scheme]`
# derives every token from sixteen base16 numbers, so a token missing there is a
# token that falls back to nothing under twenty palettes at once.
_TOKEN_BLOCKS = {
    "light": r"^:root \{(.*?)^\}",
    "dark-by-toggle": r'^:root\[data-theme="dark"\] \{(.*?)^\}',
    "dark-by-system": (
        r"@media \(prefers-color-scheme: dark\) \{\s*"
        r':root:not\(\[data-theme="light"\]\) \{(.*?)^  \}'
    ),
    "base16": r"^:root\[data-scheme\] \{(.*?)^\}",
}


def test_the_bands_two_new_tokens_are_defined_everywhere_the_first_one_is():
    """A colour defined in one block is right for the readers who match that
    block and wrong for everybody else, and most readers never touch the toggle:
    they match the media query and nothing else.

    Asked against `--band`, which has been in all four for a year, rather than
    against a list of block names typed out here — the claim is that the two new
    tints are defined wherever the tint they are a variation of is.
    """
    shell = next(path for path in render_paths() if path.name == "shell.py")
    style = shell.read_text(encoding="utf-8")

    for name, pattern in _TOKEN_BLOCKS.items():
        block = re.search(pattern, style, re.S | re.M)
        assert block, f"{name} is not a block in shell.py any more"
        defined = set(re.findall(r"(--[\w-]+):", block.group(1)))
        assert "--band" in defined, f"{name} does not define --band; this test is asking wrongly"
        assert {"--band-alt", "--band-edge"} <= defined, name


def test_the_calendars_licence_travels_with_the_calendar(seed_index: Index):
    """The same rule Ace and Inter are held to, for the same reason.

    The minified bundle contains zero occurrences of `Copyright` and zero of
    `MIT` — upstream's minifier strips the block — and MIT's own condition is
    that the notice be included in all copies. Every page with a date field
    inlines these 35 KB, and a static export mailed to somebody is a copy that
    has left this repository behind, so a notice that lives only in `static/`
    does not travel with it.
    """
    block = _calendar_js(seed_index)
    licence = (_static_dir() / "datepicker-LICENSE.txt").read_text(encoding="utf-8")

    assert licence in block, "the picker ships in the page and its licence does not"
    assert "Copyright (c) 2019 Hidenao Miyamoto" in block
    # Ahead of the bytes rather than anywhere in the block: a notice after 35 KB
    # of minified script is a notice nobody finds.
    assert block.index("Hidenao Miyamoto") < block.index("window.Datepicker")


# --------------------------------------------------------------------------- #
# The stylesheet's four cascade claims, resolved by name
# --------------------------------------------------------------------------- #
#
# `_CALENDAR_STYLE`'s comments state four resolutions as fact — which band fill
# wins for an odd cycle, which for a cool-down, which for an odd cool-down, and
# what the selected day takes the ground from. Every one of them is a claim about
# the cascade, and a claim about the cascade cannot be checked by looking for a
# rule's text: `.datepicker-cell.next:not(.disabled)` was in the sheet, spelled
# exactly as intended, and it silently outranked every `.selected` rule below it
# because `:not()` forwards its argument's weight. The selected day, drawn as a
# spill-over from the neighbouring month, was `var(--muted)` on `var(--accent)`
# — 1.36:1 — and the day number was effectively not drawn.
#
# So these ask `tests/cascade.py`, which weighs selectors the way § Selectors 4
# does and answers WHICH RULE WINS, by name. The winning selector is asserted as
# well as the value, because a rule that wins for the wrong reason is the defect
# one commit away: `.datepicker-cell.selected` and `.datepicker-cell.selected.cyc`
# both say `var(--accent)`, and only one of them is meant to be deciding it.


@pytest.fixture
def calendar_style() -> Sheet:
    """The calendar's own sheet, read off the module at call time so a test can
    mutate the constant and watch these resolutions change."""
    return Sheet(calendar_module._CALENDAR_STYLE)


def day(classes: str, states: str = "") -> list[El]:
    """One day cell as the library builds it: a div inside the grid, carrying the
    library's own classes plus whatever the glue adds."""
    return [
        el("div", "datepicker"),
        el("div", "datepicker-picker"),
        el("div", "datepicker-grid"),
        el("div", f"datepicker-cell day {classes}", states=states),
    ]


def decided_by(sheet: Sheet, path: list[El], prop: str) -> tuple[str, str]:
    """(selector, value) of the rule a browser would use, with every rule it beat
    in the failure message — `winner` alone says who won and not who was there."""
    won = sheet.winner(path, prop)
    assert won is not None, f"no rule in the calendar's sheet sets `{prop}` here"
    return won.selector, won.value


def losers(sheet: Sheet, path: list[El], prop: str) -> str:
    return "\n".join(
        f"  {rule.specificity} {rule.selector} {{ {prop}: {rule.declarations[prop][0]} }}"
        for rule in sheet.selectors_reaching(path, prop)
    )


@pytest.mark.parametrize(
    ("what", "classes", "selector", "value"),
    [
        # An even cycle's build days: the only band rule that reaches them.
        ("an even cycle", "cyc", ".datepicker-cell.cyc", "var(--band)"),
        # The comment's first claim: `.cyc-alt` follows `.cyc` and beats it on
        # ORDER, both being (0,2,0). An odd cycle's day carries both classes.
        ("an odd cycle", "cyc cyc-alt", ".datepicker-cell.cyc-alt", "var(--band-alt)"),
        # The second: `.cyc-cool` follows both and beats them for a cool-down.
        (
            "an even cycle's cool-down",
            "cyc cyc-cool",
            ".datepicker-cell.cyc-cool",
            "color-mix(in oklab, var(--line) 50%, var(--band))",
        ),
        # The third: `.cyc-alt.cyc-cool` is (0,3,0) and beats all three on
        # weight, which is what keeps an odd cycle's cool-down on the odd
        # cycle's tint instead of collapsing every cool-down to one colour.
        (
            "an odd cycle's cool-down",
            "cyc cyc-alt cyc-cool",
            ".datepicker-cell.cyc-alt.cyc-cool",
            "color-mix(in oklab, var(--line) 50%, var(--band-alt))",
        ),
    ],
)
def test_each_band_fill_is_decided_by_the_rule_written_for_it(
    calendar_style: Sheet, what: str, classes: str, selector: str, value: str
):
    """Four fills, four rules, and the sheet says in a comment which one wins
    where. Asserting the value alone passes while the wrong rule decides it —
    `.cyc` and `.cyc-alt` are both a flat band token, and an odd cycle drawn in
    the even cycle's tint is a plausible-looking calendar that is simply wrong.
    """
    path = day(classes)
    assert decided_by(calendar_style, path, "background") == (selector, value), (
        f"the fill for a day in {what} is decided by something else:\n"
        f"{losers(calendar_style, path, 'background')}"
    )


def test_the_roving_cursor_is_an_outline_so_the_band_under_it_survives(
    calendar_style: Sheet,
):
    """The sheet says the cursor is an outline and not a background because a
    background `.datepicker-cell.focused:not(.selected)` is (0,3,0) and would
    beat all four band rules — the band would vanish from the one day the reader
    is asking about. So: the outline is decided by that rule, and the fill under
    it is still the band's.
    """
    # A CLASS and not a state: the library moves its own `focused` class from
    # cell to cell (`changeFocusedCell`), and `:focus` never leaves the input.
    path = day("cyc cyc-alt cyc-cool focused")
    assert decided_by(calendar_style, path, "outline") == (
        ".datepicker-cell.focused:not(.selected)",
        "2px solid var(--focus)",
    )
    assert decided_by(calendar_style, path, "background") == (
        ".datepicker-cell.cyc-alt.cyc-cool",
        "color-mix(in oklab, var(--line) 50%, var(--band-alt))",
    ), "the cursor took the band off the day it is on"


# --------------------------------------------------------------------------- #
# The ink ladder, and the rung that was missing
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("what", "classes", "selector", "value"),
    [
        # The rungs, in the order the sheet writes them. Each is (0,2,0) and each
        # beats the one above it on order alone.
        ("a spill-over day", "next", ".datepicker-cell.next", "var(--muted)"),
        ("a spill-over day the other way", "prev", ".datepicker-cell.prev", "var(--muted)"),
        # `.disabled` follows the muting, which is what the old `:not(.disabled)`
        # bought and what order buys now: out of range reads as out of range and
        # not merely as next month.
        (
            "a spill-over day that is out of range",
            "next disabled",
            ".datepicker-cell.disabled",
            "var(--empty)",
        ),
        # The rung the muting used to outrank, and the whole defect. A selected
        # day IS drawn as a spill-over — the library's `renderCell` adds `prev`
        # or `next` from the month it is in and `selected` from the value it
        # holds, and the two are independent — so this is the day the popup was
        # opened to show, sitting on `var(--accent)`.
        (
            "the selected day, shown as next month's spill-over",
            "next selected",
            ".datepicker-cell.selected",
            "var(--on-accent)",
        ),
        (
            "the selected day, shown as last month's spill-over",
            "prev selected",
            ".datepicker-cell.selected",
            "var(--on-accent)",
        ),
    ],
)
def test_the_ink_on_a_day_is_a_ladder_the_selected_day_stands_on_top_of(
    calendar_style: Sheet, what: str, classes: str, selector: str, value: str
):
    """`.datepicker-cell.next:not(.disabled)` is (0,3,0) — `:not()` forwards its
    argument's weight — and every rule in the `.selected` block that could reach
    a plain spill-over cell is (0,2,0). So the muting won, and the selected day
    rendered `var(--muted)` on `var(--accent)`: 1.36:1 in the light theme, 1.12:1
    in dark, against the 7.6:1 and 8.32:1 `--on-accent` gives. The day number was
    there and effectively not drawn, on the one cell the popup exists to point at.

    The value alone does not catch it — `var(--muted)` and `var(--on-accent)` are
    different, so it would — but the two rungs above it resolve to the right value
    for the wrong reason the moment somebody re-qualifies one, which is exactly
    what happened. Hence the selector.
    """
    path = day(classes)
    assert decided_by(calendar_style, path, "color") == (selector, value), (
        f"the ink on {what} is decided by something else:\n"
        f"{losers(calendar_style, path, 'color')}"
    )


def test_the_selected_day_takes_the_ground_from_every_band_including_the_heaviest(
    calendar_style: Sheet,
):
    """The sheet's fourth claim, and the reason the `.selected` block spells out
    combinations instead of standing on order alone.

    Three of the four band fills are (0,2,0), so a bare `.datepicker-cell.selected`
    written after them wins on order. The fourth, `.cyc-alt.cyc-cool`, is (0,3,0)
    and order cannot reach it — an odd cycle's cool-down day kept the band as its
    ground while taking `--on-accent` as its ink, which is white on pale blue.
    So the fill is asserted for each band, and the SELECTOR says whether order or
    the enumeration is what won it.
    """
    for classes, selector in [
        ("cyc selected", ".datepicker-cell.selected.cyc"),
        ("cyc cyc-alt selected", ".datepicker-cell.selected.cyc-alt"),
        ("cyc cyc-cool selected", ".datepicker-cell.selected.cyc-cool"),
        ("cyc cyc-alt cyc-cool selected", ".datepicker-cell.selected.cyc-cool"),
    ]:
        path = day(classes)
        assert decided_by(calendar_style, path, "background") == (selector, "var(--accent)"), (
            f"a selected day on `{classes}` does not stand on the accent:\n"
            f"{losers(calendar_style, path, 'background')}"
        )
        assert decided_by(calendar_style, path, "color") == (selector, "var(--on-accent)"), (
            f"a selected day on `{classes}` does not take the accent's ink:\n"
            f"{losers(calendar_style, path, 'color')}"
        )
