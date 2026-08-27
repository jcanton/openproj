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

The landing page is **Records** — every record in the plan, one line each, sorted by last edited,
with the search box above it. It is how you get back to the thing you were writing yesterday. The
PM work happens in the tabs, which are the same records seen several ways: **Table** is the one
people live in, **Graph** is the dependency diagram, where dependencies are drawn and removed in a
mode of its own, **Timeline** the derived Gantt, **Cycles** one page per cycle with its bets and
its capacity, **People** who is on what and who is full, and **Help**, which is this file and the four
documents below it, drawn on one page inside the app. Every filter is in the URL, so a view is a
link, and a field can be asked for more than one value at a time — two statuses means either of
them. Pointing at a row, a node or a bar opens the same card in all three: what the record is, who
is on it, when it runs, and its shaping document under a rule.

The search box is a small language, and it is the same language on the server and in the browser:
bare words match a record's fields — its id, title, tags, PR references and the people named on it,
never the shaping document — and `field:value` asks one field. `and`, `or`, `not` and brackets do
what they look like, two terms side by side mean both, and `tag:gpu and tag:distributed` is the
query the dropdowns cannot express, because a menu means OR within a field. A field this plan has
not got matches nothing rather than everything, and a query that cannot be read says what is wrong
with it and matches nothing while you finish typing.

The two inboxes — issues and notes — are records like any other now, with the same page and the
same editor, and they are two because they answer different questions: an issue is "we found
something existing that is broken", a note is "we are thinking of creating something that does not
exist and our ideas are confused". Neither carries an appetite or an owner and neither appears on
the table, the graph or the timeline; they live on Records and on their own pages. **Promote** is
what stops either from being an inbox nobody empties: it turns a note into a project, a pitch or a
task, and an issue into a pitch or a task — in one commit, and the new record says in its own
shaping document where it came from.

`docs/quickstart.md` is the five-minute version for somebody opening it for the first time.

**The tool and the plan are two repositories** — this one holds code, tests and fixtures; the plan
holds markdown and nothing else. A plan commit must not run the tool's CI, and the credential the
server writes with must be structurally incapable of touching source. The seam is the `--repo`
argument, so pointing a deployment at a different plan is a flag rather than a fork.

## Locally

```bash
uv sync
uv run openproj demo
```

That is the whole of it. `demo` builds a plan repository out of the bundled demo corpus in a
temporary directory, serves it with sign-in switched off, and prints the URL. No network, no
credentials, and nothing to clean up: the repository is fresh every run and goes when you stop the
server, so every button in it is safe to press. It draws the plan around the corpus's own "today"
rather than around yours — `--today` moves it — and signs you in as somebody the corpus names, so
the parts of the tool that are about a person are on screen too.

`seed/` is that corpus and nobody's plan; `seed/README.md` says which parts of it are invented.
Pointing the server at a real plan is `openproj serve --repo <a bare clone>`, and
`docs/architecture.md` has the recipe.

The same corpus, as static files:

```bash
uv run openproj render seed out --today 2026-08-17
open out/index.html
```

That is also the answer to what happens if the service goes away: the plan stays readable, and
stays checkable, from any clone.

```bash
uv run openproj check seed        # every rule, exits non-zero only on blockers
uv run openproj schedule seed     # the derived dates, one line per record, with the reason
```

`check` is the load-bearing one, and it is deliberately quiet about warnings. A warning that fails
the build is a rule that gets reverted rather than adopted, so only a blocker is worth gating a
merge on. All three take a plan repository as their first argument; `schedule` and `render` also
take `--today`, because half of what they print depends on which day it is.

## From anywhere, with nothing installed

Every command above also runs straight out of the published package, which is the form to reach for
from a script, a CI job, or a coding agent working in the codebase a plan is about:

```bash
uvx openproj new issue . --title "Quadratic extrapolation lives in two places" --as jcanton
uvx --from git+https://github.com/jcanton/openproj openproj check .   # unreleased main
```

`new` is the write path for somebody without a browser. It mints the id, files the record under its
kind's directory, starts the body from that kind's template, stamps the date and the schema version
the repository is on — and holds the record to every rule `check` holds it to before anything reaches
the disk, so a record that would fail the gate never becomes a file. `docs/quickstart.md` has the
flags and the reasoning.

## Where to read next

|                        |                                                                                                  |
| ---------------------- | ------------------------------------------------------------------------------------------------ |
| `docs/quickstart.md`   | day one — what a pitch, a task and a cycle are, and how to write one                             |
| `docs/data-model.md`   | one record type and six kinds, what the index derives, and what promotes into what               |
| `docs/architecture.md` | the pages, the two repositories, the layout of the code                                          |
| `docs/shape-up.md`     | how this maps to what the team kept in HackMD, and where it departs from the book                |
| `AGENTS.md`            | the invariants, how to write code here, and how to find the bug that is already here             |
| `design/`              | design records — why a subsystem is the way it is, and what was measured. Not user documentation |
| `deploy/RUNBOOK.md`    | the deployment — credentials, the Cloud Run flags, and what is left to do                        |

The first four of those, and this file, are also the app's **Help** page — the same bytes, read
off the same files, so there is one copy of every sentence and nothing to keep in step. The last two
are for somebody with a checkout and stay in the repository.

## Status

Deployed, and editable in the browser by anybody in C2SM. The plan repository holds its
configuration and no records yet, on purpose: it fills up from what the team bets on rather than
from a seeded example nobody wrote.

🤖 Written by an agent on behalf of @jcanton
