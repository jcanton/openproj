# Seed corpus — this is a DEMO, not a plan

This directory is the demo corpus shipped with `openproj`. It exists so that
`openproj check`, `openproj schedule` and `openproj render` have something to chew on that
looks like real planning data. **It is not anybody's real plan, it is not anybody's
commitment, and nobody named in it has agreed to anything.**

## Shape

Two products, two projects, eight pitches and sixteen tasks.

```
prod-0f0001  kiln4py
└── proj-000001  whole_roast
    ├── pitch-0a0001  Testing rank reproducibility  (cycle 37)
    ├── pitch-0b0001  Porting throughflow           (cycle 36)
    ├── pitch-0c0001  Porting the bed               (cycle 37)  depends on 0b0001
    ├── pitch-0d0001  Aroma transport convergence   (cycle 36)
    ├── pitch-0e0001  Burner radiation port         (cycle 37)  depends on 0a0001
    └── pitch-0f0002  Chaff optics in the burner    (still shaping, never bet)

prod-0f0002  hearth
└── proj-000002  scan_backend
    ├── pitch-0f0001  Scan operator on the GPU backend  (cycle 37)
    └── pitch-0f0003  Tap-deck rewrite                  (shelved at the cycle-37 table)

task-0f1005  Retire the f2py shim  (cycle 37, and parented on nothing on purpose)
```

Beside them: six issues and six notes. Two of the notes were thought about and dropped; three
were promoted — `note-55cc66` into `pitch-0e0001` and `note-66dd77` into a project and a
pitch, both of which say so in their own shaping documents, and `note-77ee88` into a pitch
that no longer exists, whose body argues for leaving the broken link rather than blanking the
field. The sixth is still being turned over. That is the whole shape of a note's life, in six
files.

"Today" for the demo is **2026-08-17**, the first working day of cycle 37. Both `done` records
sit in cycle 36; everything live sits in 36–37. Two live chains run past the end of the cycle
they were bet in, on purpose — a scheduler that never shows an overrun is not worth looking at.

## Everything here is invented

The domain, the people, the pull requests and the calendar are all made up. There is no
`KILN`, no `kiln4py`, no `hearth`, no Griddle programme and no Kettleworth Institute; the
handles are not anybody's handles; `kilnlab/kiln4py#2318` is not a pull request and should
not be dereferenced.

It is written the way a real plan is written, because that is the point of a demo corpus —
a body that reads as filler teaches a reader nothing about what a shaping document is for.
The engineering in it is meant to hang together: a legacy Fortran simulator of a
coffee-roasting plant is being re-implemented in Python subsystem by subsystem, nothing may
replace it until it reproduces it bit-for-bit, and the records argue about how to get there.
None of it happened.

## What is invented — do not read any of this as fact

| Field | Status |
|---|---|
| The `whole_roast` project itself | **Invented.** No such milestone has been declared. |
| Every `owner`, `assignees`, `reviewers` | **Invented.** The handles are invented too, and nobody agreed to any of this. |
| Every `person_weeks` | **Invented.** Chosen so that the plan behaves like a plan — see *Appetites and calendars* below — not measured or estimated by anyone. |
| Every `cycle` and `start_date` | **Invented.** The cycle *dates* in `config/cycles.yaml` are a plausible 2026 calendar, not anybody's. |
| Every `depends_on` edge | **Invented.** Deliberately sparse so the graph stays readable. |
| Every entry in `prs` | **Invented.** These PR numbers are plausible-looking and should not be dereferenced. |
| Every `id` | Fixed by hand so cross-references resolve. Not how ids are minted in practice. |
| `priority` | **Invented.** |
| The technical substance of every body | **Invented.** It is meant to be self-consistent, not true. |

## Appetites and calendars

An appetite is in PERSON-weeks, and the box it buys is in calendar weeks: the appetite
divided by the availability of the people named on the pitch. Its *contents* are the working
days its tasks actually occupy — which the scheduler already knows, because it books people,
and somebody holding two tasks queues behind themselves. Those two numbers are what the
appetite cell compares and what `openproj check` warns on, and every number below was chosen
so that the comparison says something true about these files.

Three consequences the corpus is built to show, because all three surprise people:

- **Naming another person on a pitch makes its box smaller, not larger.** Two people on a
  six-week bet have bought three calendar weeks. So the names on a pitch have to be the people
  who actually hold its tasks — `pitch-0e0001` names Hoopoe and Kittiwake, and both of them are
  on both burner tasks — or the box is being measured over somebody who is not working on it.
- **Chained tasks cannot spend two people at once.** `pitch-0b0001` bets 7.5 weeks across two
  people and its two halves run one after the other, so one of the two is always idle, and the
  bet overruns however well each half was estimated on its own.
- **A gap is not charged.** `pitch-0d0001` runs from June to the end of August, and most of that
  stretch is days on which nobody worked on it. Its contents are the seventeen working days its
  three tasks occupy, not the nine weeks between the first day and the last.

## Configuration

`config/cycles.yaml`, `config/holidays.yaml` and `config/defaults.yaml` are merged into one
`Config` by `openproj.model.load_config`. The holidays are an ordinary European public-holiday
year plus a plant shutdown between Christmas and New Year; the cycle calendar is synthetic.

Every record is `created_schema_version: 2`, so a rule stamped above 2 can only ever warn here
rather than block (spec 5.4). The version-5 rule that a `done` record must write down the date
it ended is the live example: it blocks a record created today and would only warn at these
files, which is why both `done` tasks carry an `end_date` outright instead of leaning on the
demotion. `config/defaults.yaml` says the same thing from the other side.

The corpus is expected to pass `uv run openproj check seed --today 2026-08-17` with **zero
blockers and six warnings**, and every one of the six is left in on purpose:

| Warning | Why it is here |
|---|---|
| `note-55cc66`: `dabchickly` is not in `config/people.yaml` | The roster is kept by hand and is always slightly behind reality. One name off it is what gives that rule a real document to fire on. |
| `note-77ee88`: `became pitch-000000, which is missing` | The note argues in its own body for leaving the broken link rather than blanking the field, because the promotion did happen. |
| `pitch-0b0001`: its tasks need 4.8 weeks, more than the 3.8 the bet buys at 2 | The air-side port took twenty-three working days against the twenty its four-week appetite bought, and the bed-side half is chained behind it, so the second of the two people is idle for most of the bet. |
| `pitch-0d0001`: its tasks need 3.4 weeks, more than the 3.0 the bet buys at 2 | Six person-weeks across two people is three calendar weeks. The convergence study runs behind the halo exchange rather than beside it, so the pitch occupies three and a half. |
| `task-0f1004`: blocked by `task-0f1003`, which is shelved | The writer was carried into cycle 37 and the reader was left on the shelf. The task's own body argues that this is the honest state and not a thing to tidy away. |
| `task-0f1005`: a task should have a parent | Retiring the f2py shim belongs to no pitch and the betting table has no row for that; `issue-c9d0e1` is the complaint about the table, kept separate from the chore. |

The two appetite warnings are the only checks on this list whose output is a conversation
rather than a correction, and a demo in which nothing ever exceeds its appetite teaches that
the number cannot be exceeded. They are both cycle-36 bets, which is why those two carried;
the four cycle-37 bets all fit the calendar their appetites bought, which is what a plan looks
like on the first morning of a cycle.

Only what is bet carries a `cycle:`: the six pitches that were bet, plus `task-0f1005`, which
was bet on its own because it hangs under no pitch. Every other task takes the cycle of the
pitch it belongs to, and the products, the projects, the pitch still being shaped and the
shelved one have none at all.

## If you fork this

Replace every row of the invented table above with something a human has agreed to, and
delete this file's warnings once they are no longer true. A demo fixture that quietly
graduates into a plan is how a tracker starts lying.
