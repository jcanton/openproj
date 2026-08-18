# openproj

Planning for the icon4py team. The plan is markdown files in a git repository — one file per record,
the fields in frontmatter and the shaping document as the body. The bet and the argument for it are
one file, which is the whole idea: there is no shape doc to link to, nothing to keep in step with
anything else, and `git log` on a plan is a record of decisions rather than of edits.

Nobody types a date. A person writes a size in person-weeks and one `assigned_on` — the earliest day
the work may start. Start dates, end dates, the critical path and every rollup are derived from
that, from the dependency graph, and from who is on the work at what availability. When a date looks
wrong, the thing to change is a size, a dependency or an availability.

## The live one

<https://openproj-392761827400.europe-west1.run.app>, serving `github.com/jcanton/icon4py-plan`.

Sign in with GitHub; membership of C2SM is what decides who may write. A save is one commit on the
plan repository with you as its author, and a file you change by hand and push is read on the next
request. Both directions are first class on purpose — a tool that owns your files is a tool you
cannot leave.

The tabs are the same records seen several ways: **Table** is the one people live in, **Graph** is
the dependency diagram, **Timeline** the derived Gantt, **Cycles** one page per cycle with its bets
and its capacity, **People** who is on what and who is full, **Issues** the pile of things somebody
noticed, **Notes** the pile of things somebody is still thinking about. Every filter is in the URL,
so a view is a link.

The last two are inboxes rather than views of the plan, and they are two because they answer
different questions: an issue is "we found something existing that is broken", a note is "we are
thinking of creating something that does not exist and our ideas are confused". Neither carries an
appetite or an owner and neither appears on the table, the graph or the timeline. **Promote** is
what stops either from being an inbox nobody empties: it turns a note into a project, a pitch or a
task — and an issue into a pitch — in one commit, and the new record says in its own shaping
document where it came from.

`docs/quickstart.md` is the five-minute version for somebody opening it for the first time.

**The tool and the plan are two repositories** — this one holds code, tests and fixtures; the plan
holds markdown and nothing else. A plan commit must not run the tool's CI, and the credential the
server writes with must be structurally incapable of touching source. The seam is the `--repo`
argument, so pointing a deployment at a different plan is a flag rather than a fork.

## Locally

`seed/` is a demo corpus and nobody's plan; `seed/README.md` says which parts of it are invented.

```bash
uv sync
uv run openproj render seed out --today 2026-08-17
open out/index.html
```

That writes the pages as static files, which is also the answer to what happens if the service goes
away: the plan stays readable, and stays checkable, from any clone.

```bash
uv run openproj check seed        # every rule, exits non-zero only on blockers
uv run openproj schedule seed     # the derived dates, one line per record, with the reason
```

`check` is the load-bearing one, and it is deliberately quiet about warnings. A warning that fails
the build is a rule that gets reverted rather than adopted, so only a blocker is worth gating a
merge on. All three take a plan repository as their first argument; `schedule` and `render` also
take `--today`, because half of what they print depends on which day it is.

## Where to read next

| | |
|---|---|
| `docs/quickstart.md` | day one — what a pitch, a task and a cycle are, and how to write one |
| `docs/data-model.md` | the fields, the rules that are enforced, and what each is load-bearing for |
| `docs/architecture.md` | the pages, the two repositories, the layout of the code |
| `docs/shape-up.md` | how this maps to what the team kept in HackMD, and where it departs from the book |
| `AGENTS.md` | the invariants, how to write code here, and how to find the bug that is already here |
| `deploy/RUNBOOK.md` | the deployment — credentials, the Cloud Run flags, and what is left to do |
| `docs/superpowers/specs/` | the design records: appetite, cycles, and what was tailored to the team |

## Status

Deployed, and editable in the browser by anybody in C2SM. The plan repository holds its
configuration and no records yet, on purpose: it fills up from what the team bets on rather than
from a seeded example nobody wrote.

🤖 Written by an agent on behalf of @jcanton
