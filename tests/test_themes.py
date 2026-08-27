"""Colour schemes: sixteen numbers in, fifty-five tokens out.

The app draws with fifty-five colour tokens and a base16 scheme supplies sixteen,
so the other thirty-nine are derived — once, for every scheme, in `_scheme_css`.
That is the only reason offering eighteen palettes is a small feature rather than
eighteen small features, and it is also the risk: one mapping that is wrong is
wrong everywhere.

So the numbers are asked of the schemes themselves. Twice, in two different
places, because they are two different questions. What a palette hands us is
arithmetic and is asked in Python. What the page ends up painting is `color-mix`
and cascade, and is asked of Chrome.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from browser import chrome, measured_in

from openproj.index import build_index
from openproj.model import load_repo
from openproj.render import (
    ROUTES,
    STATUS_SLOTS,
    STATUSES,
    _chosen,
    _scheme_css,
    render_graph,
    render_table,
)
from openproj.themes import FAMILIES, SLOTS, contrast

HEAD = "0" * 40


def test_every_palette_is_sixteen_colours():
    """The format is a fixed list, and a palette missing one of them would be a
    page with an unresolvable `var()` on it — which draws as nothing rather than
    as an error."""
    assert FAMILIES, "no schemes at all"
    for family in FAMILIES:
        for palette in (family.light, family.dark):
            slots = palette.slots
            assert tuple(slots) == SLOTS, palette.source
            for slot, value in slots.items():
                assert re.fullmatch(r"#[0-9a-f]{6}", value), (palette.source, slot, value)


def test_a_family_is_a_light_and_a_dark():
    """The picker chooses the family and the switch still chooses the polarity, so
    a family that answers only one of them is a switch that does nothing on that
    scheme."""
    for family in FAMILIES:
        light = family.light.slots
        dark = family.dark.slots
        assert contrast(light["base00"], "#ffffff") < contrast(dark["base00"], "#ffffff"), (
            f"{family.key}: the light palette's background is not lighter than the dark one's"
        )
    assert len({family.key for family in FAMILIES}) == len(FAMILIES), "two families, one key"


def test_the_ink_a_scheme_is_read_in_clears_the_floor():
    """base05 is what the format calls the foreground and a terminal scheme is
    free to make it anything: Material Lighter's is a teal at 1.8:1 against its
    own background, which is why that family is not offered. The pick is by
    contrast, so this is the assertion the pick exists to satisfy — on every
    palette, including the ones added after today.
    """
    for family in FAMILIES:
        for palette in (family.light, family.dark):
            slots = palette.slots
            picked = _chosen(slots)
            ink = contrast(slots[picked["fg"]], slots["base00"])
            muted = contrast(slots[picked["muted"]], slots["base00"])
            link = contrast(slots[picked["accent"]], slots["base00"])
            assert ink >= 7.0, f"{palette.source}: ink at {ink:.1f}:1"
            assert muted >= 4.5, f"{palette.source}: secondary ink at {muted:.1f}:1"
            assert link >= 3.5, f"{palette.source}: links at {link:.1f}:1"
            assert muted < ink, (
                f"{palette.source}: the secondary ink is not quieter than the primary, "
                "so the page has one level of hierarchy where it draws two"
            )


def test_the_stylesheet_answers_all_three_states_of_the_switch():
    """A theme choice has three states — light, dark, and the default, which
    follows the system — and a scheme has to answer all of them or a reader who
    has never touched the switch gets a light palette on a dark desktop.
    """
    css = _scheme_css()
    for family in FAMILIES:
        assert f':root[data-scheme="{family.key}"] {{' in css
        assert f':root[data-scheme="{family.key}"][data-theme="dark"] {{' in css
        assert f'  :root[data-scheme="{family.key}"]:not([data-theme="light"]) {{' in css, (
            f"{family.key} does not follow a dark system"
        )
    # And the derivation is one block for all of them, not one per scheme.
    page = render_table(
        build_index(*_seed(), date(2026, 8, 17)), ROUTES, base_commit=HEAD, may_write=True
    )
    assert page.count(":root[data-scheme] {") == 1 + len(STATUS_SLOTS)


def _seed():
    records, config, _ = load_repo(Path(__file__).resolve().parents[1] / "seed")
    return records, config


# Every scheme, both polarities, in one page load: set the attributes, read what
# the page actually resolves, and hand back the ratios. `getComputedStyle` on a
# custom property returns the token stream it was written as, so a mix has to go
# through something that computes it — the same 1x1 canvas the graph uses to hand
# cytoscape a colour it can read.
_CONTRAST = """
const dye = document.createElement('canvas').getContext('2d', {willReadFrequently: true});
const rgb = value => {
  dye.clearRect(0, 0, 1, 1);
  dye.fillStyle = '#000';
  dye.fillStyle = value;
  dye.fillRect(0, 0, 1, 1);
  const [r, g, b] = dye.getImageData(0, 0, 1, 1).data;
  return [r / 255, g / 255, b / 255];
};
const lum = value => {
  const [r, g, b] = rgb(value).map(one =>
    one <= 0.03928 ? one / 12.92 : Math.pow((one + 0.055) / 1.055, 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
};
const ratio = (one, two) => {
  const [a, b] = [lum(one), lum(two)].sort((x, y) => x - y);
  return (b + 0.05) / (a + 0.05);
};
const root = document.documentElement;
const token = name => getComputedStyle(root).getPropertyValue(name).trim();

const out = [];
for (const scheme of SCHEMES) {
  for (const polarity of ['light', 'dark']) {
    if (scheme) root.dataset.scheme = scheme; else delete root.dataset.scheme;
    root.dataset.theme = polarity;
    const bg = token('--bg');
    const worst = {};
    worst.fg = ratio(token('--fg'), bg);
    worst.muted = ratio(token('--muted'), bg);
    worst.accent = ratio(token('--accent'), bg);
    for (const status of STATUSES) {
      // The chip: its word on its own soft ground.
      worst['chip:' + status] = ratio(token(`--st-${status}-text`),
                                      token(`--st-${status}-soft`));
      // The node and the bar: the title on the fill it is drawn on.
      worst['fill:' + status] = ratio(token(`--st-${status}-ink`), token(`--st-${status}`));
    }
    out.push({scheme: scheme || 'openproj', polarity, worst});
  }
}
return out;
"""


def test_every_scheme_is_readable_where_the_page_paints_it(tmp_path: Path):
    """The derivation, measured where it happens.

    Python can check what a palette hands us; only a browser can check what the
    cascade and `color-mix` make of it. Every family, both polarities, every
    status chip and every status fill — which is 190 ratios, and the reason they
    are worth having is that the mapping is ONE mapping: a mix at the wrong
    proportion is unreadable on eighteen palettes at once, and pleasant on the
    one somebody happened to look at.

    4.5:1 is AA for body text and is what a chip's word and a node's title are.
    """
    page = render_table(
        build_index(*_seed(), date(2026, 8, 17)), ROUTES, base_commit=HEAD, may_write=True
    )
    keys = ["", *(family.key for family in FAMILIES)]
    # Both lists interpolated, and the second one used not to be: it was the
    # status ladder retyped as a JavaScript literal in a test file, which is the
    # "corpus that does not contain the one string that matters" failure with the
    # corpus written by hand. This is the ONE harness that measures what
    # `color-mix` actually paints per scheme, so a rung it does not know about is
    # a rung nobody has ever measured — and it stayed green through the commit
    # that added one, still reporting 190 ratios about five statuses.
    script = (
        f"const SCHEMES = {keys!r};\nconst STATUSES = {list(STATUSES)!r};\n" + _CONTRAST
    ).replace("'", '"')
    got = measured_in(
        chrome(), page, tmp_path / "contrast.html", 1200, script, height=900, patience=2500
    )

    # 4.5:1 is AA for body text, which is what a chip's word and a node's title
    # are. Links are held to 3.5 and the floor is argued where it is set
    # (`_LINK_FLOOR` in `render.py`): Solarized's blue on Solarized's cream is
    # 4.1, and refusing Solarized over that is refusing the scheme half the
    # people who asked for this meant by it.
    floor = {"accent": 3.5}
    bad = [
        f"{one['scheme']}/{one['polarity']} {what} {ratio:.1f}:1"
        for one in got
        for what, ratio in one["worst"].items()
        if ratio < floor.get(what, 4.5)
    ]
    assert not bad, bad


_PICKER = """
const select = document.getElementById('scheme');
const before = document.documentElement.dataset.scheme;
select.value = 'gruvbox';
select.dispatchEvent(new Event('change'));
const chosen = {scheme: document.documentElement.dataset.scheme,
                stored: localStorage.getItem('openproj:scheme'),
                bg: getComputedStyle(document.documentElement).getPropertyValue('--bg').trim()};
select.value = '';
select.dispatchEvent(new Event('change'));
const cleared = {scheme: document.documentElement.dataset.scheme ?? null,
                 stored: localStorage.getItem('openproj:scheme'),
                 bg: getComputedStyle(document.documentElement).getPropertyValue('--bg').trim()};
return {before: before ?? null, chosen, cleared,
        offered: [...select.options].map(o => o.value)};
"""


def test_the_picker_puts_the_scheme_on_the_page_and_takes_it_off_again(tmp_path: Path):
    """Choosing a scheme is one attribute on the root element, and choosing
    "openproj" is the absence of it — not a scheme named default.

    The whole stylesheet is written for a page with no `data-scheme` on it, and
    every rule that answers a scheme is one specificity step above that. A
    "default" scheme would be a second copy of the app's own palette, free to
    drift from the one every page without a choice is still drawn in.
    """
    page = render_table(
        build_index(*_seed(), date(2026, 8, 17)), ROUTES, base_commit=HEAD, may_write=True
    )
    got = measured_in(
        chrome(), page, tmp_path / "picker.html", 1200, _PICKER, height=900, patience=2000
    )

    assert got["before"] is None, "a page nobody has chosen for arrives with a scheme"
    assert got["offered"][0] == "", "the app's own colours are the first option"
    assert set(got["offered"][1:]) == {family.key for family in FAMILIES}
    assert got["chosen"]["scheme"] == "gruvbox"
    assert got["chosen"]["stored"] == "gruvbox"
    assert got["chosen"]["bg"] == "#fbf1c7", got["chosen"]
    assert got["cleared"]["scheme"] is None, "the attribute stayed on the page"
    assert got["cleared"]["stored"] == ""
    assert got["cleared"]["bg"] == "#ffffff", got["cleared"]


_BOXES = """
const root = document.documentElement;
root.dataset.scheme = 'gruvbox';
root.dataset.theme = 'light';
const bg = getComputedStyle(document.body).backgroundColor;
const boxes = [...document.querySelectorAll('input[type="search"], input[type="text"], textarea')];
return {
  bg,
  count: boxes.length,
  odd: boxes.filter(one => getComputedStyle(one).backgroundColor !== bg)
    .map(one => one.id || one.name || one.type),
};
"""


def test_a_scheme_reaches_the_boxes_people_type_into(tmp_path: Path):
    """A search box is a `<input type=search>` with no background of its own, so
    it is drawn in the browser's Field colour — white on every light
    `color-scheme`, whatever the page around it is painted.

    jcanton, 2026-08-20, having switched schemes: "the search boxes backgrounds
    are still white/black". Buttons and selects had been given the app's colours
    when the controls were made consistent; the boxes had not, because nothing in
    the default palette made them look wrong.
    """
    page = render_table(
        build_index(*_seed(), date(2026, 8, 17)), ROUTES, base_commit=HEAD, may_write=True
    )
    got = measured_in(
        chrome(), page, tmp_path / "boxes.html", 1400, _BOXES, height=900, patience=1500
    )

    assert got["count"], "no typing boxes on the page at all"
    assert got["bg"] == "rgb(251, 241, 199)", f"the scheme did not apply: {got['bg']}"
    assert got["odd"] == [], f"drawn in the browser's colours, not the page's: {got['odd']}"


_CANVAS = """
const fills = {};
cy.nodes().filter(n => n.isChildless()).forEach(n => {
  fills[n.data('status')] = n.style('background-color');
});
return {fills, token: token('--st-done'), edge: cy.edges()[0].style('line-color')};
"""


def test_the_drawing_gets_colours_it_can_actually_read(tmp_path: Path):
    """cytoscape is handed strings, and a custom property's computed value is the
    token stream it was written as — so a scheme's `--st-done` arrives as
    `color-mix(in oklab, #859900 42%, #002b36)`, or as the `oklab(...)` that
    computes to, and cytoscape parses neither.

    It drew every node in its default grey with the borders still correct, which
    is a drawing that looks deliberate. So the tokens the canvas reads go through
    the browser's own conversion first, and what arrives is `rgb(...)`.
    """
    index = build_index(*_seed(), date(2026, 8, 17))
    page = render_graph(index, ROUTES, base_commit=HEAD).replace(
        "<html", '<html data-scheme="solarized" data-theme="dark"', 1
    )
    got = measured_in(
        chrome(), page, tmp_path / "canvas.html", 1500, _CANVAS, height=900, patience=3500
    )

    assert all(re.fullmatch(r"rgb\(\d+,\s*\d+,\s*\d+\)", one) for one in got["fills"].values()), (
        got["fills"]
    )
    assert len(set(got["fills"].values())) == len(got["fills"]), (
        f"the statuses are drawn in {len(set(got['fills'].values()))} colours: {got['fills']}"
    )
    assert re.fullmatch(r"rgb\(\d+,\s*\d+,\s*\d+\)", got["edge"]), got["edge"]
