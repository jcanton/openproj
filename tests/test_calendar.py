"""The calendar popup, asked of the document rather than of a string.

The native calendar an `<input type="date">` opens is browser chrome: no
stylesheet here can reach a day in it. So this is a widget, and everything a
widget owes a reader — a name, a keyboard, an announcement — is ours.
"""

from __future__ import annotations

import json
import re
from datetime import date
from html.parser import HTMLParser
from pathlib import Path

import pytest
from browser import chrome, measured_in, measured_on_a_phone
from cascade import El, Sheet, el

import openproj.render.calendar as calendar_module
from openproj.index import Index, build_index
from openproj.model import load_repo
from openproj.render import (
    ROUTES,
    render_cycle,
    render_cycles,
    render_detail,
    render_graph,
    render_help,
    render_people,
    render_records,
    render_static,
    render_table,
    render_timeline,
)
from openproj.render.calendar import _calendar_js
from openproj.vendor import _static_dir
from tests.pages import elements, render_paths, tags

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
    """One date box and the real widget, with nothing else on the page.

    The box is inside a `<form id="edit">` because that is where the record page
    keeps it — `CONTROLS` is `FORM.querySelectorAll('[data-type]')` — and two
    claims here rest on it. The library inserts its popup with
    `inputField.after()`, so the whole widget lands INSIDE that form, which is
    what makes a bare `<button>` in the chip row a submit button. And Reset
    announces itself by dispatching one `input` on the form rather than on any
    box, so the event this widget has to hear is a form's.
    """
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        f"<style>{calendar_module._CALENDAR_STYLE}</style></head><body>"
        '<form id="edit"><label for="start">Starts on</label>'
        f'<input type="date" id="start" name="start_date" data-type="date"'
        f' value="{value.isoformat()}"></form>'
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
    // Which language the DAY NAMES came out in. The popup's own furniture — the
    // header, the days-of-week row, Today and Clear — is the library's `en`
    // table and is English for everybody; a cell's name is
    // `toLocaleDateString(undefined, …)`, which is the reader's locale and is
    // the right default for a date. So the month-name assertions below are
    // asked only where they can be answered, and say so when they are not.
    locale: Intl.DateTimeFormat().resolvedOptions().locale,
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


def _in_english(found: dict) -> bool:
    """Whether a day's name can be checked against a month name at all.

    A cell's name is `toLocaleDateString(undefined, …)` — the reader's own
    locale, which is the right default for a date and is not a thing a Chrome
    flag will move: `--lang=de-DE` leaves `Intl` resolving to whatever the
    machine is set to. Everything these tests actually rest on is
    language-independent — the day number, the year, the cycle, `aria-selected`
    and the live region — and every one of them fails under the redraw mutation
    on its own. The month name is the belt beside those braces, so it is asked
    where it can be answered rather than making the suite depend on the locale of
    the machine that runs it.
    """
    english = str(found["locale"]).startswith("en")
    if not english:  # pragma: no cover - depends on the machine, not on the code
        print(f"the browser formats dates as {found['locale']}: month names not checked")
    return english


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
        assert str(day.year) in cell["name"], f"{day} is announced as {cell['name']!r}"
        if _in_english(opened):
            assert _library_months()[day.month - 1] in cell["name"]
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
        # The day number is the one that catches it and needs no language: with
        # the wiring gone the 31st of August is still announced as the 27th of
        # July, and "31" is not in that sentence in any locale.
        assert str(day.day) in cell["name"], f"{day} is announced as {cell['name']!r}"
        assert str(day.year) in cell["name"], f"{day} is announced as {cell['name']!r}"
        if _in_english(found):
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


# --------------------------------------------------------------------------- #
# The seam between the box and the widget, in both directions
# --------------------------------------------------------------------------- #
#
# `input.value` is the only channel between this widget and the rest of the app,
# and a channel has two ends. Neither end carried anything on its own: a value
# assigned by script fires no event, so the widget never heard the page, and the
# library assigns `inputField.value` in `refreshUI` and dispatches only its own
# `changeDate`, so the page never heard the widget. Both were measured before
# either was written, and the scripts below are those measurements.

# What Reset really does, and the whole reason this is not a `change` listener.
# `resetEdits` (`detail.py`) assigns every control and then dispatches ONE `input`
# on the form — its own comment says why, and the plan this was written from
# assumed a `change` on the box that nothing anywhere fires.
RESET = """
  const box = document.getElementById('start');
  const picker = openCalendar(box);
  const iso = (d) => d ? `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
    + `-${String(d.getDate()).padStart(2, '0')}` : null;
  const reading = () => ({
    value: box.value,
    picker: iso(picker.getDate()),
    shown: document.querySelector('.view-switch').textContent,
    live: document.querySelector('.datepicker [aria-live]').textContent,
    selected: [...document.querySelectorAll('.datepicker-cell.selected')]
      .map((cell) => [cell.firstChild.nodeValue, cell.getAttribute('aria-selected')]),
  });

  const before = reading();
  box.value = '2026-12-25';
  document.getElementById('edit').dispatchEvent(new Event('input', {bubbles: true}));
  const after = reading();

  // And the other thing Reset restores: a field that was cleared. An empty box
  // is not a date and must not be parsed as one.
  box.value = '';
  document.getElementById('edit').dispatchEvent(new Event('input', {bubbles: true}));
  const cleared = reading();

  // The same emptiness, reached the way a person reaches it: a native date box
  // reports `''` the instant ANY segment is cleared, and that fires `input` on
  // the BOX. So this is the keystroke path rather than the Reset path, and it is
  // the one the defect was measured on.
  box.value = '2027-02-17';
  box.dispatchEvent(new Event('input', {bubbles: true}));
  const typed = reading();
  box.value = '';
  box.dispatchEvent(new Event('input', {bubbles: true}));
  const backspaced = reading();

  return {before, after, cleared, typed, backspaced,
          open: !!document.querySelector('.datepicker.active')};
"""


def test_a_reset_moves_the_calendar_with_the_box_it_belongs_to(
    seed_index: Index, tmp_path: Path
):
    """A value set from outside does not reach the widget. Measured, with a
    dispatched event and everything: `getDate()` stayed on the old date and the
    grid stayed on the old month.

    Two paths here set a date field from outside and neither is a person typing —
    Reset restoring from `BASELINE`, and the table's `draw()` replacing its
    tbody. A calendar still showing the edited month after a Reset disagrees with
    the box it belongs to, in the one flow whose entire job is undoing a mistake,
    and it disagrees silently: the next click in the grid writes December's
    answer to August's question.

    The whole widget is asked and not only `getDate()`, because the selection and
    the drawing are two different things — `setDate(…, {render: false})` moves one
    and leaves the other — and what a reader sees is the drawing.
    """
    page = _page_with_a_date_field(seed_index, date(2026, 8, 17))
    found = measured_in(chrome(), page, tmp_path / "calendar.html", 1280, RESET)

    assert found["before"]["picker"] == "2026-08-17", "the popup did not open on the box's date"
    assert found["before"]["shown"] == "August 2026"

    after = found["after"]
    assert after["value"] == "2026-12-25", "the test did not set the box"
    assert after["picker"] == "2026-12-25", "the widget is holding a date the box does not"
    # The three a reader can actually see: the month in the header, the month in
    # the live region, and which day is drawn as chosen.
    assert after["shown"] == "December 2026", "the grid is still drawing the month Reset undid"
    assert after["live"] == "December 2026"
    assert after["selected"] == [["25", "true"]]
    assert found["open"], "the popup shut itself on a Reset, which is not what Reset does"

    # A cleared field is not a date. `update()` is the library's own read of the
    # input field and takes the empty string as "nothing selected"; parsing
    # `box.value` by hand is how `''` becomes today, or Invalid Date.
    assert found["cleared"]["picker"] is None
    assert found["cleared"]["value"] == "", "the widget wrote a date back into a cleared box"
    assert found["cleared"]["selected"] == []
    # **And the month it is cleared ON, which is half the claim and was missing.**
    # `update()` forces `viewDate: undefined`, so an empty input field sends the
    # library to `defaultViewDate` — today — and the grid left the month the
    # reader was looking at. A test that asked only whether the selection went
    # passed against a widget that threw the reader out of December on its way.
    assert found["cleared"]["shown"] == "December 2026", (
        "clearing the box moved the grid off the month it was drawing"
    )
    assert found["cleared"]["live"] == "December 2026"

    # The keystroke path, which is where this costs somebody something: every
    # half-typed date reads `''`, so a backspace in the year is a clear.
    assert found["typed"]["shown"] == "February 2027", "the grid did not follow what was typed"
    assert found["backspaced"]["picker"] is None
    assert found["backspaced"]["shown"] == "February 2027", (
        "one backspace in the year threw the reader out of the month they were on"
    )
    assert found["backspaced"]["live"] == "February 2027"


PICK_A_DAY = """
  const box = document.getElementById('start');
  const form = document.getElementById('edit');
  const heard = [];
  form.addEventListener('input', (event) => heard.push('input:' + event.target.id));
  form.addEventListener('change', (event) => heard.push('change:' + event.target.id));

  openCalendar(box);
  // A day this month, by its own number: a spill-over cell would commit a date
  // in a month this grid is not drawing, which is a different claim.
  const cell = [...document.querySelectorAll('.datepicker-cell.day')].find((one) =>
    !one.classList.contains('prev') && !one.classList.contains('next')
    && one.firstChild.nodeValue === '21');
  cell.click();
  return {value: box.value, heard, clicked: cell.firstChild.nodeValue};
"""


def test_picking_a_day_tells_the_page_the_way_a_date_field_would(
    seed_index: Index, tmp_path: Path
):
    """The other end of the same channel, and it was open. Measured: clicking a
    day wrote `2026-08-21` into the box and the form heard nothing at all.

    `refreshUI` ASSIGNS `inputField.value`, and a value assigned by script fires
    no event — the fact `resetEdits` is written around — while the only thing the
    library dispatches is its own `changeDate`, which nothing outside
    `calendar.py` listens for. The record page marks itself dirty from `input` and
    `change` on the form (`FORM.addEventListener` in `detail.py`) and the table
    commits a cell from `change`, so a day picked in this popup was an edit the
    save bar did not know about and a cell that never committed: the new date on
    screen and nothing holding it, until a reload took it away.

    Both events and in this order, because that is what a native date field fires
    when a person picks a date, and every page here was written against one.
    """
    page = _page_with_a_date_field(seed_index, date(2026, 8, 17))
    found = measured_in(chrome(), page, tmp_path / "calendar.html", 1280, PICK_A_DAY)

    assert found["clicked"] == "21", "this test clicked something other than a day"
    assert found["value"].endswith("-21"), "the picker did not write the day that was clicked"
    assert found["heard"] == ["input:start", "change:start"]


def test_replacing_a_tbody_takes_its_calendars_with_it(seed_index: Index, tmp_path: Path):
    """The second path that sets a date field from outside: the table's `draw()`,
    which assigns `tbody.innerHTML` and throws every row away.

    The open question was whether a popup survives that. It is the library's
    `container` option that decides it — with one, the popup is appended to that
    element and would outlive the row it belongs to; without one, `Picker` does
    `inputField.after(this.element)` and the popup is the input's next sibling, so
    a replaced tbody takes both. No `container` is passed, and this is that
    measurement rather than a reading of the source: pass one and the count below
    stays at two, which is a popup anchored to a cell that no longer exists,
    still listening on `document`.

    So there is no `destroy()` in `calendarFor` — the fix that would be needed if
    this answered the other way — and this is what says it is still not needed.
    """
    page = _page_with_a_date_field(seed_index, date(2026, 8, 17))
    found = measured_in(chrome(), page, tmp_path / "calendar.html", 1280, """
      // The form's own box first, and it is the control: it is not in the
      // tbody, so it has to be there afterwards. A count that went to zero
      // would say the redraw took every calendar on the page, which is a
      // different and much worse answer than the one this is asking for.
      document.getElementById('start').focus();
      // Then the table's own gesture, on the table's own shape: a row built at
      // runtime, a picker opened in its cell, and then `tbody.innerHTML = …`,
      // which is the line `draw()` ends on.
      const table = document.createElement('table');
      table.innerHTML = '<tbody id="rows"><tr><td>'
        + '<input type="date" id="cell" value="2026-08-17"></td></tr></tbody>';
      document.body.appendChild(table);
      const cell = document.getElementById('cell');
      cell.focus();
      const opened = document.querySelectorAll('.datepicker').length;
      document.getElementById('rows').innerHTML =
        '<tr><td><input type="date" id="cell2" value="2026-08-17"></td></tr>';
      const left = document.querySelectorAll('.datepicker').length;
      // A stray click anywhere is what the library's own outside-click listener
      // answers, and a dead picker answering it is how this fails loudly rather
      // than by leaking.
      let threw = null;
      try { document.body.click(); } catch (error) { threw = String(error); }
      return {opened, left, threw, alive: document.querySelectorAll('.datepicker').length};
    """)

    # Two: the form's, and the cell's. Without this the count below proves
    # nothing — a redraw that removes a popup that was never built is not a
    # measurement of anything.
    assert found["opened"] == 2, "focusing the cell built no calendar, so nothing was redrawn"
    assert found["left"] == 1, "a calendar outlived the row it was anchored to"
    assert found["threw"] is None
    assert found["alive"] == 1


# --------------------------------------------------------------------------- #
# The chip row
# --------------------------------------------------------------------------- #

CHIPS = """
  const box = document.getElementById('start');
  const form = document.getElementById('edit');
  // A form that answers `submit` at all, because the claim is that nothing here
  // ever asks it to. A bare <button> inside a form is a submit button, and the
  // library puts this popup inside whatever form the box is in.
  let submitted = 0;
  form.addEventListener('submit', (event) => { submitted += 1; event.preventDefault(); });
  const heard = [];
  form.addEventListener('change', (event) => heard.push('change:' + event.target.id));

  openCalendar(box);
  // `null` rather than a throw when there is no row, because a script that dies
  // on the missing thing reports nothing at all — and "the page reported
  // nothing" is the harness's sentence for a page that never laid out. A row
  // that stopped being drawn has to arrive as the assertion below.
  const row = document.querySelector('.cyc-chips');
  const chips = row ? [...row.querySelectorAll('button')] : [];
  const chosen = () => [...document.querySelectorAll('.datepicker-cell.selected')].map(
    (cell) => [cell.firstChild.nodeValue, cell.getAttribute('aria-label'),
               cell.getAttribute('aria-selected')]);

  // Nothing below can be asked of a row that is not there, and the assertion
  // that says so is `drawn`.
  if (chips.length) {
    chips[0].focus();
    chips[0].click();
  }

  return {
    drawn: !!row,
    // Where the row sits in the popup's own tree. `.datepicker` is only the
    // dropdown's positioning box; the card is `.datepicker-picker`, and a row
    // appended to the outer one floats beside the calendar rather than under it.
    inCard: row ? row.parentElement.className === 'datepicker-picker' : null,
    last: row ? row.parentElement.lastElementChild === row : null,
    insideForm: row ? !!row.closest('form') : null,
    count: chips.length,
    labels: chips.map((chip) => chip.textContent),
    names: chips.map((chip) => chip.getAttribute('aria-label')),
    types: chips.map((chip) => chip.getAttribute('type')),
    tabbable: chips.every((chip) => chip.tabIndex >= 0),
    // The row is inside a popup as wide as the grid, so a row wider than the
    // card is a row drawn outside the box it belongs to.
    fits: row ? row.getBoundingClientRect().width
      <= row.parentElement.getBoundingClientRect().width : null,
    value: box.value,
    submitted: submitted,
    heard: heard,
    shown: document.querySelector('.view-switch').textContent,
    live: document.querySelector('.datepicker [aria-live]').textContent,
    selected: chosen(),
    open: !!document.querySelector('.datepicker.active'),
    // Where a reader's focus is after the press, and whether they can see it.
    focusHidden: document.activeElement
      ? !document.activeElement.getClientRects().length : null,
  };
"""


def test_a_chip_per_cycle_sets_the_date_to_the_day_that_cycle_opens(
    seed_index: Index, tmp_path: Path
):
    """The day a cycle opens is the date most of these fields are being set to,
    and the gesture this replaces is pressing Next eleven times to reach it.

    Every claim the row makes is asked here at once because they are one control:
    it is a real button rather than a hint, it carries a name a reader who is not
    looking at it can find, it is `type="button"` because the library puts this
    popup inside the form the box is in and a bare `<button>` in a form submits
    it, and pressing it writes the date and tells the page — which nothing in
    this widget did until the same commit that taught the day cells to.
    """
    page = _page_with_a_date_field(seed_index, date(2026, 8, 17))
    found = measured_in(chrome(), page, tmp_path / "calendar.html", 1280, CHIPS)
    windows = seed_index.cycle_windows()

    assert found["drawn"], "the popup carries no chip row at all"
    assert found["inCard"] and found["last"], "the chips are not inside the popup's card"
    assert found["insideForm"], "the popup did not open inside a form, so `type` proves nothing"
    assert found["fits"], "the chip row is wider than the popup it is drawn in"

    assert found["count"] == len(windows)
    assert found["labels"] == [f"C{window.number}" for window in windows]
    assert found["types"] == ["button"] * len(windows)
    assert found["tabbable"], "a control a pointer can reach and a keyboard cannot"
    # A name, and the right one: a `<button>` falls back to its own text, so
    # `assert name` alone passes on "C34" — three glyphs, which is not a name.
    for window, name in zip(windows, found["names"], strict=True):
        assert f"cycle {window.number}" in name, name
        assert name != f"C{window.number}"

    assert found["submitted"] == 0, "pressing a chip submitted the form it opened inside"
    assert found["value"] == windows[0].opens.isoformat()
    assert found["heard"] == ["change:start"], "the page was not told the date had moved"

    # What the press looks like, which is the only confirmation it happened.
    year = windows[0].opens.year
    assert str(year) in found["shown"] and str(year) in found["live"]
    assert [cell[0] for cell in found["selected"]] == [str(windows[0].opens.day)]
    # And the names were rebuilt for the month it moved to: the library reuses
    # its forty-two cells, so a name left alone is the old month's name on the
    # new month's day.
    assert str(year) in found["selected"][0][1], found["selected"][0][1]
    assert found["selected"][0][2] == "true"

    # The popup stays up, and the reason is the reader's focus: a chip is a
    # focusable control inside the popup, unlike the day cell it stands for, so
    # closing on the press strands `document.activeElement` on a `display: none`
    # button. Measured — that is what it did.
    assert found["open"], "the popup shut itself under the control that was just pressed"
    assert found["focusHidden"] is False, "focus was left on something nobody can see"


def test_a_chip_moves_the_grid_even_when_it_names_the_date_already_chosen(
    seed_index: Index, tmp_path: Path
):
    """The library skips the re-render when the new date equals the selection, so
    without `forceRefresh` a chip pressed from three months away moved nothing at
    all — and moved the grid when pressed from anywhere else.

    A control that works on some presses and not others is one nobody can learn,
    and this is the press where it fails: the reader is looking at a month, the
    chip names the cycle they already chose, and the answer to "take me there" is
    the grid standing still.
    """
    page = _page_with_a_date_field(seed_index, date(2026, 8, 17))
    found = measured_in(chrome(), page, tmp_path / "calendar.html", 1280, """
      const box = document.getElementById('start');
      // The form answers `submit` by refusing, and that is not politeness. A
      // chip that lost its `type="button"` submits this form, the page reloads,
      // the injected script runs again and presses the chip again — measured,
      // and it does not stop: Chrome's virtual clock restarts on the
      // navigation, so the run never ends and nothing is ever reported. A
      // regression has to fail as an assertion and not as a hung CI leg.
      document.getElementById('edit').addEventListener('submit',
        (event) => event.preventDefault());
      openCalendar(box);
      const chip = document.querySelector('.cyc-chips button');
      // Same reason as in CHIPS: a script that throws on the missing row
      // reports nothing at all, and nothing at all is what the harness says
      // when a page never laid out.
      if (!chip) return {missing: true};
      chip.click();
      const arrived = document.querySelector('.view-switch').textContent;
      // Three months away, by the popup's own control.
      for (let step = 0; step < 3; step += 1) {
        document.querySelector('.datepicker-controls .next-btn').click();
      }
      const wandered = document.querySelector('.view-switch').textContent;
      chip.click();
      return {
        arrived, wandered,
        back: document.querySelector('.view-switch').textContent,
        live: document.querySelector('.datepicker [aria-live]').textContent,
        value: box.value,
      };
    """)
    opens = seed_index.cycle_windows()[0].opens

    assert not found.get("missing"), "the popup carries no chip row at all"
    assert found["wandered"] != found["arrived"], "the grid did not move, so nothing was tested"
    assert found["back"] == found["arrived"], "the chip did nothing the second time"
    # The live region as well as the header: the month a reader hears has to be the
    # month a reader sees, and a re-render that skipped `describeGrid` would
    # leave the two disagreeing.
    assert found["live"] == found["back"]
    assert found["value"] == opens.isoformat()


def test_a_plan_with_no_dated_cycle_gets_a_calendar_and_no_chip_row(
    seed_root: Path, tmp_path: Path
):
    """A chip row with no chips is a border and a gap saying nothing, under a
    calendar that is otherwise exactly a calendar. Empty must not look like
    broken — and the popup that opens here is the plain one, not a missing one.
    """
    records, config, _ = load_repo(seed_root)
    index = build_index(records, config.model_copy(update={"cycles": {}}), TODAY)
    page = _page_with_a_date_field(index, date(2026, 8, 17))
    found = measured_in(chrome(), page, tmp_path / "calendar.html", 1280, """
      openCalendar(document.getElementById('start'));
      return {
        rows: document.querySelectorAll('.cyc-chips').length,
        opened: !!document.querySelector('.datepicker.active'),
        days: document.querySelectorAll('.datepicker-cell.day').length,
        banded: document.querySelectorAll('.datepicker-cell.cyc').length,
      };
    """)

    assert found["opened"], "a plan with no dated cycle got no calendar at all"
    assert found["days"] == 42, "the grid did not draw"
    assert found["banded"] == 0
    assert found["rows"] == 0, "an empty chip row was drawn"


# --------------------------------------------------------------------------- #
# On the pages
# --------------------------------------------------------------------------- #
#
# The widget is imported by the pages that want it, not carried by the shell —
# the same shape `_FILTER_JS`, `_REQUIRED_JS` and the combobox already have, and
# the same reason `pop.py` gives for its own: `shell.py` ships on all twelve
# pages, and two of them — `/help` and `/people` — have no date field anywhere
# on them. Measured on the frozen corpus, the block is 53 KB of script and 7 KB
# of stylesheet.


def _sheet_of_everything(page: str) -> Sheet:
    """Every `<style>` block a page serves, concatenated in document order.

    `cascade.sheet_of` reads the first one, which is the shell's and holds the
    page's own sheet inlined into it. That is the whole sheet on nine of the
    eleven pages and not on the record page, which appends Ace's look and the
    editing surface's after it — and later is exactly what wins a tie. The
    calendar's cell rules are written to win theirs on source order, so a
    question about them has to see everything written after them.
    """
    return Sheet("\n".join(re.findall(r"<style>(.*?)</style>", page, re.S)))


class _Chain(HTMLParser):
    """The open elements above the first `<input type="date">` on a page."""

    VOID = frozenset("area base br col embed hr img input link meta source track wbr".split())

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._open: list[El] = []
        self.found: list[El] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        got = {k: v or "" for k, v in attrs}
        if tag == "input" and got.get("type") == "date" and self.found is None:
            self.found = list(self._open)
        if tag not in self.VOID:
            self._open.append(
                el(tag, got.get("class", ""), got.get("id", ""))
            )

    def handle_endtag(self, tag: str) -> None:
        for depth in range(len(self._open) - 1, -1, -1):
            if self._open[depth].tag == tag:
                del self._open[depth:]
                return


def _where_the_box_is(page: str) -> list[El]:
    """The real ancestry of a date box on a rendered page, parsed off it.

    The library inserts the popup with `inputField.after()`, so a day cell's
    ancestors are these elements and then `.datepicker > .datepicker-picker >
    .datepicker-grid`. Derived and not typed out, because it is the part that
    moves: the record page's box sits in `form#edit > .panes > aside.facts >
    dl#facts > dd`, and every one of those is a name some other stylesheet on
    the page selects on.
    """
    parser = _Chain()
    parser.feed(page)
    assert parser.found is not None, "this page draws no date box to hang a popup off"
    return parser.found


def _boxes_in(page: str) -> list[str]:
    """The id of every `<input type="date">` the markup really holds.

    Parsed and not searched for: `type="date"` appears in the prose of
    `table.py`'s own stylesheet, in `calendar.py`'s selectors and in four
    comments, all of which ship inside the page.
    """
    return [
        one.attrs.get("id", "")
        for one in elements(page)
        if one.tag == "input" and one.attrs.get("type") == "date"
    ]


@pytest.fixture
def surfaces(seed_index: Index) -> dict[str, tuple[str, bool]]:
    """Every page, in both modes, beside whether a date box can appear on it.

    The second half of each pair is the rule and not a recording: a page earns
    the calendar by having somewhere for a date box to be, and it is written
    down here per page because for one of them — the table — it is not a
    question the rendered markup can answer.
    """
    head = "0123456789abcdef0123456789abcdef01234567"
    one = sorted(seed_index.plan)[0]
    number = max(seed_index.cycles)
    return {
        # The record page and the create form: `_control_html` draws a date as
        # text for a reader, so the read-only page — which is what the export
        # writes to `detail.html` — holds no box at all.
        "record": (render_detail(seed_index, ROUTES, only=one, base_commit=head), True),
        "new": (render_detail(seed_index, ROUTES, base_commit=head, creating="task"), True),
        "record (reader)": (render_detail(seed_index, ROUTES, only=one), False),
        # **The table serves no date box in its markup and still needs the
        # widget.** Every cell is drawn by `draw()` and the box is built by
        # `openEditor` when one is opened, so a rule written as "the document
        # holds an `input[type=date]`" would have taken the calendar off the one
        # page that makes date boxes for a living. The gate is `editable`, which
        # is what the cell editor is behind.
        "table": (render_table(seed_index, ROUTES, base_commit=head, may_write=True), True),
        "table (reader)": (render_table(seed_index, ROUTES, base_commit=head), False),
        # The cycle page draws `#setup` in both modes — it has no reading/editing
        # toggle — so a reader has the two boxes and gets the popup on them.
        "cycle": (render_cycle(seed_index, number, ROUTES, base_commit=head), True),
        "cycle (reader)": (render_cycle(seed_index, number, ROUTES), True),
        # The listing's two boxes are in "Start a cycle", which is inside the
        # template's `{% if editable %}`.
        "cycles": (render_cycles(seed_index, ROUTES, base_commit=head), True),
        "cycles (reader)": (render_cycles(seed_index, ROUTES), False),
        # `#tl-from` and `#tl-to` say which slice of the calendar is drawn, which
        # is a question a reader asks too. The one exported page with a date box.
        "timeline": (render_timeline(seed_index, ROUTES), True),
        # The four with no date field anywhere on them, in the mode that carries
        # the most: a page that grew 60 KB for a control it does not have would
        # otherwise grow it quietly.
        "graph": (render_graph(seed_index, ROUTES, base_commit=head, may_write=True), False),
        "records": (render_records(seed_index, ROUTES), False),
        "people": (render_people(seed_index, ROUTES, editable=True), False),
        "help": (render_help(seed_index, ROUTES), False),
    }


def test_a_page_carries_the_calendar_exactly_where_a_date_box_can_appear(
    surfaces: dict[str, tuple[str, bool]],
):
    """Both halves, because they are two edits in two files.

    The script is a template slot and the stylesheet is a `+` in the `_page`
    call, so a page can be given one without the other — and a page with the
    glue and no sheet is a popup drawn as a column of unstyled text over the
    form, while a page with the sheet and no glue is 7 KB nothing will ever
    match. The sheet is asked of the cascade rather than of a substring:
    `datepicker` is a word in the bundle, in this module's prose and in the
    licence notice, all of which ship inside the page.
    """
    for name, (page, wanted) in surfaces.items():
        sheet = _sheet_of_everything(page)
        glue = "const CYCLE_WINDOWS = " in page
        painted = sheet.winner(day("cyc"), "background") is not None
        assert glue is wanted, f"{name}: script {'present' if glue else 'missing'}"
        assert painted is wanted, f"{name}: stylesheet {'present' if painted else 'missing'}"
        # And the derived half, which cannot go stale: whatever the table above
        # says, a page that really does draw a date box needs the popup on it.
        if _boxes_in(page):
            assert glue, f"{name} draws {_boxes_in(page)} and carries no calendar"


def test_the_export_carries_the_calendar_on_the_one_page_that_has_a_date_box(
    seed_index: Index, tmp_path: Path
):
    """`render_static` renders these same templates with no server at all, and
    every one of them with `base_commit=None`.

    So the export is not "the served pages minus the routes": it is the reader's
    mode of each, where the record page and the table draw their dates as text
    and the listing has no create form. `timeline.html` is the only exported
    page with a date box in it, because the window controls are a reader's
    controls. A second page appearing here is 60 KB in a directory somebody
    mails, and it would arrive silently.
    """
    render_static(seed_index, tmp_path)
    carried = {
        path.name
        for path in sorted(tmp_path.glob("*.html"))
        if "const CYCLE_WINDOWS = " in path.read_text(encoding="utf-8")
    }
    assert carried == {"timeline.html"}
    for path in sorted(tmp_path.glob("*.html")):
        page = path.read_text(encoding="utf-8")
        if _boxes_in(page):
            assert path.name in carried, f"{path.name} draws a date box and carries no calendar"


# The cells whose ground the sheet decides, and the rule that has to decide it.
# The same five the isolated resolution above asks about, because the claim here
# is not that the ladder is right — that is settled — but that nothing a real
# page brings with it gets in front of the answer.
# The surfaces whose date boxes exist only once a script has run, beside the
# ancestry a popup on one really hangs off.
#
# **This is the page this test's docstring is about, and it was the page the
# test skipped.** `_where_the_box_is` parses the served markup, and the table
# serves no `input[type="date"]` at all: every cell is drawn by `draw()` and the
# box is built inside `td.edit` by `openEditor`. So the `td.edit` ancestry named
# above was never resolved against — delete every calendar rule from
# `_CALENDAR_STYLE` and the table leg still passed, because there was no table
# leg.
#
# Written out rather than parsed off anything, because there is nothing to parse
# it off. A `tr` carries no class in its resting state, and `cell()` writes
# `data-col` on the `td` — left out on purpose: the frozen-column rules select
# on it, and what this asks is whether the popup wins where the plainest cell
# puts it. A cell with more attributes can only bring more rules to lose.
_BUILT_BY_A_SCRIPT = {
    "table": [
        el("div", "table-scroll"),
        el("table", "", "rows"),
        el("tbody"),
        el("tr"),
        el("td", "edit"),
    ],
}


_ON_A_REAL_PAGE = [
    ("an even cycle", "cyc", ".datepicker-cell.cyc"),
    ("an odd cycle", "cyc cyc-alt", ".datepicker-cell.cyc-alt"),
    ("a cool-down", "cyc cyc-cool", ".datepicker-cell.cyc-cool"),
    ("an odd cool-down", "cyc cyc-alt cyc-cool", ".datepicker-cell.cyc-alt.cyc-cool"),
    ("the selected day", "cyc cyc-alt cyc-cool selected", ".datepicker-cell.selected.cyc-cool"),
]


def test_the_calendars_cells_still_win_against_the_page_they_were_put_on(
    surfaces: dict[str, tuple[str, bool]],
):
    """A page carrying the widget is a page whose cascade is no longer this
    sheet in isolation.

    The muting at the top of `_CALENDAR_STYLE` was deliberately weakened to
    (0,2,0) so that the `.selected` block below it could take the tie on order.
    Three of the five band fills are (0,2,0) as well. A rule that wins on order
    alone wins only against what is written before it — and five stylesheets are
    now written before it, plus the shell's, on pages whose date boxes sit
    inside `dl#facts`, `p.editbar`, `form.tl-controls` and `td.edit`.

    So the resolution is asked again with the page's own ancestry above the
    popup and every rule the page serves in the sheet, and it is asked of the
    cells, the chip row and the header's buttons — the three places the widget
    borrows a class name (`.button`, `button`, `.day`) that these pages already
    use for something else.

    That ancestry is parsed off the served markup where there is one to parse,
    and taken from `_BUILT_BY_A_SCRIPT` where the boxes are built at runtime —
    which is the table, the one page of the five whose `td.edit` this docstring
    has always named. It served no date box, so it fell out of the loop and was
    never resolved against at all.
    """
    for name, (page, wanted) in surfaces.items():
        if not wanted:
            continue
        sheet = _sheet_of_everything(page)
        above = _BUILT_BY_A_SCRIPT.get(name)
        if above is None:
            # **A surface that cannot be resolved against must not drop out of
            # this census in silence.** The skip this replaces read `if not
            # wanted or not _boxes_in(page): continue`, and a page that stopped
            # drawing a date box would have stopped being asked the question
            # instead of failing it.
            assert _boxes_in(page), (
                f"{name} is marked as carrying the calendar and its markup holds "
                "no date box. Either it stopped drawing one — in which case the "
                "table above is wrong — or its boxes are now built by a script, "
                "and it belongs in `_BUILT_BY_A_SCRIPT` beside the ancestry they "
                "are built into."
            )
            above = _where_the_box_is(page)
        for what, classes, selector in _ON_A_REAL_PAGE:
            path = above + day(classes)
            won, value = decided_by(sheet, path, "background")
            assert won == selector, (
                f"{name}: {what} is grounded by `{won} {{ background: {value} }}`,\n"
                f"not by the calendar's own `{selector}`. Everything reaching it:\n"
                + losers(sheet, path, "background")
            )
        # The chip row's controls are bare `<button>`s inside a form on four of
        # these five pages, and `#setup button`, `.editbar button` and
        # `.tl-controls .acts button` are all rules that exist.
        chips = above + [
            el("div", "datepicker"),
            el("div", "datepicker-picker"),
            el("div", "cyc-chips"),
            el("button"),
        ]
        won, value = decided_by(sheet, chips, "background")
        assert won == ".cyc-chips button", (
            f"{name}: a chip is grounded by `{won} {{ background: {value} }}`\n"
            + losers(sheet, chips, "background")
        )
        # And the month arrows, which the library gives the class every primary
        # control on these pages already wears.
        arrow = above + [
            el("div", "datepicker"),
            el("div", "datepicker-picker"),
            el("div", "datepicker-header"),
            el("div", "datepicker-controls"),
            el("button", "button prev-btn"),
        ]
        won, value = decided_by(sheet, arrow, "background")
        assert won == ".datepicker-controls .button", (
            f"{name}: a month arrow is grounded by `{won} {{ background: {value} }}`\n"
            + losers(sheet, arrow, "background")
        )


# The five grounds and the spill-over's ink, forced onto a cell the library
# really built rather than onto a div made here — the classes are ours, the
# element and its place in the popup are the library's.
_PAINTED = """
  const box = document.querySelector('input[type="date"]');
  openCalendar(box);
  const cells = [...document.querySelectorAll('.datepicker-grid .datepicker-cell.day')];
  const paint = (classes) => {
    const cell = cells[10];
    const was = cell.className;
    cell.className = 'datepicker-cell day ' + classes;
    const seen = [getComputedStyle(cell).backgroundColor, getComputedStyle(cell).color];
    cell.className = was;
    return seen;
  };
  const root = getComputedStyle(document.documentElement);
  return {
    accent: root.getPropertyValue('--accent').trim(),
    onAccent: root.getPropertyValue('--on-accent').trim(),
    grounds: {
      cyc: paint('cyc'),
      alt: paint('cyc cyc-alt'),
      cool: paint('cyc cyc-cool'),
      altcool: paint('cyc cyc-alt cyc-cool'),
      selected: paint('cyc cyc-alt cyc-cool selected'),
      spill: paint('next'),
    },
  };
"""


def _hex(value: str) -> str:
    """`rgb(15, 92, 107)` as `#0f5c6b`, so a painted pixel can be compared with
    the token it is meant to be."""
    numbers = re.findall(r"\d+", value)
    return "#" + "".join(f"{int(one):02x}" for one in numbers[:3])


def test_a_real_page_paints_the_ladder_in_five_colours_and_not_in_none(
    seed_index: Index, tmp_path: Path
):
    """The one claim the resolver cannot make, asked on two pages that share no
    stylesheet but the shell's.

    **The host the driven tests above use defines no colour tokens at all.**
    It is `_CALENDAR_STYLE` and the widget on a bare document, so `var(--band)`
    resolves to nothing and every band cell in those nine tests is painted
    `rgba(0, 0, 0, 0)` over black. That is the right host for the questions they
    ask — classes, names, the live region, what a chip does — and it is exactly
    the wrong one for this: a ladder of five fills that is really one
    transparent cell five times over would pass every one of them.

    So it is asked where the tokens are, on the record page and on the timeline
    — `_DETAIL_STYLE` and `_SUGGEST_STYLE` against `_timeline_css()` and
    `_POP_STYLE`, with the shell underneath both. Five distinct grounds, the
    selected day on the page's own `--accent` in its own `--on-accent`, and the
    two pages agreeing to the byte.
    """
    head = "0123456789abcdef0123456789abcdef01234567"
    seen = {
        name: measured_in(chrome(), page, tmp_path / f"{name}.html", 1280, _PAINTED)
        for name, page in (
            (
                "record",
                render_detail(
                    seed_index,
                    ROUTES,
                    only=sorted(seed_index.plan)[0],
                    base_commit=head,
                    may_write=True,
                ),
            ),
            ("timeline", render_timeline(seed_index, ROUTES)),
        )
    }

    for name, found in seen.items():
        grounds = found["grounds"]
        # The four band fills, each a real colour and each its own. `color-mix`
        # comes back as an unresolved `oklab(...)` and a flat token as `rgb(...)`,
        # so they are compared as strings — which is all "these are five
        # different fills" needs.
        rungs = ("cyc", "alt", "cool", "altcool", "selected")
        ladder = [grounds[rung][0] for rung in rungs]
        assert len(set(ladder)) == 5, f"{name}: the ladder paints {len(set(ladder))}: {ladder}"
        for rung, painted in zip(rungs, ladder, strict=True):
            assert painted != "rgba(0, 0, 0, 0)", f"{name}: {rung} is painted nothing at all"
        # The selected day is the answer to the question the popup was opened to
        # ask, and the sentence for that here is "it takes the accent".
        assert _hex(grounds["selected"][0]) == found["accent"], name
        assert _hex(grounds["selected"][1]) == found["onAccent"], name
        # And the spill-over rung, which is the one the ladder was weakened for:
        # no ground of its own, and ink that is not the ink of a day in the month.
        assert grounds["spill"][0] == "rgba(0, 0, 0, 0)", f"{name}: a spilled day took a ground"
        assert grounds["spill"][1] != grounds["cyc"][1], f"{name}: a spilled day is not muted"

    assert seen["record"]["grounds"] == seen["timeline"]["grounds"], (
        "the calendar is painted differently on two pages that carry the same sheet"
    )


# --------------------------------------------------------------------------- #
# Under a thumb
# --------------------------------------------------------------------------- #

def _a_bare_date_box(index: Index) -> str:
    """One date box and the whole widget, with nothing sizing the box.

    It is here because the app's own boxes are all given a width — 350, 192, 147
    and 146 pixels on the four pages below — and a box whose width is written
    down cannot show whether the native indicator is taking room inside it. The
    viewport tag is not decoration: without one Chrome lays a `mobile` override
    out at 980px, which is the first thing `measured_on_a_phone` asserts.
    """
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width">'
        f"<style>{calendar_module._CALENDAR_STYLE}</style></head>"
        '<body><input type="date" value="2026-08-17">'
        f"{_calendar_js(index)}</body></html>"
    )


# **`getComputedStyle(box, '::-webkit-calendar-picker-indicator')` cannot answer
# this.** Measured: on a bare page it reports `display: inline-block` and a width
# of 120px for an input 125px wide — it is handing back the ORIGINATING element's
# style, not the pseudo-element's. The first version of this test read `display`
# off it, got `none` on the record page, and what it had actually read was the
# record page hiding its own boxes until the page is put into editing mode.
#
# So the indicator is measured the way a reader meets it: as room inside the box.
# Chrome's default date box is 125.3px wide and 108px with the indicator hidden.
_UNDER_A_THUMB = """
  const all = [...document.querySelectorAll('input[type="date"]')];
  const box = all.find(one => one.getClientRects().length);
  if (!box) return {missing: true, boxes: all.length};
  box.focus();
  box.dispatchEvent(new KeyboardEvent('keydown',
    {key: 'ArrowDown', altKey: true, bubbles: true}));
  const declined = !document.querySelector('.datepicker.active');
  // And then it is told to open, which is what makes the line above a refusal
  // rather than a page with no widget on it. A synthetic `keydown` is
  // `isTrusted: false` and runs no default action — which is wanted, since the
  // listener is a plain `addEventListener` and fires either way.
  let told = null;
  if (typeof openCalendar === 'function') {
    openCalendar(box);
    told = !!document.querySelector('.datepicker.active');
  }
  return {
    width: innerWidth,
    fine: matchMedia('(pointer: fine)').matches,
    coarse: matchMedia('(pointer: coarse)').matches,
    box: Math.round(box.getBoundingClientRect().width * 100) / 100,
    declined: declined,
    told: told,
  };
"""

# 4 is POINTER_FINE and 2 is HOVER_HOVER, said at launch because
# `Emulation.setEmulatedMedia` ignores both features outright — the same flags
# and the same measurement `test_render.py` records for the hover wash. Not
# `primaryPointerType=1`, which is `none` rather than `coarse`: under it both
# `(pointer: fine)` and `(pointer: coarse)` are false, so a rule written for a
# thumb is switched off beside the rule written for a mouse.
_A_MOUSE = (
    "--blink-settings=primaryHoverType=2,availableHoverTypes=2,"
    "primaryPointerType=4,availablePointerTypes=4",
)


def test_a_phone_keeps_the_native_picker_and_our_popup_stays_shut(
    seed_index: Index, tmp_path: Path
):
    """The first `pointer: coarse` rule in this codebase, asked through
    `measured_on_a_phone` and not through a narrow window.

    `--window-size` floors at 500px and 500px is above the one narrow breakpoint
    these pages have, so a phone claim asked any other way is a claim about a
    desktop wearing a phone's name. The metrics override has no floor — and, as
    of the same commit as this test, it emulates touch as well, because on its
    own it left the page reporting `(pointer: fine)`, `(hover: hover)` and
    `maxTouchPoints` 0 at a width of 390.

    Two halves and both are asserted, because hiding the native indicator
    without shutting our popup — or shutting it without leaving the indicator —
    is a date field with no picker at all, which is worse than either alone.
    The script half is asked on the four pages whose boxes are on screen, both
    through `focusin` and through Alt+Down, which are two `FINE.matches` gates
    and not one; and each page is then told to open the calendar, so that a
    refusal is told apart from a page that has no calendar to refuse with.

    The record page is not among them and the create form stands in for it: a
    record somebody is only READING draws its dates as text and its boxes are
    `display: none`, so a focus there refuses for a reason that has nothing to do
    with a thumb. Same template, same stylesheet, editing mode already on — the
    argument `tests/test_cascade.py` makes for the same substitution.
    """
    head = "0123456789abcdef0123456789abcdef01234567"
    number = max(seed_index.cycles)
    host = _a_bare_date_box(seed_index)
    pages = {
        "new": render_detail(seed_index, ROUTES, base_commit=head, may_write=True, creating="task"),
        "cycle": render_cycle(seed_index, number, ROUTES, base_commit=head),
        "cycles": render_cycles(seed_index, ROUTES, base_commit=head),
        "timeline": render_timeline(seed_index, ROUTES),
        "a bare box": host,
    }
    on_a_phone = measured_on_a_phone(chrome(), pages, tmp_path / "phone", _UNDER_A_THUMB)

    for page, found in on_a_phone.items():
        assert not found.get("missing"), f"{page} has no date box on screen: {found}"
        assert found["width"] == 390, f"{page} laid out at {found['width']}, not at a phone's width"
        assert found["coarse"] and not found["fine"], (
            f"{page}: the emulated phone reports {found} — the harness is the thing under test"
        )
        assert found["declined"] is True, f"{page}: our popup opened under a thumb"
        assert found["told"] is True, (
            f"{page} could not open the calendar when told to, so it never had one to decline"
        )

    # The stylesheet's half, in the only unit a hidden indicator has: the room it
    # is not taking. Against the same box under a mouse rather than against a
    # number written down here, so what is asserted is the difference the media
    # query makes and not Chrome's default metrics.
    with_a_mouse = measured_in(
        chrome(), host, tmp_path / "mouse.html", 1280, _UNDER_A_THUMB, flags=_A_MOUSE
    )
    assert with_a_mouse["fine"] and not with_a_mouse["coarse"], with_a_mouse
    assert with_a_mouse["told"] is True, "the widget did not open for a mouse either"
    assert with_a_mouse["declined"] is False, (
        "Alt+Down did not open the popup for a mouse, so the keyboard has no door"
    )
    assert with_a_mouse["box"] < on_a_phone["a bare box"]["box"], (
        f"the same box is {with_a_mouse['box']}px under a mouse and "
        f"{on_a_phone['a bare box']['box']}px under a thumb — the native indicator is "
        f"taking the same room in both, so one of the two readers has two pickers or none"
    )
