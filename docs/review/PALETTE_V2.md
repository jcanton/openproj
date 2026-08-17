# Status palette, version 2 — supersedes the status table in DESIGN_TOKENS.md

Version 1 separated the five statuses by hue alone. On the graph and the timeline
fill is the only channel — no label sits on a bar — and five hues at the same
lightness collapse into one colour for a dichromat. Roughly 1 in 12 men is one.

Version 2 puts the statuses on a **luminance ladder**, because lightness is the one
channel every kind of colour vision keeps. Work gets more solid as it advances:
parked is the faintest, done is the darkest and most settled. Hue still carries the
meaning; lightness guarantees it survives.

Everything else in DESIGN_TOKENS.md — the font, the chip shapes, the base tokens,
the focus rule, the severity tokens — stands unchanged. Only the values below move.

## Light theme

| status | `--st-X` | `--st-X-ink` | ink ratio | vs page | vs previous rung |
|---|---|---|---|---|---|
| shelved | `#8A979F` | `#101416` | 6.18 | 3.00 | — |
| shaping | `#7E61C2` | `#FFFFFF` | 4.80 | 4.80 | 1.60 |
| ready | `#275E92` | `#FFFFFF` | 6.77 | 6.77 | 1.41 |
| in_progress | `#603A04` | `#FFFFFF` | 9.98 | 9.98 | 1.47 |
| done | `#0D311F` | `#FFFFFF` | 14.23 | 14.23 | 1.43 |

## Dark theme

| status | `--st-X` | `--st-X-ink` | ink ratio | vs page | vs previous rung |
|---|---|---|---|---|---|
| shelved | `#5E6A73` | `#FFFFFF` | 5.55 | 3.23 | — |
| shaping | `#9077CB` | `#101416` | 5.02 | 4.86 | 1.50 |
| ready | `#7AACDC` | `#101416` | 7.73 | 7.49 | 1.54 |
| in_progress | `#F9C275` | `#101416` | 11.47 | 11.11 | 1.48 |
| done | `#D7F4E6` | `#101416` | 15.85 | 15.36 | 1.38 |

Note the ink column: it is no longer white everywhere. It flips per status, in both
themes, because the fills now span the whole lightness range. `--st-X-ink` already
exists per status — this is what it was for.

Every fill also clears 3:1 against its own page, so a bar or a node is a real shape
against the ground even before its border.

## Chips

The `--st-X-soft` / `--st-X-text` chip pairs keep their job: a soft tinted ground
with saturated text. Re-derive them from the new hues, keep them at or above 4.5:1,
and report the ratio you land on for each. Chips carry a text label, so they do not
need the ladder.

## The redundant channel

The ladder makes the five fills separable. It does not make them *nameable*. On any
surface where a fill is the only thing distinguishing two items, colour must not be
the only channel:

- **Timeline** — every bar carries a tooltip already (F17). Add one more channel to
  the bar itself: a status glyph at the bar's left edge, or a distinct stroke
  treatment per status. Not hatching — hatching already means estimated or unowned
  and must keep meaning only that.
- **Graph** — nodes carry their title. Add the status as a small chip inside the
  node, or as a distinct border style per status.
- **Legend** — both views get one (F3, F17) naming every colour in words.

## Other token corrections

These failed their jobs in version 1 and are not negotiable:

```
--line-strong  light #879398 (3.15:1 on white)   dark #5C7076 (3.45:1)
```
It is the only boundary of every drawn input, button and popup, so it is a UI
boundary and owes 3:1. It was 1.81.

```
--empty        light #5F7176 (5.11:1)            dark #84969C (5.83:1)
```
The em dash that means "no value" is *text*, so it owes 4.5:1, not the 3.45 the
first brief specified. That was my error, not the implementer's.
