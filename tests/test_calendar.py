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
