# Shape Up, as this tool practises it

## How this maps to a pitch note in a wiki

The tool was tailored for a team whose shaping lived in a wiki: a note per pitch with the fields in
its header, a sheet per cycle with the available people and a task table, and one table across
cycles — theirs was called Greenline — for what depends on what. The table below is the mapping;
where a row is more than a rename, the reason is in the row.

| in the wiki                                            | in openproj                                                                                                                                                                                    |
| ------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| A pitch note                                           | a `pitch` record — frontmatter, and the shaping doc as the body                                                                                                                                |
| `Shaped by: @a and @b` in the header                   | `owner` — who shaped it and holds it. One name where the header takes two: a deliberate trade, made to stop owner, shaped-by, assignees and reviewers being four lists of people on one record |
| `Appetite (FTEs, weeks)`                               | `person_weeks` — the work one person would need; the people on it divide it                                                                                                                    |
| The cycle sheet's `Available people`                   | `availability:` in `cycles/<n>.md`, a fraction of the build weeks                                                                                                                              |
| The cycle sheet's task table                           | the betting table on `/cycle/<n>`                                                                                                                                                              |
| The sheet's `## Goal`, and what was said while betting | the cycle record's body, editable on that page                                                                                                                                                 |
| `Support`                                              | `reviewers` — the role includes support, and it makes somebody accountable                                                                                                                     |
| The Greenline table's `Depends on`                     | `depends_on`, with `blocks` derived from it                                                                                                                                                    |
| The Greenline table's `Shape doc` link                 | there is no link: the shaping doc *is* the record                                                                                                                                              |

## Where this departs from the book

Deliberately, and with the practice of the team it was tailored for as the reason:

- A size is person-weeks and staffing divides it, so the tool forecasts dates the book would not.
- Cycles are soft walls and the scheduler runs work past them rather than stopping, because the
  circuit breaker is a human decision made at the review meeting.
- `project` is a milestone layer the book does not have, because the Greenline table already tracks
  cross-cycle dependencies.
- Progress is the body's own checklist rather than a hill chart, because a checklist is what the
  team it was tailored for actually keeps. The hill on every record draws `status`, not progress —
  nine of ten boxes ticked can honestly still be uphill, because the tenth is the one nobody knows
  how to do — so the tool draws both and converts neither into the other. The ball is the control
  that sets the status, and it only moves while the record is being edited, so a move costs the
  sentence that explains it.

Five things that team asked for at the tailoring pass were declined; `AGENTS.md` has them and the
reason for each. Everything here is paraphrase — Shape Up is free to read online, but the
reproduction terms are somebody's to check.

🤖 Written by an agent on behalf of @jcanton
