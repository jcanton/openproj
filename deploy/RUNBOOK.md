# Deploying openproj

Four steps. Everything that could be done without your credentials is done: the
push credential is implemented and proven against a private repository, the
container clones with it, and a half-configured deployment is refused at startup
rather than silently failing to push.

What is left needs your GitHub org and your Google account, and is below.

**Does it work with private repositories?** Yes, and it is now the tested path.
An installation token authenticates a clone, a fetch and a push regardless of
visibility. Verified end to end against `jcanton/icon4py-plan` while it was
private: cloned, wrote a record, pushed, `pushed: True`, the commit appeared on
GitHub authored by a person. Private also costs nothing here — the only thing the
old note claimed for public was unlimited Actions minutes, and a private repo on
the Free plan gets 2,000 a month, which a nightly check will not come close to.

______________________________________________________________________

## What is already done

- `Store` takes a credential and asks it for callbacks **per push**, not once at
  startup — an installation token lives under an hour and a server lives for
  weeks.
- `GitHubApp` signs the RS256 assertion, exchanges it for an installation token,
  and caches that token until five minutes before it expires.
- `deploy/boot.py` clones with the same credential.
- `create_app` **refuses to start** if `OPENPROJ_REMOTE` names an https remote and
  no credential is configured. Without that check the tool looks like it is
  working while every commit stays on one container's disk until it is replaced.
- `GitHubApp.from_environment` returns `None` unless all three variables are set:
  two of three is a deployment somebody stopped half way through.

______________________________________________________________________

## 1. The plan repository

Already created: **`jcanton/icon4py-plan`**, private, skeleton only.

**Branch protection is already on**, applied and checked: an ordinary fast-forward
is accepted — which is all the server ever does — and a force-push is refused with
`GH006: Protected branch update failed`. It blocks force-push and deletion, and it
applies to admins too, so it converts "history destroyed" into "revert three
commits" for everybody including you.

To re-apply it, or to apply it to another plan repository, pass the body as JSON:

```bash
gh api -X PUT repos/jcanton/icon4py-plan/branches/main/protection --input - <<'JSON'
{
  "required_status_checks": null,
  "enforce_admins": true,
  "required_pull_request_reviews": null,
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false
}
JSON
```

Not with `-f key=null`: `-f` sends the *string* `"null"` and the endpoint answers
422 with three screens of `No subschema in "anyOf" matched`. `-F` would parse the
literal, but four of these six fields have to be JSON null or false and one wrong
flag gives the same wall of text — a JSON body has one obvious reading.

Check it:

```bash
gh api repos/jcanton/icon4py-plan/branches/main/protection \
  -q '"force pushes: \(.allow_force_pushes.enabled)  deletions: \(.allow_deletions.enabled)"'
```

______________________________________________________________________

## 2. The GitHub App — the credential the server writes with

A **GitHub App**, not a PAT and not a deploy key:

|                            | scope        | tied to a person               | if it leaks                              |
| -------------------------- | ------------ | ------------------------------ | ---------------------------------------- |
| Fine-grained PAT           | repo         | **yes** — dies when they leave | valid up to 366 days                     |
| Deploy key                 | one repo     | no                             | **valid forever**, until a human notices |
| **App installation token** | **one repo** | no                             | **expires in under an hour**             |

A PAT also breaks the audit story: every commit's *committer* would trace to a
human's token, which is what the author/committer split exists to avoid.

**Once, at https://github.com/settings/apps/new** (a personal App, since the repo
is under your account; move it to the C2SM org if the tool is adopted):

1. **GitHub App name:** anything not already taken, e.g. `openproj-icon4py`. This
   is a name, not a repository — there is no repo behind it.
   **Homepage URL:** `https://github.com/jcanton/openproj`. The field is required
   and entirely cosmetic: GitHub shows it on the App's page and nothing reads it.
   Unlike the OAuth callback in step 3 it does not have to match anything, so it
   does not have to wait for the service URL to exist, and it can be edited later
   without touching the installation or the key.
   **Uncheck Webhook → Active.**
2. **Repository permissions → Contents: Read and write.** Nothing else. No
   account permissions, no org permissions.
3. Create it, then **Install App** → *Only select repositories* →
   **`icon4py-plan`** alone. This installation scope *is* the guarantee: the
   credential cannot name `icon4py` or `gt4py`, because the installation does not
   include them.
4. On the App's page, note the **App ID**. Generate a **private key** and keep the
   downloaded `.pem`.
5. Get the **installation id**:

```bash
gh api /app/installations --jq '.[] | "\(.id)  \(.account.login)"'   # needs the App JWT
# easier: open the installation's settings page, the id is the last path segment of
# https://github.com/settings/installations/<INSTALLATION_ID>
```

**Check it works before deploying anything** — this uses the code that ships, and
names any variable you left out rather than failing several frames later:

```bash
cd ~/projects/openproj
OPENPROJ_APP_ID=<app id> \
OPENPROJ_INSTALLATION_ID=<installation id> \
OPENPROJ_APP_KEY=/path/to/app-key.pem \
uv run python -c "
import os
from openproj.github import GitHubApp
absent = GitHubApp.missing(dict(os.environ))
if absent:
    raise SystemExit('not set: ' + ', '.join(absent))
print('token minted, first 8:', GitHubApp.from_environment(dict(os.environ)).token()[:8])
"
```

All three are required. The **App ID** is on the App's own settings page
(`https://github.com/settings/apps/<name>`), a six- or seven-digit number near the
top — it is *not* the Client ID beside it, and it is not the installation id.

A token printed means the App, the key and the installation all line up:

| what you see                     | what it means                                                   |
| -------------------------------- | --------------------------------------------------------------- |
| `token minted, first 8: ghs_...` | all three agree; go to step 3                                   |
| `not set: OPENPROJ_APP_ID`       | that variable is missing from the command                       |
| `401 Unauthorized`               | the key does not belong to that App, or the App ID is wrong     |
| `404 Not Found`                  | the installation id is wrong, or the App is not installed there |

______________________________________________________________________

## 3. The OAuth app — how a person signs in

Separate from step 2 and doing a different job: step 2 lets the *server* write to
one repository, this lets a *person* prove who they are.

**An OAuth App, and not the GitHub App from step 2.** The two do different jobs:
step 2's App writes to one repository and holds no user identity; this one
identifies a person and touches no repository. A GitHub App *can* authorise
users, but its user-to-server token carries the App's permissions rather than a
scope — so `/user/memberships/orgs/{org}`, which is how `identify` decides who
may write, would need an org-members permission this App deliberately does not
have.

Register at **https://github.com/settings/applications/new**.

- **Application name:** anything, e.g. `openproj`.

- **Homepage URL:** `https://github.com/jcanton/openproj`. Cosmetic, like the
  App's in step 2.

- **Redirect URIs** — the field older docs call the authorization callback URL.
  **A URL on YOUR service, not on github.com**, and the one field here that is
  load-bearing: it is where GitHub sends the browser after somebody signs in, and
  it must reach openproj. Pointed at a github.com address, sign-in lands on a 404
  and no session is ever created.

  The form takes up to ten, so **one app covers local and deployed both**. Add
  the loopback one now and the service one after the first deploy:

  ```
  http://127.0.0.1:8000/auth/callback                  a local test, today
  https://<service>.<region>.run.app/auth/callback     added after step 4
  ```

  The path is exactly `/auth/callback` — the server derives it from its own route
  (`request.url_for("callback")`), so what it sends is whatever host it is served
  on plus that path.

  **Leave wildcard matching off.** It would let a token be sent to any subdomain
  and any deeper path of a registered URI, which is a large blast radius bought
  for nothing: the two exact URIs above are all this ever needs.

- Record the **client ID** and generate a **client secret**.

**The chicken and egg is smaller than it looks.** The deployed callback needs a
URL that exists only after step 4 — but since the form takes ten, you register
the loopback one now, test sign-in today, and come back to add the `*.run.app`
one without touching the client id or secret.

**Test sign-in locally first, today.** Register the app with the loopback
callback above, then:

```bash
cd ~/projects/openproj
OPENPROJ_SECRET=$(python -c "import secrets;print(secrets.token_urlsafe(48))") \
OPENPROJ_CLIENT_ID=<client id> \
OPENPROJ_CLIENT_SECRET=<client secret> \
uv run openproj serve --repo /tmp/plan.git --auth github --org C2SM --port 8000
```

Open http://127.0.0.1:8000/ and sign in. This exercises the whole path — the
redirect, the code exchange, the `read:org` membership check — against real
GitHub, with nothing deployed. Worth doing before the meeting: it is the one part
of the stack that cannot be checked any other way.

After step 4, add the `*.run.app` URI to the same app. If you would rather not
have sign-in in the way of the first deploy at all, deploy once with
`OPENPROJ_AUTH=dev`, read the URL off the output, add the URI, and redeploy with
`OPENPROJ_AUTH=github`. The hostname is stable across revisions either way.

**The scope is `read:org` and nothing else.** Never `repo`: that would put a
write-capable GitHub token in every session. The token here establishes identity
once and is discarded.

**`OPENPROJ_ORG` decides who may write** — it is checked against org membership,
and it is not where the repo lives. Keep `C2SM` even though the repository is
under your account: the question is "is this person on the team", and the answer
still comes from C2SM.

______________________________________________________________________

## 4. Deploy

**Before anything else: the project needs billing enabled.** Cloud Run, Cloud
Build and Artifact Registry all refuse without it, free tier included — and a
billing account cannot be created from the CLI, because it takes a card. Make one
at <https://console.cloud.google.com/billing>, then:

```bash
gcloud projects create icon4py-plan-<something-unique> --name openproj
gcloud billing accounts list      # the dashed ID, 01ABCD-EF2345-6789GH
gcloud billing projects link icon4py-plan-<...> --billing-account <that ID>
gcloud billing projects describe icon4py-plan-<...>   # billingEnabled: true
```

`--billing-account` wants that ID and not your email address; given an email it
answers `INVALID_ARGUMENT: Request contains an invalid argument`, naming neither
the field nor the format.

Everything below is in **`gcloud_deploy.sh`** at the repository root. Fill in the
block marked FILL IN — the project, the two GitHub App ids, the OAuth client id —
and run it from the root:

```bash
./gcloud_deploy.sh
```

It is safe to run again: everything it creates is checked for first, so a second
run redeploys the current commit and leaves the secrets, the service account and
the registry alone. It asks for the OAuth client secret at the prompt rather than
reading it from the file, so that one value is never on disk or in your history.
It builds `./Dockerfile`, deploys, runs the four checks below, and prints
the callback URI to add to the OAuth App.

What it is doing, and why the flags are what they are:

**Secrets go in Secret Manager, not `--set-env-vars`.** A plain env var is in the
revision's metadata: readable by anyone with `roles/run.viewer`, printed by
`gcloud run services describe`, in your shell history, and in every past revision
forever. The App ID and installation id are *not* secret and are fine as env vars.

**The flags that are not decoration:**

- **`--max-instances 1` with `--concurrency 200`.** High concurrency is deliberate
  and is the opposite of the usual instinct. One instance is what makes the
  `flock` mean anything; high concurrency is what keeps the count at one.
  Lowering concurrency here does not increase safety, it destroys it. Note
  max-instances *can* be briefly exceeded, so the `flock` is the real guard.
  The budget is **open connections, not requests a second**: every page holds an
  `/api/events` stream for as long as it is open and a detail page holds a
  WebSocket beside it, so a reader costs one slot and somebody editing costs two.
  At 80 the wall stood at forty open editors, and with one instance there is
  nowhere for the overflow to go — it queues. The reasoning, and the alternative
  that was rejected, is written out beside the flags in `gcloud_deploy.sh`.
- **`--min-instances 0`.** One instance for a month is 2,592,000 instance-seconds
  against a 180,000 vCPU-second grant — **14× the free tier**.
- **Never `--no-cpu-throttling`.** Two to three orders of magnitude more expensive,
  from a flag whose name mentions neither billing nor instances. Google's
  Recommender will suggest it periodically. For a scale-to-zero service it is wrong.
- **`--cpu 1`, not less.** Below 1 vCPU Cloud Run forces concurrency to 1, which
  means one instance per in-flight request — catastrophic for a single-writer app.
- **Pin the two env-var secret versions.** With `:latest`, two instances can hold
  different session keys and a cookie minted by one is rejected by the other. The
  PEM is a file mount instead, so rotating it needs no redeploy.

**Verify, in this order.** The script runs these four itself; they are here so
they can be re-run by hand later, when something that worked stops working.

```bash
URL=$(gcloud run services describe openproj --region $REGION --format='value(status.url)')
curl -fsS $URL/api/health; echo                       # 200 {"ok":true,…,"unpushed":0}
curl -s -o /dev/null -w '%{http_code}\n' $URL/graph   # 200, not 500 — static/ resolved
curl -s -X PATCH $URL/api/record/x -d '{}'            # 401 — writes are gated
gcloud run services logs read openproj --region $REGION --limit 20 | grep cloning
```

`/api/health` and not `/healthz`: Google's frontend answers that path itself,
with its own 404 page, and the request never reaches the container — so the check
meant to prove the service is alive is the one URL that cannot reach it. The route
still answers on `/healthz` for a run behind anything else.

`/graph` is the one worth checking explicitly: `static/` is not in the wheel, and
a container that resolved it wrongly serves every other page fine and 500s only
there. The `cloning` line proves the credential worked on a cold start — if it is
missing and the service is up, it is serving an empty plan it made itself.

**This check can fail, and before this change it could not.** `ok` was the
literal `true` in the source, and for a while it was false in fact: the
concurrency audit found a container whose clone had forked from the plan,
refusing every save for its whole life, answering `ok` on all six asks and
serving every page perfectly throughout. On that condition the route now answers
**503**, which is why the line above is `curl -fsS` rather than `curl -s` — `-f`
is what turns a red service into a non-zero exit. It also suppresses the body, so
when it goes quiet, ask again without it and read `detail`.

Three of the payload's fields answer "can this service do its job":

- **`ok`** — can it write. False only for a forked history, which is permanent and
  needs a person. It is not set or cleared by anything: it is read per request
  from two refs on the container's own disk, so it goes false when the fork is
  discovered and true again when it is gone, with no restart and no flag for
  anybody to reset.
- **`unpushed`** — commits on the container's disk that origin does not have.
  Normally 0. Above zero means a push failed, usually because GitHub was away for
  a moment; it goes back to 0 at the next successful save, because a push sends
  everything that is ahead. **It is also the number of commits a restart would
  destroy**, which is why the check reports it and why *The service cannot write*
  below opens with "do not restart".
- **`detail`** — `null`, or the sentence saying what is wrong and what to do.

`/api/health` is deliberately not wired as a Cloud Run **liveness probe**, and
must not be. Cloud Run answers a failing liveness probe by replacing the
container, and replacing the container is exactly the move that clears this
condition by throwing away the unpushed commits. The deploy sets no HTTP probe;
the default startup probe is TCP on the port and stays that way.

Anything watching from outside — an uptime check, a cron, a status page — should
treat the status code as the alarm and `unpushed` as a separate, slower-tempered
one. Do not alert on `unpushed` at the first sample; alert if it has stayed above
zero for a few minutes.

______________________________________________________________________

## The service, as deployed

**<https://openproj-392761827400.europe-west1.run.app>** — project
`icon4py-plan-gcloud`, region `europe-west1`, serving
`github.com/jcanton/icon4py-plan`.

Cloud Run answers on a second, generated hostname as well, which the deploy
prints. Both are permanent and both reach the same service; the project-number
one above is the one to hand round, because the other is a token nobody can
retype. GitHub matches a redirect URI exactly, so **both** belong on the OAuth
App — otherwise sign-in works or 404s depending on which link somebody followed.

## The service cannot write

`/api/health` answers **503** with `"ok": false`, every save is refused with the
same sentence, and every page still draws perfectly. The sentence names two
shas:

> local `abc1234` and remote `def5678` have both moved; refusing to guess which
> commits to discard

This container's clone and the plan repository have forked: each holds commits
the other has never seen. `Store._absorb_remote` refuses to pick between them,
and that refusal is why this is an outage rather than a loss — every automatic
answer discards somebody's commits. Nothing is damaged. The plan repository is
fine, and no write left anything half-done: the branch is rewound before the
refusal, so the container's HEAD did not move across any of the 26 refused writes
the audit measured.

It takes two ordinary events, in order, neither of them a mistake. A save is
committed while GitHub is unreachable, so it is real, local and on no origin
(`unpushed: 1`). Then somebody pushes to the plan from a terminal, which they are
entitled to do and which the CLI does by design. Now neither history contains the
other.

**Do not restart, redeploy, or `gcloud run services update` yet.** The
container's filesystem is in memory. A replacement clones the plan afresh and
comes up green — by discarding the `unpushed` commits, which exist nowhere else.
That is the same outage wearing a different hat and it is the expensive way to
clear it. Worse, with `--min-instances 0` the instance goes away on its own after
a few quiet minutes, so this is a clock rather than a decision.

1. **Read `unpushed`.** `curl -sS $URL/api/health` — if it is 0 there is nothing
   to save and you can go straight to step 4.

2. **Get that work off the container, first.** Reads still serve the container's
   own head, so the unpushed edits are on the live site and nowhere else:

   ```bash
   curl -sS "$URL/api/index.json" > container-plan.json   # every record's frontmatter
   ```

   The shaping documents are not in that payload — open `$URL/detail/<id>` for
   each id whose frontmatter differs from the plan repository and copy the text
   out of the editing box. `container-plan.json` carries `head`, which is the sha
   in the refusal's first half; `git log` in a clone of the plan against the
   second half tells you which records to look at.

3. **Put it back through git, from a clone.** Re-apply those edits to a checkout
   of the plan repository, commit and push. Origin is then correct, and it is
   still not a descendant of the container's history — the content is recovered,
   the commits are not, and that is fine.

4. **Then replace the instance**, which is now the cheap move rather than the
   destructive one. `deploy/boot.py` clones at start, so a new container comes up
   level with origin. Leaving the service alone does it by itself — with
   `--min-instances 0` the instance goes after a few quiet minutes and the next
   request cold-starts a fresh clone. To do it on purpose rather than on a timer,
   change any env var, which is what makes Cloud Run cut a new revision:

   ```bash
   gcloud run services update openproj --region $REGION \
     --update-env-vars "OPENPROJ_RECLONED_AT=$(date -u +%FT%TZ)"
   curl -fsS $URL/api/health; echo    # 200 {"ok":true,…,"unpushed":0}
   ```

   The variable is read by nothing; its value is a note to whoever reads the
   revision list later and wonders why it exists.

Force-pushing origin back behind the fork is the other way out and it is not
available: branch protection on `main` blocks force-push and deletion for
everybody including admins (step 1). That is deliberate — it is what keeps the
worst thing this service can do to the plan "add a commit".

**What makes it less likely.** Two instances is the fastest route here: each
container clones into its own in-memory filesystem and takes its own `flock` on
its own file, so neither can see the other and both are granted. `--max-instances 1` can be briefly exceeded. If this recurs, look at `container/instance_count`
before looking at anything else.

## Day one, before anybody else uses it

- Branch protection on `icon4py-plan`'s `main` (step 1).

- A nightly `git clone --mirror` of the plan somewhere off GitHub.

- The runtime service account holding `secretAccessor` on three secrets and
  nothing else.

- **Activate the full account before 16 November 2026.** The CHF 246 of trial
  credit expires then, and Google deletes a lapsed trial's resources rather than
  charging the card. Activating means pay-as-you-go with a card on file — and
  then the always-free tier applies, which is a separate and permanent thing from
  the trial credit. The plan survives either way, since it is in git and the
  container is a cache, but the service does not.

- **Tear down what is left in `europe-west6`.** The first deployment went to
  Zurich, which is a Tier 2 pricing region and therefore possibly outside Cloud
  Run's always-free allowance; the service now runs in `europe-west1`. A deploy
  script does not delete a service behind you, so the old one is still there,
  still serving, and still on the OAuth App:

  ```bash
  gcloud run services delete openproj --region europe-west6
  gcloud artifacts repositories delete openproj --location europe-west6
  gcloud storage rm -r gs://icon4py-plan-gcloud_europe-west6_cloudbuild
  ```

  Then remove its two redirect URIs from the OAuth App, so a stale bookmark fails
  visibly rather than signing somebody into a service nobody is watching.

- `config/people.yaml` in the plan is `known_people: []`. An unlisted login is a
  warning rather than a refusal, so nothing breaks, but nothing autocompletes
  either.

- If the tool is adopted: move both repositories to `C2SM`, reinstall the App
  there, and change `OPENPROJ_REMOTE`. Nothing else changes.
