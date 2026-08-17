# openproj UX review — the 29 findings to implement

All of them. Including the low ones. A finding is done when the behaviour it
describes is gone, not when something adjacent has been adjusted.

## Cross-cutting

**F1 — Zero results is indistinguishable from a broken app.** Filtering to nothing
renders a column header over an empty void; so does a plan that failed to load; so
does an empty plan. Render an empty state *inside the table body*: "No entity
matches these filters" plus a **Clear filters** control that resets the query
string. Give the genuinely-empty plan its own copy ("This plan has no entities
yet") and the load failure its own ("The plan could not be loaded"). Same treatment
on the people page and the timeline.

**F2 — The blocking-problem count is a dead end.** "1 blocking problems" is not a
link, never pluralises, and is drawn in the danger colour even at zero. The
offending row carries its reason only in a native `title` tooltip. Make the count a
link that applies the existing predicate filter (`missing_required_fields` etc. —
see `COMPUTED_PREDICATES` in `index.py`); mute it at zero; pluralise it; mark
problem rows with `border-left: 3px solid var(--sev-blocker)` and a warning glyph
in the offending cell whose accessible name is the message already in `title`.

**F3 — Status has a colour language everywhere except where people live.** The
`--st-*` tokens are used by the graph and the timeline only. Add a status chip
(soft + text tokens) to the table, the people page, the detail page and the cycle
bet table. Add a legend to the graph and to the timeline naming every colour.

**F4 — Contrast.** Three of five status fills failed AA with their own label;
`--muted` was 4.46; the `.empty` dash was 1.77 and effectively invisible. The new
token table in DESIGN_TOKENS.md fixes all of them — apply it.

**F5 — Two save models on one page, no way to tell them apart.** On the cycle page
some fields autosave and the setup fields need "Save the setup", parked off-screen
at the top. Pick one model for the page and make it visible: a sticky action bar
that shows dirty state and confirms a save landed. Nothing silently autosaves next
to something that does not.

**F6 — Your own edit is reported to you as somebody else's.** After a PATCH from
the table, the SSE toast says "The plan changed" because `mine` is decided by the
entity the page shows, which is null on the table. Track the commit your own write
returned and suppress the toast for it. Also refresh the blocking-problem count and
the row markers in place after a write instead of leaving them stale until reload.

**F7 — Editing is invisible until you guess.** Editable cells look identical to
derived ones and the only affordance is a 12px hint. Give `td.edit` a hover
treatment (dotted underline or a `--surface-2` ground) and a `title`/`aria`
description. Double-clicking a *derived* cell must say why it cannot be edited:
"derived from assigned_on and size".

**F8 — Sorting is mouse-only and directionless.** `th` are `tabindex="-1"` with no
role and no `aria-sort`; the direction is invisible. Put a real `<button>` inside
each sortable `th`, set `aria-sort="ascending|descending|none"`, and show an
up/down glyph on the sorted column.

**F9 — No sticky header, no sticky identity column, no breakpoints.** The table is
~1670px wide and the only media query in the app is `prefers-color-scheme`. Make
`thead` sticky and the id and title cells sticky-left (they need a solid
`--surface` background and a z-index above the body cells). Below ~1100px, hide the
low-value columns.

**F10 — The tags column sets every row's height.** Tags wrap to five lines and
triple the row height. Clamp the cell to one line and reveal the rest behind a
"+N" affordance. Do not add row padding anywhere while doing it.

**F11 — Internal identifiers are shown to users.** `in_progress`,
`missing_required_fields`, `overruns_cycle`, `review_waived` appear verbatim; the
filter holding them is labelled STATE. Add one central label map (there is already
a `LABELS` dict — extend it) and render human labels everywhere while keeping the
identifier as the value. Rename the STATE facet to "Flags".

**F12 — One field, three names, and two date formats.** APPETITE (WEEKS) on detail,
EFFORT (WEEKS) on the create form, WEEKS in the table are the same quantity. Use
"appetite" everywhere (it is the domain word and the spec's). Every displayed date
is ISO but every `<input type=date>` shows browser locale — echo the ISO value
beside each date input so the format never changes under the user.

## Table

Covered by F1, F2, F3, F6, F7, F8, F9, F10, F11, F12.

## New entity form

**F13 — Every foreign key is a free-text box.** owner, assignees, reviewers,
parent, cycle, blocked_by are references and are typed by hand. `_COMBOBOX` already
exists and is used on the detail page, and `_suggestions(index)` already builds the
lists. Wire it to all six on the create form.

**F14 — Requiredness is status-gated and invisible.** `REQUIRED_FROM` already
encodes the rules. Mark the fields the currently selected status requires, and
re-mark live when the status select changes.

**F15 — Commit actions sit above the thing they commit.** Create / Edit / Save the
setup all sit above their form. Move the primary action below the form or into a
sticky action bar. Consistent across all four pages that have one.

## Timeline

**F16 — The controls do not reflect the state they control.** FROM and TO render
empty while the page says "Showing 2026-02-02 to 2026-11-27". Prefill both with the
current window. Give Apply and Reset matching visual weight.

**F17 — No legend, no tooltip, unhoverable bars.** Add a legend. Add a hover
tooltip per bar with title, status, owner, appetite and the ISO start and end.
Enforce a minimum bar width (~3px) so a same-day span is hoverable and clickable.

**F18 — The hierarchy is thrown away.** Rows are flat and ordered by start date.
Order them by the containment tree (project, then its pitches, then their tasks)
and indent by depth in the left label column.

**F19 — Cycle labels collide with the month row and the today line.** Give cycles
their own band above the months and label the today line.

## Graph

**F20 — Group labels are unreadable and collide with edges.** Project and pitch
names render around 8px in light grey on the group border. Put the label inside the
box, top-left, at readable size with a `--surface` backing.

**F21 — Graph and timeline have no filters.** The README says three views share one
filter model; only the table exposes it. Render the same facet bar on the graph and
the timeline, reading and writing the same query-string state.

## People

**F22 — Fifteen tables where one belongs.** Each person gets an independent table
with its own header, so columns shift between people. One table, person as a group
row, one sticky header.

**F23 — Counts where weeks are the question.** "1 as owner, 2 as assignee, 12 as
reviewer" is a workload in item counts. Show weeks committed against availability
per person, reusing the load bar the cycle page already draws.

**F24 — Names are not links.** Link each person to the table filtered by that
person.

## Cycles

**F25 — The headline number is a bullet fragment.** "9.2 of 19.8 weeks bet" is the
sentence the method turns on. Give every cycle a card with the capacity meter the
cycle page already draws, and list every cycle the plan references, not only the
ones with a record.

**F26 — "Start it" writes with no framing and no confirmation.** Put a heading and
a rule above the create form so it is not at the same level as the list. Add a
confirm step to starting a cycle and to the unlabelled trash glyph that removes a
person from a cycle; give that glyph an accessible name.

## Detail

**F27 — Reads as a two-pane layout whose second pane failed.** An 832px article
flush left with a hard right border. Centre the column, or use the space
deliberately: the fact table as a sidebar, the shaping document in the measure.

**F28 — The most decision-relevant line is styled like the least.** "overruns cycle
37 by 6.1 weeks" wears the same muted italic as every other derived value. Keep the
derived italic, add `--warn`, so it reads as computed *and* as a problem.

**F29 — The title appears twice.** The page heading and the shaping document's own
leading heading are the same text at the same weight. Suppress the body's leading
heading when it matches the entity title.
