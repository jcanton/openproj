"""Where the other people in the room are, drawn.

A name says somebody else is in the document. It does not say which paragraph
they are in — and in a shaping document that is the thing you need in order not
to rewrite the sentence somebody is halfway through.

Everything here is measured in Chrome with a stubbed socket. Two logins cannot be
driven from one browser: a cookie is per origin, not per tab, so signing one tab
in as somebody else signs both. The socket is therefore replaced before the
page's own scripts run, and the frames the room would send are pushed by hand —
which is the same shape as the room, with the network taken out.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from browser import chrome, measured_in

from openproj.index import Index, build_index
from openproj.model import load_repo
from openproj.render import ROUTES, render_detail

HEAD = "0123456789abcdef0123456789abcdef01234567"


@pytest.fixture
def index(demo_root: Path) -> Index:
    records, config, _ = load_repo(demo_root)
    return build_index(records, config, date(2026, 8, 17))


def a_record_with_a_document(index: Index) -> str:
    for record_id, record in sorted(index.plan.items()):
        if record.body.count("\n") > 8:
            return record_id
    raise AssertionError("no record here has a document long enough to sit in")


# The socket the page opens, replaced before the page's scripts run. `welcome`
# seeds the editor and `who` is the frame under test; both are what the server
# actually sends, spelled the same way.
STUB = """
<script>
window.__frames = [];
class FakeSocket {
  // The four constants the page reads off the CLASS: its `send` is guarded by
  // `socket.readyState === WebSocket.OPEN`, and a stub without them compares a
  // number against `undefined` and silently sends nothing at all.
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;
  constructor(url) {
    window.__socket = this;
    this.url = url;
    this.readyState = 1;
    setTimeout(() => this.onopen && this.onopen(), 0);
  }
  send(data) { window.__frames.push(JSON.parse(data)); }
  close() {}
  hear(message) { this.onmessage && this.onmessage({data: JSON.stringify(message)}); }
}
window.WebSocket = FakeSocket;
</script>
"""

# Open the editor, answer the handshake the way the room does, and put somebody
# else in the document at a known place.
#
# The document is typed in rather than delivered in the welcome: a room seeded
# from an empty state vector holds an empty text, and `reflect` writes that into
# the textarea — so every band was measured against no text at all and they all
# landed on line one. The lines are numbered so the assertion can name the one
# the band should be on.
LINES = "\\n".join(f"line {n}" for n in range(12))

SEAT = """
<script>
addEventListener('load', () => setTimeout(() => {
  flipEditing();
  const socket = window.__socket;
  socket.hear({t: 'welcome', seed: null, sv: 'AA==', update: '', people: ['ann', 'bo']});
  const body = document.querySelector('textarea[name=body]');
  body.value = '%LINES%';
  body.dispatchEvent(new Event('input'));
  // The start of the third line, which is where the band should be drawn.
  window.__at = body.value.indexOf('line 2');
  socket.hear({t: 'who', people: ['ann', 'bo'],
               where: [{login: 'bo', at: window.__at}]});
}, 200));
</script>
""".replace("%LINES%", LINES)

_DRAWN = """
const layer = document.getElementById('seats');
const band = layer.firstElementChild;
const body = document.querySelector('textarea[name=body]');
const style = getComputedStyle(body);
return {
  bands: layer.children.length,
  name: band ? band.textContent : '',
  top: band ? band.getBoundingClientRect().top : null,
  height: band ? Math.round(band.getBoundingClientRect().height) : null,
  line: Math.round(parseFloat(style.lineHeight)),
  bodyTop: body.getBoundingClientRect().top,
  events: band ? getComputedStyle(band).pointerEvents : '',
  at: window.__at,
};
"""


def test_the_room_draws_a_band_where_somebody_else_is(index: Index, tmp_path: Path):
    """One band, on the line their caret is in, with their name on it.

    A band and not a caret: a caret drawn through a mirror element is wrong by a
    pixel or two and reads as a claim about a character, while a band is either
    right about the line or visibly wrong about it — and visibly wrong is a state
    somebody can act on.
    """
    record_id = a_record_with_a_document(index)
    # `may_write`, because the socket is only offered to somebody the server
    # would take a frame from — see `test_socket_offer.py`. Without it this page
    # carries no room at all and there is nothing here to test. `editor="plain"`
    # for the other half of the same sentence: the bands are drawn over a
    # `<textarea>`, and since 2026-08-20 an address that says nothing gets Ace.
    page = render_detail(
        index, ROUTES, only=record_id, base_commit=HEAD, may_write=True, editor="plain"
    )
    page = page.replace("<head>", "<head>" + STUB, 1).replace("</body>", SEAT + "</body>")

    got = measured_in(chrome(), page, tmp_path / "seat.html", 1200, _DRAWN, height=900)

    assert got["bands"] == 1, "nobody was drawn"
    assert got["name"] == "bo"
    assert got["height"] == got["line"], "the band is not one line tall"
    # The third line of the document, which is where the caret was put. Measured
    # in line-heights from the top of the box, which is what a reader sees.
    lines = round((got["top"] - got["bodyTop"]) / got["line"])
    assert lines == 2, f"the band is {lines} lines down and the caret is on line 2"
    assert got["events"] == "none", "the layer takes clicks that belong to the box"


_MINE = """
const layer = document.getElementById('seats');
return {bands: layer.children.length};
"""

MY_OWN_SEAT = """
<script>
addEventListener('load', () => setTimeout(() => {
  flipEditing();
  // `you` is how the room tells a tab which of the names is its own — the page
  // does not know until the welcome says so, which is why this frame carries it.
  window.__socket.hear({t: 'welcome', seed: null, sv: 'AA==', update: '',
                        you: 'ann', people: ['ann']});
  window.__socket.hear({t: 'who', people: ['ann'], where: [{login: 'ann', at: 40}]});
}, 200));
</script>
"""


def test_nobody_is_drawn_a_band_for_themselves(index: Index, tmp_path: Path):
    """Your own caret is the one thing on the page you can already see."""
    record_id = a_record_with_a_document(index)
    # `may_write`, because the socket is only offered to somebody the server
    # would take a frame from — see `test_socket_offer.py`. Without it this page
    # carries no room at all and there is nothing here to test. `editor="plain"`
    # for the other half of the same sentence: the bands are drawn over a
    # `<textarea>`, and since 2026-08-20 an address that says nothing gets Ace.
    page = render_detail(
        index, ROUTES, only=record_id, base_commit=HEAD, may_write=True, editor="plain"
    )
    page = page.replace("<head>", "<head>" + STUB, 1).replace(
        "</body>", MY_OWN_SEAT + "</body>"
    )

    got = measured_in(chrome(), page, tmp_path / "mine.html", 1200, _MINE, height=900)

    assert got["bands"] == 0


TWO_PEOPLE = """
<script>
addEventListener('load', () => setTimeout(() => {
  flipEditing();
  const socket = window.__socket;
  socket.hear({t: 'welcome', seed: null, sv: 'AA==', update: '',
               people: ['ann', 'bo', 'cy']});
  const body = document.querySelector('textarea[name=body]');
  body.value = '%LINES%';
  body.dispatchEvent(new Event('input'));
  socket.hear({t: 'who', people: ['ann', 'bo', 'cy'],
               where: [{login: 'bo', at: body.value.indexOf('line 1')},
                       {login: 'cy', at: body.value.indexOf('line 7')}]});
}, 200));
</script>
""".replace("%LINES%", LINES)

_COLOURS = """
const bands = [...document.getElementById('seats').children];
return {
  count: bands.length,
  names: bands.map(band => band.textContent),
  grounds: bands.map(band => band.style.background),
  tops: bands.map(band => Math.round(band.getBoundingClientRect().top)),
};
"""


def test_two_people_get_two_colours_and_two_places(index: Index, tmp_path: Path):
    """The colour comes from the login, so the same person is the same colour in
    everybody's window and nothing has to allocate one. The name is on the band
    because a colour on its own is a colour a reader has to be told the meaning
    of."""
    record_id = a_record_with_a_document(index)
    # `may_write`, because the socket is only offered to somebody the server
    # would take a frame from — see `test_socket_offer.py`. Without it this page
    # carries no room at all and there is nothing here to test. `editor="plain"`
    # for the other half of the same sentence: the bands are drawn over a
    # `<textarea>`, and since 2026-08-20 an address that says nothing gets Ace.
    page = render_detail(
        index, ROUTES, only=record_id, base_commit=HEAD, may_write=True, editor="plain"
    )
    page = page.replace("<head>", "<head>" + STUB, 1).replace(
        "</body>", TWO_PEOPLE + "</body>"
    )

    got = measured_in(chrome(), page, tmp_path / "two.html", 1200, _COLOURS, height=900)

    assert got["count"] == 2
    assert got["names"] == ["bo", "cy"]
    assert got["grounds"][0] != got["grounds"][1], "two people, one colour"
    assert got["tops"][0] != got["tops"][1], "two carets, one line"


_SENT = """
const body = document.querySelector('textarea[name=body]');
body.focus();
body.selectionStart = body.selectionEnd = body.value.indexOf('line 5');
body.dispatchEvent(new Event('keyup'));
return {wanted: body.value.indexOf('line 5'),
        sent: window.__frames.filter(frame => frame.t === 'at').map(frame => frame.at)};
"""


def test_this_tab_says_where_it_is_sitting(index: Index, tmp_path: Path):
    """The other half: a room can only draw what its members tell it."""
    record_id = a_record_with_a_document(index)
    # `may_write`, because the socket is only offered to somebody the server
    # would take a frame from — see `test_socket_offer.py`. Without it this page
    # carries no room at all and there is nothing here to test. `editor="plain"`
    # for the other half of the same sentence: the bands are drawn over a
    # `<textarea>`, and since 2026-08-20 an address that says nothing gets Ace.
    page = render_detail(
        index, ROUTES, only=record_id, base_commit=HEAD, may_write=True, editor="plain"
    )
    page = page.replace("<head>", "<head>" + STUB, 1).replace("</body>", SEAT + "</body>")

    got = measured_in(chrome(), page, tmp_path / "sent.html", 1200, _SENT, height=900)

    assert got["wanted"] in got["sent"], (
        f"the caret moved to {got['wanted']} and the room heard {got['sent']}"
    )


# S3.1's regression test, and the only one in this file that is about a pixel
# rather than about a line.
#
# The band under test sits BELOW a paragraph long enough to wrap dozens of times,
# so where it lands is a question about where every one of those wraps falls —
# which is a question about the mirror's width, to a fraction of a pixel. The
# mirror this replaces set `ghost.style.width = BODY.clientWidth + 'px'` on a
# `border-box` element it had also handed the textarea's border, so it measured a
# content box two whole borders narrower than the real one, and `clientWidth` is
# an integer where the box is fractional. At a width sitting on a wrap boundary
# that flips one break and every band below it is a whole 20.15px row out.
#
# So the width is SWEPT, one CSS pixel at a time. A single width proves nothing:
# the error is invisible at most of them and a line height at a few.
_WRAPPING = "\\n".join((
    "first line",
    "a paragraph of ordinary prose that has to wrap many times over at every one "
    "of the widths this sweeps, which is what makes where it ends sensitive to a "
    "mirror that is two pixels narrower than the box it mirrors. " * 10,
    "third line",
    "fourth line",
    "fifth line, and the caret below is in this one",
))

WRAPPED_SEAT = """
<script>
addEventListener('load', () => setTimeout(() => {
  flipEditing();
  const socket = window.__socket;
  socket.hear({t: 'welcome', seed: null, sv: 'AA==', update: '', people: ['ann', 'bo']});
  const body = document.querySelector('textarea[name=body]');
  body.value = '%LINES%';
  body.dispatchEvent(new Event('input'));
  window.__at = body.value.indexOf('the caret below is in this one');
  socket.hear({t: 'who', people: ['ann', 'bo'],
               where: [{login: 'bo', at: window.__at}]});
}, 200));
</script>
""".replace("%LINES%", _WRAPPING)

_BAND_AT_EVERY_WIDTH = """
const body = document.querySelector('textarea[name=body]');
const layer = document.getElementById('seats');
const article = document.querySelector('article.record');
const settle = ms => new Promise(go => setTimeout(go, ms));

// The ground truth, built here and owing nothing to the page: a CONTENT-box div
// with no padding and no border, given the box's real content width term by
// term, and a zero-width marker at the caret. The page's mirror is a BORDER-box
// div handed the box's padding and border — two constructions that have to
// agree. Using the page's own would be a test that agrees with whatever the page
// does, which is how the scroll-sync test came to pin its own defect in place.
function truthTop(index) {
  const style = getComputedStyle(body);
  const mirror = document.createElement('div');
  for (const name of ['fontFamily', 'fontSize', 'fontWeight', 'lineHeight',
                      'letterSpacing', 'whiteSpace', 'wordBreak', 'overflowWrap',
                      'tabSize']) {
    mirror.style[name] = style[name];
  }
  mirror.style.position = 'absolute';
  mirror.style.top = '0';
  mirror.style.left = '-9999px';
  mirror.style.boxSizing = 'content-box';
  mirror.style.padding = '0';
  mirror.style.border = '0';
  const bars = body.offsetWidth - body.clientWidth
    - parseFloat(style.borderLeftWidth) - parseFloat(style.borderRightWidth);
  mirror.style.width = (body.getBoundingClientRect().width
    - parseFloat(style.borderLeftWidth) - parseFloat(style.borderRightWidth)
    - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight) - bars) + 'px';
  mirror.textContent = body.value.slice(0, index);
  const mark = document.createElement('span');
  mark.textContent = '\\u200b';
  mirror.append(mark);
  document.body.append(mirror);
  const top = mark.getBoundingClientRect().top - mirror.getBoundingClientRect().top;
  mirror.remove();
  // On the screen: the box's border box, plus its border, plus its padding.
  return body.getBoundingClientRect().top
    + parseFloat(style.borderTopWidth) + parseFloat(style.paddingTop) + top;
}

// Let the gutter settle first. Its column is the box's own left padding, so it
// changes where every line wraps — and it is the reason a band can be a whole row
// out at a width where nothing else moved.
await settle(120);

// **The width is swept on `.bodywrap`, and it used to be swept on `--measure`.**
// That was a sweep that never moved anything. Editing puts the page in full page
// — `article.record.full`, `body.fullpage` — and `article.record.full` overrides
// the `width: var(--measure)` this was writing, so the box measured 800px at all
// eighty widths and the worst error across the whole sweep was exactly 0.00px.
// The test passed for as long as it has existed and asked nothing.
//
// `.bodywrap` carries no width rule of its own — `position: relative` and
// nothing else — so an inline width lands on the box the mirror mirrors, and the
// gutter's column, the scrollbar and the wrap all move with it, which is the
// question this file's hardest test exists to ask.
const wrap = body.closest('.bodywrap');
const line = parseFloat(getComputedStyle(body).lineHeight);
const answers = [];
for (let measure = 460; measure < 540; measure++) {
  wrap.style.width = measure + 'px';
  // Synchronous, and that is why it is the event and not a wait: `drawSeats`
  // listens for this one directly, while a `ResizeObserver` is delivered on the
  // rendering step, which the headless clock runs exactly once.
  dispatchEvent(new Event('openproj:editing'));
  const band = layer.firstElementChild;
  answers.push({
    measure,
    bands: layer.children.length,
    width: body.getBoundingClientRect().width,
    off: band ? Math.abs(band.getBoundingClientRect().top - truthTop(window.__at)) : null,
  });
}

// And the last case, which is the one this stage created and had to close: the
// gutter's column IS the box's own `padding-left`, so a document going from nine
// lines to ten widens it by a character, narrows the content box and rewraps
// every line under every band. Nothing dispatches an `input` for that, and the
// bands were left where the old wrapping had put them until something else
// happened to redraw them.
wrap.style.width = '500px';
dispatchEvent(new Event('openproj:editing'));
await settle(120);
const narrow = getComputedStyle(body).paddingLeft;
body.value = body.value + '\\n'
  + Array.from({length: 12}, (_, at) => 'tail line ' + at).join('\\n');
body.dispatchEvent(new Event('input', {bubbles: true}));
await settle(120);
const widened = {
  was: narrow,
  now: getComputedStyle(body).paddingLeft,
  off: Math.abs(layer.firstElementChild.getBoundingClientRect().top
                - truthTop(window.__at)),
};

return {answers, widened, line,
        widths: [...new Set(answers.map(answer => answer.width))].length,
        numbered: wrap.classList.contains('numbered')};
"""


def test_a_seat_band_lands_on_the_right_line_at_a_width_that_wraps(
    index: Index, tmp_path: Path
):
    """S3.1, and the reason it is a correctness fix and not a tidy-up.

    A band that is one line out is worse than no band: it points at the sentence
    above the one somebody is actually typing in, and it does it silently.
    `VENDOR.md` holds this whole feature to exactly that sentence.

    The width is swept a pixel at a time because the failure only appears at a
    width sitting on a wrap boundary — at most widths a mirror two pixels too
    narrow gives the same answer as a correct one, which is why nothing in this
    suite noticed for as long as it was there.
    """
    record_id = a_record_with_a_document(index)
    # `may_write`, because the socket is only offered to somebody the server
    # would take a frame from — see `test_socket_offer.py`. Without it this page
    # carries no room at all and there is nothing here to test. `editor="plain"`
    # for the other half of the same sentence: the bands are drawn over a
    # `<textarea>`, and since 2026-08-20 an address that says nothing gets Ace.
    page = render_detail(
        index, ROUTES, only=record_id, base_commit=HEAD, may_write=True, editor="plain"
    )
    page = page.replace("<head>", "<head>" + STUB, 1).replace(
        "</body>", WRAPPED_SEAT + "</body>"
    )

    got = measured_in(
        chrome(), page, tmp_path / "wrapped.html", 1200, _BAND_AT_EVERY_WIDTH,
        height=900, patience=4800,
    )

    assert got["numbered"], (
        "the gutter is off, so this sweep never asks the question it exists for: "
        "the column is the box's own left padding and it decides where lines wrap"
    )
    # And the other half of the same guard, which was missing for as long as this
    # test has existed: a sweep whose box never changes width sweeps nothing. It
    # measured 800px at all eighty widths and reported a worst error of 0.00px.
    assert got["widths"] > 1, (
        f"the box was the same width at all {len(got['answers'])} widths in the "
        "sweep, so every sample asked the same question and none of them was the "
        "one this test exists for"
    )
    worst = max(answer["off"] for answer in got["answers"])
    where = max(got["answers"], key=lambda answer: answer["off"])
    assert all(answer["bands"] == 1 for answer in got["answers"]), "nobody was drawn"
    assert worst < 1.0, (
        f"a band is {worst:.2f}px off the row its caret is in at --measure: "
        f"{where['measure']}px, on a {got['line']:.2f}px row"
    )

    # The gutter's own column, which is the box's left padding: a document that
    # grows past nine lines widens it, and everything under every band rewraps.
    assert got["widened"]["now"] != got["widened"]["was"], (
        "the column did not change width, so this half of the test asks nothing"
    )
    assert got["widened"]["off"] < 1.0, (
        f"turning the gutter's column wider moved the text and left the band "
        f"{got['widened']['off']:.2f}px behind, on a {got['line']:.2f}px row — "
        "which is the defect this stage exists to remove, arriving through the "
        "stage's own new feature"
    )


_REMOTE_LINES = """
const body = document.querySelector('textarea[name=body]');
const settle = ms => new Promise(go => setTimeout(go, ms));
await settle(140);
const before = {
  numbers: document.querySelectorAll('.lineno').length,
  lines: body.value.split('\\n').length,
};

// A real update, built the way the room builds one: a second document, a real
// insert into the same named text, and `encodeStateAsUpdate` — which is byte for
// byte what arrives down the socket when somebody else types. Not a synthetic
// frame: applying it goes through `YJS.applyUpdate` and out through the page's
// own `text.observe`, which is the path under test.
const other = new YJS.Doc();
other.getText('body').insert(0, 'a remote line\\nand a second\\nand a third\\n');
const update = YJS.encodeStateAsUpdate(other);
let bytes = '';
for (const byte of update) bytes += String.fromCharCode(byte);
window.__socket.hear({t: 'update', u: btoa(bytes)});
await settle(140);

return {before, after: {
  numbers: document.querySelectorAll('.lineno').length,
  lines: body.value.split('\\n').length,
}};
"""


def test_somebody_elses_keystroke_leaves_the_numbers_counting_the_document_there_is_now(
    index: Index, tmp_path: Path
):
    """`reflect` puts the room's text into the box by assigning `.value`, and
    assigning `.value` fires no `input` event.

    Everything drawn over this box hangs off one. `heard` already calls
    `drawSeats(); sit();` here and says why — "somebody else's text arrived, so
    every band below the change is now on the wrong line" — and the gutter is a
    band by another name that was added later and was not given the same wake-up.
    So in a live room somebody else adding three lines left your numbers counting
    a document nobody had any more, until you typed or resized the window.
    """
    record_id = a_record_with_a_document(index)
    # `may_write`, because the socket is only offered to somebody the server
    # would take a frame from — see `test_socket_offer.py`. Without it this page
    # carries no room at all and there is nothing here to test. `editor="plain"`
    # for the other half of the same sentence: the bands are drawn over a
    # `<textarea>`, and since 2026-08-20 an address that says nothing gets Ace.
    page = render_detail(
        index, ROUTES, only=record_id, base_commit=HEAD, may_write=True, editor="plain"
    )
    page = page.replace("<head>", "<head>" + STUB, 1).replace("</body>", SEAT + "</body>")

    got = measured_in(
        chrome(), page, tmp_path / "remote.html", 1200, _REMOTE_LINES, height=900,
        patience=2800,
    )

    assert got["before"]["numbers"] == got["before"]["lines"], (
        "the gutter was already wrong before anybody else typed"
    )
    assert got["after"]["lines"] > got["before"]["lines"], (
        "the remote update added no lines, so this test asks nothing"
    )
    assert got["after"]["numbers"] == got["after"]["lines"], (
        f"somebody else added lines and the gutter still shows "
        f"{got['after']['numbers']} numbers for {got['after']['lines']} lines"
    )


# The same room, on the second surface. Nothing is typed: the question is what
# the page does when somebody else arrives and this editor cannot draw where
# they are.
_ACE_SEAT = """
<script>
addEventListener('load', () => setTimeout(() => {
  flipEditing();
  const socket = window.__socket;
  socket.hear({t: 'welcome', seed: null, sv: 'AA==', update: '', people: ['ann', 'bo']});
  socket.hear({t: 'who', people: ['ann', 'bo'], where: [{login: 'bo', at: 3}]});
}, 300));
</script>
"""

_ACE_DRAWN = """
const host = document.querySelector('.acebox');
// Forced, for the reason the sweep's `paint` gives: the marker layer redraws on
// a frame, and the headless clock this runs under fires roughly none.
if (host) host.env.editor.renderer.updateFull(true);
const band = host ? host.querySelector('.op-seat') : null;
return {
  surface: host ? 'ace' : 'textarea',
  bands: host ? host.querySelectorAll('.op-seat').length : 0,
  layer: document.getElementById('seats').children.length,
  // The login is a custom property the marker layer's own `cssText` carries,
  // drawn by `::after` — see the rule in `editor.py` for why it is not a child
  // element. So it is read the way it is written.
  name: band ? getComputedStyle(band, '::after').content : '',
  ink: band ? getComputedStyle(band, '::after').backgroundColor : '',
  together: document.getElementById('together').textContent,
  // The sentence the refusal used to say. It is gone, and it has to be gone
  // rather than merely outvoted by a band: a page that draws the seat AND says
  // seats are not drawn here is worse than either half on its own.
  said: document.getElementById('state').textContent
        + ' ' + document.getElementById('announce').textContent,
};
"""


def test_the_second_surface_draws_where_everybody_is(index: Index, tmp_path: Path):
    """The band reaches the other editor, and the refusal goes with it.

    This test is the inverse of the one it replaces. `provides.seats` was false
    on Ace and `drawSeats` announced "not drawn in this editor" instead — an
    honest refusal, and the right one for as long as the band's origin was a
    number nothing had measured. It is not a number any more: the band is drawn
    by Ace's own marker layer, in Ace's own coordinate space, on the same frame
    as the selection and the active line.

    So the announcement is not merely redundant now, it is wrong, and a page
    that draws a band while saying it cannot is worse than either half alone.
    """
    record_id = a_record_with_a_document(index)
    page = render_detail(
        index, ROUTES, only=record_id, base_commit=HEAD, may_write=True, editor="ace"
    )
    page = page.replace("<head>", "<head>" + STUB, 1).replace("</body>", _ACE_SEAT + "</body>")

    got = measured_in(
        chrome(), page, tmp_path / "ace-seat.html", 1200, _ACE_DRAWN, height=900,
        query="?editor=ace", patience=4800,
    )

    assert got["surface"] == "ace", "the page did not open on the second surface"
    assert got["bands"] == 1, "somebody else is in the document and no band was drawn"
    assert "bo" in got["name"], (
        f"the band is drawn and does not say whose it is: it reads {got['name']!r}"
    )
    assert got["ink"] not in ("", "rgba(0, 0, 0, 0)"), (
        "the login is drawn with no ground under it, so it is dark text on whatever "
        "the document happens to say underneath"
    )
    assert "bo" in got["together"], "and the half that always survived — the name — is missing"
    assert "not drawn in this editor" not in got["said"], (
        "the band is drawn and the page still announces that it is not: "
        f"the live region reads {got['said']!r}"
    )
    assert got["layer"] == 0, (
        "the textarea's own seat layer drew something on a surface that is not the "
        "textarea — two bands for one caret, one of them measured through a mirror "
        "of a box nobody is typing in"
    )



# A login is a string off a socket, and on this surface it is written into a CSS
# string inside an inline `style` — which is a mechanism a value can be spelled
# to equal, exactly as `AGENTS.md`'s table records for `BARS_JSON`. Two
# characters end a CSS string; this is the login that spells both, plus the
# `;` that would start the next declaration and the `}` that would leave the
# block, and asks whether any of it became CSS.
_HOSTILE = "bo';background:red;--x:'} .op-seat{background:red"

_HOSTILE_SEAT = """
<script>
addEventListener('load', () => setTimeout(() => {
  flipEditing();
  const socket = window.__socket;
  socket.hear({t: 'welcome', seed: null, sv: 'AA==', update: '', people: ['ann', '%WHO%']});
  socket.hear({t: 'who', people: ['ann', '%WHO%'], where: [{login: '%WHO%', at: 3}]});
}, 300));
</script>
""".replace("%WHO%", _HOSTILE.replace("\\", "\\\\").replace("'", "\\'"))

_HOSTILE_DRAWN = """
const host = document.querySelector('.acebox');
if (host) host.env.editor.renderer.updateFull(true);
const band = host ? host.querySelector('.op-seat') : null;
return {
  bands: host ? host.querySelectorAll('.op-seat').length : 0,
  ground: band ? getComputedStyle(band).backgroundColor : '',
  name: band ? getComputedStyle(band, '::after').content : '',
  // Every declaration the marker layer actually ended up with, so a hole shows
  // as itself rather than only through the one property this thought to check.
  css: band ? band.style.cssText : '',
  // The question a substring scan cannot answer: the login's `;background:red`
  // is INSIDE the string it was escaped into, so it is in `cssText` and inert.
  // What would say otherwise is a declaration the page never wrote — `--x` is
  // the one this login tries to open — or a `background` the parser took from
  // the login rather than from `hueOf`.
  smuggled: band ? band.style.getPropertyValue('--x') : null,
};
"""


def test_a_login_cannot_write_css_into_the_band_it_is_drawn_in(
    index: Index, tmp_path: Path
):
    """The band's colour and the name in it are one inline `style`, so a login is
    a value inside a mechanism.

    The other surface writes the login with `textContent` into an element of its
    own and never faces this. This one has no element to write into — the marker
    layer recycles its divs and never clears their text, which is why the name
    rides in as a custom property — and a custom property is CSS. So the escape
    is load-bearing rather than defensive, and this is the test that says which.

    `AGENTS.md` records three shipped instances of a value spelled to equal the
    mechanism carrying it. This is the fourth place one could be.
    """
    record_id = a_record_with_a_document(index)
    page = render_detail(
        index, ROUTES, only=record_id, base_commit=HEAD, may_write=True, editor="ace"
    )
    page = page.replace("<head>", "<head>" + STUB, 1).replace(
        "</body>", _HOSTILE_SEAT + "</body>"
    )

    got = measured_in(
        chrome(), page, tmp_path / "ace-hostile.html", 1200, _HOSTILE_DRAWN, height=900,
        query="?editor=ace", patience=4800,
    )

    assert got["bands"] == 1, "the band was not drawn at all, so this asks nothing"
    assert got["ground"] != "rgb(255, 0, 0)", (
        f"a login wrote its own background into the band: the style reads {got['css']!r}"
    )
    assert got["smuggled"] == "", (
        f"a login closed the CSS string it was written into and opened a declaration "
        f"of its own: the style reads {got['css']!r}"
    )

    # And the other half, which a strip would fail: the name a person chose is
    # the name that is drawn, escaped rather than censored.
    assert _HOSTILE in got["name"], (
        f"the login was altered on its way to the band: it reads {got['name']!r}"
    )


# The same question the mirror sweep asks, on the surface that has no mirror.
#
# The document is set through Ace rather than the hidden `<textarea>`, and the
# caret is put at the index under test and LEFT there: it is this test's oracle,
# and moving it once per sample would scroll the box out from under the band
# between the two measurements being compared.
_ACE_WRAPPED_SEAT = """
<script>
addEventListener('load', () => setTimeout(() => {
  flipEditing();
  const socket = window.__socket;
  socket.hear({t: 'welcome', seed: null, sv: 'AA==', update: '', people: ['ann', 'bo']});
  const editor = document.querySelector('.acebox').env.editor;
  editor.setValue('%LINES%', -1);
  window.__at = editor.session.getValue().indexOf('the caret below is in this one');
  editor.moveCursorToPosition(editor.session.doc.indexToPosition(window.__at));
  socket.hear({t: 'who', people: ['ann', 'bo'],
               where: [{login: 'bo', at: window.__at}]});
}, 300));
</script>
""".replace("%LINES%", _WRAPPING)

# Two oracles, and the weaker one is named as weaker.
#
# `.ace_cursor` is Ace's own caret, put at the same index the seat frame carries.
# It is not fully independent — it is Ace laying out a position, and so is the
# band — but it is independent of THIS FEATURE's arithmetic: the cursor is placed
# from a document position the page did not compute, and the band from a screen
# row the marker works out for itself. An index converted in the wrong space, a
# screen row cached across a fold, a scroll offset counted twice: each of those
# separates the two.
#
# The painted row owes nothing to either. It finds the element in Ace's text
# layer that actually carries the words the caret is in and reads its top off the
# screen. It costs a scroll to bring the row into the DOM at all — Ace renders
# only what is visible — which is why it is one sample at the end rather than the
# whole sweep.
_ACE_BAND_AT_EVERY_WIDTH = """
const host = document.querySelector('.acebox');
const editor = host.env.editor;
const session = editor.session;
// The same lever the mirror sweep uses, for the reason written there: editing is
// full page, `article.record.full` overrides `width: var(--measure)`, and
// `.bodywrap` is the box in this pane that carries no width rule of its own.
const wrap = host.closest('.bodywrap');
const settle = ms => new Promise(go => setTimeout(go, ms));
const bands = () => host.querySelectorAll('.op-seat');
const cursorTop = () => host.querySelector('.ace_cursor').getBoundingClientRect().top;

// **Forced, and not awaited.** `updateBackMarkers` schedules a redraw on Ace's
// own render loop, which is a `requestAnimationFrame` — and the headless clock
// this harness runs under fires that roughly never. In a browser the band lands
// on the next frame like the selection does; here it lands when this asks.
const paint = () => editor.renderer.updateFull(true);
// And the caret's row kept on screen, because Ace renders only the rows that
// are. A seat outside them is deliberately not drawn — asserted on its own
// below — so a sweep that let the row scroll away would measure that instead.
const show = () => { editor.renderer.scrollCursorIntoView(null, 0.5); paint(); };

await settle(220);
// Painted once before anything is read off the renderer: `lineHeight` is
// measured lazily and answers 0 until it has been, and a 0 here silently turns
// every row comparison below into a comparison against nothing.
paint();
const line = editor.renderer.lineHeight;
const answers = [];
const wraps = new Set();
for (let measure = 460; measure < 540; measure++) {
  wrap.style.width = measure + 'px';
  dispatchEvent(new Event('openproj:editing'));
  // Ace lays out into a box it is given and does not poll it. The grip's own
  // drag is the same shape, so this is the page's case and not the test's.
  editor.resize(true);
  show();
  // What the sweep is FOR. A width that never changes the wrap asks the same
  // question eighty times; this is the guard that says it did not.
  wraps.add(session.getScreenLength());
  const band = bands()[0];
  answers.push({
    measure,
    bands: bands().length,
    off: band ? Math.abs(band.getBoundingClientRect().top - cursorTop()) : null,
    height: band ? band.getBoundingClientRect().height : null,
  });
}

wrap.style.width = '500px';
dispatchEvent(new Event('openproj:editing'));
editor.resize(true);
show();
await settle(80);

// A scrolled box. The marker layer draws in the scroller's own space, so a band
// that has taken the offset off twice, or not at all, is right only at the top.
// Three rows, and the caret was centred, so it is still on screen.
session.setScrollTop(session.getScrollTop() + 3 * line);
paint();
await settle(80);
const scrolled = bands()[0]
  ? Math.abs(bands()[0].getBoundingClientRect().top - cursorTop()) : null;

// A fold above the caret takes screen rows out from under it. This is the case
// the other surface's mirror cannot have at all, and the one a screen row worked
// out once and remembered gets wrong.
const Range = ace.require('ace/range').Range;
session.addFold('...', new Range(0, 0, 1, 4));
show();
await settle(80);
const folded = bands()[0]
  ? Math.abs(bands()[0].getBoundingClientRect().top - cursorTop()) : null;
const foldedRows = session.getScreenLength();

// Scrolled away from the caret altogether. Ace renders only what is on screen
// and this band is deliberately one of the things that go with it — a div in the
// marker layer with no text under it is not a seat, it is a stripe.
session.setScrollTop(0);
paint();
await settle(80);
const away = bands().length;
show();
await settle(80);

// A band per person, and the two of them a different colour. `hueOf` is shared
// with the other surface, so what is under test here is that the colour reaches
// the DOM at all on this one — a class cannot carry it.
window.__socket.hear({t: 'who', people: ['ann', 'bo', 'cy'],
                      where: [{login: 'bo', at: window.__at},
                              {login: 'cy', at: window.__at + 1}]});
show();
await settle(80);
const two = Array.from(bands()).map(band => getComputedStyle(band).backgroundColor);
const twoNames = Array.from(bands())
  .map(band => getComputedStyle(band, '::after').content);

// Ten more frames saying exactly what the room already said. A marker added per
// frame instead of once per room leaks one every time anybody moves.
const markersBefore = Object.keys(session.getMarkers(false)).length;
for (let n = 0; n < 10; n++) {
  window.__socket.hear({t: 'who', people: ['ann', 'bo', 'cy'],
                        where: [{login: 'bo', at: window.__at},
                                {login: 'cy', at: window.__at + 1}]});
}
show();
await settle(80);
const markersAfter = Object.keys(session.getMarkers(false)).length;

// And the independent oracle, which owes nothing to Ace's idea of where the
// caret is: the PAINTED row of text the caret is in.
window.__socket.hear({t: 'who', people: ['ann', 'bo'],
                      where: [{login: 'bo', at: window.__at}]});
show();
await settle(160);
let painted = null;
for (const node of host.querySelectorAll('.ace_text-layer *')) {
  if (!node.children.length && node.textContent.includes('the caret below is in this one')) {
    painted = node.getBoundingClientRect().top;
  }
}
const paintedOff = (painted === null || !bands()[0])
  ? null : Math.abs(bands()[0].getBoundingClientRect().top - painted);

// The band must stay inside the box it is drawn over. The marker layer sits in
// `.ace_content`, whose right edge is the scroller's only while wrap is on — and
// the badge is pinned to the band's right edge, so this asks the badge's
// question on the one box that has a rect. A pseudo-element has none.
const scroller = host.querySelector('.ace_scroller').getBoundingClientRect();
const inside = bands()[0]
  ? bands()[0].getBoundingClientRect().right <= scroller.right + 0.5 : null;

return {answers, line, scrolled, folded, foldedRows, away, paintedOff, painted,
        wraps: wraps.size, two, twoNames, markersBefore, markersAfter, inside,
        badge: bands()[0] ? getComputedStyle(bands()[0], '::after').content : '',
        surface: host ? 'ace' : 'textarea'};
"""


def test_a_seat_band_lands_on_the_right_line_on_the_second_surface(
    index: Index, tmp_path: Path
):
    """The sweep, on Ace, and the rule it is held to is the same rule.

    `VENDOR.md` holds this feature to "a caret one line off is worse than no
    caret", and that sentence is why the band was absent here rather than
    guessed. It is the sentence this test discharges: wrap, scroll and a fold,
    at eighty widths, against a caret Ace placed itself.

    The band is not measured through a mirror on this surface. It is a marker in
    Ace's own layer, laid out on the frame Ace lays out its selection on, so the
    numbers this asserts are not a mirror agreeing with a box — they are two
    things Ace drew agreeing with each other, plus one reading off the painted
    text that owes nothing to either.
    """
    record_id = a_record_with_a_document(index)
    page = render_detail(
        index, ROUTES, only=record_id, base_commit=HEAD, may_write=True, editor="ace"
    )
    page = page.replace("<head>", "<head>" + STUB, 1).replace(
        "</body>", _ACE_WRAPPED_SEAT + "</body>"
    )

    got = measured_in(
        chrome(), page, tmp_path / "ace-wrapped.html", 1200, _ACE_BAND_AT_EVERY_WIDTH,
        height=900, patience=6800,
    )

    assert got["surface"] == "ace", "the page did not open on the second surface"
    assert got["line"] > 1, (
        f"the editor reports a row {got['line']}px tall, so every comparison below "
        "is against a number the renderer had not measured yet"
    )
    assert got["wraps"] > 1, (
        "the document wrapped the same way at every width in the sweep, so this "
        "test asked one question eighty times and none of them was the one it "
        "exists for"
    )
    assert all(answer["bands"] == 1 for answer in got["answers"]), "nobody was drawn"

    worst = max(answer["off"] for answer in got["answers"])
    where = max(got["answers"], key=lambda answer: answer["off"])
    assert worst < 1.0, (
        f"a band is {worst:.2f}px off the row its caret is in at --measure: "
        f"{where['measure']}px, on a {got['line']:.2f}px row"
    )
    tallest = max(abs(answer["height"] - got["line"]) for answer in got["answers"])
    assert tallest < 1.0, (
        f"a band is {tallest:.2f}px off one row tall — it covers the line it means "
        f"and part of another, on a {got['line']:.2f}px row"
    )

    assert got["scrolled"] < 1.0, (
        f"the band is {got['scrolled']:.2f}px out once the box is scrolled, which is "
        "the offset counted twice or not at all"
    )
    assert got["foldedRows"] > 0, "the fold did not take, so this case asked nothing"
    assert got["folded"] < 1.0, (
        f"a fold above the caret left the band {got['folded']:.2f}px behind: the screen "
        "row is being remembered rather than asked for"
    )
    # And the other half of what a marker layer buys: Ace renders the rows that
    # are on screen and nothing else, so a seat scrolled away is not drawn at all.
    # The mirror on the other surface has no way to say this — it builds the div
    # either way and lets `overflow: hidden` hide it.
    assert got["away"] == 0, (
        f"{got['away']} band(s) drawn for a caret scrolled off the screen: a div in "
        "the marker layer with no text under it is a stripe, not a seat"
    )

    assert got["painted"] is not None, (
        "the row the caret is in was never brought on screen, so the one oracle here "
        "that owes nothing to Ace's own caret asked nothing"
    )
    assert got["paintedOff"] < 1.0, (
        f"the band is {got['paintedOff']:.2f}px off the row of text it is drawn over — "
        f"measured against the painted words, on a {got['line']:.2f}px row"
    )

    assert len(got["two"]) == 2, "two people are in the document and two bands were not drawn"
    assert got["two"][0] != got["two"][1], (
        f"two people share one colour, so the band says somebody is there and not who: "
        f"{got['two']}"
    )
    assert {"bo", "cy"} == {name.strip(chr(34) + chr(39)) for name in got["twoNames"]}, (
        f"the two bands do not name the two people in the room: {got['twoNames']}"
    )
    assert got["markersAfter"] == got["markersBefore"], (
        f"ten frames saying what the room already said left "
        f"{got['markersAfter'] - got['markersBefore']} markers behind: they are added "
        "per frame rather than once for the room"
    )
    assert "bo" in got["badge"], f"the band carries no login: it reads {got['badge']!r}"
    assert got["inside"], (
        "the badge is drawn outside the scroller it labels, which is the content box's "
        "right edge standing in for the viewport's"
    )




# A shaping document, in the shape the corpus actually has: a heading, a blank
# line, a bullet, a blank line, and the paragraph somebody is writing in. The
# short lines above the paragraph are the whole point — a stale index walks back
# through CHARACTERS, so three of them cross three characters of prose and two
# whole rows of a checklist.
_PITCH = "\\n".join((
    "## Problem",
    "",
    "- one",
    "",
    "the paragraph the other person has their caret in",
))

_JITTER = """
<script>
window.__tops = [];
addEventListener('load', () => setTimeout(() => {
  flipEditing();
  const socket = window.__socket;
  socket.hear({t: 'welcome', seed: null, sv: 'AA==', update: '', people: ['ann', 'bo']});
  const body = document.querySelector('textarea[name=body]');
  body.value = '%LINES%';
  body.dispatchEvent(new Event('input'));
  window.__at = body.value.indexOf('the paragraph');
  socket.hear({t: 'who', people: ['ann', 'bo'],
               where: [{login: 'bo', at: window.__at}]});
  // Every redraw from here on, recorded. The band is on one line and one line
  // only for the whole of what follows: nothing below adds or removes a line.
  const top = () => {
    const band = document.getElementById('seats').firstElementChild;
    return band ? Math.round(band.getBoundingClientRect().top) : null;
  };
  window.__tops.push(top());
  // Three characters typed into the HEADING, above them — one `input` each, the
  // way a keyboard delivers them. No `who` follows: the room is a round trip
  // away and this is what the page draws in the meantime, which is the whole of
  // what somebody sees while they type.
  for (const character of 'xyz') {
    const cut = body.value.indexOf('\\n');
    body.value = body.value.slice(0, cut) + character + body.value.slice(cut);
    body.dispatchEvent(new Event('input'));
    window.__tops.push(top());
  }
}, 200));
</script>
""".replace("%LINES%", _PITCH)

_JITTERED = """
const body = document.querySelector('textarea[name=body]');
return {
  tops: window.__tops,
  line: Math.round(parseFloat(getComputedStyle(body).lineHeight)),
  at: window.__at,
};
"""


def test_typing_above_somebody_does_not_move_their_band(index: Index, tmp_path: Path):
    """Their band is on their line, and this tab's keystrokes are not their line.

    Reported from two people in one document: "the other user's presence line was
    jumping up and down 2-3 lines while I was typing, one jump per char I typed,
    but this didn't happen in the other user's view."

    `seats` holds an ABSOLUTE index into the document — where the room last said
    that person's caret was — and `drawSeats` is subscribed to `onInput`, so every
    keystroke this tab makes repaints their band against an index that keystroke
    has just invalidated. The correction is a full round trip away: this tab's
    update reaches them, `splice` carries their caret across it, their `sit()`
    goes back to the server, and a `who` comes here. So the band alternates
    between the wrong row and the right one, once per character.

    It walks back through characters and lands on rows, which is why the corpus
    shape matters: three characters is three characters of prose, or the whole of
    a blank line, a `- one` and another blank line. A shaping document is made of
    the second kind.

    And that is the asymmetry too, with nothing else needed to explain it. A `who`
    comes back only when the OTHER person's index changed, which happens only when
    you edit above them. Somebody typing below your caret moves nothing of yours,
    `sit()` sees the same `at` it last sent and returns, and their copy of your
    band never moves.
    """
    record_id = a_record_with_a_document(index)
    page = render_detail(
        index, ROUTES, only=record_id, base_commit=HEAD, may_write=True, editor="plain"
    )
    page = page.replace("<head>", "<head>" + STUB, 1).replace(
        "</body>", _JITTER + "</body>"
    )

    got = measured_in(
        chrome(), page, tmp_path / "jitter.html", 1200, _JITTERED, height=900,
        patience=2800,
    )

    assert got["tops"] and all(top is not None for top in got["tops"]), (
        f"the band was not drawn for one of the four samples: {got['tops']}"
    )
    settled = set(got["tops"])
    assert len(settled) == 1, (
        f"typing above somebody moved their band through {len(settled)} different rows "
        f"without one word of theirs changing: {got['tops']}, on a {got['line']}px row. "
        "Their caret is where it was; only this tab's idea of the index moved."
    )



_ACE_JITTER = """
<script>
window.__tops = [];
addEventListener('load', () => setTimeout(() => {
  flipEditing();
  const socket = window.__socket;
  socket.hear({t: 'welcome', seed: null, sv: 'AA==', update: '', people: ['ann', 'bo']});
  const editor = document.querySelector('.acebox').env.editor;
  const session = editor.session;
  editor.setValue('%LINES%', -1);
  window.__at = session.getValue().indexOf('the paragraph');
  socket.hear({t: 'who', people: ['ann', 'bo'],
               where: [{login: 'bo', at: window.__at}]});
  const top = () => {
    editor.renderer.updateFull(true);
    const band = document.querySelector('.op-seat');
    return band ? Math.round(band.getBoundingClientRect().top) : null;
  };
  window.__tops.push(top());
  // Typed through Ace's own document, which is the path a keystroke takes here:
  // one delta, converted at arrival, out through `spliced` — and NOT the path
  // the other surface's `typed` takes. This one never had the transform at all.
  for (const character of 'xyz') {
    session.insert({row: 0, column: 2}, character);
    window.__tops.push(top());
  }
}, 300));
</script>
""".replace("%LINES%", _PITCH)

_ACE_JITTERED = """
const editor = document.querySelector('.acebox').env.editor;
return {tops: window.__tops, line: Math.round(editor.renderer.lineHeight),
        at: window.__at};
"""


def test_typing_above_somebody_does_not_move_their_band_on_the_second_surface(
    index: Index, tmp_path: Path
):
    """The same claim, on the surface whose write path never carried anything.

    The band is drawn from the same `seats` here, so the defect is the same one —
    but it arrives by a different road. This surface reports its own deltas and
    goes out through `spliced`, where the other one diffs its value and goes out
    through `typed`, and neither of them transformed the roster. The fix is in
    `text.observe`, which is downstream of both, and this is the half of that
    claim the other test cannot make.
    """
    record_id = a_record_with_a_document(index)
    page = render_detail(
        index, ROUTES, only=record_id, base_commit=HEAD, may_write=True, editor="ace"
    )
    page = page.replace("<head>", "<head>" + STUB, 1).replace(
        "</body>", _ACE_JITTER + "</body>"
    )

    got = measured_in(
        chrome(), page, tmp_path / "ace-jitter.html", 1200, _ACE_JITTERED, height=900,
        query="?editor=ace", patience=4800,
    )

    assert got["tops"] and all(top is not None for top in got["tops"]), (
        f"the band was not drawn for one of the four samples: {got['tops']}"
    )
    settled = set(got["tops"])
    assert len(settled) == 1, (
        f"typing above somebody moved their band through {len(settled)} different rows "
        f"without one word of theirs changing: {got['tops']}, on a {got['line']}px row"
    )


# The socket, counted rather than merely replaced: the claim is about how many
# connections a page opens and WHEN, so every construction is kept, and close()
# behaves like a real socket — readyState moves and onclose fires — so a
# reconnect after the session ended would be visible as a second entry.
COUNTING = """
<script>
window.__sockets = [];
class CountingSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;
  constructor(url) {
    window.__sockets.push(this);
    this.url = url;
    this.readyState = 1;
    setTimeout(() => this.onopen && this.onopen(), 0);
  }
  send(data) {}
  close() {
    this.readyState = 3;
    setTimeout(() => this.onclose && this.onclose({}), 0);
  }
  hear(message) { this.onmessage && this.onmessage({data: JSON.stringify(message)}); }
}
window.WebSocket = CountingSocket;
</script>
"""

READING = """
<script>
addEventListener('load', () => setTimeout(() => {
  window.__atLoad = window.__sockets.length;
  flipEditing();
  window.__inSession = window.__sockets.length;
  document.getElementById('cancel').click();
  window.__afterCancel = window.__sockets.map(one => one.readyState);
  // Past the first reconnect backoff (500ms): a machine that reconnects after
  // the session ended shows up as a second socket here.
  setTimeout(() => { window.__later = window.__sockets.length; }, 800);
}, 200));
</script>
"""

_HELD = """
return {atLoad: window.__atLoad, inSession: window.__inSession,
        afterCancel: window.__afterCancel, later: window.__later,
        listed: document.getElementById('together').textContent};
"""


def test_a_reader_holds_no_seat(index: Index, tmp_path: Path):
    """Spec test 5: opening a record is not editing it.

    `connect()` ran at script load, so a signed-in person who merely OPENED a
    record took a co-editing seat: listed to everyone else as "also editing",
    and holding a Room, a git watch and an outbox task on the server per
    record visited, lingering after they left. The seat, the presence entry
    and the Room task are all downstream of the one socket this counts — no
    connection at load means none of them exist, and the last-person-out
    commit never waits on a reader.
    """
    record_id = a_record_with_a_document(index)
    page = render_detail(
        index, ROUTES, only=record_id, base_commit=HEAD, may_write=True, editor="plain"
    )
    page = page.replace("<head>", "<head>" + COUNTING, 1).replace("</body>", READING + "</body>")

    got = measured_in(
        chrome(), page, tmp_path / "seatless.html", 1200, _HELD, height=900, patience=2400
    )

    assert got["atLoad"] == 0, "a reader took a seat by opening the page"
    assert got["inSession"] == 1, "and opening a session did not take one"
    assert got["afterCancel"] == [3], "Cancel did not give the seat back"
    assert got["later"] == 1, "the seat was retaken after the session ended"
    assert got["listed"] == "", "somebody is listed as editing a page nobody edited"


RESEATED = """
<script>
addEventListener('load', () => setTimeout(() => {
  // End a session and start the next one a click apart — before the ended
  // socket's close event, which is a queued task, has fired.
  flipEditing();
  document.getElementById('cancel').click();
  flipEditing();
  window.__now = window.__sockets.map(one => one.readyState);
  const stale = window.__sockets[0];
  const live = window.__sockets[1];
  // The live room seats somebody and hands this tab its base.
  live.hear({t: 'welcome', seed: null, base: '1'.repeat(40), you: 'ann',
             sv: 'AA==', update: '', people: ['ann', 'bo']});
  live.hear({t: 'who', people: ['ann', 'bo'], where: []});
  window.__roster = document.getElementById('together').textContent;
  // Frames that were in flight when the first session ended deliver as their
  // own tasks, through the closed socket: a roster and a commit that must not
  // reach a page that socket no longer speaks for.
  stale.hear({t: 'who', people: ['ann', 'cy'], where: []});
  stale.hear({t: 'saved', commit: 'f'.repeat(40), outcome: 'committed', pushed: true});
  window.__afterStale = {
    roster: document.getElementById('together').textContent,
    base: document.querySelector('[name=base_commit]').value,
  };
  // Past the stale socket's own close event AND the first reconnect backoff
  // (500ms), where a reconnect it armed would have landed.
  setTimeout(() => { window.__later = {
    states: window.__sockets.map(one => one.readyState),
    roster: document.getElementById('together').textContent,
  }; }, 800);
}, 200));
</script>
"""


def test_the_next_session_is_one_seat_not_two(index: Index, tmp_path: Path):
    """A session ended and the next begun before the old socket has gone quiet.

    Every socket event is a queued task and the next Write press is a click
    away, so the ended session's socket still speaks after the live one is up —
    its close, and any frame that was in flight when the session ended. None of
    it may reach the page: the close must not wipe the live room's roster or
    arm a reconnect BESIDE the live socket (measured without the
    `opened !== socket` guard in `connect`: a third socket at the backoff, two
    open at once, one person seated twice), and a stale frame must not be
    heard — a stale `who` rewrites who is listed as editing, and a stale
    `saved` moves `base_commit` under a session it does not belong to, which is
    the silent-overwrite family by wire.
    """
    record_id = a_record_with_a_document(index)
    page = render_detail(
        index, ROUTES, only=record_id, base_commit=HEAD, may_write=True, editor="plain"
    )
    page = page.replace("<head>", "<head>" + COUNTING, 1).replace("</body>", RESEATED + "</body>")

    got = measured_in(
        chrome(), page, tmp_path / "reseated.html", 1200,
        "return {now: window.__now, roster: window.__roster,"
        "        afterStale: window.__afterStale, later: window.__later};",
        height=900, patience=2400,
    )

    assert got["now"] == [3, 1], f"one closed seat and one live one, not {got['now']}"
    assert got["roster"] == "also editing: bo", (
        f"the live room never seated bo, so the stale halves below prove nothing: "
        f"{got['roster']!r}"
    )
    assert got["afterStale"]["roster"] == "also editing: bo", (
        "a frame in flight when the old session ended was heard: the ended socket "
        f"rewrote the live room's roster to {got['afterStale']['roster']!r}"
    )
    assert got["afterStale"]["base"] == "1" * 40, (
        "a stale `saved` moved base_commit under a session it does not belong to: "
        f"{got['afterStale']['base']!r}"
    )
    assert got["later"]["states"] == [3, 1], (
        f"the ended session's close re-seated this reader beside the live socket: "
        f"{got['later']['states']}"
    )
    assert got["later"]["roster"] == "also editing: bo", (
        "the ended session's close wiped the live room's roster"
    )
