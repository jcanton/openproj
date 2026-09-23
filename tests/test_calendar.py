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
from browser import chrome, measured_in
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


# --------------------------------------------------------------------------- #
# The widget itself, driven
# --------------------------------------------------------------------------- #
#
# **Chrome, and not `tests/js/drive.js`.** The cells exist in no rendered file —
# the library builds all forty-two of them when the popup opens — so the question
# has to be put to the script that builds them, and the way this repository
# usually does that is the node shim. Measured, not assumed: the bundle does not
# run in it. Its first statement is `const E = document.createRange()`, which the
# shim has not got, so it throws before `Datepicker` is ever defined and every
# assertion after that is a claim about an empty page.
#
# Handing the shim a `createRange` is not the end of it. The library builds its
# whole picker by parsing a template string and then walks the result with
# `firstChild`, `childNodes`, `replaceChild`, `getRootNode` and
# `previousElementSibling` — and the shim answers the last of those `null` for
# every element, deliberately and with a comment saying so. A shim extended far
# enough to get this library running would be a shim whose wrong answers land
# inside somebody else's layout code, where they read as "the calendar drew
# nothing unusual". That is the vacuous green `drive.js` has already produced
# three times, and two of those rounds were about this repository's own editor.
# So the question goes to a real browser, which is the medium the answer lives in.
#
# **The host page is built here, and that is the caveat.** No served page carries
# the calendar yet: wiring it into the six pages that have a date field is its own
# commit, so a test that drove `served["record"]` would find no `.datepicker` in
# it and pass by finding nothing. What is synthesised is only the HOST — the
# library, the cycles and the glue are `_calendar_js(index)` exactly as a page
# will be handed it, and the box is the `<input type="date">` the record form
# already writes. When the wiring lands, the host becomes the served page and
# none of these scripts changes.


def _library_months() -> list[str]:
    """The month names the popup's header is built from, read out of the bundle.

    The header's text is this file's one anchor on *which days the grid is
    showing* that does not go through the code under test. A list typed in here
    would be a second copy of the library's `locales.en`, and a second copy goes
    stale on the commit that re-vendors.
    """
    bundle = (_static_dir() / "datepicker.min.js").read_text(encoding="utf-8")
    found = re.search(r'months:\["January"((?:,"[A-Za-z]+"){11})\]', bundle)
    assert found, "the vendored bundle no longer carries the month table this reads"
    return ["January", *re.findall(r'"([A-Za-z]+)"', found.group(1))]


def _a_month_holding_more_than_build_days(index: Index) -> date:
    """The day to open the popup on: a month that holds an opening edge, a
    closing edge, a cool-down and days in no cycle at all.

    Picked out of the corpus rather than typed in, and the census below asserts
    every one of those is really there. A run over a month where every day is a
    plain build day would agree with the code about almost nothing — which is the
    same trap as a corpus with no emoji in it.
    """
    windows = index.cycle_windows()
    for window in windows:
        month = (window.opens.year, window.opens.month)
        if any((other.closes.year, other.closes.month) == month for other in windows
               if other.number != window.number):
            return window.opens
    raise AssertionError("no cycle in this corpus opens in a month another one closes in")


def _page_with_a_date_field(index: Index, value: date) -> str:
    """One date box and the real widget, with nothing else on the page."""
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        f"<style>{calendar_module._CALENDAR_STYLE}</style></head><body>"
        '<label for="start">Starts on</label>'
        f'<input type="date" id="start" name="start_date" value="{value.isoformat()}">'
        f"{_calendar_js(index)}</body></html>"
    )


# Every cell of the open grid, as the four things a claim here is made about:
# which days they are, what bands they wear, what they say, and what they read
# as.
CENSUS = """
  const grid = document.querySelector('.datepicker-grid');
  const live = document.querySelector('.datepicker [aria-live]');
  return {
    opened: !!document.querySelector('.datepicker.active'),
    shown: document.querySelector('.view-switch').textContent,
    gridRole: grid.getAttribute('role'),
    live: live ? live.textContent : null,
    liveClass: live ? live.className : null,
    cells: [...grid.querySelectorAll('.datepicker-cell')].map((cell) => {
      const badge = cell.querySelector('.cyc-n');
      return {
        // `firstChild` and not `textContent`, because the reading ORDER is the
        // claim: the badge is a child of the cell, so the 17th of cycle 37
        // reads "1737" and its first child is the text "17". A badge written in
        // front of the day number would leave this null, which is the "3 3"
        // defect stated as an assertion rather than as a comment.
        day: cell.firstChild ? cell.firstChild.nodeValue : null,
        text: cell.textContent,
        classes: cell.className.split(/\\s+/).filter(Boolean),
        role: cell.getAttribute('role'),
        name: cell.getAttribute('aria-label'),
        selected: cell.getAttribute('aria-selected'),
        badge: badge ? badge.textContent : null,
        badgeHidden: badge ? badge.getAttribute('aria-hidden') : null,
      };
    }),
  };
"""

OPEN_IT = """
  const box = document.getElementById('start');
  openCalendar(box);
""" + CENSUS

OPEN_IT_AND_STEP_A_MONTH = """
  const box = document.getElementById('start');
  openCalendar(box);
  document.querySelector('.datepicker-controls .next-btn').click();
""" + CENSUS


def _stepped(year: int, month: int, by: int) -> tuple[int, int]:
    moved = year * 12 + (month - 1) + by
    return moved // 12, moved % 12 + 1


def _days_of(found: dict) -> list[date]:
    """Which calendar day each cell stands for, worked out from the header and
    the cell's own text.

    Deliberately NOT from `dataset.date`, and not from anything `isoOf` touched:
    the whole question in the timezone case below is whether the widget put the
    band on the day the grid is drawing, and a test that asked the widget which
    day that was could only ever agree with itself.
    """
    name, year = found["shown"].split()
    shown_year, shown_month = int(year), _library_months().index(name) + 1
    days = []
    for cell in found["cells"]:
        assert cell["day"], f"a cell with no day number in it: {cell}"
        step = -1 if "prev" in cell["classes"] else 1 if "next" in cell["classes"] else 0
        at_year, at_month = _stepped(shown_year, shown_month, step)
        days.append(date(at_year, at_month, int(cell["day"])))
    return days


def _bands_for(day: date, windows: list) -> set[str]:
    """What the band classes on that day have to be.

    The rule and not a recording of the output: a cycle runs from the day it
    opens to the day it closes, alternates tint by its own number so that two
    touching cycles read as two, wears the cool-down fill after the last build
    day, and carries an edge on each of the two days that are facts. Written here
    in Python against `cycle_windows()` so that the browser's copy has something
    to disagree with.
    """
    for window in windows:
        if window.opens <= day <= window.closes:
            bands = {"cyc"}
            if window.number % 2:
                bands.add("cyc-alt")
            if day > window.builds_until:
                bands.add("cyc-cool")
            if day == window.opens:
                bands.add("cyc-opens")
            if day == window.closes:
                bands.add("cyc-closes")
            return bands
    return set()


@pytest.fixture
def opened(seed_index: Index, tmp_path: Path) -> dict:
    """The popup, opened on a month worth looking at, in a real browser."""
    page = _page_with_a_date_field(seed_index, _a_month_holding_more_than_build_days(seed_index))
    return measured_in(chrome(), page, tmp_path / "calendar.html", 1280, OPEN_IT)


# UTC first and on purpose: it is the CONTROL, and it passes with the defect in
# place. The picker hands `beforeShowDay` a local-midnight Date, so
# `toISOString()` on one prints the day before at every positive offset and the
# right day at zero — which is why a suite run on a UTC machine can watch a band
# sit one cell to the right of where it belongs for every reader in Europe and
# report nothing at all. Zurich is the offset the widget was written at.
@pytest.mark.parametrize("zone", ["UTC", "Europe/Zurich"])
def test_every_day_wears_the_band_of_the_cycle_it_is_really_in(
    seed_index: Index, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, zone: str
):
    """Forty-two days, each checked against `cycle_windows()` by the rule rather
    than against a recording.

    Measured with `toISOString()` in place of the local read: under Zurich the
    opening edge and the cycle's number both move to the 18th while the grid goes
    on drawing the 17th, and under UTC nothing moves at all.
    """
    monkeypatch.setenv("TZ", zone)
    page = _page_with_a_date_field(seed_index, _a_month_holding_more_than_build_days(seed_index))
    found = measured_in(chrome(), page, tmp_path / "calendar.html", 1280, OPEN_IT)
    windows = seed_index.cycle_windows()

    assert found["opened"], "the popup did not open, so nothing below was measured"
    days = _days_of(found)
    worn = [{name for name in cell["classes"] if name.startswith("cyc")}
            for cell in found["cells"]]

    # The corpus guard, first: a month of plain build days would agree with the
    # code about almost nothing, so the month under test has to hold each kind.
    seen = set().union(*worn)
    assert {"cyc", "cyc-alt", "cyc-cool", "cyc-opens", "cyc-closes"} <= seen, seen
    assert any(not bands for bands in worn), "every day in this month is in some cycle"

    for day, bands in zip(days, worn, strict=True):
        assert bands == _bands_for(day, windows), f"{zone}: {day} is drawn as {bands or 'no cycle'}"


def test_the_cycles_number_sits_on_the_day_it_opens_and_behind_the_day_number(
    opened: dict, seed_index: Index
):
    """`beforeShowDay`'s content replaces the cell's WHOLE contents — the day
    number the library wrote a line earlier is thrown away — so the day has to be
    back in it, and it has to come first: with the badge in front, day 3 of cycle
    3 read "3 3" to a screen reader.
    """
    days = _days_of(opened)
    opens = {window.opens: window.number for window in seed_index.cycle_windows()}
    badged = {day: cell for day, cell in zip(days, opened["cells"], strict=True) if cell["badge"]}

    assert badged, "no day in this month carries a cycle number"
    assert set(badged) == {day for day in days if day in opens}
    for day, cell in badged.items():
        assert cell["badge"] == str(opens[day])
        # The order, said three ways: the day number is the cell's first child,
        # the badge follows it, and the two read as one string in that order.
        assert cell["day"] == str(day.day)
        assert cell["text"] == f"{day.day}{opens[day]}"
        assert cell["badgeHidden"] == "true", "the number is read out beside the day it labels"


def test_the_calendar_says_what_it_is_although_its_library_does_not(opened: dict):
    """Counted rather than assumed: zero `aria-*` attributes and zero `role`s in
    the whole 35 KB bundle. The grid is a div, the selected day announces nothing,
    and the band that tells a sighted reader which cycle a day is in tells a
    reader who is not looking at it nothing whatever.
    """
    assert opened["gridRole"] == "grid"
    assert opened["live"] == opened["shown"], "the month the popup is on is announced to nobody"

    for day, cell in zip(_days_of(opened), opened["cells"], strict=True):
        assert cell["role"] == "gridcell"
        assert cell["name"], f"a day with no name at all: {cell['text']}"
        # The whole date and not just the day number, which the month spelled out
        # underneath it would supply on its own: "2" is inside "2026". The name is
        # written rather than left to the cell's contents, which are a day number
        # and a badge hidden precisely so it is not read — leaving "14" as the
        # whole of what this cell would otherwise announce.
        assert str(day.day) in cell["name"]
        assert _library_months()[day.month - 1] in cell["name"]
        assert str(day.year) in cell["name"], f"{day} is announced as {cell['name']!r}"
        assert cell["selected"] == ("true" if "selected" in cell["classes"] else "false")

    named = [cell for cell in opened["cells"] if "cyc" in cell["classes"]]
    assert named, "no day in this month is in a cycle, so nothing here was tested"
    assert all("cycle" in cell["name"] for cell in named)
    cooled = [cell for cell in named if "cyc-cool" in cell["classes"]]
    assert cooled and all("cool-down" in cell["name"] for cell in cooled)


def test_the_month_change_rebuilds_the_names_the_library_leaves_behind(
    seed_index: Index, tmp_path: Path
):
    """The redraw, and the reason it is not asked about with `role`.

    The library reuses its forty-two cells — `renderCell` rewrites `className`,
    `textContent` and `dataset.date` on the same `<span>` — so an attribute set
    once at construction SURVIVES a month change. Measured with the redraw hook
    deleted: `role` comes back `grid`, every cell still says `gridcell`, and both
    assertions pass over a widget that has never re-described anything. What is
    wrong is everything that was about the days themselves — the first cell
    announces "Monday, 27 July 2026, cycle 36" on September's grid, a cell that
    is no longer selected still says `aria-selected="true"`, and the live region
    says August while the header says September.

    So those three are the assertions, and `role` is here only to show it is not.
    """
    page = _page_with_a_date_field(seed_index, _a_month_holding_more_than_build_days(seed_index))
    found = measured_in(
        chrome(), page, tmp_path / "calendar.html", 1280, OPEN_IT_AND_STEP_A_MONTH
    )
    windows = seed_index.cycle_windows()

    assert found["gridRole"] == "grid"
    assert found["live"] == found["shown"]
    for day, cell in zip(_days_of(found), found["cells"], strict=True):
        assert str(day.year) in cell["name"], f"{day} is announced as {cell['name']!r}"
        assert _library_months()[day.month - 1] in cell["name"]
        assert cell["selected"] == ("true" if "selected" in cell["classes"] else "false")
        found_in = _bands_for(day, windows)
        assert ("cycle" in cell["name"]) == bool(found_in)


def test_a_date_box_made_after_the_page_loaded_gets_the_calendar_too(
    seed_index: Index, tmp_path: Path
):
    """One delegated listener and not a hook per host. Three of the places a date
    box appears are built at runtime — the table's cells, its draft row and the
    `#pop` form's third face — and none of them exists when a page's script first
    runs, so a per-host hook is three places for one to be forgotten and a fourth
    host to arrive with none.
    """
    page = _page_with_a_date_field(seed_index, _a_month_holding_more_than_build_days(seed_index))
    found = measured_in(chrome(), page, tmp_path / "calendar.html", 1280, """
      const before = document.querySelectorAll('.datepicker').length;
      const made = document.createElement('input');
      made.type = 'date';
      made.id = 'later';
      document.body.appendChild(made);
      made.focus();
      // The last grid on the page, and `null` rather than a throw when there is
      // none: a script that dies on the missing popup reports nothing at all,
      // and "the page reported nothing" is the harness's sentence for a page
      // that never laid out. The defect has to arrive as the assertion below.
      const grid = [...document.querySelectorAll('.datepicker-grid')].pop();
      return {
        before: before,
        active: document.querySelectorAll('.datepicker.active').length,
        banded: grid ? [...grid.querySelectorAll('.datepicker-cell.cyc')].length : null,
      };
    """)

    # Nothing is built until a box is focused: the picker is the cost of using a
    # date field and not the cost of loading a page that has one.
    assert found["before"] == 0
    assert found["active"] == 1, "focusing a box made after load opened no calendar"
    assert found["banded"] > 0, "the new box got a calendar with no cycles in it"


def test_the_keyboard_opens_the_calendar_as_well_as_the_pointer(
    seed_index: Index, tmp_path: Path
):
    """Every editable surface has a keyboard path beside the pointer one. Focus
    opens the popup, and Alt+Down is what reopens it after an Escape — which is
    the gesture a native date field and every combobox on these pages already
    answer to, so it is the one a reader will try.
    """
    page = _page_with_a_date_field(seed_index, _a_month_holding_more_than_build_days(seed_index))
    found = measured_in(chrome(), page, tmp_path / "calendar.html", 1280, """
      const box = document.getElementById('start');
      box.focus();
      const onFocus = !!document.querySelector('.datepicker.active');
      calendarFor(box).hide();
      const shut = !document.querySelector('.datepicker.active');
      box.dispatchEvent(new KeyboardEvent('keydown',
        {key: 'ArrowDown', altKey: true, bubbles: true}));
      return {onFocus: onFocus, shut: shut,
              reopened: !!document.querySelector('.datepicker.active')};
    """)

    assert found["onFocus"], "tabbing into the field opened nothing"
    assert found["shut"], "this test cannot say anything about reopening a popup that is up"
    assert found["reopened"], "Alt+Down did not bring it back"


def test_the_popups_live_region_wears_a_name_the_shell_actually_defines():
    """`.sr-only` is the shell's own name for "in the document and off the
    screen", and its rule ships on every page that will carry this widget. A
    second name for it — `visually-hidden`, say — is not an invisible region: it
    is a class nothing defines, which draws the month a second time underneath
    the header that already says it.
    """
    shell = next(path for path in render_paths() if path.name == "shell.py")
    assert ".sr-only {" in shell.read_text(encoding="utf-8")
    assert 'live.className = \'sr-only\';' in calendar_module._GLUE


def test_the_widget_turns_no_value_into_markup():
    """The day cells are the one place in this widget where a cell's contents are
    built from data, and `beforeShowDay` will take a string of HTML — so this is
    where a third escaping boundary would be invented, in a language that has two
    here. It takes nodes instead: a text node for the day and a `<span>` whose
    number goes in through `textContent`.

    Six injection sites existed at once because six places each decided for
    themselves, and the fix is the seam rather than the escape.
    """
    glue = str(calendar_module._GLUE)

    assert "createTextNode" in glue and "textContent" in glue
    for markup in ("innerHTML", "insertAdjacentHTML", "outerHTML"):
        assert markup not in glue, f"the calendar's glue builds markup with {markup}"
