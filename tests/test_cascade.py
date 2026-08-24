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

import re
from datetime import date
from pathlib import Path

import pytest
from cascade import El, Sheet, el, sheet_of, split_list

from openproj.index import Index, build_index
from openproj.model import load_repo
from openproj.render import (
    ROUTES,
    STATUSES,
    render_cycle,
    render_cycles,
    render_detail,
    render_table,
    render_timeline,
)

HEAD = "0123456789abcdef0123456789abcdef01234567"


@pytest.fixture
def index(seed_root: Path) -> Index:
    records, config, _ = load_repo(seed_root)
    return build_index(records, config, date(2026, 8, 17))


@pytest.fixture
def served_pages(index: Index) -> dict[str, str]:
    """Every page a person clicks a control on, as the server renders it — with a
    base commit and write permission, because a reader's page is missing exactly
    the controls this is about."""
    from openproj.render import (
        render_graph,
        render_timeline,
    )

    return {
        "table": render_table(index, ROUTES, base_commit=HEAD),
        "graph": render_graph(index, ROUTES, base_commit=HEAD),
        "timeline": render_timeline(index, ROUTES),
        "detail": render_detail(index, ROUTES, only=sorted(index.plan)[0],
                                base_commit=HEAD, may_write=True),
        # The editing surface, which a served detail page does not show: the
        # toolbar, the view switcher and the status bar are all `.field`s inside
        # `article.record.editing`, so on a record somebody is only READING they
        # have no client rects and the sweep below never sees them. The create
        # page is the same markup and the same stylesheet with the mode already
        # on — twenty controls that would otherwise be measured on no page at all.
        "create": render_detail(index, ROUTES, base_commit=HEAD, may_write=True,
                                creating="task"),
    }


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


def test_the_column_control_is_drawn_as_a_control_and_the_label_is_not(table: Sheet):
    """Two buttons in one `<th>` that must not look alike.

    `th button` strips the sort control of its border and its background on
    purpose: the header word is the control, and only the focus ring says so. The
    column's `+` is the opposite claim — it has to read as the badge it repeats
    one level down — and it is reached by that same rule. `th .expand` is (0,1,1)
    against (0,0,2), so it wins on weight and not on the order two stylesheets are
    concatenated in, which is the only thing that ever decides ties in this file.
    """
    control = header("reviewers", "expands") + [el("button", "expand")]
    label = header("reviewers", "expands") + [el("button")]

    assert table.value(control, "border") == "1px solid var(--line-strong)", says(
        table, control, "border")
    assert table.value(control, "position") == "absolute", says(table, control, "position")
    won = table.winner(control, "border")
    lost = table.winner(label, "border")
    assert won is not None and lost is not None
    assert won.specificity > lost.specificity, (
        f"`{won.selector}` and `{lost.selector}` are the same weight, so which "
        f"button is drawn as a control is decided by the order of the stylesheets"
    )

    # And the sort control keeps the look that makes a header word a header word.
    assert table.value(label, "border") == "0", says(table, label, "border")
    assert table.value(label, "background") == "none", says(table, label, "background")


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
    number = max(e.cycle for e in index.plan.values() if e.cycle)
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
    timeline's filter bar. The table's create action — the one way to bring a
    record into existence from the UI — wore the class with nothing behind it and
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


def test_the_nav_marks_where_you_are_even_on_a_link_you_have_already_used(index: Index):
    """The same trap as `.button`, in the component every page carries.

    The shell says `a, a:visited { color: var(--accent) }`, and `a:visited` weighs
    (0,1,1) — heavier than a bare `nav a` at (0,0,2). Written the obvious way, the
    nav links a reader had already clicked would have stayed in the accent while
    the rest went muted, so the nav would have highlighted *history* rather than
    position, and it would have looked correct on a fresh profile and wrong on
    everybody's.

    The current item has the same fight one rung up: `nav a[aria-current="page"]`
    is (0,1,2) and ties `nav a:visited`, which is decided by whichever is written
    last. Ties that are settled by source order are how the frozen columns lost
    three rules to one qualifier, so this one is settled by weight instead — the
    `:visited` twin is (0,2,2) and beats both.
    """
    nav = [el("body"), el("nav")]
    for name, page in pages(index).items():
        sheet = sheet_of(page)
        for states in ("", "visited"):
            other = nav + [el("a", states=states)]
            assert sheet.value(other, "color") == "var(--muted)", (
                f"{name} ({states or 'unvisited'}): {says(sheet, other, 'color')}"
            )
            here = nav + [el("a", states=states, aria_current="page")]
            assert sheet.value(here, "color") == "var(--accent)", (
                f"{name} ({states or 'unvisited'}): {says(sheet, here, 'color')}"
            )
            # Colour is one of three, and the other two have to reach the same
            # element: a highlight that is only a hue is one this app does not
            # accept anywhere, and on a visited link it was the one most at risk.
            assert sheet.value(here, "font-weight") == "600", name
            assert sheet.value(here, "border") == "1px solid var(--accent)", name
            assert sheet.value(here, "background") == "var(--surface-2)", name
            # And nothing hands a sibling the same box.
            assert sheet.value(other, "border") is None, name
            assert sheet.value(other, "background") is None, name

        # The claim the `:visited` twin exists for, which every assertion above
        # would pass without it — `nav a[aria-current="page"]` alone is (0,1,2),
        # ties `nav a:visited`, and takes it on order. Order is what the frozen
        # columns lost three rules to, so this asks that the winner is *heavier*
        # than everything it beats and not merely later than it.
        here = nav + [el("a", states="visited", aria_current="page")]
        won = sheet.winner(here, "color")
        for rule in sheet.selectors_reaching(here, "color"):
            assert rule.selector == won.selector or rule.specificity < won.specificity, (
                f"{name}: `{won.selector}` only beats `{rule.selector}` on source "
                f"order — both are {won.specificity}, so moving either rule flips it"
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
    overrun, `Porting the bed` among them.
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
    # STATUSES, because this is the one harness that can answer "does the
    # generated .st-<word> rule actually WIN, and against what" — and written as
    # five literal words it was not asked about the sixth.
    for status in STATUSES:
        swatch = PAGE + [el("ul", "legend"), el("li"), el("span", f"swatch st-{status}")]
        assert sheet.value(swatch, "background") == f"var(--st-{status})", status
        assert sheet.value(swatch, "border") == f"1px solid var(--st-{status}-line)", (
            says(sheet, swatch, "border")
        )
        # The key is the same 20x11 as every other key: on content-box a border
        # would have made the bordered ones two pixels taller than the rules.
        assert sheet.value(swatch, "box-sizing") == "border-box", status


# --------------------------------------------------------------------------- #
# B6: the icon picker, which is a popup that has to beat a sticky header, and
#     the one line on this page that says a write was refused
# --------------------------------------------------------------------------- #


@pytest.fixture
def people(index: Index) -> Sheet:
    """The People page as the server draws it for the person signed in — the only
    reader who gets a picker at all."""
    from openproj.render import render_people

    who = sorted(e.owner for e in index.plan.values() if e.owner)[0]
    return sheet_of(render_people(index, ROUTES, editable=True, me=who))


GROUP = PAGE + [el("table", id="roles"), el("tbody", "person"), el("tr", "group"), el("th")]
LINE = GROUP + [el("div", "groupline")]


WRAP = LINE + [el("span", "pickwrap")]
SHUT = WRAP + [el("ul", "picker", id="picker", hidden="")]
OPEN = WRAP + [el("ul", "picker", id="picker")]


def test_the_picker_is_hidden_by_the_attribute_and_not_by_source_order(people: Sheet):
    """A `display` that reaches an element carrying `hidden` is a popup that is
    always open.

    The two rules are `.picker` at (0,1,0) and `.picker[hidden]` at (0,2,0), so
    the attribute wins on specificity — which is the thing worth asserting,
    because the page's own stylesheet is inlined *after* the shell's and a rule
    that relied on order would be the loser in the other direction. It matters
    more now than it did: the popup went from twelve buttons on one line to
    twenty-five rows of drawing and name, so a picker that failed to hide is not
    a stray strip any more, it is a panel over the rows.

    Asked of a cascade engine and not by looking for the rule: a rule being in
    the sheet says nothing about whether it wins, which is what three
    frozen-column rules found out.
    """
    assert people.value(SHUT, "display") == "none", says(people, SHUT, "display")
    # Nothing sets one on the open list, which is the point: it is a `<ul>` and
    # block is what it wants. The rule above is what would have to be beaten if
    # anybody ever gave it one.
    assert people.value(OPEN, "display") is None, says(people, OPEN, "display")


def test_the_open_picker_is_painted_over_the_sticky_header_and_not_under_it(people: Sheet):
    """The popup that replaced the strip has to win a fight the strip never had.

    It floats now — twenty-five rows in the flow would push every person below
    down by the height of the list — and the thing it floats near is a `position:
    sticky` header with a z-index of its own. Left open while the page scrolls,
    the header rides down over the list; the two numbers are resolved here, by
    name, rather than assumed.

    The wrapper is the other half of it and is the part that is easy to get
    wrong: `position: relative` with NO z-index does not open a stacking context,
    so the list's 3 is weighed against the header's 2 in the page's own context.
    Given a z-index the wrapper would become the context, the list would be
    trapped at the wrapper's level, and both assertions below would still pass
    while the header painted over the list — so the absence is asserted too.
    """
    header = PAGE + [el("table", id="roles"), el("thead"), el("tr"), el("th")]

    assert people.value(OPEN, "position") == "absolute", says(people, OPEN, "position")
    assert people.value(WRAP, "position") == "relative", says(people, WRAP, "position")
    assert people.value(WRAP, "z-index") is None, says(people, WRAP, "z-index")

    over = people.value(OPEN, "z-index")
    under = people.value(header, "z-index")
    assert over and under and int(over) > int(under), (
        f"the list is z-index {over} and the sticky header {under}\n"
        + says(people, OPEN, "z-index")
        + "\n"
        + says(people, header, "z-index")
    )


def test_the_picker_scrolls_inside_itself_rather_than_off_the_page(people: Sheet):
    """Twenty-five rows at a row's height is taller than most windows have room
    for under a button that can be anywhere on the page. The list is bounded and
    scrolls; without the bound, choosing an icon near the bottom of the set means
    scrolling the PAGE, and the page scrolling moves the button the list is
    hanging off."""
    assert people.value(OPEN, "max-height"), says(people, OPEN, "max-height")
    assert people.value(OPEN, "overflow-y") == "auto", says(people, OPEN, "overflow-y")


def test_a_mark_does_not_shrink_out_of_the_line_it_sits_in(people: Sheet):
    """The group line wraps. A flex item defaults to `flex-shrink: 1`, so an icon
    beside a long name and a load meter would be squeezed first — and the width
    where it disappears is exactly the width where the name is all that is
    left."""
    mark = LINE + [el("span", "avatar")]

    assert people.value(mark, "flex") == "none", says(people, mark, "flex")


def test_a_refusal_lands_somewhere_a_sighted_reader_can_read_it(people: Sheet):
    """This page had no `#state`, and that is a defect rather than a detail.

    `announce` writes into `#state` where a page has one and into the shell's
    `#announce` otherwise — and `#announce` carries `.sr-only`, which is
    `position: absolute; clip-path: inset(50%)`. So every refusal this feature
    could produce went to a screen reader and nowhere else: somebody sighted
    pressed a picture and the button did nothing, silently, for good.

    The region here is in the ordinary flow of the group line, which is what
    makes it visible; asserted by asking for the two properties that hide the
    other one rather than by looking for a class name.
    """
    state = LINE + [el("span", id="state")]

    assert people.value(state, "position") is None, says(people, state, "position")
    assert people.value(state, "clip-path") is None, says(people, state, "clip-path")
    assert people.value(state, "color") == "var(--muted)", says(people, state, "color")


def test_a_refusal_is_coloured_as_one_and_a_receipt_is_not(people: Sheet):
    """One region carries both sentences a write produces, so the refusal has to
    be told apart from the receipt by something. `.groupline #state.bad` is
    (1,2,0) against `.groupline #state`'s (1,1,0) and wins on specificity — not
    on order, which is the tie this file keeps losing."""
    bad = LINE + [el("span", "bad", id="state")]

    assert people.value(bad, "color") == "var(--warn)", says(people, bad, "color")


# --------------------------------------------------------------------------- #
# The row nobody has created yet
# --------------------------------------------------------------------------- #

# The draft row's id cell, which until there is an id carries the row's own
# controls: create it, abandon it, and what it is going to be.
DRAFTING = SCROLL + [
    el("tbody"),
    el("tr", "draft"),
    el("td", "draft-id", data_col="id"),
    el("span", "drafting"),
]


@pytest.mark.parametrize("control", ["draft-create", "draft-cancel"])
def test_a_drawn_mark_has_a_size_of_its_own(index: Index, control: str):
    """The check and the cross the draft row is created and cancelled with are
    `<svg class="icon">`, and that element carries no `width` or `height`
    attribute — every other page sizes it from the box it sits in
    (`.avatar svg`, `.picker .art svg`, both `width: 100%`).

    In a button that has no such rule an SVG with no intrinsic size lays out at
    0x0, and the two controls that create and abandon a record are two empty
    boxes. They were, on the served page, while the suite was green: nothing in
    it asked what a browser resolves for the drawing, only that the markup was
    emitted. This asks the cascade, which is the only thing that answers.
    """
    mark = DRAFTING + [el("button", "draft-do", id=control), el("svg", "icon")]
    sheet = sheet_of(render_table(index, ROUTES, base_commit=HEAD))
    for prop in ("width", "height"):
        value = sheet.value(mark, prop)
        assert value not in (None, "auto", "0", "0px"), (
            f"{control}'s drawing resolves {prop} to {value!r}, which is no "
            f"drawing at all:\n{says(sheet, mark, prop)}"
        )


def test_the_draft_rows_controls_stand_on_one_line(index: Index):
    """Two marks and the kind picker, side by side in the narrowest column on
    the table.

    Laid out by the wrapper and not by the cell: a `<td>` that is a flex
    container stops being a table cell. Without the rule the three sat as
    inline boxes and the picker wrapped under the marks, which made the draft
    twice the height of every other row — the exact thing the comment above
    `draftControls` says the marks exist to avoid. And the picker has to be
    allowed to shrink: a flex item's `min-width` is `auto`, so its longest
    option decided the width of a 135px column.
    """
    sheet = sheet_of(render_table(index, ROUTES, base_commit=HEAD))
    assert sheet.value(DRAFTING, "display") == "inline-flex", (
        says(sheet, DRAFTING, "display")
    )
    assert sheet.value(DRAFTING, "align-items") == "center"
    picker = DRAFTING + [el("select", id="draft-kind")]
    assert sheet.value(picker, "min-width") == "0", says(sheet, picker, "min-width")


# --------------------------------------------------------------------------- #
# The full page, which is a third mode over two that already fight
# --------------------------------------------------------------------------- #


@pytest.fixture
def detail(index: Index) -> Sheet:
    """The detail page as a writer gets it: the shell, then `_DETAIL_STYLE`, then
    `_SUGGEST_STYLE`, in the order they are inlined."""
    return sheet_of(render_detail(index, ROUTES, base_commit=HEAD))


def _writing(mode: str) -> list[El]:
    """Inside the surface, in one of the three views."""
    return PAGE + [
        el("article", f"record editing full view-{mode}"),
        el("form", id="edit"),
        el("div", "panes"),
        el("div", "main"),
        el("div", "bodysplit"),
    ]


def test_the_full_page_class_does_not_beat_the_editing_class(detail: Sheet):
    """Qualifying a selector to win a fight is this stylesheet's characteristic
    failure — twice in one week, and both times the rule that lost was one nobody
    had asked the cascade about.

    Full page is a third mode over two that are already one class apart, so every
    one of its rules is `.record.full …` at (0,3,x) sitting above `.record.editing
    .field` at (0,3,0) — the rule that puts the controls on the page at all.
    What is asserted is that the full-page rules changed the *geometry* and left
    the two modes to decide what exists: a `display` on the box or the pane taken
    by a view rule is a box that edit mode cannot bring back.
    """
    box = _writing("both") + [el("div", "bodywrap"), el("textarea", "field body-field")]
    pane = _writing("both") + [el("div", "field doc", id="body-preview")]

    for path, what in ((box, "the box"), (pane, "the rendered pane")):
        won = detail.winner(path, "display")
        assert won and won.selector == ".record.editing .field", (
            f"{what} is displayed by {won} in the split view\n" + says(detail, path, "display")
        )

    # And the two rules that *do* take a pane away name the view they belong to,
    # so leaving that view gives it back.
    gone = _writing("view") + [el("div", "bodywrap")]
    assert detail.value(gone, "display") == "none", says(detail, gone, "display")
    assert detail.winner(gone, "display").selector.startswith("article.record.full.view-view")
    kept = _writing("both") + [el("div", "bodywrap")]
    assert detail.value(kept, "display") is None, says(detail, kept, "display")

    # The surface is the window, so the measure has to lose here and win
    # everywhere else. Both are `article.record…`, and (0,2,1) beats (0,1,1).
    inside = PAGE + [el("article", "record editing full view-edit")]
    outside = PAGE + [el("article", "record editing")]
    assert detail.value(inside, "width") == "auto", says(detail, inside, "width")
    assert detail.value(outside, "width") == "var(--measure, 64rem)"

    # And the toolbar refuses to shrink, which is what keeps it on one row. It
    # is the last rule in the last stylesheet, so nothing here is deciding it by
    # order alone.
    marks = PAGE + [el("span", "marks", id="marks")]
    assert detail.value(marks, "flex") == "none", says(detail, marks, "flex")


def test_the_handle_between_the_panes_is_a_control_in_one_view_and_nowhere_else(
    detail: Sheet
):
    """The splitter, resolved by name, because "the rule is in the stylesheet" is
    not what a reader sees.

    Three fights, and each of them is one somebody could lose by accident:

    * the handle is `display: none` by default and the split view is what turns it
      on. `#splitter` is (1,0,0) and every rule that could give it back a box is a
      class selector, so the *default* has to be the id — an `article.record.full
      .bodysplit > div` written to lay the panes out would otherwise draw a
      separator on the cycle page, the cycles index and the deck, which have no
      document to split;
    * the two prose tracks keep `minmax(0, …)`. A bare fraction there is a track
      whose minimum is its content, and one unbroken line of prose is wider than
      half a window;
    * and the rendered pane draws no line of its own where the handle draws one.
      Two lines down the middle of a split is worse than none, and the pane's
      border is the line that was there first.

    **`cascade.py` skips at-rules by construction**, which is a real limit here
    and is stated rather than papered over: the `@media (width < 58.5rem)` block
    that takes the handle away and hands the pane its border back is invisible to
    this engine, so that half is asked of Chrome in
    `test_there_is_no_handle_where_there_is_nothing_to_divide`. What is resolved
    here is the wide window, which is the state the feature exists in.
    """
    split = _writing("both")
    won = detail.winner(split, "grid-template-columns")
    assert won and won.selector == "article.record.full.view-both .bodysplit", (
        f"the split's columns are decided by {won}\n"
        + says(detail, split, "grid-template-columns")
    )
    assert won.value == "minmax(0, var(--split, 1fr)) 1.5rem minmax(0, 1fr)", won.value

    handle = _writing("both") + [el("div", id="splitter")]
    on = detail.winner(handle, "display")
    assert on and on.value == "block", (
        f"the handle is displayed by {on} in the split view\n"
        + says(detail, handle, "display")
    )
    # And every other place it could be drawn, which is every other place it is
    # rendered into: the two one-pane views, and the page outside the surface.
    for where in (
        _writing("edit") + [el("div", id="splitter")],
        _writing("view") + [el("div", id="splitter")],
        PAGE + [el("article", "record editing"), el("form", id="edit"),
                el("div", "bodysplit"), el("div", id="splitter")],
    ):
        off = detail.winner(where, "display")
        assert off and off.value == "none" and off.selector == "#splitter", (
            f"a splitter outside the split view is displayed by {off}\n"
            + says(detail, where, "display")
        )

    pane = _writing("both") + [el("div", "field doc", id="body-preview")]
    assert detail.value(pane, "border-left") is None, (
        "the rendered pane draws a line down its left edge and so does the handle "
        "beside it, which is two lines down the middle of one split\n"
        + says(detail, pane, "border-left")
    )

# --------------------------------------------------------------------------- #
# One editing surface, one stylesheet
# --------------------------------------------------------------------------- #


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


_RECORD_EDITING = [
    el("body"), el("main", id="main"), el("article", "record editing"),
]


def test_the_record_pages_bar_still_beats_the_field_rule_it_once_lost_to(record: Sheet):
    """The fight the old issue-page suite was written for, re-resolved after
    the mode class moved off `<body>` and onto the article — and now held on
    the one surviving surface.

    `.record.editing .field` and `.record.editing .bodybar` are both (0,3,0), so
    the tie is decided by order and nothing else — which is why the answer has to
    be asked rather than assumed. And the tie is real: every bar on the merged
    page wears `.field`, because that class is how a bar hides in read mode, so
    `_EDITING_STYLE` being concatenated after `_DETAIL_STYLE` is the only guard
    between the toolbar and `.field`'s `display: block`. The bare bar is asked
    too, because the answer must not depend on a class list a refactor could
    trim.
    """
    bar = _RECORD_EDITING + [el("p", "bodybar markbar")]
    won = record.winner(bar, "display")
    assert won and won.selector == ".record.editing .bodybar" and won.value == "flex", (
        f"the toolbar is displayed by {won}\n" + says(record, bar, "display")
    )

    # And the bar as the page actually writes it, wearing `.field`: `flex`
    # still, and by order alone — this half is the live markup.
    with_field = _RECORD_EDITING + [el("p", "field bodybar markbar")]
    reaching = record.selectors_reaching(with_field, "display")
    assert reaching[-1].selector == ".record.editing .bodybar", (
        "the bar loses to `.field` on the page as it is written\n"
        + says(record, with_field, "display")
    )
    assert reaching[-1].specificity == reaching[-2].specificity, (
        "it is winning on weight, so the ordering argument above is no longer "
        f"what is holding it up: {says(record, with_field, 'display')}"
    )


def test_the_box_on_a_record_page_is_monospace_and_fits_its_pane(record: Sheet):
    """The one declaration for the box and the column of numbers beside it.

    `--gutter` is written in `ch`, and `ch` is resolved in the font of whoever
    uses the value — so a box in one face and a gutter in another is a column of
    numbers that does not line up with the lines it names. And `width: 100%`
    means the box: the record pages once had no `box-sizing` rule of their own,
    so their textarea hung past the container it was in.

    The 44rem reading-measure cap this asserted went with the record pages'
    own stylesheet: on the surviving sheet the measure lives on
    `article.record` as `--measure`, dragged by `#grip`, and the box fills the
    article.
    """
    box = _RECORD_EDITING + [
        el("form", id="edit"), el("div", "bodysplit"), el("div", "bodywrap"),
        el("textarea", "field body-field"),
    ]
    assert record.value(box, "font-family") == "var(--font-mono)", says(
        record, box, "font-family"
    )
    # **This engine cannot see a shorthand fight, and that is worth stating
    # rather than leaving as a gap.** `_DETAIL_STYLE` carries
    # `input.field, select.field, textarea.field { font: inherit }` at the same
    # (0,1,1) as the `font-family` declaration above, and a shorthand is what
    # decides the face. `_declarations` records a property by the name it is
    # written under, so `font` and `font-family` are two different properties
    # here and no conflict is visible — while a browser expands one into the
    # other and concatenation order decides which wins. So the ordering
    # argument is asked of Chrome instead, in
    # `test_the_box_and_the_column_beside_it_are_one_face`.
    assert record.value(box, "font") == "inherit", (
        "the shorthand this note is about is gone, so either the browser test it "
        "points at is now the only guard or it is no longer needed\n"
        + says(record, box, "font")
    )

    assert record.value(box, "box-sizing") == "border-box", says(record, box, "box-sizing")

    # And inside the full-page surface any measure loses, because the pane IS
    # the window.
    inside = [
        el("body", "fullpage"), el("main", id="main"),
        el("article", "record editing full view-both"),
        el("form", id="edit"), el("div", "bodysplit"), el("div", "bodywrap"),
        el("textarea", "field body-field"),
    ]
    assert record.value(inside, "max-width") == "none", says(record, inside, "max-width")


def test_a_hidden_control_stays_hidden_on_the_one_stylesheet(record: Sheet):
    """`[hidden] { display: none }` is the UA sheet's, and an author rule of any
    weight beats it. This ran over two stylesheets while there were two; the
    guard survives on the one editing surface there is, and the rendered pane —
    a `.field`, `hidden` until a view asks for it — must stay dark.
    """
    pane = [
        el("body"), el("main", id="main"), el("article", "record editing"),
        el("div", "field doc", id="body-preview", hidden="hidden"),
    ]
    won = record.winner(pane, "display")
    assert won and won.value == "none", (
        f"a hidden pane is displayed by {won}\n" + says(record, pane, "display")
    )


def test_the_handle_between_the_panes_is_one_control_on_the_one_stylesheet(
    record: Sheet,
):
    """The splitter, resolved against the surviving sheet.

    While there were two stylesheets this looped over both, because a second
    copy of the editing rules under a different mode class is the failure mode
    this file exists for. The fight worth asking about is unchanged: `#splitter`
    is (1,0,0) and the rules that give it a box are class selectors, so if the
    sheet ever loses the id rule the separator appears with no document to
    divide.

    `touch-action` is here for the same reason it is asserted in the browser: a
    handle a finger can start a pan on is one the browser may take the pointer
    back from mid-drag.
    """
    inside = [
        el("body", "fullpage"), el("main", id="main"),
        el("article", "record editing full view-both"), el("form", id="edit"),
        el("div", "bodysplit"), el("div", id="splitter"),
    ]
    won = record.winner(inside, "display")
    assert won and won.value == "block", (
        f"the handle in the split view is displayed by {won}\n"
        + says(record, inside, "display")
    )
    assert record.value(inside, "touch-action") == "none", (
        "a finger on the handle can start a pan\n" + says(record, inside, "touch-action")
    )

    outside = [
        el("body"), el("main", id="main"), el("article", "record editing"),
        el("div", "bodysplit"), el("div", id="splitter"),
    ]
    off = record.winner(outside, "display")
    assert off and off.value == "none" and off.selector == "#splitter", (
        f"a splitter outside the split view is displayed by {off}\n"
        + says(record, outside, "display")
    )


# --------------------------------------------------------------------------- #
# One commit bar, four pages, one rule
# --------------------------------------------------------------------------- #


def test_every_commit_bar_sticks_to_the_same_edge_and_one_rule_decides_it(index: Index):
    """The four pages that draw a commit bar agree about which edge it sticks to,
    and they agree because one rule says so rather than because four sheets
    happen to.

    This is the test the defect it was written for would have failed. The detail
    page's bar moved to the top by way of `#commitbar { top: 0; bottom: auto }` in
    `_DETAIL_STYLE` — and `_DETAIL_STYLE` is loaded by the detail page, the create
    form, the cycle page, the cycles index and the deck. Two of those still had their bar
    last in the markup, so an id override written for one page took `bottom: 0`
    away from two others and gave them nothing in its place: a `top: 0` sticky box
    at the foot of a document is a box you cannot see until you have scrolled to
    it, which is exactly the defect the create page's own test was written for.
    Measured in Chrome at 1400x900: 1178px down the create page, 1113px down the
    cycle page, on screen from neither top.

    A rule being in the stylesheet says nothing about whether it wins, and on the
    two broken pages every rule involved was in the stylesheet and read correctly.
    What was wrong was which one won, on which pages — so that is what is asked,
    by name, per page.
    """
    from openproj.render import render_cycle, render_graph

    number = sorted(index.cycles)[0]
    bar = el("div", "commitbar", id="commitbar")
    pages = {
        "detail": (render_detail(index, ROUTES, only=sorted(index.plan)[0],
                                 base_commit=HEAD, may_write=True),
                   [el("article", "record editing"), bar]),
        "create": (render_detail(index, ROUTES, base_commit=HEAD, may_write=True,
                                 creating="task"),
                   [el("article", "record editing"), bar]),
        "cycle": (render_cycle(index, number, ROUTES, base_commit=HEAD), [bar]),
        "graph": (render_graph(index, ROUTES, base_commit=HEAD), [bar]),
    }

    for name, (page, tail) in pages.items():
        sheet = sheet_of(page)
        path = [el("body"), el("main", id="main"), *tail]
        for prop, edge in (("top", "0"), ("bottom", "auto")):
            won = sheet.winner(path, prop)
            assert won and won.selector == ".commitbar" and won.value == edge, (
                f"on the {name} page the bar's {prop} is decided by {won}\n"
                + says(sheet, path, prop)
            )
            # And decided by exactly one rule, which is the half that would have
            # caught this: the broken pages had two, and the loser was the one
            # every test asserted the text of.
            reaching = sheet.selectors_reaching(path, prop)
            assert len(reaching) == 1, (
                f"the {name} page's bar has {len(reaching)} answers to {prop}\n"
                + says(sheet, path, prop)
            )
        assert sheet.value(path, "position") == "sticky", (
            f"the {name} page's bar is not sticky, so which edge it names is a "
            "coordinate rather than a guarantee\n" + says(sheet, path, "position")
        )
# Every button and every select on the page, and what it is actually drawn with.
# Measured, not read: the version of this test that read the stylesheet passed
# while `#preview`, `#connect`, `#clear-filters` and a dozen others were being
# drawn by the operating system, because it checked that ONE rule existed and
# never asked which controls it reached.
_DRAWN = """
const out = [];
for (const el of document.querySelectorAll('button, select')) {
  if (!el.getClientRects().length) continue;
  const s = getComputedStyle(el);
  // A segment of a segmented control is drawn by the GROUP it sits in. Three
  // states of one thing share one rectangle on purpose — giving each segment its
  // own would draw a doubled border down every join — so the rectangle to ask
  // about is the one a reader actually sees, and it still has to be the app's.
  // Reported this way rather than excused: an exception measured on the wrong
  // element is an exception that stops being measured at all.
  const box = el.closest('.views') || el;
  const r = getComputedStyle(box);
  out.push({
    what: el.tagName.toLowerCase() + (el.id ? '#' + el.id : '')
          + (typeof el.className === 'string' && el.className.trim()
             ? '.' + el.className.trim().split(/\s+/).join('.') : ''),
    border: r.borderTopWidth + ' ' + r.borderTopStyle,
    radius: r.borderTopLeftRadius,
    // What the control puts on the page under its border, which is the other
    // half of "is anything drawn here at all".
    ground: r.backgroundColor,
    size: s.fontSize,
    family: s.fontFamily.split(',')[0].replace(/["']/g, ''),
  });
}
return out;
"""

def bare(one: dict) -> bool:
    """Whether this control is deliberately drawn with nothing.

    Asked of the DRAWING and of nothing else, which is the correction the styling
    rule itself needed one commit earlier. This was a list of names — an id, a
    `closest('th')`, a substring — and a list has the two failures that argument
    is about: it excuses the controls somebody thought of and none of the ones
    they did not, and it cannot tell a control that is deliberately bare from one
    that has drifted, because a name goes on matching whatever the control turns
    into.

    So the question is whether anything is drawn here at all: no border and no
    ground. That is exactly what each of these controls already says in its own
    rule — the theme icon in the corner, the column headers that must go on
    looking like headers, the filter buttons that draw their own caret inside
    themselves, the status strip's pickers that are words until you point at
    them, all of them `background: none; border: 0` under a class or an id, which
    outranks an element selector. The browser's own chrome is neither of those
    things — `2px outset` over an opaque `buttonface` — so the defect this test
    was written for still lands in the set that has to match.
    """
    return one["border"].endswith(" none") and one["ground"] == "rgba(0, 0, 0, 0)"


@pytest.mark.parametrize(
    "view", ["table", "graph", "timeline", "detail", "create"]
)
def test_every_control_on_every_page_is_drawn_the_same(view, served_pages, tmp_path):
    """jcanton, 2026-08-20, on finding "Preview the body" still native: "I thought
    we had managed to impose the style of buttons and dropdowns to be coherent
    across the entire app? why did that work? this is rather important for
    preventing future drifts".

    It did not work, and the reason is the shape of the rule rather than the rule.
    It named ids and classes, so it reached the eight controls somebody thought of
    and none of the twenty they did not, and the failure is silent: the button
    looks like the operating system and nobody notices until two of them are side
    by side.

    The rule is now the default for `button` and `select`, and this measures the
    result in a browser rather than reading the source. A test that reads a
    stylesheet can only ever check that a rule exists; what matters is which
    controls it reaches.
    """
    from browser import chrome, measured_in

    drawn = measured_in(chrome(), served_pages[view], tmp_path / f"{view}.html", 1400, _DRAWN)
    assert drawn, f"the {view} page has no controls at all"

    styled = [one for one in drawn if not bare(one)]
    assert styled, f"every control on the {view} page claims to be deliberately bare"

    # The border, not the type size. A "show 1 more" button inside a table cell is
    # legitimately smaller than Save; what has to match is the rectangle, which is
    # what the eye reads as "these are the same kind of thing".
    assert {one["border"] for one in styled} == {"1px solid"}, (
        f"controls on the {view} page are bordered differently: "
        + "; ".join(
            f"{one['what']} is {one['border']}"
            for one in styled if one["border"] != "1px solid"
        )
    )
    # And the corner, of everything that HAS one. `50%` is not a corner, it is a
    # circle: the theme toggle is a round icon button, and giving it 3px would
    # make it a square with a sun in it. Asked of the drawing rather than excused
    # by name — the version of this list that named `button#theme` excused its
    # border along with its corner, and a round control still owes the app its
    # border. Nothing drifts into `50%` by accident, which is what a name cannot
    # say for itself.
    corners = {one["radius"] for one in styled if one["radius"] != "50%"}
    assert corners == {"3px"}, (
        f"controls on the {view} page are cornered differently: "
        + "; ".join(
            f"{one['what']} is r{one['radius']}"
            for one in styled if one["radius"] not in ("3px", "50%")
        )
    )
    # `2px outset` is Chrome's own default for a button nobody styled, and it is
    # what this page showed for half a day: the rule was there, in a stylesheet,
    # behind a comment somebody had left unclosed. The parser threw the rule away
    # and said nothing. Named here because the symptom is indistinguishable from
    # a selector that simply does not match.
    assert not [one for one in styled if one["border"] == "2px outset"], (
        f"{view}: a control is wearing the browser's own chrome"
    )


def test_no_stylesheet_has_an_unclosed_comment(served_pages):
    """A CSS comment that never closes eats the rules after it, silently.

    That is not hypothetical: the rule making every control look the same was
    written correctly, put in the shell, shipped — and did nothing, because the
    comment above it had been edited and left with its `*/` in the middle. The
    parser discarded everything from there to the next `*/` and reported nothing,
    and the symptom on the page is identical to a selector that does not match.

    Counted rather than parsed: every `/*` must have its `*/`, and an odd number
    of either is a stylesheet with a hole in it.
    """
    for view, page in served_pages.items():
        for style in re.findall(r"<style[^>]*>(.*?)</style>", page, re.S):
            opens, closes = style.count("/*"), style.count("*/")
            assert opens == closes, (
                f"{view}: {opens} comment openings and {closes} closings — "
                "everything after the odd one out is being thrown away"
            )
