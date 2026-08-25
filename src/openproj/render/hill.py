"""The hill chart: its geometry, where each word stands on it, and the ball that rolls."""

from __future__ import annotations

import math

from markupsafe import Markup

from ..model import ISSUE_STATUS, NOTE_STATUS
from .env import _fragment
from .tokens import STATUSES, _human

# The ball, moved. Everything that makes this a control — arrow keys, the focus
# ring, the group, "3 of 5" — is the radios' and the browser's; this is what makes
# the picture follow them and the form serialise the answer.
#
# Emitted beside `_REQUIRED_JS` and for the same reason: the create form and the
# detail page carry the same hill, and two copies of a gesture is one copy that
# quietly stops matching.
_HILL_JS = Markup("""
function attachHill(form) {
  const hill = form.querySelector('.hill[role=radiogroup]');
  // What the form actually sends. `markRequired` and the create form's refusal
  // both ask this element for a value and neither knows the control became a
  // picture.
  const value = form.querySelector('input[name=status]');
  const ball = hill && hill.querySelector('.hill-ball');
  const stops = hill ? [...hill.querySelectorAll('.hill-stop')] : [];
  if (!hill || !value || !ball || !stops.length) return;

  // Where a stop stands, read off the percentages the server positioned it with.
  // Read and not recomputed: the curve is one function in `render.py`, and a
  // second copy of it here is exactly the drift that puts a ball off its line.
  const at = stop => [parseFloat(stop.style.left), parseFloat(stop.style.top)];
  const wordOf = stop => stop.querySelector('input').value;

  // What each stop MEANS, said under the control while somebody is choosing.
  // Read off the span's own `data-teach` rather than handed down in the page's
  // data: this file draws a hill and has no business importing the Shape Up
  // copy, and the element that carries the sentence is the honest place to keep
  // the sentences. Absent on the create form and on the two inbox ladders, which
  // is what the guard in `teachAbout` is for.
  const teach = form.querySelector('.teach[data-teach]');
  const TEACH = teach ? JSON.parse(teach.dataset.teach) : null;

  // Inside `show` and not beside `choose`, so the sentence follows the BALL:
  // somebody dragging onto `shelved` is deciding what shelved means, and a line
  // describing where they came from is help for the wrong decision. A drag that
  // is abandoned puts the old word back through the same call.
  //
  // Empty and not hidden for a word with nothing to say. `.record.editing
  // .teach:empty` in `_DETAIL_STYLE` is what stops it taking a line, and it is
  // written there rather than as a `hidden` here because an author rule setting
  // `display: block` outranks the `hidden` attribute and this row has one.
  function teachAbout(word) {
    if (TEACH) teach.textContent = TEACH[word] || '';
  }

  function show(word) {
    const stop = stops.find(one => wordOf(one) === word);
    if (!stop) return;
    ball.style.left = stop.style.left;
    ball.style.top = stop.style.top;
    // Which way is up where it lands, so it rests on the line there rather than
    // keeping the angle of the place it came from. Copied off the stop rather
    // than recomputed: the curve is one function in `render.py`.
    ball.style.setProperty('--nx', stop.style.getPropertyValue('--nx'));
    ball.style.setProperty('--ny', stop.style.getPropertyValue('--ny'));
    // The word it is about to take, said while a drag is in flight. `data-word`
    // on the stop and not `_human` again here: the words on this page come from
    // one map, and the second copy is the one that goes stale.
    ball.dataset.word = stop.dataset.word;
    // Only ever one of this ladder's own words, which is why it may be written
    // into a class at all — nothing out of a file reaches this line.
    ball.className = 'hill-ball hill-' + word;
    teachAbout(word);
  }

  function choose(word) {
    const stop = stops.find(one => wordOf(one) === word);
    if (!stop) return;
    const input = stop.querySelector('input');
    input.checked = true;
    show(word);
    value.value = word;
    // The word beside the value, because the create form's refusal prints the
    // status in the words on the page and used to read them off a `<select>`'s
    // selected option. Without this it would print `in_progress`, which is what
    // git holds and not what anybody is looking at.
    value.dataset.word = input.dataset.word;
    // `change` bubbles, so the unsaved counter and the required marks answer
    // without either of them knowing that a hill exists.
    value.dispatchEvent(new Event('change', {bubbles: true}));
  }

  hill.addEventListener('change', event => choose(event.target.value));

  // And the other direction, for when something that is not this hill sets the
  // status: `resetEdits` writes `ORIGINAL` into every control, and a value
  // assigned by script fires no event for the picture to hear — so without this
  // the ball sat on the status that had just been undone, with the drawing and
  // the value disagreeing on a page nobody was editing.
  //
  // **Two events, one handler, and the second is not a duplicate of the first.**
  // `openproj:reverted` is "the fields were put back" and is what Reset
  // dispatches; `openproj:session` with a false detail is "the session ended",
  // which is a different fact and used to be the only one — because until
  // 2026-08-25 putting the fields back and ending the session were one button.
  // They are two now, and the picture has to follow the values whichever
  // happens.
  const follow = () => {
    const input = stops.map(one => one.querySelector('input'))
      .find(one => one.value === value.value);
    if (input) input.checked = true;
    show(value.value);
  };
  addEventListener('openproj:reverted', follow);
  addEventListener('openproj:session', event => {
    if (event.detail) return;                      // a session beginning, not ending
    follow();
  });

  // Distance in painted pixels and not in the box's own units: the box is two and
  // a half times wider than it is tall, so a nearest-stop measured in percent
  // would answer with the stop that looks further away.
  function nearest(x, y) {
    const box = hill.getBoundingClientRect();
    let best = stops[0], closest = Infinity;
    for (const stop of stops) {
      const [left, top] = at(stop);
      const dx = box.left + box.width * left / 100 - x;
      const dy = box.top + box.height * top / 100 - y;
      if (dx * dx + dy * dy < closest) { closest = dx * dx + dy * dy; best = stop; }
    }
    return best;
  }

  // Drag is an enhancement over the radios and lands only on stops, because there
  // is nothing between them for a ball to mean. `pointerdown` does not
  // `preventDefault`: a press that begins and ends on one stop is a click on that
  // stop's own label element, and letting the browser handle it is what puts focus
  // where the ball is. A press that ends somewhere else fires no label click at
  // all — the two events share only the hill as an ancestor — which is why the
  // drag has to commit for itself.
  let from = null;
  hill.addEventListener('pointerdown', event => {
    if (event.button !== 0) return;
    from = value.value;
    hill.classList.add('dragging');
    hill.setPointerCapture(event.pointerId);
    show(wordOf(nearest(event.clientX, event.clientY)));
  });
  hill.addEventListener('pointermove', event => {
    if (from !== null) show(wordOf(nearest(event.clientX, event.clientY)));
  });
  hill.addEventListener('pointerup', event => {
    if (from === null) return;
    from = null;
    hill.classList.remove('dragging');
    const stop = nearest(event.clientX, event.clientY);
    choose(wordOf(stop));
    stop.querySelector('input').focus({preventScroll: true});
  });
  // A cancelled drag is not a status change. Put the ball back where it was
  // rather than wherever the pointer happened to be when the gesture died.
  hill.addEventListener('pointercancel', () => {
    if (from === null) return;
    show(from);
    from = null;
    hill.classList.remove('dragging');
  });
}
""")


# The hill, and where each word stands on it.
#
# Shape Up draws a piece of work as a ball on a hill: uphill is figuring out what
# to do, the summit is knowing, downhill is doing it. `status` already carries
# that distinction and a chip cannot say it — `shaping` and `in_progress` are one
# rung apart in a list and opposite sides of a hill in the book. This is the same
# five words, drawn as the shape they mean.
#
# A raised cosine, chosen for where its slope is steepest rather than for its
# looks: it grounds at both ends, peaks at t=0.5, and passes through exactly half
# its height at t=0.25 and t=0.75 — so `shaping` stands halfway up and
# `in_progress` halfway down without a coordinate anybody typed.
_HILL_BOX = (120, 48)
_HILL_GROUND = 40.0
_HILL_AMPLITUDE = 32.0
_HILL_FOOT, _HILL_CREST = 12.0, 108.0
# Ground drawn past both feet. A hill whose ground begins where the hill does
# reads as a ramp off the edge of the box rather than as a hill standing on
# something.
_HILL_APRON = 8.0
# Smooth at 240px wide, and 48 segments rather than 240 because this path ships
# on every page that can draw a card.
_HILL_SAMPLES = 48


def _hill_at(t: float) -> tuple[float, float]:
    """Where the line is at `t` along the hill: 0 at the foot, 1 at the finish."""
    x = _HILL_FOOT + t * (_HILL_CREST - _HILL_FOOT)
    y = _HILL_GROUND - _HILL_AMPLITUDE * (1 - math.cos(2 * math.pi * t)) / 2
    return round(x, 2), round(y, 2)


def _hill_normal(t: float) -> tuple[float, float]:
    """Which way is up, out of the hill, at `t`. A unit vector in SVG's axes.

    A stop is a point ON the line, and a ball centred on a point is a ball the
    line runs through — which is not how a ball rests on a hill. It is lifted
    along this, by its own radius, in CSS: the lift has to be in painted pixels
    because the ball is an HTML element sized in px while the drawing is a
    viewBox that scales, and a lift written in viewBox units would be right at
    exactly one width. A unit vector times a pixel length is right at all of them.

    `y` grows downward here, so the outward normal is the one with the negative
    `y`: `(m, -1)` normalised, where `m` is the slope. On the flat — the two ends
    and the two that came off the path — that is straight up, which is also the
    answer for a ball resting on level ground.
    """
    slope = -_HILL_AMPLITUDE * math.pi * math.sin(2 * math.pi * t) / (_HILL_CREST - _HILL_FOOT)
    length = math.hypot(slope, 1)
    return round(slope / length, 4), round(-1 / length, 4)


# On the curve for the five words work moves through; on the ground under the
# summit for the two that mean "this came off the path". Not past the finish:
# past the finish reads as "after done", which is the one thing shelved is not.
_HILL_ALONG = {"thinking": 0.0, "shaping": 0.25, "ready": 0.5, "in_progress": 0.75, "done": 1.0}
_HILL_OFF_THE_PATH = ("shelved", "dropped")
_HILL_STOPS = {word: _hill_at(t) for word, t in _HILL_ALONG.items()} | {
    word: (_hill_at(0.5)[0], _HILL_GROUND) for word in _HILL_OFF_THE_PATH
}
# And which way each of them is up. Off the path is level ground, so it is the
# same answer the two ends of the hill give.
_HILL_NORMALS = {word: _hill_normal(t) for word, t in _HILL_ALONG.items()} | {
    word: (0.0, -1.0) for word in _HILL_OFF_THE_PATH
}
# Which stops a record of each kind may stand on, in ladder order. Derived from
# the vocabularies rather than written out beside them: a status added to one of
# them tomorrow fails `test_every_issue_word_stands_on_the_hill` (or
# `test_every_status_a_record_can_hold_has_a_stop`, which holds the other two
# ladders) instead of quietly having nowhere to stand, which on a hill means no
# ball at all.
HILL_LADDERS = {
    "record": tuple(word for word in STATUSES if word in _HILL_STOPS),
    "issue": tuple(word for word in ISSUE_STATUS if word in _HILL_STOPS),
    "note": tuple(word for word in NOTE_STATUS if word in _HILL_STOPS),
}

# Which ladder each kind's status stands on. Only the two unplanned kinds have
# ladders of their own; every planned kind stands on the `record` ladder, whose
# key promises more than it holds — issues and notes are records too and keep
# their own. Product is not here because `statuses=()` keeps status in its
# `unread_fields` — no status row is ever built for it.
_LADDER_OF = {"issue": "issue", "note": "note"}

# Why a status control is locked, per kind — the sentence beside it when the
# state is derived from a link rather than typed. Verbatim from the two pages
# this replaced, because the people reading it already learned these words. No
# planned kind appears: `Record.state` answers `status`, so a planned kind can
# never satisfy the lock condition and never needs a sentence.
_STATE_HINT = {
    "issue": "from the work it was pitched into",
    "note": "from what it became",
}


def _hill_path() -> str:
    """The curve, sampled from `_hill_at` and from nothing else.

    One function emits both this and the stops, for the reason `days_after` is one
    function: a number written in two places is a number that will be wrong in one
    of them, and here that is a ball floating off the line it is drawn on. Held by
    `test_every_hill_stop_is_on_the_line`.
    """
    points = (_hill_at(step / _HILL_SAMPLES) for step in range(_HILL_SAMPLES + 1))
    return "M" + " L".join(f"{x:g} {y:g}" for x, y in points)


def hill_geometry() -> dict:
    """The numbers both renderers draw from.

    The detail page builds its hill in Jinja and the card builds one in
    JavaScript. Handing the browser this rather than a second implementation is
    what stops the two from disagreeing about where `ready` is — the mistake
    `appetite_weeks` reading as three numbers on three pages already cost once.
    """
    return {
        "box": list(_HILL_BOX),
        "ground": _HILL_GROUND,
        "apron": [_HILL_FOOT - _HILL_APRON, _HILL_CREST + _HILL_APRON],
        "path": _hill_path(),
        "stops": {word: list(where) for word, where in _HILL_STOPS.items()},
        # Which way is up at each of them, so the card rests its ball on the line
        # the same way the server does rather than working the curve out again.
        "normals": {word: list(up) for word, up in _HILL_NORMALS.items()},
        "ladders": {kind: list(words) for kind, words in HILL_LADDERS.items()},
        # Position is the channel this control is made of and the one channel a
        # screen reader never gets, so the sentence each coordinate draws travels
        # with the coordinates rather than being written a second time in JS.
        "where": dict(_HILL_WHERE),
        # Which words mean "this came off the path", so the browser dims the hill
        # for the same two the server does rather than for a list of its own.
        "off": list(_HILL_OFF_THE_PATH),
    }


def _hill_percent(where: tuple[float, float]) -> tuple[str, str]:
    """A stop as percentages of the box, which is how it is positioned in CSS.

    Percent and not the SVG's own units: the ball is an HTML element over the
    drawing rather than a `<circle>` in it, so that it can carry a real
    `<input type=radio>` and take its keyboard, its focus ring and its group
    semantics from the platform instead of from hand-written ARIA.
    """
    return f"{100 * where[0] / _HILL_BOX[0]:.3f}%", f"{100 * where[1] / _HILL_BOX[1]:.3f}%"


# Where the ball is, said in words. Position is the whole point of this control
# and position is the one channel that reaches nobody using a screen reader, so
# each stop carries the sentence its coordinates draw. Not "25% along": that is
# the implementation, and what a person means by it is halfway up.
_HILL_WHERE = {
    "thinking": "at the foot of the hill",
    "shaping": "halfway up the hill",
    "ready": "at the top of the hill",
    "in_progress": "halfway down the hill",
    "done": "at the bottom, over the hill",
    "shelved": "off the hill",
    "dropped": "off the hill",
    "promoted": "handed on, at the start of the climb",
}

# A state that is not a stop, and where it stands anyway.
#
# `promoted` is a note's, it is derived from `became` and no person can set it, so
# it is not on the note's ladder and there is no radio for it. Left at that, every
# promoted note drew a hill with no ball on it — empty looking exactly like
# broken, which is finding F1 arriving through a new mechanism. It stands where
# `shaping` does because that is literally where it went: `promote` creates the
# pitch or the task in `shaping`, so the ball did not roll back down, it was
# handed to a record that is now a quarter of the way up a hill of its own.
_HILL_HANDED_ON = {"promoted": "shaping"}

# `hill-<word>` and not `st-<word>`: the invariant is that a status out of a FILE
# reaches a class attribute only through `_status_class`, and no word here comes
# out of a file. These come from `HILL_LADDERS`, which is built from the two
# vocabularies in this module — the record's own `status` is used to compare
# against them and never to build an attribute. A `thinking` note has no rung on
# the status ladder to borrow a colour from, which is the other half of the
# reason: `_status_class` would have called it `st-ready` and put it on a summit.
_HILL = """
<span data-hill="{{ ladder }}"
      class="hill{% if control %} hill-control{% endif %}{% if dim %} hill-off{% endif %}"
     {% if describedby %}aria-describedby="{{ describedby }}"{% endif %}
     {% if live %}role="radiogroup" aria-label="{{ label }}"
     {% else %}role="img" aria-label="{{ said }}"{% endif %}>
  {#- The drawing is scenery: every name a reader needs is on the stops, and a
      screen reader announcing a path element would announce the hill twice. -#}
  <svg viewBox="0 0 {{ box[0] }} {{ box[1] }}" aria-hidden="true" focusable="false">
    <path class="hill-ground" d="M{{ apron[0] }} {{ ground }}L{{ apron[1] }} {{ ground }}"/>
    <path class="hill-line" d="{{ path }}"/>
  </svg>
  {#- Faint at every stop this record could stand on. They are the encoding and
      not decoration: one ball on a curve says where the work is, and a row of
      ghosts says that the curve has places to be and which ones. -#}
  {% for stop in stops %}
  <span class="hill-ghost" style="left: {{ stop.left }}; top: {{ stop.top }};
        --nx: {{ stop.nx }}; --ny: {{ stop.ny }}"></span>
  {% endfor %}
  {#- No ball at all when the status is a word nobody defined. `status` is
      permissive on purpose, so a hand-edited file reaches here holding anything;
      `_status_class` answers `st-ready` for those, which is right for a chip
      whose word says what it really is and wrong here, where it would park an
      unrecognised status on the summit and say something false. -#}
  {% if ball %}
  <span class="hill-ball hill-{{ ball.word }}" data-word="{{ ball.label }}"
        style="left: {{ ball.left }}; top: {{ ball.top }};
        --nx: {{ ball.nx }}; --ny: {{ ball.ny }}"></span>
  {% endif %}
  {#- One real radio per stop, so arrow keys, the focus ring, the group and
      "3 of 5" all come from the browser. The input is the hit target and paints
      its own outline; it carries no `data-type`, because `CONTROLS` is keyed by
      `name` and five elements sharing one would leave `ORIGINAL` with one entry
      and `changed()` with four wrong answers. The value the form serialises is
      the hidden input beside this. -#}
  {% if live %}{% for stop in stops %}
  <label class="hill-stop hill-{{ stop.word }}" data-word="{{ stop.label }}"
         style="left: {{ stop.left }}; top: {{ stop.top }};
         --nx: {{ stop.nx }}; --ny: {{ stop.ny }}">
    <input type="radio" name="{{ group }}" value="{{ stop.word }}"
           data-word="{{ stop.label }}"{% if stop.checked %} checked{% endif %}>
    <span class="sr-only">{{ stop.said }}</span>
  </label>
  {% endfor %}{% endif %}
</span>
"""


def _hill_html(
    status: str,
    ladder: str = "record",
    *,
    live: bool = False,
    control: bool = False,
    label: str = "Status",
    group: str = "hill",
    describedby: str = "",
) -> Markup:
    """The ball on the hill: read-only, or with its stops live.

    `live` is edit mode and nothing else. A drag that committed on its own would
    make a status change the cheapest thing on the page, and a status change is
    the one that should cost the sentence in the body explaining it.
    """
    words = HILL_LADDERS[ladder]
    stops = []
    for word in words:
        left, top = _hill_percent(_HILL_STOPS[word])
        up, down = _HILL_NORMALS[word]
        stops.append(
            {
                "word": word,
                "label": _human(word),
                "said": f"{_human(word)} — {_HILL_WHERE[word]}",
                "left": left,
                "top": top,
                "nx": f"{up:g}",
                "ny": f"{down:g}",
                "checked": word == status,
            }
        )
    # This ladder's own words and not `_HILL_STOPS`: `thinking` has a stop, and a
    # record whose file says `thinking` is as unrecognisable to a pitch's hill as
    # `banana` is. Both get the same answer — no ball, and the word said in full.
    known = status in words
    stands_at = status if known else _HILL_HANDED_ON.get(status)
    ball = None
    if stands_at:
        left, top = _hill_percent(_HILL_STOPS[stands_at])
        up, down = _HILL_NORMALS[stands_at]
        ball = {
            "word": status,
            "label": _human(status),
            "left": left,
            "top": top,
            "nx": f"{up:g}",
            "ny": f"{down:g}",
        }
    return _fragment(
        _HILL,
        ladder=ladder,
        live=live,
        # A hill that is the row's control, whether or not it has stops on it.
        control=control or live,
        label=label,
        # The word as written when it is one nobody defined, so the page says what
        # the file holds rather than pretending the record has no status at all.
        said=f"{_human(status)} — {_HILL_WHERE.get(status, 'not on the hill')}"
        if stands_at
        else f"{_human(status)} — not on the hill",
        # Quiet for the two that came off the path, and for a word nobody defined.
        # Not for `promoted`: that ball is on its way up, which is the opposite of
        # what a dimmed hill says.
        dim=status in _HILL_OFF_THE_PATH or not stands_at,
        stops=stops,
        ball=ball,
        group=group,
        describedby=describedby,
        box=_HILL_BOX,
        ground=f"{_HILL_GROUND:g}",
        apron=[f"{_HILL_FOOT - _HILL_APRON:g}", f"{_HILL_CREST + _HILL_APRON:g}"],
        path=_hill_path(),
    )
