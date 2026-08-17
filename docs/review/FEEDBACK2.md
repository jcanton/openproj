# Round seven — jcanton's second set of notes

Three more from using it. The third is a real bug and I reproduced it before
writing this down.

---

## 1. What the clamp hides should be readable without opening the editor

> "is it possible to have the hidden things in the table appear on hover? i.e.
> assignees msimberg +1, if I hover on the cell I see 'double click to edit
> assignees', can the hidden +1 appear before the double click instruction
> message? same for all cells that have the hidden option"

Right, and it is the obvious gap the clamp left. Four columns now show one item and
a `+N` — assignees, reviewers, tags, prs — and the only affordance for the rest is
a click on a small badge. Hovering the cell currently answers a question nobody
asked ("Double-click to edit assignees") while the question they did ask — *who is
the +1?* — needs a click.

`render.py:1858`:

```js
const tip = note || (editable ? 'Double-click to edit ' + named : WHY[key] || '');
```

The hidden values come first, then the instruction. Every clamped cell, not only
assignees. Keep the badge working exactly as it does — this adds a way to read,
it does not replace the way to reveal.

Two things to get right:

- The problem message still wins. `note` is a validation problem and it is the
  most important thing a cell can say; it stays first when there is one.
- A cell showing everything it has needs no reveal line. Only add it when
  something is actually hidden, or every tooltip in the table grows a redundant
  sentence.

A native `title` takes newlines, so the shape is the hidden values on one line and
the instruction under them. If a `title` cannot carry it well — sixty tags, say —
say so and cap it sensibly rather than emitting a paragraph.

## 2. The graph page has no room left for the graph

> "not a lot of space is left to the graph itself, between title, instructions,
> search box, filters, legend, 17/17 shown and the banner at the bottom to edit
> dependencies. can we inline some things? e.g. instructions to the right of the
> search box, right aligned; 17 of 17 shown to the right of the legend, also right
> aligned"

Measured at his window: the canvas starts 268px down an 806px viewport. Six stacked
rows before any graph.

Do what he asked: the pan/zoom hint moves onto the search box's row, right-aligned;
`N of N shown` moves onto the legend's row, right-aligned. That is two rows back,
about 50px.

Then check the same stack on the timeline and the table, which are built from the
same parts — if the pattern is right it is right on all three, and if it is only
right here, say why.

## 3. The edit bar is drawn on top of the graph

> "I think the 'edit dependencies' banner/bar overlaps the graph and loading the
> page two nodes are drawn underneath it."

Confirmed, and worse than it looks. `#cy` is `height: 78vh` — a fixed fraction of
the viewport that knows nothing about the six rows above it or the sticky bar
below. At his window the canvas runs from y=268 to y=899 in an 806px viewport, and
`.commitbar` is `position: sticky` across 759–806. So **140px of the canvas is
underneath the bar**, and the page scrolls as well.

`78vh` was always going to be wrong; it is only a question of by how much. The
canvas should take the room that is actually left, and the table already has the
mechanism — `.table-scroll` sizes itself from a `--above-rows` measured in JS.
Reuse it rather than inventing a second one, so the graph, the timeline and the
table all answer "how much room is left" the same way.

Verify at several window heights, including a short one, and confirm the bottom of
the canvas clears the top of the sticky bar with nothing drawn underneath — and
that the graph's own fit-to-view still centres the plan in the space it ends up
with, rather than in the space it thought it had.
