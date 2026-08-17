"""What the served stylesheet actually resolves to, on the elements it is about.

Every assertion anybody had written about these rules was a substring search for
the rule's own text, and a rule being present says nothing about whether it wins.
Three of them did not: qualifying the two frozen columns by `.table-scroll` took
them from (0,1,0) to (0,2,0), which outranks the three rules written to correct
them — so both frozen headers were painted over by their own rows, the title
header lost the line along its bottom edge, and a blocking problem on the id
column, which is the catch-all for any problem whose field has no column of its
own, got no ground. The suite stayed green through all of it.

So these ask a cascade engine instead: for this element and this property, which
rule wins and what does it say. See `tests/cascade.py`.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from cascade import El, Sheet, el, sheet_of, split_list

from openproj.index import Index, build_index
from openproj.model import load_repo
from openproj.render import (
    ROUTES,
    render_cycle,
    render_cycles,
    render_detail,
    render_table,
    render_timeline,
)

HEAD = "0123456789abcdef0123456789abcdef01234567"


@pytest.fixture
def index(seed_root: Path) -> Index:
    entities, config = load_repo(seed_root)
    return build_index(entities, config, date(2026, 8, 17))


@pytest.fixture
def table(index: Index) -> Sheet:
    """The editable table: `_TABLE_STYLE` and then `_SUGGEST_STYLE`, after the
    shell — which is the order that decides every tie below."""
    return sheet_of(render_table(index, ROUTES, base_commit=HEAD))


# --------------------------------------------------------------------------- #
# Where the cells are
# --------------------------------------------------------------------------- #

PAGE = [el("body"), el("main", id="main")]
SCROLL = PAGE + [el("div", "table-scroll"), el("table", id="rows")]
# The same table with the class its scroll handler adds once `scrollLeft > 0`.
# The frozen pair's right edge is drawn from here and nowhere else, so the two
# states are two different elements as far as this engine is concerned.
SCROLLED = PAGE + [el("div", "table-scroll scrolled"), el("table", id="rows")]
# The table itself, for the one property every shadow on it depends on.
TABLE = SCROLL


def header(column: str, classes: str = "", within: list[El] | None = None) -> list[El]:
    return (within or SCROLL) + [el("thead"), el("tr"), el("th", classes, data_col=column)]


def cell(
    column: str, classes: str = "", within: list[El] | None = None, states: str = ""
) -> list[El]:
    return (within or SCROLL) + [
        el("tbody"), el("tr"), el("td", classes, states=states, data_col=column)
    ]


def says(sheet: Sheet, path: list[El], prop: str) -> str:
    """The winning declaration, and every rule it beat, for a failure message."""
    reaching = sheet.selectors_reaching(path, prop)
    return "\n".join(f"  {r.specificity} {r.selector} {{ {prop}: {r.declarations[prop][0]} }}"
                     for r in reaching) or "  (no rule sets it)"


# --------------------------------------------------------------------------- #
# B1: the two frozen columns and the three rules that correct them
# --------------------------------------------------------------------------- #


def test_the_frozen_columns_keep_the_position_their_left_offset_is_meant_for(table: Sheet):
    """`left` means nothing to a static box and something else entirely to a
    relative one.

    `_SUGGEST_STYLE` used to say `dd, td.edit { position: relative }` so the
    suggestion popup had something to anchor to, and the table appends that
    stylesheet after its own. At (0,1,1) it beat the bare `[data-col="title"]`,
    so the title column kept the `left` written for a sticky box and used it as a
    relative offset instead: 187px to the right of its own header, on top of
    priority and status.
    """
    for path, offset in ((cell("id"), "0"), (cell("title", "edit"), "var(--sticky-1, 0px)")):
        assert table.value(path, "position") == "sticky", says(table, path, "position")
        assert table.value(path, "left") == offset, says(table, path, "left")
    # The header is sticky in both axes: `top` from `thead th`, `left` from the
    # column. Losing either one is a frozen column that is frozen in one place.
    assert table.value(header("title"), "position") == "sticky"
    assert table.value(header("title"), "top") == "0"
    assert table.value(header("title"), "left") == "var(--sticky-1, 0px)"


def test_the_frozen_headers_are_drawn_over_the_rows_that_pass_under_them(table: Sheet):
    """A frozen header cell is above two things at once: the rows scrolling up
    under it and the columns scrolling sideways under it. Below either, the plan
    scrolls its own header away."""
    for column in ("id", "title"):
        assert table.value(header(column), "z-index") == "4", says(
            table, header(column), "z-index")
    # Above the rest of the header, which is above the rest of the body.
    assert table.value(header("owner"), "z-index") == "3"
    assert table.value(cell("id"), "z-index") == "1"
    assert table.value(cell("title", "edit"), "z-index") == "1"
    assert table.value(cell("owner", "edit"), "z-index") is None


def test_the_title_header_keeps_the_rule_along_its_bottom_edge(table: Sheet):
    """A collapsed border is not painted on a sticky cell, so the header's bottom
    rule is an inset shadow — and the title column overwrote it with the shadow
    that draws the frozen pair's right edge. The cell needs both, and only in the
    state that has a right edge to draw."""
    drawn = table.value(header("title", within=SCROLLED), "box-shadow")
    assert drawn == "inset 0 -1px 0 var(--line), inset -1px 0 0 var(--line)", says(
        table, header("title", within=SCROLLED), "box-shadow")
    # Unscrolled it is a header like any other. This is the half that regressed:
    # the right-edge shadow replaced the bottom rule wholesale, so naming one
    # without the other is how the line along the bottom disappears again.
    assert table.value(header("title"), "box-shadow") == "inset 0 -1px 0 var(--line)", says(
        table, header("title"), "box-shadow")
    # The id header has no right edge of its own — the title column carries it
    # for the pair — so it keeps the plain bottom rule every other header has.
    assert table.value(header("id"), "box-shadow") == "inset 0 -1px 0 var(--line)"
    assert table.value(header("id", within=SCROLLED), "box-shadow") == (
        "inset 0 -1px 0 var(--line)"
    )


def test_the_frozen_edge_is_drawn_only_while_the_table_is_scrolled(table: Sheet):
    """The rule down the right of the title column says "what is left of this is
    being held still while the rest passes under it". At `scrollLeft === 0`
    nothing passes under anything and the table has no other column separators,
    so it read as one column having been singled out for a border — which is what
    the first person to use this asked about.

    It is the class, not the property, that decides: the rules that draw it are
    all under `.scrolled`, so a body cell in the resting state has no rule
    setting `box-shadow` at all.

    **What this cannot tell you is whether anything is painted**, and that is how
    the edge shipped dead. It resolved to `1px 0 0 var(--line)` — the value this
    asserted, on the element it asserted it on — and Chrome paints no *outset*
    box-shadow at all on a cell inside a `border-collapse: collapse` table, so
    there was no pixel in either state. A resolved value is a promise about
    pixels that a stylesheet cannot keep on its own.
    Two things stand behind this now: `test_a_frozen_cell_never_asks_for_an
    _outset_shadow` below, which is the rule that was broken said as an
    invariant, and `test_table.test_the_frozen_edge_is_a_pixel_a_browser_draws`,
    which opens the page in Chrome and compares the screenshots.
    """
    assert table.value(cell("title", "edit"), "box-shadow") is None, says(
        table, cell("title", "edit"), "box-shadow")
    assert table.value(cell("title", "edit", within=SCROLLED), "box-shadow") == (
        "inset -1px 0 0 var(--line)"
    ), says(table, cell("title", "edit", within=SCROLLED), "box-shadow")
    # And the ground under it is unchanged by either state: `.scrolled` adds an
    # edge, and must not win `background` off the severity rules below.
    for path in (cell("title", "edit sev-cell-blocker"),
                 cell("title", "edit sev-cell-blocker", within=SCROLLED)):
        assert table.value(path, "background") == "var(--sev-blocker-soft)", says(
            table, path, "background")


def test_a_frozen_cell_never_asks_for_an_outset_shadow(table: Sheet):
    """One fact about this table decides every shadow on it: its borders are
    collapsed, and Chrome paints no outset box-shadow on a cell in a collapsed
    table. Not a dimmer one — none.

    So on these cells `inset` is not a style choice, it is the difference between
    a line and nothing, and the file already knew it for the header's bottom rule
    while the right edge beside it was written outset and drew nothing for two
    rounds. Said here as the invariant rather than as five separate expected
    values, because the next shadow anybody adds to this table is the one this
    has to catch.
    """
    assert table.value(TABLE, "border-collapse") == "collapse", (
        "the premise of every assertion here"
    )
    for path in (header("id"), header("title"), header("owner"),
                 header("id", within=SCROLLED), header("title", within=SCROLLED),
                 cell("id"), cell("title", "edit"), cell("owner", "edit"),
                 cell("id", within=SCROLLED), cell("title", "edit", within=SCROLLED),
                 cell("title", "edit", within=SCROLLED, states="hover"),
                 cell("owner", "edit", states="hover")):
        drawn = table.value(path, "box-shadow")
        if drawn in (None, "none"):
            continue
        for layer in split_list(drawn):
            assert layer.startswith("inset "), (
                f"`{table.winner(path, 'box-shadow').selector}` draws `{layer}`, and an "
                f"outset shadow on a cell in a collapsed table is not painted:\n"
                f"{says(table, path, 'box-shadow')}"
            )


@pytest.mark.parametrize("column", ["id", "title", "owner"])
@pytest.mark.parametrize("severity", ["blocker", "warn"])
def test_a_problem_on_a_frozen_column_still_gets_its_ground(
    table: Sheet, column: str, severity: str
):
    """`id` is the catch-all: a problem whose field has no column of its own is
    marked there. A frozen column that paints `--surface` over its own severity
    ground is a table where the marked cells are the ones nobody can see."""
    path = cell(column, f"edit sev-cell-{severity}")
    assert table.value(path, "background") == f"var(--sev-{severity}-soft)", says(
        table, path, "background")


@pytest.mark.parametrize("column", ["id", "title", "owner"])
def test_a_refused_cell_says_so_on_a_frozen_column_too(table: Sheet, column: str):
    """The fourth casualty of the same weight, and the one nobody listed: the
    ground that says a save came back refused is a `td.` rule as well."""
    path = cell(column, "edit refused")
    assert table.value(path, "background") == "var(--surface-2)", says(
        table, path, "background")


def test_every_rule_that_corrects_a_frozen_column_outweighs_it(table: Sheet):
    """The invariant behind the three tests above, said once.

    The two frozen-column rules state a *default* ground and a *default* layer.
    Three rules exist to correct them, and each has to be strictly heavier than
    the rule it corrects — otherwise which one lands is decided by the order two
    stylesheets happen to be concatenated in, and that order is set 4,000 lines
    away from here by a `+`.
    """
    frozen = table.winner(cell("title", "edit"), "position")
    assert frozen is not None
    for path, prop in (
        (header("id"), "z-index"),
        (header("title"), "z-index"),
        (header("title"), "box-shadow"),
        (cell("id", "sev-cell-blocker"), "background"),
        (cell("title", "edit sev-cell-warn"), "background"),
        (cell("title", "edit refused"), "background"),
    ):
        correction = table.winner(path, prop)
        assert correction is not None, says(table, path, prop)
        assert correction.specificity > frozen.specificity, (
            f"`{correction.selector}` corrects `{frozen.selector}` and is not "
            f"heavier than it, so the order of the stylesheets decides {prop}:\n"
            f"{says(table, path, prop)}"
        )


# --------------------------------------------------------------------------- #
# B2: the popup and the box that used to clip it
# --------------------------------------------------------------------------- #


def test_the_table_body_scrolls_in_a_box_that_clips_what_is_inside_it(table: Sheet):
    """The premise of the test below: this box really does clip. Fourteen columns
    do not fit a screen and the rows scroll in here rather than in the page."""
    box = PAGE + [el("div", "table-scroll")]
    assert table.value(box, "overflow") == "auto"


def test_the_suggestion_popup_hangs_off_the_body_where_nothing_clips_it(table: Sheet):
    """`attachSuggest` parks the list on the body, so the only ancestor it has is
    one with no overflow and no stacking context of its own.

    As the input's next sibling it was inside `.table-scroll` — cut off against
    the bottom of the box on the last rows — and, in the title column, inside the
    stacking context a sticky cell with a z-index establishes, which put it under
    the sticky header as well.
    """
    popup = [el("body"), el("ul", "suggest", id="suggest-1")]
    assert table.value(popup[:1], "overflow") in (None, "visible"), says(
        table, popup[:1], "overflow")
    assert table.value(popup, "position") == "absolute"
    # Above the commit bar (10) and below the banner that says the plan moved
    # under you (40), which is the one thing that must never be behind anything.
    assert table.value(popup, "z-index") == "20"
    # And no rule anywhere gives anything a `position: relative` for it to anchor
    # to — that rule is what was stealing `sticky` from the title column.
    assert table.value(cell("title", "edit"), "position") == "sticky"


# --------------------------------------------------------------------------- #
# B3: the classes the page templates share
# --------------------------------------------------------------------------- #


def pages(index: Index) -> dict[str, str]:
    number = max(e.cycle for e in index.entities.values() if e.cycle)
    return {
        "table": render_table(index, ROUTES, base_commit=HEAD),
        "cycle": render_cycle(index, number, ROUTES, base_commit=HEAD),
        "cycles": render_cycles(index, ROUTES, base_commit=HEAD),
        "detail": render_detail(index, ROUTES, base_commit=HEAD),
        "timeline": render_timeline(index, ROUTES),
    }


def test_the_row_a_pages_own_controls_stand_in_is_a_row_on_every_page(index: Index):
    """`.editbar` was defined in `_DETAIL_STYLE`, which the table does not load,
    so the table's editbar was a `<p>` with the browser's default margin."""
    for name, page in pages(index).items():
        sheet = sheet_of(page)
        bar = PAGE + [el("p", "editbar")]
        assert sheet.value(bar, "display") == "flex", f"{name}: {says(sheet, bar, 'display')}"
        assert sheet.value(bar, "margin") == ".4rem 0 1rem", name


def test_a_link_that_is_a_control_is_drawn_as_one_on_every_page(index: Index):
    """The only `.button` rule was `.tl-controls .button`, scoped to the
    timeline's filter bar. The table's create action — the one way to bring an
    entity into existence from the UI — wore the class with nothing behind it and
    rendered as underlined blue text in a default-margin paragraph."""
    for name, page in pages(index).items():
        sheet = sheet_of(page)
        for states in ("", "visited"):
            button = PAGE + [el("p", "editbar"), el("a", "button", states=states)]
            assert sheet.value(button, "border") == "1px solid var(--line-strong)", (
                f"{name} ({states or 'unvisited'}): {says(sheet, button, 'border')}"
            )
            assert sheet.value(button, "text-decoration") == "none", name
            # `a:visited` in the shell is (0,1,1) and would beat a bare `.button`:
            # the control turned back into a link the moment somebody used it.
            assert sheet.value(button, "color") == "var(--fg)", (
                f"{name} ({states or 'unvisited'}): {says(sheet, button, 'color')}"
            )
        hovered = PAGE + [el("p", "editbar"), el("a", "button", states="visited hover")]
        assert sheet.value(hovered, "color") == "var(--accent)", (
            f"{name}: {says(sheet, hovered, 'color')}"
        )


@pytest.mark.parametrize("kind", ["project", "pitch", "task"])
def test_every_kind_chip_is_the_same_shape(index: Index, kind: str):
    """Three answers to one question, drawn three ways: a project chip carried
    the accent and extra weight, a pitch a plain hairline, and a task no border
    at all — which reads as two of them being special rather than as three of a
    kind, and was the first thing anybody said about the id column.

    Asked of the resolved value and not of the rule text, because "one grouped
    selector exists" says nothing about whether something later singles one of
    them out again.
    """
    for name, page in pages(index).items():
        sheet = sheet_of(page)
        chip = PAGE + [el("span", f"chip kind-{kind}")]
        assert sheet.value(chip, "border") == "1px solid var(--kind-line)", (
            f"{name}: {says(sheet, chip, 'border')}"
        )
        assert sheet.value(chip, "color") == "var(--kind-ink)", f"{name}"
        assert sheet.value(chip, "font-weight") is None, (
            f"{name}: {says(sheet, chip, 'font-weight')}"
        )


def test_the_timeline_window_controls_stand_on_one_line(index: Index):
    """FROM, TO, ZOOM, Apply and Reset are one row, and the ISO echo under each
    date box must not push what is beside it out of line.

    As a flex row it could not be both: the echo makes the two date labels a line
    taller than the zoom label, so `align-items: end` dropped ZOOM and both
    buttons a whole line below the boxes and the bar read as two rows. Three
    explicit grid rows say it directly, and this asks which row each part of the
    bar actually lands in.
    """
    sheet = sheet_of(render_timeline(index, ROUTES))
    bar = PAGE + [el("form", "tl-controls")]

    assert sheet.value(bar, "display") == "grid", says(sheet, bar, "display")
    assert sheet.value(bar, "grid-auto-flow") == "column"
    assert sheet.value(bar, "align-items") == "end"
    for child, row in (
        (el("label", "facet"), "1"),      # FROM, TO, ZOOM
        (el("input"), "2"),               # the two date boxes
        (el("select"), "2"),              # the zoom picker, level with them
        (el("span", "acts"), "2"),        # and Apply and Reset, level with those
        (el("span", "iso"), "3"),         # the echo, under the box it came from
    ):
        path = bar + [child]
        assert sheet.value(path, "grid-row") == row, says(sheet, path, "grid-row")


def test_the_timeline_still_says_which_of_its_two_controls_is_the_verb(index: Index):
    """Apply and Reset are the same size and shape; only the fill separates them.
    The variant moved to the shell with the rule it varies."""
    sheet = sheet_of(render_timeline(index, ROUTES))
    bar = PAGE + [el("form", "tl-controls")]
    apply = bar + [el("button", "button primary")]
    reset = bar + [el("a", "button reset")]

    assert sheet.value(apply, "background") == "var(--accent)", says(sheet, apply, "background")
    assert sheet.value(apply, "color") == "var(--on-accent)"
    assert sheet.value(reset, "background") == "var(--surface)"
    assert sheet.value(apply, "padding") == sheet.value(reset, "padding")


# --------------------------------------------------------------------------- #
# C3: the report a conflict comes back with
# --------------------------------------------------------------------------- #


def test_a_conflict_report_is_a_report_on_the_table_as_well_as_the_detail_page(index: Index):
    """The same box, twice: `#conflict` beside the editor and `#row-conflict`
    beside the row. The rule was written in `_DETAIL_STYLE`, which the table does
    not load, so a report naming a file and every field that disagreed collapsed
    into one run of unstyled text — on the page where it is the only thing saying
    the save did not land."""
    for name, page, box in (
        ("detail", render_detail(index, ROUTES, base_commit=HEAD), el("div", id="conflict")),
        ("table", render_table(index, ROUTES, base_commit=HEAD), el("div", id="row-conflict")),
    ):
        sheet = sheet_of(page)
        path = PAGE + [box]
        # The line breaks are the report: one field per line, and `pre-wrap` is
        # what keeps them.
        assert sheet.value(path, "white-space") == "pre-wrap", (
            f"{name}: {says(sheet, path, 'white-space')}"
        )
        assert sheet.value(path, "border-left") == "3px solid var(--danger)", name
        assert sheet.value(path, "padding") == ".5rem .8rem", name


# --------------------------------------------------------------------------- #
# D: the status border, and the outline it must not smother
# --------------------------------------------------------------------------- #


def test_an_overrunning_bar_still_reads_as_overrunning(index: Index):
    """Every bar has a border now — the light theme's fills are tints, and a tint
    on a white page is not a shape without one — and "overruns its cycle" was
    already drawn as a `--danger` outline on the same rectangle.

    That is two rules setting `stroke` on one element, `rect.bar.late` and
    `rect.bar.st-ready`, both (0,2,1). Specificity cannot separate them, so
    document order is the whole of the answer, and getting it backwards paints
    the alarm out in a status colour on every bar that carries it — while every
    existing assertion about `rect.late` keeps passing, because the rule is
    still in the sheet. Ten of the seventeen bars in the shipped demo corpus
    overrun, `Porting land` among them.
    """
    sheet = sheet_of(render_timeline(index, ROUTES))
    plot = PAGE + [el("div", "tl"), el("div", "scroll"), el("svg"), el("a")]
    ordinary = plot + [el("rect", "bar st-ready")]
    overrun = plot + [el("rect", "bar late st-ready")]
    # The hatch is a second rect over the bar, same geometry. A stroke on it would
    # be drawn after the bar's and straight down the middle of the outline.
    hatch = plot + [el("rect", "mark mark-estimated st-ready")]

    assert sheet.value(ordinary, "stroke") == "var(--st-ready-line)", (
        says(sheet, ordinary, "stroke")
    )
    assert sheet.value(ordinary, "stroke-width") == "1"
    assert sheet.value(overrun, "stroke") == "var(--danger)", says(sheet, overrun, "stroke")
    assert float(sheet.value(overrun, "stroke-width")) > float(
        sheet.value(ordinary, "stroke-width")
    ), "the alarm has to be heavier than the border every other bar wears"
    assert sheet.value(hatch, "stroke") is None, says(sheet, hatch, "stroke")


def test_a_bar_and_the_key_that_names_it_are_drawn_the_same_way(index: Index):
    """A legend that redraws a mark in its own way is a legend that can be wrong
    about the picture beside it. The overrun key was 1.5px while an overrunning
    bar was the only bar with a stroke on it; now that every bar has one, a key
    at the old width keys the ordinary border rather than the alarm."""
    sheet = sheet_of(render_timeline(index, ROUTES))
    plot = PAGE + [el("div", "tl"), el("div", "scroll"), el("svg"), el("a")]
    overrun = plot + [el("rect", "bar late st-ready")]
    key = PAGE + [el("ul", "legend"), el("li"), el("span", "swatch outline late")]

    width = sheet.value(overrun, "stroke-width")
    assert sheet.value(key, "border") == f"{width}px solid var(--danger)", (
        says(sheet, key, "border")
    )
    for status in ("shaping", "ready", "in_progress", "done", "shelved"):
        swatch = PAGE + [el("ul", "legend"), el("li"), el("span", f"swatch st-{status}")]
        assert sheet.value(swatch, "background") == f"var(--st-{status})", status
        assert sheet.value(swatch, "border") == f"1px solid var(--st-{status}-line)", (
            says(sheet, swatch, "border")
        )
        # The key is the same 20x11 as every other key: on content-box a border
        # would have made the bordered ones two pixels taller than the rules.
        assert sheet.value(swatch, "box-sizing") == "border-box", status
