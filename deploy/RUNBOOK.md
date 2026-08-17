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

---

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

---

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

---

## 2. The GitHub App — the credential the server writes with

A **GitHub App**, not a PAT and not a deploy key:

| | scope | tied to a person | if it leaks |
|---|---|---|---|
| Fine-grained PAT | repo | **yes** — dies when they leave | valid up to 366 days |
| Deploy key | one repo | no | **valid forever**, until a human notices |
| **App installation token** | **one repo** | no | **expires in under an hour** |

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

| what you see | what it means |
|---|---|
| `token minted, first 8: ghs_...` | all three agree; go to step 3 |
| `not set: OPENPROJ_APP_ID` | that variable is missing from the command |
| `401 Unauthorized` | the key does not belong to that App, or the App ID is wrong |
| `404 Not Found` | the installation id is wrong, or the App is not installed there |

---

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

---

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
It builds `deploy/Dockerfile`, deploys, runs the four checks below, and prints
the callback URI to add to the OAuth App.

What it is doing, and why the flags are what they are:

**Secrets go in Secret Manager, not `--set-env-vars`.** A plain env var is in the
revision's metadata: readable by anyone with `roles/run.viewer`, printed by
`gcloud run services describe`, in your shell history, and in every past revision
forever. The App ID and installation id are *not* secret and are fine as env vars.

**The flags that are not decoration:**

- **`--max-instances 1` with `--concurrency 80`.** High concurrency is deliberate
  and is the opposite of the usual instinct. One instance is what makes the
  `flock` mean anything; high concurrency is what keeps the count at one.
  Lowering concurrency here does not increase safety, it destroys it. Note
  max-instances *can* be briefly exceeded, so the `flock` is the real guard.
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
curl -s $URL/healthz                                  # {"ok":true,"head":"..."}
curl -s -o /dev/null -w '%{http_code}\n' $URL/graph   # 200, not 500 — static/ resolved
curl -s -X PATCH $URL/api/entity/x -d '{}'            # 401 — writes are gated
gcloud run services logs read openproj --region $REGION --limit 20 | grep cloning
```

`/graph` is the one worth checking explicitly: `static/` is not in the wheel, and
a container that resolved it wrongly serves every other page fine and 500s only
there. The `cloning` line proves the credential worked on a cold start — if it is
missing and the service is up, it is serving an empty plan it made itself.

---

## Day one, before anybody else uses it

- Branch protection on `icon4py-plan`'s `main` (step 1).
- A nightly `git clone --mirror` of the plan somewhere off GitHub.
- The runtime service account holding `secretAccessor` on three secrets and
  nothing else.
- This file updated with the real service URL, so the next person does not have
  to reconstruct it.
- If the tool is adopted: move both repositories to `C2SM`, reinstall the App
  there, and change `OPENPROJ_REMOTE`. Nothing else changes.
