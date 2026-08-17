# Round four — jcanton's notes from using it

He drove the running app at :8010 and wrote these down. They are the owner's
preferences about his own tool, so where one contradicts an earlier brief, this
wins. Where one is phrased as a question, it is still a decision to make and to
justify in the commit message.

---

## 1. The kind chips leave the table

> "in the table why are pitch and project in the ID written inside a box but not
> task? I'd rather not have those boxes: the entity type is already obvious by the
> id string. if anything box the id strings?"

He is right about the inconsistency, and it was deliberate and wrong: the design
brief said project and pitch carry a border and task does not, which reads as two
of them being special rather than as three of a kind.

**Remove the kind chip from the table's id cell entirely.** `pitch-0c0001` already
says pitch, in a prefix the data model guarantees agrees with the kind — the chip
was restating the first word of the cell it sits in. Kind stays filterable in the
KIND facet, which is where the question "show me only tasks" is actually asked.

Do **not** box the id string in its place. He offered it as an alternative, not a
request, and a box around all seventeen ids is the same noise wearing a different
hat — the id is already monospace, which is what marks it as a token to be cited.
Say so in the commit message so the choice is visible and easy to reverse.

The kind chip stays on the detail page (see 6) and in the people and cycle tables,
where the id is not present to carry it.

## 2. The table's default view: columns fit their contents, table fits the window

Two separate things, both real.

**2a — The vertical rule beside the frozen title column must go.** He reads it as a
stray column separator, which is exactly what it looks like when the table is not
scrolled sideways. It is the `box-shadow: 1px 0 0 var(--line)` that tells you the
frozen columns end there. Show it **only while the table is actually scrolled
horizontally** — set a class from the scroll handler — or drop it. Never paint it at
`scrollLeft === 0`.

**2b — The default fit is wrong.** Measured at his window: the table computes to
1780px inside a 1460px container, so it scrolls sideways on arrival. He describes
what he wants precisely, and it is what the tool did before this branch:

> "all columns just large enough to fit their contents without newlines, except the
> tags column, and total table width = page/browser width"

So: measure each column at its widest cell on one line and give it exactly that —
`fitWidths()` currently multiplies by 1.1, which is 10% of fourteen columns of
padding and is most of the overflow. Then tags absorbs the remainder. If the
natural total still exceeds the container, take the difference from the text
columns worst-first (title is the only one whose content is a sentence), never from
the numeric and date columns, which have exactly one right width.

The result must be: **no horizontal scrollbar in the default view at a normal
window**, every column showing its content on one line, tags clamped with the `+N`
badge he likes.

Keep the `+N` badge exactly as it is. He called it out as a thing he likes.

**2c — Make it deterministic.** He saw a broken first paint that a reload fixed.
Part of that was a bug already fixed mid-session, but the underlying hazard stands:
widths are measured from a layout that may still be using fallback font metrics,
because the face arrives as a `data:` URI with `font-display: swap`. Refit once on
`document.fonts.ready` so a first paint measured against the wrong metrics cannot
stick. First load and reload must produce identical widths — assert it.

## 3. The graph loses its mode paragraph

> "when clicking edit dependencies the line below graph changes ... this seems
> unnecessary since the explanation already appears next to the 'edit dependencies'
> button, I would remove it"

Delete the `#howto` paragraph that swaps in on entering edit mode. The status text
beside the button already says what to do, and two explanations of one mode, in two
places, is one too many.

The standing hint — "Double-click a node to open it. Drag to pan, scroll to zoom,
drag a node to move it." — stays as it is, in both modes.

## 4. Timeline: FROM, TO and ZOOM belong on one line

They wrap onto separate lines. Put the whole control row — FROM, TO, ZOOM, Apply,
Reset — on one line, and keep the ISO echo under each date input where it is. It
should stay on one line down to a reasonable window before it wraps sensibly.

## 5. People: the groups need air

> "I would add a newline before each person, now they're stuck to the end of the
> list of the previous person"

Space above each person's group row so the eye can find where one person ends and
the next begins. Space, not a rule — the rows already have hairlines and another
line would make it noisier. The first group should not get a leading gap.

## 6. Detail: the kind goes before the title

> "I'd put the pitch/task/project boxes before the titles, owners at the end are
> fine."

The kind chip moves above the `<h1>`, as an eyebrow. What a thing *is* should be
readable before you read its name, and it currently sits below the title in a meta
line that also carries the id and the status.

The status chip stays in the meta line under the title — he did not ask for it to
move, and status changes while kind does not. The rest of the meta line is unchanged.

Check the same header on the cycle page and the new-entity form so all three agree.
