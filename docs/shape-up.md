# Shape Up, as this team practises it

## How this maps to what the team already keeps

| in HackMD | in openproj |
|---|---|
| A pitch note | a `pitch` record — frontmatter, and the shaping doc as the body |
| `Shaped by: @a and @b` in the header | `shaped_by: [a, b]` |
| `Appetite (FTEs, weeks)` | `person_weeks` — the work one person would need; the people on it divide it |
| The cycle sheet's `Available people` | `availability:` in `cycles/<n>.md`, a fraction of the build weeks |
| The cycle sheet's task table | the betting table on `/cycle/<n>` |
| The sheet's `## Goal`, and what was said while betting | the cycle record's body, editable on that page |
| `Support` | `reviewers` — the role includes support, and it makes somebody accountable |
| The Greenline table's `Depends on` | `depends_on`, with `blocks` derived from it |
| The Greenline table's `Shape doc` link | there is no link: the shaping doc *is* the record |

## Where this departs from the book

Deliberately, and with the team's practice as the reason:

- A size is person-weeks and staffing divides it, so the tool forecasts dates the book would not.
- Cycles are soft walls and the scheduler runs work past them rather than stopping (D2), because the
  circuit breaker is a human decision made at the review meeting.
- `project` is a milestone layer the book does not have, because the Greenline table already tracks
  cross-cycle dependencies.
- Progress is the body's own checklist rather than a hill chart, because a checklist is what the
  team actually keeps. The hill is on every record and draws `status`, not progress: `shaping` is
  the climb, `ready` the summit, `in_progress` the descent, and `shelved` the ground under the
  summit. The two measure different things — nine of ten boxes ticked can honestly still be
  uphill, because the tenth is the one nobody knows how to do — so the tool draws both and
  converts neither into the other. The ball is the control that sets the status, and it only
  moves while the record is being edited, so a move costs the sentence in the body that explains
  it. The five status marks stay characters and are not small hills: the same five go inside
  `<option>` elements — the table's inline editor, every facet menu — and an option is a string, so
  a hill in the chips would add a third vocabulary rather than remove the second. Mocked against the
  real stylesheet at 26×11, `shelved` reads as a ball floating inside the hill instead of resting on
  the ground under it, and `ready` and `shaping` are two dots a few pixels apart, in the one column
  already under width pressure.

## What the team asked for and did not get

Declined at the tailoring pass, 2026-08-16, each with its reason.

- **`postponed` as a bet outcome** — leaving a pitch `ready` says the same thing; it produced a
  better idea instead, the notes box on the cycle page, so what came up at the betting table has
  somewhere to live.
- **Appetite in cycle units** — appetite is person-week effort and the assignees divide it; "full
  cycle" on the team's own sheet is staffing shorthand, not a second unit.
- **A roster grouped by institution** — if institutions turn out to matter, the answer is separate
  plans and separate deployments, not a grouping column.
- **An availability field that admits uncertainty** — better a lie that forces a good estimate than
  a field that accepts `some time > 0`.
- **A `buggy` status** — work that is wrong does not get merged; it goes back to `in_progress` or is
  shelved.

🤖 Written by an agent on behalf of @jcanton
