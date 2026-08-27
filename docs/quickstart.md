# Quickstart

The plan is at <https://openproj-392761827400.europe-west1.run.app>. Sign in with GitHub; if you are
in C2SM you can write. There is no database behind it — every page is drawn from markdown files in
`github.com/jcanton/icon4py-plan`, and every save is a commit there with your name on it.

The landing page is **Records**: every record in the plan, one line each, newest edit first, with
the search box above it — it is how you get back to the thing you were writing. The tabs are the
plan seen several ways. **Table** is the plan's records, filterable and searchable, and is where
most people live. **Graph** is the dependency diagram. **Timeline** is the Gantt. **Cycles** is one
page per cycle, with what was bet in it and who has room. **People** is who is on what. **Help** is this page
and the rest of the documentation, on one page inside the app. Clicking any record opens its own
page, which is where you edit it.

Filters live in the URL, so the view in front of you is a link, and there are no saved views to
manage.

The plan is empty today, on purpose: it grows out of what the team bets on rather than out of an
example nobody wrote. Start a cycle from **Cycles**, then write the first pitch.

## The three things

A **pitch** is a bet: a problem, a solution shaped to fit an appetite, and the argument for spending
the time on it. It is what the betting table says yes or no to, and it is one file — the fields at
the top, the shaping document underneath, so the thing being bet on and the reasoning never drift
apart.

A **task** is a piece of a pitch, with its own size and its own people, taking its cycle from the
pitch it belongs to — a bet is made once, on the thing the room named. A task with no parent is a
chore nobody pitched, and then it is bettable in its own right.

A **cycle** is the block of weeks the team bets in, and its record stores two dates, both of them
meetings: `starts_on` is the betting table and the first day of build, `reviews_on` is the review
meeting. Where build ends, how many working weeks that is once the holidays are out, and where the
cool-down ends are worked out from those two and from what fraction of the weeks each person has.

Two more you will meet. A **project** groups pitches into a milestone: it has no size, is never bet,
and its span is the rollup of what is inside it. An **issue** is somewhere to put a half-formed
thing — most issues will never be worked on, which is exactly what they are for, and a shaped issue
is a pitch.

And one that is none of those. A **note** is an idea before anybody knows what it is: an issue is
"we found something existing that is broken", a note is "we are thinking of creating something that
does not exist and our ideas are confused". It has no appetite, no owner and no size, and it lives
on **Records** and its own page, on no view of the plan — which is the point, because a plan
showing bets nobody has made is a plan you cannot read. When it turns out to be work, **Promote**
turns it into a project, a pitch or a task in one commit: the new record starts in Shaping carrying
the note's title, tags and text, and says in its own shaping document where it came from. The note
stays, and points at what it became. The same button on an issue writes the pitch — or the task —
for it.

## Appetite is person-weeks

A size is the work **one person** would need. It is not elapsed time, and that is the distinction
people get wrong first.

Six person-weeks with one person on it, at full availability, is six weeks. Put two people on it and
it is three. Give it to one person who is half on something else and it is twelve. The cycle's
roster says what fraction each person has, and the scheduler divides the size among the people at
their own availability.

A pitch that has tasks takes its dates and its load from them, so the pitch's own appetite stays
what it always was: **the bet**, as the room agreed it, kept as written. When the tasks add up to
more than it, the pitch page says so and `openproj check` warns. Nothing refuses the save — cutting
scope or re-betting is a decision for a person, not for a validator.

## Nobody types a date

There is exactly one date to type: `assigned_on`, the earliest day the work may start. Starts, ends,
the critical path, when a person frees up, whether something runs past the end of its cycle — all
derived, from the sizes, the dependencies and the roster.

So when a date is wrong, do not go looking for the date. Change a size, change what the thing
depends on, or change an availability. There is nowhere to type an end date on purpose: a typed date
is a second copy of a fact the graph already holds, and the two disagree within the week.

Only `depends_on` is stored, and it is stored on the thing that is waiting. What a record blocks is
derived by reversing that, so the two can never contradict each other. Any kind may depend on any
kind — a task can wait on a whole pitch — and a dependency written on a pitch is what every task
inside it waits for.

## Writing one

**New record**, then choose the kind. The body starts as the team's own template, with its guidance
in comments that never render: Problem, Appetite, Solution, Rabbit holes, No-gos, For later. It is
the HackMD template you already write, so a pitch drafted in either place is the same document.

Write prose. Nothing here validates it, rewrites it, or asks for a word of it. Two headings are read
rather than judged:

- `## Progress` on a **task** is its checklist. A pitch's progress is its tasks instead, weighted by
  their sizes — so `4/7.5 wk` means four weeks of a seven-and-a-half-week bet, not four ticks out of
  seven. It is counted, never stored: a checkbox kept beside a task's status is stale the first time
  somebody closes that task from the table.
- `## For later` on a pitch is scope cut to fit the appetite. It is the only record the plan keeps of
  a bet that was trimmed, and it was invisible until it had a name.

The header lines of the HackMD template are covered without being headings: Appetite and Developers
are fields here, and Shaped by is what `owner` records now. A heading restating a field is the
two-copies-of-one-fact problem this tool exists to end.

## The statuses

Six, in the order work moves through them. What each one additionally requires is checked when you
save and by `openproj check`.

| status | what it means | what it then requires |
|---|---|---|
| `thinking` | nobody has looked at this yet, and it is where a new record opens | nothing |
| `shaping` | an idea nobody has bet on | nothing — it has no owner and no size by definition |
| `ready` | shaped, and bettable | an owner, somebody assigned, a reviewer or `review_waived`, and a size |
| `in_progress` | being built | `assigned_on`, and a reviewer who is not the owner |
| `done` | finished | at least one PR |
| `shelved` | parked | nothing — parked work is not broken work |

An issue has four of them. There is no `shaping`, because a shaped issue is a pitch — and no
`thinking`, because an issue is something somebody noticed and reported, which is already more
thought than `thinking` claims.

A note has `thinking` and `dropped` and nothing between them: a note is not work being done, it is
a thought waiting to be promoted into something that is.

A record that is missing something still saves and still loads; the page says what is wrong, beside
the record it is wrong on. A rule only *blocks* records written after that rule existed — older ones
warn instead — so a new required field does not invalidate the plan overnight.

## Editing it in git

Both directions are first class. The files are ordinary markdown, a save from the browser is one
commit, and a commit you push by hand is read on the next request. A save only rewrites the fields
whose values actually changed, so comments, key order and list style survive it.

From a clone, with no service running:

```bash
openproj check .        # every rule, exits non-zero only on blockers
openproj schedule .     # the derived dates, one line per record, with the reason
openproj render . out/  # the pages as static files
```

🤖 Written by an agent on behalf of @jcanton
