"""The filter bar, driven in the browser it is used in.

A facet is a button and a list of checkboxes now, and it exists because
`apply_filters` and `matches` have always been able to answer more than a
`<select>` can ask: OR within a field, AND across them, with the field carried
twice in the URL. The menu was the only thing insisting on one value.

Everything here is asked of Chrome rather than of the shim. Three of the claims
are about things a shim does not have — where the keyboard goes when a menu
closes, whether a popup is over the thing under it, what a click on a `<label>`
does to the checkbox inside it — and a harness that answers those from a model
of the DOM is answering about itself.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from browser import chrome, measured_in

from openproj.index import NO_VALUE, Index, apply_filters, build_index
from openproj.model import load_repo, unread_fields
from openproj.render import render_table

HEAD = "0123456789abcdef0123456789abcdef01234567"


@pytest.fixture
def index(demo_root: Path) -> Index:
    records, config, _ = load_repo(demo_root)
    return build_index(records, config, date(2026, 8, 17))


@pytest.fixture
def page(index: Index) -> str:
    return render_table(index, base_commit=HEAD, may_write=True)


# Open one field, tick two of its values, and report what the page then says
# about itself: the URL, the summary in the closed control, and which rows the
# shared `matches()` keeps.
_TWO_VALUES = """
const facet = document.querySelector('.facet[data-field="status"]');
const opener = facet.querySelector('.facetopen');
opener.click();
// Two VALUES, so `(none)` is skipped. It sits first in every menu it appears in
// (`_facet_order` in `index.py` puts it there on purpose) and Status grew one on
// 2026-08-23, when the corpus gained a product — a rung that reads no status at
// all. It is not a value of the field: it is the question "which of these has
// nothing in it", which `test_the_empty_option_asks_about_the_list_and_not_
// inside_it` below asks on its own terms. The oracle underneath is `row.status
// is one of these two` and it stays exactly that literal, because an oracle
// taught the sentinel's branch is a copy of `matches` agreeing with itself.
//
// `NO_VALUE` is the page's own constant, not a fourth spelling of `(none)`.
const boxes = [...facet.querySelectorAll('input[type=checkbox]')]
  .filter(box => box.value !== NO_VALUE);
const wanted = [boxes[0].value, boxes[1].value];
boxes[0].click();
boxes[1].click();
return {
  wanted,
  url: params.getAll('status'),
  said: facet.querySelector('.facetsaid').textContent,
  label: opener.getAttribute('aria-label'),
  chosen: facet.classList.contains('chosen'),
  kept: Object.keys(DATA.rows).filter(id => matches(DATA.rows[id])).sort(),
  either: Object.keys(DATA.rows)
    .filter(id => wanted.includes(DATA.rows[id].status)).sort(),
};
"""


def test_two_values_of_one_field_mean_either(page: str, tmp_path: Path):
    """The thing a `<select>` could not ask, and the filter underneath could
    always answer. OR within a field: two statuses means either of them, which is
    what `apply_filters` has done with a URL carrying the field twice since
    before there was a control that could produce one."""
    got = measured_in(chrome(), page, tmp_path / "two.html", 1460, _TWO_VALUES)

    assert got["url"] == got["wanted"], "the URL did not carry both values"
    assert got["kept"] == got["either"]
    assert len(got["kept"]) > 0


# The one option that is not a value. Tick it alone and report what the bar
# keeps, beside what the rows themselves say is empty.
_THE_EMPTY_OPTION = """
const facet = document.querySelector('.facet[data-field="status"]');
facet.querySelector('.facetopen').click();
const box = [...facet.querySelectorAll('input[type=checkbox]')]
  .find(one => one.value === NO_VALUE);
if (!box) return {offered: false};
box.click();
return {
  offered: true,
  said: facet.querySelector('.facetsaid').textContent,
  url: params.getAll('status'),
  kept: Object.keys(DATA.rows).filter(id => matches(DATA.rows[id])).sort(),
  // The same question asked of the row rather than through `matches`: which
  // rows carry no status at all. `?? []` and not `|| []`, because a status of
  // `''` is a status somebody wrote and `0` is not a thing this field holds.
  blank: Object.keys(DATA.rows).filter(id =>
    [].concat(DATA.rows[id].status ?? []).filter(v => v !== '').length === 0).sort(),
};
"""


def test_the_empty_option_asks_about_the_list_and_not_inside_it(
    index: Index, page: str, tmp_path: Path
):
    """`(none)` selects the records with no status, and a record has no status
    when its rung does not read one.

    This could not be asked of Status until 2026-08-23. `build_index` offers the
    option only where something is actually missing — "a menu never carries an
    option that can select nothing" — and every planned record had a status, so
    the branch that adds it was reached on Cycle and Owner and never here. Then
    the corpus grew a product, which reads no status at all (`statuses=()` on its
    rung, so `unread_fields("product")` names it and `_row` nulls it), and the
    option appeared.

    What it caught on the way in: `test_two_values_of_one_field_mean_either` was
    ticking the first two boxes in the menu, which had silently become `(none)`
    and `shaping`, and comparing them against an oracle that only knew how to
    read a status off a row. The bar was right, the server agreed with it, and
    the oracle was the one thing that did not know the sentinel existed.
    """
    got = measured_in(chrome(), page, tmp_path / "empty.html", 1460, _THE_EMPTY_OPTION)

    assert got["offered"], (
        "the Status menu offers no way to ask for the records that have not got one, "
        "although this corpus holds records of a kind that reads no status"
    )
    assert got["url"] == [NO_VALUE], "the sentinel did not reach the query string"
    # It asks about the list, so what comes back is what has nothing in it — and
    # not, for instance, everything, which is how a filter that fails open reads.
    assert got["kept"] == got["blank"]
    # And which records those are is the ladder's answer, not this test's list.
    unstatused = sorted(
        record_id
        for record_id, record in index.plan.items()
        if "status" in unread_fields(record.kind)
    )
    assert got["kept"] == unstatused, (
        f"the bar kept {got['kept']} and the ladder says the records with no status "
        f"are {unstatused}"
    )
    assert unstatused, "no planned record reads no status, so this asks nothing"
    # The server answers the same question the same way. The sentinel is spelled
    # once, in `index.NO_VALUE`, and both halves reach it from there.
    assert apply_filters(index, {"status": [NO_VALUE]}, "") == got["kept"], (
        "the server and the bar disagree about which records have no status"
    )


def test_the_closed_control_says_what_is_set(page: str, tmp_path: Path):
    """A filter you cannot see is a filter you forget you set, and this bar
    spends most of its life closed. One value is named; two are counted, because
    two tag names do not fit in a button on a bar of ten of them."""
    got = measured_in(chrome(), page, tmp_path / "said.html", 1460, _TWO_VALUES)

    assert got["said"] == "2 chosen"
    assert got["chosen"], "the field does not read as set"
    # And the count is in the accessible name too, not only in the ink.
    assert got["label"].endswith("2 chosen")
    assert got["label"].lower().startswith("status")


_ONE_VALUE = """
const facet = document.querySelector('.facet[data-field="status"]');
facet.querySelector('.facetopen').click();
// A VALUE, so `(none)` is skipped — this asks how a value the server holds under
// a machine name is spelled to a reader, and the sentinel is not one of those:
// it is spelled `(none)` on both sides and would make both claims below true by
// saying nothing. That is what it silently did on 2026-08-23, when the corpus
// grew a product and `(none)` arrived at the head of the Status menu; this probe
// took the first checkbox, so the test went on passing and stopped asking.
const box = [...facet.querySelectorAll('input[type=checkbox]')]
  .find(one => one.value !== NO_VALUE);
box.click();
const said = facet.querySelector('.facetsaid').textContent;
box.click();
return {said, value: box.value, emptied: facet.querySelector('.facetsaid').textContent,
        chosen: facet.classList.contains('chosen'), url: params.getAll('status')};
"""


def test_one_value_is_named_and_unticking_it_puts_the_field_back(page: str, tmp_path: Path):
    """`in_progress` is not what the page calls it anywhere else, so the word
    comes off the checkbox the server drew rather than out of a second copy of
    the vocabulary in this script."""
    got = measured_in(chrome(), page, tmp_path / "one.html", 1460, _ONE_VALUE)

    assert got["value"] != NO_VALUE, (
        "the sentinel is spelled the same on both sides, so naming it proves nothing"
    )
    assert got["said"] != got["value"] or "_" not in got["value"]
    assert " " in got["said"] or got["said"].istitle() or got["said"] == got["value"]
    assert got["emptied"] == "all"
    assert got["chosen"] is False
    assert got["url"] == []


_KEYBOARD = """
const facet = document.querySelector('.facet[data-field="kind"]');
const opener = facet.querySelector('.facetopen');
opener.focus();
opener.click();
const box = facet.querySelector('input[type=checkbox]');
box.focus();
const reachable = document.activeElement === box;
box.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true}));
return {
  reachable,
  hidden: facet.querySelector('.facetmenu').getBoundingClientRect().height === 0,
  expanded: opener.getAttribute('aria-expanded'),
  handedBack: document.activeElement === opener,
};
"""


def test_escape_closes_the_menu_and_hands_the_keyboard_back(page: str, tmp_path: Path):
    """The second half is the one that gets forgotten. Without it Escape drops
    focus on `<body>` and the next Tab starts from the top of the page — the same
    defect the draft row's Escape had, in a different control."""
    got = measured_in(chrome(), page, tmp_path / "keys.html", 1460, _KEYBOARD)

    assert got["reachable"], "the checkboxes cannot be reached with the keyboard"
    assert got["hidden"] is True
    assert got["expanded"] == "false"
    assert got["handedBack"], "Escape closed the menu and dropped the keyboard"


# `drawn` and not `.hidden`: the attribute is a request, and an author rule that
# sets `display` on the same element outranks the browser's `[hidden]` and simply
# ignores it. That is not a hypothetical — it shipped, and every menu on the bar
# stood open over the plan while `.hidden` answered `true` for all of them.
_ONE_AT_A_TIME = """
const drawn = facet => facet.querySelector('.facetmenu').getBoundingClientRect().height > 0;
const facets = [...document.querySelectorAll('.facet[data-field]')];
const [first, second] = facets;
const onLoad = facets.filter(drawn).length;
first.querySelector('.facetopen').click();
const firstOpen = drawn(first);
second.querySelector('.facetopen').click();
return {
  onLoad,
  firstOpen,
  firstStillOpen: drawn(first),
  secondOpen: drawn(second),
};
"""


def test_opening_one_field_closes_the_last(page: str, tmp_path: Path):
    """Ten fields whose menus all stayed open is a bar that covers the plan it is
    filtering."""
    got = measured_in(chrome(), page, tmp_path / "alone.html", 1460, _ONE_AT_A_TIME)

    # The bar arrives closed. Asked first because the version of this that asked
    # `.hidden` passed while all ten menus were drawn open on load.
    assert got["onLoad"] == 0, f"{got['onLoad']} menus are open before anybody pressed anything"
    assert got["firstOpen"]
    assert got["secondOpen"]
    assert got["firstStillOpen"] is False


_CLEARS = """
const status = document.querySelector('.facet[data-field="status"]');
const kind = document.querySelector('.facet[data-field="kind"]');
for (const facet of [status, kind]) {
  facet.querySelector('.facetopen').click();
  const boxes = [...facet.querySelectorAll('input[type=checkbox]')];
  boxes[0].click();
  if (boxes[1]) boxes[1].click();
}
const before = params.toString();
clearFilters();
return {
  before,
  after: params.toString(),
  ticked: [...document.querySelectorAll('.facetmenu input:checked')].length,
  said: [...document.querySelectorAll('.facetsaid')].map(s => s.textContent),
};
"""


def test_clearing_puts_every_field_back(page: str, tmp_path: Path):
    """A Clear that leaves a control set is a Clear that did not clear — the rule
    that already cost this bar one defect, when the people page's `role` was left
    behind because it is not a field of a record."""
    got = measured_in(chrome(), page, tmp_path / "clear.html", 1460, _CLEARS)

    assert got["before"], "nothing was set, so this asks nothing"
    assert got["after"] == ""
    assert got["ticked"] == 0
    assert set(got["said"]) == {"all"}


_PASTED = """
return {
  ticked: [...document.querySelectorAll('.facet[data-field="status"] input:checked')]
    .map(box => box.value).sort(),
  said: document.querySelector('.facet[data-field="status"] .facetsaid').textContent,
};
"""


def test_a_link_opens_with_its_boxes_ticked(index: Index, tmp_path: Path):
    """Every filter is in the URL, so a view is a link — and a link that opens
    with the rows filtered and the controls saying `all` is a page lying about
    why it is short."""
    page = render_table(index, base_commit=HEAD, may_write=True).replace(
        "<script>", "<script>history.replaceState(null,'','?status=ready&status=done');", 1
    )
    got = measured_in(chrome(), page, tmp_path / "pasted.html", 1460, _PASTED)

    assert got["ticked"] == ["done", "ready"]
    assert got["said"] == "2 chosen"


def test_the_server_answers_the_same_two_values(index: Index, page: str, tmp_path: Path):
    """And the half of this that never had a control: `apply_filters` has always
    ORed within a field, and now something can ask it to."""
    got = measured_in(chrome(), page, tmp_path / "server.html", 1460, _TWO_VALUES)

    assert apply_filters(index, {"status": got["wanted"]}, "") == got["kept"], (
        f"the server and the bar disagree about {json.dumps(got['wanted'])}"
    )


# --------------------------------------------------------------------------- #
# One page, several scripts, one global scope
# --------------------------------------------------------------------------- #


PAGES = ("records", "table", "graph", "timeline", "people", "cycle", "detail")


def every_page(index: Index) -> dict[str, str]:
    from openproj.render import (
        render_cycle,
        render_detail,
        render_graph,
        render_people,
        render_records,
        render_timeline,
    )

    number = max(e.cycle for e in index.plan.values() if e.cycle)
    return {
        # The landing shares the whole control bar's scope with a script of its
        # own, so it is in the sweep from the commit that adds it.
        "records": render_records(index, base_commit=HEAD, edited={}, now=0, may_write=True),
        "table": render_table(index, base_commit=HEAD, may_write=True),
        "graph": render_graph(index, base_commit=HEAD),
        "timeline": render_timeline(index),
        # The people page has no `base_commit`: what it writes is one icon, and
        # `editable` is how it is asked for.
        "people": render_people(index, editable=True),
        "cycle": render_cycle(index, number, base_commit=HEAD),
        "detail": render_detail(index, base_commit=HEAD),
    }


DECLARED = __import__("re").compile(r"^(?:function|const|let|var|class)\s+([A-Za-z_$][\w$]*)", 8)

# The opening bytes of each vendored bundle, read from the files themselves so a
# re-vendoring cannot leave this list behind.
STATIC = Path(__file__).parent.parent / "static"
VENDOR_MARKS = tuple(
    (STATIC / name).read_text(errors="replace")[:60]
    for name in sorted(path.name for path in STATIC.glob("*.js"))
    if (STATIC / name).exists()
)


@pytest.mark.parametrize("name", PAGES)
def test_no_two_scripts_on_a_page_declare_the_same_name(index: Index, name: str):
    """A page is several `<script>` blocks and one global scope.

    The shared control bar declares into the same namespace as the view under it,
    and the two are written in different places by different people at different
    times. This cost a whole afternoon twice in one hour: the bar's summary
    function was called `summarise`, the table already had a `summarise` that
    writes "17 of 17 shown", the table's won — and every field's button said
    `undefined` with nothing thrown anywhere. The other two were worse and
    louder: `const BAR` and `const labelOf` in the bar against the same names on
    the detail, cycle and graph pages, which is a page that does not run at all.

    Asked of the served page rather than of the source, because that is where the
    blocks end up in one scope. Top-level is approximated by column zero, which
    is this file's own formatting and is what a redeclaration would have to be.
    """
    page = every_page(index)[name]
    seen: dict[str, int] = {}
    for block in __import__("re").findall(r"<script[^>]*>(.*?)</script>", page, 16):
        # Vendored libraries are skipped, and only they: cytoscape's bundle
        # carries lodash's own top-level names twice inside one IIFE, which is
        # its business and not this page's. They are recognised by being the
        # files `static/SHA256SUMS` pins rather than by their size.
        if any(mark in block[:400] for mark in VENDOR_MARKS):
            continue
        for declared in DECLARED.findall(block):
            seen[declared] = seen.get(declared, 0) + 1

    twice = sorted(word for word, count in seen.items() if count > 1)
    assert not twice, (
        f"the {name} page declares {twice} more than once at the top level of its "
        f"scripts, so whichever block loads last silently wins"
    )


_PEOPLE_TWO_ROLES = """
const facet = document.querySelector('.facet[data-field="role"]');
facet.querySelector('.facetopen').click();
const boxes = [...facet.querySelectorAll('input[type=checkbox]')];
const wanted = [boxes[0].value, boxes[1].value];
boxes[0].click();
boxes[1].click();
const rows = [...document.querySelectorAll('tr[data-role]')];
return {
  wanted,
  url: params.getAll('role'),
  shown: rows.filter(row => !row.hidden).map(row => row.dataset.role),
  said: facet.querySelector('.facetsaid').textContent,
};
"""


def test_the_people_page_honours_both_values_too(index: Index, tmp_path: Path):
    """It draws the same bar, and it filters with a loop of its own — rows are
    rendered by the server there and hidden rather than rebuilt.

    Its loop read `params.get`, which is the first value and nothing else. A
    control that can set two and a page that reads one is exactly the divergence
    that was fixed in the search blob this morning, arriving through the control
    rather than through the data.
    """
    from openproj.render import render_people

    page = render_people(index, editable=True)
    got = measured_in(chrome(), page, tmp_path / "people.html", 1460, _PEOPLE_TWO_ROLES)

    assert got["url"] == got["wanted"]
    assert set(got["shown"]) == set(got["wanted"]), (
        f"the page shows {sorted(set(got['shown']))} for {got['wanted']}"
    )
    assert got["said"] == "2 chosen"


_THE_WAY_OUT = """
const out = document.getElementById('unfilter');
const atRest = out.hidden;
const facet = document.querySelector('.facet[data-field="status"]');
facet.querySelector('.facetopen').click();
facet.querySelector('input[type=checkbox]').click();
const once = out.hidden;
out.click();
return {atRest, once, after: out.hidden, params: params.toString(),
        ticked: document.querySelectorAll('.facetmenu input:checked').length};
"""


def test_the_way_out_appears_only_when_there_is_one(page: str, tmp_path: Path):
    """A Clear that is always there is a control that does nothing most of the
    time, and a reader has to read it to find that out. It appears when something
    is set, it clears everything, and it goes again."""
    got = measured_in(chrome(), page, tmp_path / "out.html", 1460, _THE_WAY_OUT)

    assert got["atRest"] is True, "a page with no filters offers a way out of them"
    assert got["once"] is False, "a field was set and nothing offered to unset it"
    assert got["after"] is True
    assert got["params"] == ""
    assert got["ticked"] == 0


_LOOKS_LIKE_A_MENU = """
const said = document.querySelector('.facet[data-field="status"] .facetsaid');
// Read into plain values before anything is clicked. `getComputedStyle` hands
// back a LIVE object: keeping the reference and clicking gave two readings of
// the open state and a test that said the caret had no ink in it.
const ink = () => {
  const drawn = getComputedStyle(said, '::after');
  return {top: drawn.borderTopColor, bottom: drawn.borderBottomColor,
          width: drawn.borderTopWidth};
};
const shut = ink();
const opener = document.querySelector('.facet[data-field="status"] .facetopen');
opener.click();
const open = ink();
// The colours and not the widths: three of the four borders are there in both
// states and only one of them has ink in it, which is what makes the triangle.
return {shut, open, ground: getComputedStyle(said).backgroundColor};
"""


def test_a_facet_reads_as_a_menu_and_not_as_a_box_to_type_in(page: str, tmp_path: Path):
    """The border alone reads as somewhere to type — which is what the bar looked
    like once the selects became buttons. The caret a browser draws on a real
    `<select>` is drawn here, and it turns over when the menu opens, which is the
    one thing that says a press did something when the menu is off the bottom of
    a short window."""
    got = measured_in(chrome(), page, tmp_path / "menu.html", 1460, _LOOKS_LIKE_A_MENU)

    clear = ("transparent", "rgba(0, 0, 0, 0)")
    assert got["shut"]["width"] != "0px", "there is no caret"
    assert got["shut"]["top"] not in clear, "the caret has no ink in it"
    assert got["shut"]["bottom"] in clear, "the caret points both ways at once"
    assert got["open"]["bottom"] not in clear, "the caret does not turn over when it opens"
    assert got["open"]["top"] in clear
    assert got["ground"] not in ("rgba(0, 0, 0, 0)", "transparent"), (
        "the control has no ground of its own, so it reads as part of the page"
    )


_NOTHING_OVER_THE_MENU = """
// Every field's menu, opened one at a time, asked what is painted at three
// points down its own middle. `elementFromPoint` and not a z-index comparison:
// the question is what a press would hit, and the answer is the browser's.
const covered = [];
for (const opener of document.querySelectorAll('.facetopen')) {
  const facet = opener.closest('.facet');
  const menu = facet.querySelector('.facetmenu');
  opener.click();
  const box = menu.getBoundingClientRect();
  if (box.height < 2) { opener.click(); continue; }
  for (const fy of [0.1, 0.5, 0.9]) {
    const x = box.left + box.width / 2, y = box.top + box.height * fy;
    const hit = document.elementFromPoint(x, y);
    if (!hit || !menu.contains(hit)) {
      const named = hit ? hit.tagName + (hit.id ? '#' + hit.id : '.' +
        String(hit.className || '').split(' ')[0]) : 'nothing';
      covered.push(`${facet.dataset.field} at ${Math.round(fy * 100)}%: ${named}`);
    }
  }
  opener.click();
}
return {fields: document.querySelectorAll('.facetopen').length, covered};
"""


@pytest.mark.parametrize("name", ("graph", "table", "timeline"))
def test_an_open_menu_is_not_painted_over(index: Index, name: str, tmp_path: Path):
    """A menu that opens under the page's own furniture is a menu whose middle
    rows cannot be pressed.

    jcanton, 2026-08-21, on the graph: the filter menus were drawn under the
    "Edit dependencies" button and the row it sits in. That row is `.commitbar`,
    sticky at z-index 10 on every page that can be edited, and the menu was at 6 —
    so a menu long enough to reach it lost the labels behind it while the ones
    above and below stayed pressable, which is the confusing half of the defect.

    Asked with `elementFromPoint` rather than by comparing z-indexes, because
    what matters is what a press lands on: stacking depends on the contexts
    between the two elements as much as on the numbers written on them.
    """
    got = measured_in(
        chrome(), every_page(index)[name], tmp_path / f"over-{name}.html", 1460,
        _NOTHING_OVER_THE_MENU, height=900, patience=2500,
    )

    assert got["fields"] > 3, f"{name}: there is no filter bar to measure"
    assert got["covered"] == [], (
        f"{name}: something is painted over an open menu: {got['covered']}"
    )
