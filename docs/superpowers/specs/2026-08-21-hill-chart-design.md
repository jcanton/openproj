# The hill chart — design

**Status:** proposed, 2026-08-21. Nothing implemented.

Shape Up draws a piece of work as a ball on a hill: uphill is figuring out what to do, the top is
knowing, downhill is doing it. This puts that picture on a record, and makes it the control that
sets `status` rather than a second picture of one.

## 1. What the ball says, and what it does not

The ball's position **is `status`**. Not progress.

Progress in this tool is derived — `_progress_of` (`index.py`) counts a parent's finished tasks in
person-weeks and a leaf's ticked checkboxes, and nothing about it is stored. Binding a draggable
control to it would mean either inventing a frontmatter field for a number that is already counted,
or having a drag tick somebody else's checkbox. Both were considered and both are worse than the
thing the hill is actually good at.

They are also different measurements, which is the book's own point: a task with nine of ten boxes
ticked can honestly still be uphill, because the tenth is the one nobody knows how to do. So
`docs/shape-up.md` keeps its line — progress is the body's checklist — and gains the hill beside
it as a picture of status. The earlier decision is not reversed.

The mapping is exact rather than decorative:

| status | where | why |
|---|---|---|
| `thinking` (notes only) | on the ground, at the start | an idea nobody has begun to shape |
| `shaping` | a quarter along, mid-slope | figuring out what to do — the book's uphill |
| `ready` | the summit | shaped and bet on: we know what to do |
| `in_progress` | three quarters along, mid-slope | getting it done — the book's downhill |
| `done` | on the ground, at the finish | over the hill |
| `shelved` / `dropped` | on the ground, halfway along | fell off the path; never got over it |

`shelved` sits under the summit rather than past the finish because past the finish reads as "after
done", which is the one thing it is not.

## 2. Geometry, from one function

The curve is a raised cosine over the hill's span:

```
y(t) = ground − amplitude · (1 − cos 2πt) / 2,   t ∈ [0, 1]
```

It grounds at both ends, peaks at `t = 0.5`, and its steepest points fall exactly on `t = 0.25` and
`t = 0.75` — so `shaping` and `in_progress` land halfway up and halfway down, on the line, by
construction rather than by a coordinate somebody typed.

`viewBox="0 0 120 48"`; ground `y = 40`, apex `y = 8` (amplitude 32); the hill spans `x = 12` to
`x = 108`, with the ground line drawn from 4 to 116 so it runs past both feet. The path is 48
sampled points, `M`/`L`. Stops:

| status | x | y |
|---|---|---|
| `thinking` | 12 | 40 |
| `shaping` | 36 | 24 |
| `ready` | 60 | 8 |
| `in_progress` | 84 | 24 |
| `done` | 108 | 40 |
| `shelved`, `dropped` | 60 | 40 |

**One function emits both the path and the stops.** A ball that floats off the line it is drawn on
is this codebase's characteristic defect in a new spelling — the same argument as `days_after`: if a
number appears in two places, one of them will be wrong. A test asserts `|y(t) − stop.y| < ε` for
every stop that is on the curve.

Two vocabularies over one geometry. Entities offer `shaping, ready, in_progress, done, shelved`;
notes offer `thinking, dropped`. The stop set is per record kind, so an entity can never be dragged
to `thinking` and a note can never be dragged to `ready` — the nearest-stop search only ever sees
its own kind's stops. Issues get no hill: an issue is not a bet, and this is a picture of shaping a
bet.

Everything is on or above the ground line. Nothing is drawn below it, so the hill costs its own
height and no more.

## 3. Where it goes

**In place of the status chip and the status dropdown**, as the first row of the detail page's facts
column — which is level with the title, so it is "up top" without anything being added to the
header. `render.py:12735` records why there is no status chip beside the title: the same word, in
the same colour, twice. The hill does not reopen that. It is one control in one place, and what it
adds over the word is the thing the word cannot say — uphill or downhill.

Three sites:

1. `_fact_rows` status row (`render.py`): `display` becomes the read-only hill, `control` becomes
   the same hill with its stops live. Same row contract as every other field, so the layout does not
   move when Edit is pressed.
2. `_CONTROL` (`render.py:11544`): the `status` branch stops emitting a `<select>` and emits the
   hill. Shared by the detail page and the create form, so both change at once — which is the
   comment on `_REQUIRED_JS`'s own reason for existing.
3. `cardHtml` (`render.py:3274`): the status chip in `.card-chips` becomes a small read-only hill.
   Kind and priority chips stay. The card is drawn by the table, the graph and the timeline, so this
   is one edit for three pages.

The note page (`_NOTE`, `render.py:19644`) has a status `<select>` of its own and gets the same
treatment, with the note stop set. Its select is already `disabled` when the state is derived; the
hill inherits that and is inert on a promoted note.

`promoted` gets no ball. It is derived from `became`, a person cannot set it, and the link that
causes it is already on the page — a stop nobody can drag to is a stop that only has to be
explained.

The table's status column is untouched: it keeps its chip, and its inline editor keeps `askFor`.

## 4. The control

**The hill is not a form field.** The five stops are real `<input type="radio">`, one per status,
wrapped in a `<label>` positioned at the stop's coordinates, with the visible ball as a sibling
`<span>` and the status word as screen-reader-only text. Arrow-key movement, roving focus, group
semantics and "3 of 5" all come from the platform; there is no hand-written ARIA.

The radios carry no `data-type` and are not named `status`, because `CONTROLS` is
`FORM.querySelectorAll('[data-type]')` keyed by `name` — five elements sharing one name would give
`ORIGINAL` one entry and `changed()` four wrong answers. The value the form serialises stays a
single element named `status`; the radios write to it and dispatch a bubbling `change`.

That one line is what keeps the rest of the page working untouched:

- `dirty()` counts the unsaved change (`FORM.addEventListener('change', dirty)`)
- `markRequired` re-reads `form.querySelector('[name=status]').value` and re-marks which fields
  `in_progress` will be refused without
- `changed()` puts `status` in the PATCH body exactly as before

No new endpoint, no new validation, no second write path, and the "`in_progress` needs
`assigned_on` and a reviewer" courtesy keeps working because it was never asking the select — it was
asking `[name=status]`.

**Read view does not drag.** Dragging commits nothing on its own; the ball moves only in edit mode
and the move is saved with the rest of the edit. A status change should cost the sentence in the
body that explains it.

Pointer drag is an enhancement over the radios: `pointerdown` on the ball captures, `pointermove`
previews at the nearest stop by distance in element coordinates, `pointerup` checks that radio and
fires its `change`. Every drag lands on a stop; there is nothing between them to land on.

The `<dt>` label needs one template change. It renders `<label for="{{ row.for }}">` when a control
exists, and a `<label for>` pointing at one radio of a group is wrong. Status sets `row["for"]` to
empty and the template falls back to a plain label, with the group carrying
`role="radiogroup" aria-label="Status"`.

## 5. Paint

Curve `var(--line-strong)`, ground `var(--line)`, both `stroke-linecap: round` at 2.5 units — thick
and round is what makes it read as cartoonish without a filter, a gradient or a second font.

The ball is `var(--st-<status>)` filled with `var(--st-<status>-line)` around it: the same luminance
ladder the chips, the graph nodes and the Gantt bars already wear, so the hill obeys the ladder
rather than inventing a hue. Faint balls at the other stops show that the path has places to be —
that is the encoding, not decoration.

`shelved` and `dropped` dim the whole hill. The ball keeps its own colour so it stays findable.

An unknown status — `status` is permissive and holds whatever a hand-edited file holds — draws **no
ball**, dims the hill, and names the word as written. Not `_status_class`'s `st-ready` fallback:
that is right for a chip, where the word beside it says what it really is, and wrong here, where it
would park an unrecognised status on the summit and say something false.

The ball transitions position on change. The shell's blanket `prefers-reduced-motion` block is
inlined before every page's own stylesheet and marked `!important`, so this is already covered and
needs no rule of its own.

Focus: `input:focus-visible + .ball { outline: 2px solid var(--focus) }`, drawn on the ball rather
than on the input, which is what the reader is looking at.

Tokens go in all three blocks — bare `:root`, `:root[data-theme="dark"]`, and the media query
guarded by `:root:not([data-theme="light"])` — or reuse tokens that already are. Nothing may have
its only definition in a block half the readers never match.

## 6. How the geometry reaches the browser

One payload, `<script id="hill" type="application/json">`, in the shell beside `words` and
`chipmarks` — the shape `test_no_page_is_assembled_by_substitution` already understands. It carries
the viewBox, the path and the stops. `cardHtml` builds its hill from it; the server builds the
detail page's from the same Python function that produced it. Two renderers, one set of numbers.

## 7. Tests

- every stop that is on the curve satisfies `|y(t) − stop.y| < ε` — the geometry cannot drift from
  the drawing
- the stop sets are derived from `STATUS_ORDER` and `NOTE_STATES`, not restated: a status added
  tomorrow fails this test rather than silently having nowhere to stand
- an unknown status renders a hill, no ball, and does not raise
- pixel: the ball is painted, and its centroid is at a different x for each of the five statuses.
  Asserting the CSS resolves is not enough — the frozen column resolved to exactly the value every
  test asserted and Chrome painted nothing
- keyboard: Tab reaches a stop, an arrow key moves the ball, `[name=status]` follows, and the commit
  bar reads one unsaved change
- read view carries no radios, and a drag on it changes nothing
- an entity's hill has no `thinking` stop and a drag toward the start cannot reach one; a note's has
  no `ready`
- `PATCH` from a hill-driven change carries `status` and nothing else
- the card carries a hill on the table, the graph and the timeline

## 8. Files

`src/openproj/render.py` — geometry, `_HILL_STYLE`, `_HILL_JS`, the `_CONTROL` status branch, the
`_fact_rows` status row, the `<dt>` label fallback, the shell payload, `cardHtml`, `_NOTE`.
`docs/shape-up.md` — the hill line, rewritten to say what the hill draws.
`tests/` — as above.

No new dependency, no new endpoint, no model change, no new frontmatter key.

🤖 Written by an agent on behalf of @jcanton
