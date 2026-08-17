# Round eight — expanding a whole column, and the collapse that was never built

> "on the hidden +N columns in the table: should we have an 'expand all' button
> (with a meaningful icon, maybe a + instead of text) on each of these columns to
> expand all hidden in that column?"

Yes. With three things settled first, because the obvious implementation collides
with something already in those headers.

## 1. It is a toggle, and so is the badge — which today it is not

`render.py:2411` is the whole of the reveal:

```js
if (more) more.closest('td').classList.add('open');
```

`add`, not `toggle`. **Once a cell is expanded there is no way to collapse it
again** short of reloading the page. Nobody reported it because expanding one cell
is cheap; expanding a column of seventeen is not, and a one-way control that
doubles the height of the table is a trap.

So the per-column control is a toggle, the badge becomes a toggle, and the column
toggle reflects the column's state rather than firing blindly: if every cell is
open it offers to close them, and closing the column closes the cells inside it.
One `open` class, three ways to set it, no third state.

## 2. The four clamped columns do not have the same header

`_TABLE_COLUMNS` (render.py:302): `assignees` and `reviewers` are **sortable**, so
their `<th>` already holds a `<button>` with the label and the direction glyph.
`prs` and `tags` are **not**, so theirs is bare text. Every one of the four also
gets a resize grip appended by JS.

So on half of them the new control lands beside an existing button, in a column
whose floor is 112px, next to a drag handle. Three targets and a grip in a header
that narrow is how you get a mis-click that sorts the table when somebody meant to
expand it.

Decide this deliberately and say what you decided:

- The toggle is small and right-aligned, before the grip, and the **sort button
  must not swallow its click** — it is inside the `<th>`, not inside the button.
- At `CLAMP_FLOOR` (112px) the header must still fit the label, the sort glyph, the
  toggle and the grip without wrapping or overlapping. Measure it at that exact
  width. If it does not fit, the honest fix is to raise the floor for columns that
  carry a toggle — not to shrink the target.
- If the two shapes cannot be made to look like one control, say so and put the
  toggle somewhere it can be consistent for all four.

## 3. The icon, and what it must say

`+` is right — it is already the vocabulary of the badge, where `+4` means "four
you cannot see", so `+` in the header meaning "show all the ones you cannot see"
reads as the same idea rather than a new one. When the column is open it becomes
the inverse (`−`), because a control says exactly what it will do.

Icon only, so it needs a real accessible name and it changes with the state:
"Show all reviewers" / "Show fewer reviewers". Not a `title` alone — this is a
control, not a hint.

## What this deliberately costs

Expanding a column re-creates exactly what F10 was about: rows grow, and the plan
stops fitting on one screen. That is fine here and it was not fine there, and the
difference is the whole point — F10 was the *default* state doing it to you, this
is you asking for it, and one click puts it back. Do not let it persist across
loads; it is a way of reading, not a setting.

Check the row-height effect at seventeen rows with all four columns open, and make
sure the sticky header and the frozen columns still behave when the rows are tall.
