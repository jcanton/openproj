# openproj design system — review_design branch

Authoritative token set. Every colour and every font in the app comes from here.
Do not invent a colour. If you need one that is not listed, add it to `:root` in all
three theme blocks in `_SHELL` and say so in your report.

## Typeface

Inter Variable is vendored at `static/inter-latin-wght-normal.woff2` (48 KB, OFL,
licence at `static/inter-LICENSE.txt`, checksum already in `static/SHA256SUMS`).

It must be inlined as a `data:` URI in `_SHELL`'s `<style>`, exactly like the JS is
inlined into the graph page — no `<link>`, no URL, because `tests/test_render.py`
asserts no rendered page reaches the network and the static pages must work from
`file://`.

Add a binary sibling to `_inline`:

```python
def _inline_font(name: str) -> str:
    """A woff2 as a data: URI. Binary, so not _inline's read_text."""
    raw = (_static_dir() / name).read_bytes()
    return "data:font/woff2;base64," + base64.b64encode(raw).decode("ascii")
```

Face declaration (variable font — one file covers 100..900):

```css
@font-face {
  font-family: "Inter var";
  font-style: normal;
  font-weight: 100 900;
  font-display: swap;
  src: url("<data uri>") format("woff2-variations");
}
```

Stacks:

```css
--font-sans: "Inter var", ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
--font-mono: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace;
```

`body` uses `--font-sans`. Ids, dates, checksums, PR refs, field labels and any
column of digits use `--font-mono`. Turn on Inter's contextual alternates and
tabular figures where digits align:

```css
body { font-family: var(--font-sans); font-feature-settings: "cv05" 1, "ss03" 1; }
.derived, .num, td.weeks { font-variant-numeric: tabular-nums; }
```

## Status palette

Statuses read as a journey: an idea forming (violet), queued (blue), in flight
(amber), landed (green), parked (slate). Hue-separated and lightness-separated, and
every pill carries its text label, so colour is redundant encoding, never the only
signal.

Each status gets four tokens. Solid fill + ink are for *shapes* — graph nodes,
timeline bars. Soft + text are for *chips* — the status pill in the table, on the
detail page, on the people page, in the cycle bet table.

### Light theme

| status | `--st-X` fill | `--st-X-ink` | `--st-X-soft` | `--st-X-text` |
|---|---|---|---|---|
| shaping | `#5B4B9E` | `#FFFFFF` | `#EDE9F8` | `#4A3C86` |
| ready | `#2C5F8F` | `#FFFFFF` | `#E4EEF8` | `#23507A` |
| in_progress | `#8A5308` | `#FFFFFF` | `#F8EEDC` | `#774606` |
| done | `#2F7248` | `#FFFFFF` | `#E3F1E8` | `#256040` |
| shelved | `#566A72` | `#FFFFFF` | `#EBEFF1` | `#465861` |

Fill against white ink: 5.68 to 7.13. Chip text against chip ground: 6.37 to 7.72.

### Dark theme

| status | `--st-X` fill | `--st-X-ink` | `--st-X-soft` | `--st-X-text` |
|---|---|---|---|---|
| shaping | `#A79AE6` | `#0F1416` | `#252041` | `#B8AAF0` |
| ready | `#7FB2DE` | `#0F1416` | `#152B3E` | `#8FBEEA` |
| in_progress | `#D9A557` | `#0F1416` | `#332409` | `#E2B268` |
| done | `#6FC095` | `#0F1416` | `#14301F` | `#7ECDA2` |
| shelved | `#9DAEB6` | `#0F1416` | `#1E262A` | `#A6B7BF` |

Dark fills invert: they are light shapes carrying dark ink, so a node pops off the
dark canvas instead of sinking into it. Fill against ink: 7.43 to 8.52. Chip text
against chip ground: 7.38 to 7.73.

**Every one of these pairs passes WCAG AA (4.5:1) with margin. Do not "adjust" a
value for taste — if you change one, recompute its ratio and report the number.**

## Kind

Kind must never compete with status for attention, so it is drawn in ink, not in
hue: a monospace chip with a hairline border and a weight difference.

```
--kind-ink: var(--muted);   --kind-line: var(--line-strong);
```

project = uppercase, `--fg`, 650 weight. pitch = uppercase, `--muted`. task =
uppercase, `--muted`, no border. If you want one accent, give `project` the accent
border only.

## Base tokens

Keep the existing three-state theme structure in `_SHELL` exactly as it is — bare
`:root`, then `@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) }`,
then `:root[data-theme="dark"]`. Only the values change.

### Light

```
--bg #FFFFFF        --surface #FFFFFF     --surface-2 #F5F8F8
--fg #14211F        --muted #5A6B70       (5.57:1 — was 4.46, F4)
--line #DCE4E5      --line-strong #B4C3C7
--accent #0F5C6B    --on-accent #FFFFFF
--danger #9A3327    --warn #8A5308        --ok #2F7248
--empty #7C8D93     (3.45:1 — was 1.77, F4)
--focus #0F5C6B
```

### Dark

```
--bg #11181B        --surface #171F22     --surface-2 #1C262A
--fg #DDE6E7        --muted #93A6AA
--line #263336      --line-strong #3A4D53
--accent #5CB9CA    --on-accent #0B1214
--danger #E0796A    --warn #D9A557        --ok #6FC095
--empty #7E9199
--focus #5CB9CA
```

`--empty` is the em dash that means "no value". It was invisible at 1.77:1; it is a
real piece of information and now reads as one.

## Focus

Every interactive thing gets a visible focus ring. There is currently exactly one
`outline: none` in the file (`#bets input.live:focus`) — remove it.

```css
:where(a, button, input, select, textarea, summary, [tabindex]):focus-visible {
  outline: 2px solid var(--focus);
  outline-offset: 2px;
  border-radius: 2px;
}
```

## Severity

Problems need one language across the app:

```
--sev-blocker      = var(--danger)
--sev-warn         = var(--warn)
--sev-blocker-soft  light #F9E9E6  dark #2B1B17
--sev-warn-soft     light #F8EEDC  dark #332409
```

A row with a blocking problem gets `border-left: 3px solid var(--sev-blocker)` and
a warning glyph in the offending cell. A warning row gets `--sev-warn`.

## Shape and spacing

- Radius: `2px` on chips and inputs, `3px` on cards and panels. Nothing rounder —
  this is a dense planning tool, not a dashboard.
- Chips: `font-size: 11px`, `letter-spacing: .04em`, `padding: .1rem .4rem`,
  uppercase, mono.
- The table stays dense. Do not add vertical padding to rows; F10 is about
  *removing* height, not adding it.
