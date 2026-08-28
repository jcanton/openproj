# Quickstart

The plan is at <https://openproj-392761827400.europe-west1.run.app>. Sign in with GitHub; if you are
in C2SM you can write. There is no database behind it — every page is drawn from markdown files in
`github.com/jcanton/icon4py-plan`, and every save is a commit there with your name on it.

**Records** is the landing page: every record in the plan, one line each, newest edit first, with the
search box above it. The tabs are the plan seen several ways — **Table** is where most people live,
**Graph** is the dependency diagram, **Timeline** the Gantt, **Cycles** one page per cycle with what
was bet in it and who has room, **People** who is on what. Clicking any record opens its own page,
which is where you edit it. Filters live in the URL, so the view in front of you is a link, and there
are no saved views to manage.

The plan is empty today, on purpose. Start a cycle from **Cycles**, then write the first pitch.

## The three things

A **pitch** is a bet: a problem, a solution shaped to fit an appetite, and the argument for spending
the time on it. It is one file — the fields at the top, the shaping document underneath — so the
thing being bet on and the reasoning never drift apart.

A **task** is a piece of a pitch, with its own size and its own people, taking its cycle from the
pitch it belongs to. A task with no parent is a chore nobody pitched, and is bettable in its own
right.

A **cycle** is the block of weeks the team bets in. It stores two dates, both of them meetings:
`starts_on` is the betting table and the first day of build, `reviews_on` is the review. Where build
ends, how many working weeks that is once the holidays are out, and where cool-down ends are all
derived from those two and from each person's availability.

Three more you will meet. A **project** groups pitches into a milestone: no size, never bet, its span
the rollup of what is inside it. An **issue** is somewhere to put something existing that is broken —
most issues will never be worked on, which is exactly what they are for. A **note** is an idea before
anybody knows what it is: no appetite, no owner, no size, and on no view of the plan. **Promote**
turns either into a project, a pitch or a task in one commit; the source stays, and points at what it
became.

## Appetite is person-weeks

A size is the work **one person** would need. It is not elapsed time, and that is the distinction
people get wrong first: six person-weeks is six weeks for one person at full availability, three for
two people, twelve for one person who is half on something else. The cycle's roster says what
fraction each person has.

A pitch that has tasks takes its dates and its load from them, so the pitch's own appetite stays
**the bet**, as the room agreed it. What the bet buys is a number of *calendar* weeks — eight
person-weeks with two people on it is four weeks — and that is the box the tasks have to fit in.
When the tasks as they are actually staffed need longer, the page says so and `openproj check`
warns. Who is on them is what decides it: a four-week task and a half-week task are four and a half
weeks if one person holds both and four if they run side by side. Nothing refuses the save, because
cutting scope, re-betting, and putting another person on it are all decisions for a person.

## Two dates, and both of them happened

The only dates anybody types are the two ends of work that is real. `start_date` is the day the work
began: on something that has not begun it is a day named in advance and has to still be ahead — a
start date already in the past is refused before `in_progress` — while from `in_progress` on a past
one is expected, because "I started this on Monday and it is now Wednesday" is the ordinary case and
the only thing the field can mean once work is under way. `end_date` is the day it finished, and
marking something Done asks for it with today already filled in.

**No forecast is ever stored.** The end a plan shows for work still in flight is derived, and it has
to be: it moves when a blocker slips, when somebody fills up, when a cycle's review date is set, and
at midnight. Written into the file it would be the one number nothing else agreed with. A recorded
end is the opposite — it is what happened, it never moves again, and it is the only reason the plan
can say afterwards whether a bet landed inside its cycle.

Everything else is derived: starts, ends, the critical path, when a person frees up, whether
something runs past its cycle — all of it from the sizes, the dependencies and the roster. So when a
date is wrong, do not go looking for the date: change a size, change what the thing depends on, or
change an availability.

A date wildly outside the cycles the plan has dated is refused when you type it and reported by
`openproj check` if it got in another way. A year typed wrong parses perfectly and then belongs to no
cycle at all, so the record silently stops counting towards anybody's capacity — which is the one
kind of wrong date that leaves nothing to chase.

Only `depends_on` is stored, and on the thing that is waiting; what a record blocks is derived by
reversing it, so the two can never contradict each other. Any kind may depend on any kind — a task
can wait on a whole pitch — and a dependency written on a pitch is what every task inside it waits
for.

## Writing one

**New record**, then choose the kind. The body starts as the team's own template, with its guidance
in comments that never render: Problem, Appetite, Solution, Rabbit holes, No-gos, For later. It is
the HackMD template you already write, so a pitch drafted in either place is the same document.

Write prose; nothing validates it. Two headings are read rather than judged:

- `## Progress` on a **task** is its checklist. A pitch's progress is its tasks instead, weighted by
  their sizes — so `4/7.5 wk` means four weeks of a seven-and-a-half-week bet, not four ticks out of
  seven.
- `## For later` on a pitch is scope cut to fit the appetite. It is the only record the plan keeps of
  a bet that was trimmed, and it was invisible until it had a name.

## The statuses

Six, in the order work moves through them. What each one additionally requires is checked when you
save and by `openproj check`.

| status        | what it means                                                     | what it then requires                                                  |
| ------------- | ----------------------------------------------------------------- | ---------------------------------------------------------------------- |
| `thinking`    | nobody has looked at this yet, and it is where a new record opens | nothing                                                                |
| `shaping`     | an idea nobody has bet on                                         | nothing — it has no owner and no size by definition                    |
| `ready`       | shaped, and bettable                                              | an owner, somebody assigned, a reviewer or `review_waived`, and a size |
| `in_progress` | being built                                                       | `start_date`, a size, and a reviewer who is not the owner              |
| `done`        | finished                                                          | at least one PR, and `end_date` — the day it finished                  |
| `shelved`     | parked                                                            | nothing — parked work is not broken work                               |

An issue has four of them: no `shaping`, because a shaped issue is a pitch, and no `thinking`,
because an issue is something somebody reported. A note has `thinking` and `dropped` and nothing
between them.

A record that is missing something still saves and still loads; the page says what is wrong, beside
the record it is wrong on. A rule only *blocks* records written after that rule existed — older ones
warn instead.

## Editing a record

Clicking a record opens its page, and that page is the editor. It lands on the reading view; the
writing box and a live preview sit side by side, and the split between them is draggable. The fields
at the top are the frontmatter and the box below is the shaping document — one form, one **Save**,
one commit. **Reset** puts everything back to what was on the page when you arrived and leaves you
in the editor.

The status control is the hill beside the title: drag the ball to the stop you want. Changing a
record's kind is the chip beside it — a pitch that turns out to be a task does not have to be
rewritten. **Promote** on an issue or a note writes the pitch, the task or the project it becomes,
in the same commit that marks the source. **Delete** asks first.

The button beside the image button opens a drawing canvas; what you draw is saved as a PNG in the
plan repository and referenced from the body, so a sketch on a pitch is versioned with the pitch.

Several people can have the same document open and type in it at once. It still ends as one commit,
authored by whoever wrote the most of it, with a `Co-authored-by:` for everybody else. If somebody
committed to the same record while you were writing, the page says so in one line and keeps your
draft rather than throwing it away.

## Editing it in git

Both directions are first class. The files are ordinary markdown, a save from the browser is one
commit, and a commit you push by hand is picked up within a minute of somebody using the service. A
save only rewrites the fields whose values changed, so comments, key order and list style survive it.
From a clone, with no service running:

```bash
openproj check .        # every rule, exits non-zero only on blockers
openproj schedule .     # the derived dates, one line per record, with the reason
openproj render . out/  # the pages as static files
```

`openproj render` writes the whole plan as static files, which is the copy to keep when there is no
service left to serve it. To run the editable server against a plan of your own, point it at a bare
clone:

```bash
git clone --bare https://github.com/jcanton/icon4py-plan.git plan.git
openproj serve --repo plan.git --auth dev
```

`--auth dev` skips sign-in and is for a local run only. To see the tool with no plan to point it at,
`openproj demo` serves a bundled corpus offline, in a temporary directory it builds for itself.

## Writing a record from a terminal

`openproj new` is the other door into the plan, and the one to use when there is no browser — a
script, a CI job, an agent working in the codebase the plan is about.

```bash
openproj new issue . --title "Quadratic extrapolation lives in two places" \
    --tag dycore --as jcanton --commit
```

It mints the id, files the record in its kind's directory, starts the body from that kind's shaping
template, and stamps the day and the schema version the repository is on. Then it holds the record to
every rule `check` holds it to, *before* anything reaches the disk: a blocker means nothing is
written at all, so there is never a bad file to `rm` your way out of. A warning is printed and the
record is written anyway, which is the case this exists for:

```
warning: issue-b71a56: prs: an issue is never scheduled, so its prs is not read
```

`prs` is a real field on the model, so nothing refuses it — it is simply never read on a record that
is never scheduled, and that is the kind of thing you cannot see by copying the record next door. The
six things `new` does not ask you for are the six that somebody copying gets wrong: the id, the
directory, the body template, the opening status, the date, and the schema version.

`--set field=value` writes any other field, repeatably, with the value read as YAML — `--set person_weeks=1.5` is a number, `--set review_waived=true` is a boolean, and a field that holds a list
takes one `--set` per entry. `--body-file` replaces the template and `-` reads the body from stdin.
`--json` prints the id and the path, for a caller that is not a person. Without `--commit` it writes
the file and prints the git commands; with it, the next command is `git push` and nothing else.

Nothing has to be installed first:

```bash
uvx openproj new issue . --title "…"                              # from PyPI
uvx --from git+https://github.com/jcanton/openproj openproj new …  # straight from this repository
```

🤖 Written by an agent on behalf of @jcanton
