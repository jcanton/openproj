# Status palette, version 3 — light theme only. Supersedes PALETTE_V2.md's light table.

## What was wrong

Version 2 put white text on every fill in the light theme. That forces every fill
low on the luminance scale, and a low-luminance amber is brown, a low-luminance
green is nearly black. Side by side with the dark theme — which already inverts,
dark ink on light fills — the light timeline looked muddy and the dark one looked
right. It was not taste; it was the consequence of one decision.

The dark theme is unchanged. This brief inverts the light theme the same way, and
gives the fills a border so a pale fill is still a shape against a white page.

## Light theme

| status | `--st-X` fill | `--st-X-ink` | ink on fill | `--st-X-line` border | border vs page |
|---|---|---|---|---|---|
| shelved | `#E1E5E9` | `#101416` | 14.63 | `#8A979F` | 3.00 |
| shaping | `#D2C5EE` | `#101416` | 11.43 | `#7E61C2` | 4.80 |
| ready | `#83B8E9` | `#101416` | 8.82 | `#275E92` | 6.77 |
| in_progress | `#E18606` | `#101416` | 6.72 | `#603A04` | 9.98 |
| done | `#2B925E` | `#101416` | 4.74 | `#0D311F` | 14.23 |

The borders are exactly version 2's fills. They were already measured against the
page at 3:1 or better, which is what a UI boundary owes, so the value that used to
be the whole shape is now its edge.

Adjacent fills stay 1.28 to 1.42 apart in contrast, so the luminance ladder that
survives colour blindness survives this change too. Ordering is unchanged and means
what it meant: **`done` is always the furthest from the page ground and `shelved`
the closest** — finished work pops, parked work recedes — which is why the light
ladder runs pale-to-saturated and the dark one runs dark-to-pale.

## The new token

`--st-X-line` is new: the border of a status shape. It must be defined in all three
theme blocks like every other token.

In the **dark** theme a fill is already well clear of the ground (3.23:1 at worst),
so the border is there for shape rather than for separation — use the fill's own
value, or a slightly darker one. Do not leave it undefined in one theme.

## The ink is now one value

`--st-X-ink` is `#101416` for all five statuses in both themes. Dark's `shelved`
was the last white one and it clears 6.03:1 on dark ink, so the exception is gone.
Keep the five tokens rather than collapsing them to one — a future status may need
its own — but they all carry the same value today, and say so in a comment.

## Where the border has to be applied

A pale fill without its border is a pale shape on a white page. Everywhere a status
fill is drawn, the matching `--st-X-line` is drawn with it:

- **Timeline bars** — `stroke: var(--st-X-line)`, 1px. Watch the interaction with
  "overruns its cycle", which is already a `--danger` outline: an overrunning bar
  must still read as overrunning, so keep that outline thicker, or outside the
  status border, and check both on the seed corpus where `Porting land` overruns.
- **Graph nodes** — `border-color: var(--st-X-line)`. Cytoscape reads tokens
  through `token()` and re-reads on `themechange`; the border must do both.
- **Legend keys** on both views — same fill and same border as the thing they name,
  or the legend stops being a legend.
- **Chips** keep their own `--st-X-soft` / `--st-X-text` pair and do not change.

## Verify, do not trust

Recompute every ratio from the values you actually ship and paste the table into
your report: ink on fill, border against the page, and each adjacent pair of fills.
The existing test that pins the palette as a contract must be updated to the new
values and extended to cover the border token and its 3:1 obligation.

Then render the seed corpus and look at the light timeline and the light graph
beside the dark ones. The amber should be amber.
