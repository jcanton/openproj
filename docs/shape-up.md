# Shape Up, as this team practises it

## How this maps to what the team already keeps

| in HackMD | in openproj |
|---|---|
| A pitch note | a `pitch` entity — frontmatter, and the shaping doc as the body |
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
  team actually keeps.

The reasoning behind each is in `docs/superpowers/specs/2026-08-16-tailoring-plan.md`.

🤖 Written by an agent on behalf of @jcanton
