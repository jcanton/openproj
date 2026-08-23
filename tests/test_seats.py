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

const line = parseFloat(getComputedStyle(body).lineHeight);
const answers = [];
for (let measure = 460; measure < 540; measure++) {
  article.style.setProperty('--measure', measure + 'px');
  // Synchronous, and that is why it is the event and not a wait: `drawSeats`
  // listens for this one directly, while a `ResizeObserver` is delivered on the
  // rendering step, which the headless clock runs exactly once.
  dispatchEvent(new Event('openproj:editing'));
  const band = layer.firstElementChild;
  answers.push({
    measure,
    bands: layer.children.length,
    off: band ? Math.abs(band.getBoundingClientRect().top - truthTop(window.__at)) : null,
  });
}

// And the last case, which is the one this stage created and had to close: the
// gutter's column IS the box's own `padding-left`, so a document going from nine
// lines to ten widens it by a character, narrows the content box and rewraps
// every line under every band. Nothing dispatches an `input` for that, and the
// bands were left where the old wrapping had put them until something else
// happened to redraw them.
article.style.setProperty('--measure', '500px');
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

return {answers, widened, line, numbered:
        body.closest('.bodywrap').classList.contains('numbered')};
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

_REFUSED = """
return {
  surface: document.querySelector('.acebox') ? 'ace' : 'textarea',
  bands: document.getElementById('seats').children.length,
  together: document.getElementById('together').textContent,
  // `announce` puts it in the page's own visible status region where there is
  // one, and the detail page has one; `#announce` is the shell's fallback.
  said: document.getElementById('state').textContent
        + ' ' + document.getElementById('announce').textContent,
};
"""


def test_the_second_surface_says_it_cannot_draw_where_anybody_is(index: Index, tmp_path: Path):
    """`provides.seats` is false on Ace, and the refusal has to reach a person.

    It did not. `drawSeats` asked `BODY.getClientRects().length` first — "a box
    nothing is drawing has no rows to sit on" — and the Ace surface hides the
    `<textarea>` and draws its own box beside it, so that guard is always true on
    exactly the surface the sentence below it was written for. The branch that
    decided not to act said nothing at all, which is the pattern `AGENTS.md`
    records three shipped instances of; the two guards are in the other order
    now, because whether a surface has seats is a fact about the surface and not
    about whether the box it replaced is on screen.
    """
    record_id = a_record_with_a_document(index)
    page = render_detail(
        index, ROUTES, only=record_id, base_commit=HEAD, may_write=True, editor="ace"
    )
    page = page.replace("<head>", "<head>" + STUB, 1).replace("</body>", _ACE_SEAT + "</body>")

    got = measured_in(
        chrome(), page, tmp_path / "ace-seat.html", 1200, _REFUSED, height=900,
        query="?editor=ace", patience=4800,
    )

    assert got["surface"] == "ace", "the page did not open on the second surface"
    assert got["bands"] == 0, "a band was drawn by an editor nothing has measured bands in"
    assert "bo" in got["together"], "and the half that does survive — the name — is missing"
    assert "not drawn in this editor" in got["said"], (
        "somebody else is in the document, no band is drawn, and the page says nothing: "
        f"the live region reads {got['said']!r}"
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
