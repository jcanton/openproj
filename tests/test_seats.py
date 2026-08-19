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

import json
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
    entities, config, _ = load_repo(demo_root)
    return build_index(entities, config, date(2026, 8, 17))


def a_record_with_a_document(index: Index) -> str:
    for entity_id, entity in sorted(index.entities.items()):
        if entity.body.count("\n") > 8:
            return entity_id
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
  document.getElementById('toggle').click();
  const socket = window.__socket;
  socket.hear({t: 'welcome', seed: null, sv: 'AA==', update: '', people: ['ann', 'bo']});
  const body = document.querySelector('textarea[name=body]');
  body.value = '%s';
  body.dispatchEvent(new Event('input'));
  // The start of the third line, which is where the band should be drawn.
  window.__at = body.value.indexOf('line 2');
  socket.hear({t: 'who', people: ['ann', 'bo'],
               where: [{login: 'bo', at: window.__at}]});
}, 200));
</script>
""" % LINES

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
    entity_id = a_record_with_a_document(index)
    # `may_write`, because the socket is only offered to somebody the server
    # would take a frame from — see `test_socket_offer.py`. Without it this page
    # carries no room at all and there is nothing here to test.
    page = render_detail(index, ROUTES, only=entity_id, base_commit=HEAD, may_write=True)
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
  document.getElementById('toggle').click();
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
    entity_id = a_record_with_a_document(index)
    # `may_write`, because the socket is only offered to somebody the server
    # would take a frame from — see `test_socket_offer.py`. Without it this page
    # carries no room at all and there is nothing here to test.
    page = render_detail(index, ROUTES, only=entity_id, base_commit=HEAD, may_write=True)
    page = page.replace("<head>", "<head>" + STUB, 1).replace(
        "</body>", MY_OWN_SEAT + "</body>"
    )

    got = measured_in(chrome(), page, tmp_path / "mine.html", 1200, _MINE, height=900)

    assert got["bands"] == 0


TWO_PEOPLE = """
<script>
addEventListener('load', () => setTimeout(() => {
  document.getElementById('toggle').click();
  const socket = window.__socket;
  socket.hear({t: 'welcome', seed: null, sv: 'AA==', update: '',
               people: ['ann', 'bo', 'cy']});
  const body = document.querySelector('textarea[name=body]');
  body.value = '%s';
  body.dispatchEvent(new Event('input'));
  socket.hear({t: 'who', people: ['ann', 'bo', 'cy'],
               where: [{login: 'bo', at: body.value.indexOf('line 1')},
                       {login: 'cy', at: body.value.indexOf('line 7')}]});
}, 200));
</script>
""" % LINES

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
    entity_id = a_record_with_a_document(index)
    # `may_write`, because the socket is only offered to somebody the server
    # would take a frame from — see `test_socket_offer.py`. Without it this page
    # carries no room at all and there is nothing here to test.
    page = render_detail(index, ROUTES, only=entity_id, base_commit=HEAD, may_write=True)
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
    entity_id = a_record_with_a_document(index)
    # `may_write`, because the socket is only offered to somebody the server
    # would take a frame from — see `test_socket_offer.py`. Without it this page
    # carries no room at all and there is nothing here to test.
    page = render_detail(index, ROUTES, only=entity_id, base_commit=HEAD, may_write=True)
    page = page.replace("<head>", "<head>" + STUB, 1).replace("</body>", SEAT + "</body>")

    got = measured_in(chrome(), page, tmp_path / "sent.html", 1200, _SENT, height=900)

    assert got["wanted"] in got["sent"], (
        f"the caret moved to {got['wanted']} and the room heard {got['sent']}"
    )
