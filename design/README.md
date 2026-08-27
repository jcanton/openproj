# Design records

Not documentation. `docs/` is the user guide — what the app and the CLI are and how to find your way
around them — and everything here is the other thing: how a subsystem came to be the way it is, what
was measured, and what was refused. It is written for somebody with a checkout who is about to change
that subsystem, and it is kept because a decision whose reason is lost is a decision that gets
re-opened.

None of it reaches the running service. `docs/` is copied into the container because the Help page
reads those files off the disk; this directory is excluded in `.gcloudignore` and is not copied by
the `Dockerfile`.

| file                 | what it records                                                                           |
| -------------------- | ----------------------------------------------------------------------------------------- |
| `EDITOR.md`          | the library audit behind the markdown editor, and the dated decisions that followed it    |
| `drawings.md`        | the drawing subsystem: the spike, the five helpers, and why a PNG never touches the merge |
| `deferred-push.md`   | why a commit lands locally before it goes out, and what the page says while it has not    |
| `hackmd-observed.md` | what the team's HackMD actually contained, measured before this tool existed              |
| `QUEUE.md`           | the work queue: what is next, and what was accepted as a gap                              |
| `probes/`            | measurements — CI timings, load runs, the concurrency audit                               |

`AGENTS.md` is the entry point for changing this code, and holds the rules that are still binding.
This directory is the reasoning underneath them.

🤖 Written by an agent on behalf of @jcanton
