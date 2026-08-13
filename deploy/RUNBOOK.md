# Deploying openproj

Four steps, in this order. Step 3 depends on the URL that step 4 creates, so the
last two are done twice — that circularity is real and is called out where it bites.

**One gap before any of this is useful:** the push credential is not wired into the
code yet. `Store.push()` calls libgit2 with no callbacks, which works for a
`file://` remote and for anonymous fetch, and fails against an authenticated
GitHub remote. See [§0](#0-the-remaining-code-gap). Everything else below is ready.

---

## 0. The remaining code gap

`src/openproj/store.py` pushes with `callbacks=None`. For GitHub it needs a
`pygit2.RemoteCallbacks` supplying `UserPass("x-access-token", <installation token>)`,
and something to mint that token. The place is `Store._finish`, and the shape is:

```python
def _credentials(self) -> pygit2.RemoteCallbacks | None:
    """A GitHub App installation token, minted per push.

    Never held long enough to expire: one is minted per push and cached only
    inside a safety margin, so "the token expired mid-write" cannot happen.
    """
```

Minting is two API calls (~300–400 ms): sign a short-lived RS256 JWT with the App's
private key, then `POST /app/installations/{id}/access_tokens`. The token lives one
hour and is scoped to whatever the *installation* covers — which is the whole point
of step 2.

Until that lands, run against a local bare repo (`--repo /srv/plan.git` with no
remote) and the tool works exactly as it does now, minus durability.

---

## 1. Create the plan repository

The plan is a **different repository from this one**. See the README's "Two
repositories" — a plan commit must not run the tool's CI, and the write credential
must be structurally incapable of touching source.

```bash
gh repo create C2SM/icon4py-plan --public \
  --description "openproj plan data for icon4py. Edited at <service URL>."

# Seed it from the demo corpus, or from nothing and create entities in the UI.
git init -b main /tmp/plan && cp -R seed/. /tmp/plan/
cd /tmp/plan && rm -f README.md
git add -A && git commit -m "Seed the plan" && \
  git remote add origin git@github.com:C2SM/icon4py-plan.git && git push -u origin main
```

**Public**, unless you decide otherwise: reads are public by design, `derived/` renders
on GitHub as a fallback UI when the service is down, and a public repo gets unlimited
free Actions minutes. The only thing that argued for private was a per-person
availability roster, and the design uses a single global figure instead.

**Then turn on branch protection** for `main`: block force-push and deletion. The
server only ever fast-forwards, so this costs nothing and converts "history
destroyed" into "revert three commits". Do it before the service can write, not after.

---

## 2. Mint a push credential scoped to that repo alone

Use a **GitHub App**, not a PAT and not a deploy key. The ranking is not close:

| | scope | tied to a person | if it leaks |
|---|---|---|---|
| Fine-grained PAT | repo | **yes** — dies when they leave | valid up to 366 days |
| Deploy key | one repo | no | **valid forever**, until a human notices |
| **App installation token** | **one repo** | no | **expires in under an hour** |

The PAT also breaks the audit story: every commit's *committer* would trace to a
human's token, which is exactly what the author/committer split exists to avoid.

**Once, in the C2SM org:**

1. Create a GitHub App. Repository permission **Contents: Read and write**, and
   nothing else. No org permissions, no account permissions, no webhook.
2. Install it on **exactly one repository** — `C2SM/icon4py-plan`. Not "all
   repositories". This installation scope *is* the guarantee: the credential cannot
   name `icon4py` or `gt4py`, because the installation does not include them.
3. Generate a private key (PEM). Note the App's **client ID**, and get the
   **installation ID** from `gh api /app/installations`.
4. Store the PEM in Secret Manager. The client ID and installation ID are not
   secret and go in plain env vars.

```bash
gcloud secrets create openproj-app-key   --data-file=app-key.pem
gcloud secrets create openproj-session-secret        # python -c "import secrets;print(secrets.token_urlsafe(48))"
gcloud secrets create openproj-oauth-client-secret   # from step 3
```

**Why Secret Manager and not `--set-env-vars`:** a plain env var is stored in the
revision's metadata, so it is readable by anyone with `roles/run.viewer`, appears in
`gcloud run services describe`, lands in shell history, and persists in every past
revision forever.

**A dedicated runtime service account**, because the Compute Engine default one may
carry Editor:

```bash
gcloud iam service-accounts create openproj-run --display-name "openproj Cloud Run runtime"
for S in openproj-session-secret openproj-oauth-client-secret openproj-app-key; do
  gcloud secrets add-iam-policy-binding "$S" \
    --member "serviceAccount:openproj-run@${PROJECT}.iam.gserviceaccount.com" \
    --role roles/secretmanager.secretAccessor
done
```

That account needs **no other GCP permission**. It reads three secrets and talks to
github.com. That is the entire surface.

---

## 3. Register the OAuth app for sign-in

Separate from the GitHub App in step 2, and doing a different job: step 2 lets the
*server* write to one repository; this lets a *person* prove who they are.

In the C2SM org, create an **OAuth App**:

- **Homepage URL:** the service URL.
- **Authorization callback URL:** `<service URL>/auth/callback` — exactly, including
  the scheme. GitHub matches the host (excluding subdomains) and port exactly, and
  requires the path to be a subdirectory of the registered callback.
- Record the **client ID** (not secret) and generate a **client secret**
  (`gcloud secrets versions add openproj-oauth-client-secret --data-file=-`).

**The scope is `read:org` and nothing else.** Never `repo`: a `repo`-scoped login
would put ~30 write-capable GitHub tokens in the session store. The token here
establishes identity once and is discarded — it is never stored in the session and
never used to push.

**The circularity:** the callback needs the service URL, and the service URL exists
only after the first deploy. So: deploy once (step 4) with `OPENPROJ_AUTH=dev` and no
OAuth values, read the `*.run.app` URL off the deploy output, register the app
against it, then redeploy with `OPENPROJ_AUTH=github`. The `*.run.app` hostname is
stable across revisions, so this is a one-time dance.

**For local testing**, register a second OAuth app with callback
`http://127.0.0.1:8000/auth/callback` — GitHub special-cases loopback, so any port
matches a registered `127.0.0.1` callback.

---

## 4. Deploy

```bash
PROJECT=<your gcp project>
REGION=europe-west1
SHA=$(git rev-parse --short HEAD)

gcloud artifacts repositories create openproj --repository-format=docker --location=$REGION
gcloud builds submit --tag $REGION-docker.pkg.dev/$PROJECT/openproj/openproj:$SHA

gcloud run deploy openproj \
  --image $REGION-docker.pkg.dev/$PROJECT/openproj/openproj:$SHA \
  --region $REGION \
  --allow-unauthenticated \
  --service-account openproj-run@$PROJECT.iam.gserviceaccount.com \
  --cpu 1 --memory 512Mi \
  --cpu-throttling --cpu-boost \
  --concurrency 80 \
  --min-instances 0 --max-instances 1 \
  --timeout 300 \
  --set-env-vars OPENPROJ_AUTH=github,OPENPROJ_ORG=C2SM \
  --set-env-vars OPENPROJ_REMOTE=https://github.com/C2SM/icon4py-plan.git \
  --set-env-vars OPENPROJ_CLIENT_ID=<oauth client id> \
  --set-secrets OPENPROJ_SECRET=openproj-session-secret:1 \
  --set-secrets OPENPROJ_CLIENT_SECRET=openproj-oauth-client-secret:1 \
  --set-secrets /secrets/app-key.pem=openproj-app-key:latest
```

**The flags that are not decoration:**

- **`--max-instances 1` and `--concurrency 80`.** High concurrency is deliberate and
  is the opposite of the usual instinct for a single-writer app. One instance is what
  makes the `flock` mean anything; high concurrency is what keeps the instance count
  at one. Lowering concurrency here does not increase safety — it destroys it.
  Note that max-instances *"can be exceeded for a brief period"*, so the `flock` is
  the real guard and this only makes the second instance unlikely.
- **`--min-instances 0`.** One instance running for a month is 2,592,000
  instance-seconds against a 180,000 vCPU-second grant — **14× the free tier**. State
  the zero explicitly so nobody "optimises" it later.
- **Never `--no-cpu-throttling`.** It is a two-to-three-order-of-magnitude cost
  increase from a flag whose name mentions neither billing nor instances. Google's
  Recommender will periodically suggest it. For a scale-to-zero service it is wrong.
- **`--cpu 1`, not less.** Below 1 vCPU, Cloud Run forces concurrency to 1, which
  would mean one instance per in-flight request — catastrophic for a single-writer app.
- **Pin secret versions** for the two env-var secrets. With `:latest`, two concurrent
  instances can hold different session keys, and a cookie minted by one is rejected
  by the other. The PEM is a volume mount instead, so rotation lands without a
  redeploy.

**Verify, in this order:**

```bash
curl -s $URL/healthz                     # {"ok":true,"head":"..."}
curl -s -o /dev/null -w '%{http_code}\n' $URL/graph   # 200, not 500 — proves static/ resolved
curl -s -X PATCH $URL/api/entity/<id> -d '{}'         # 401 — writes are gated
```

`/graph` is the one worth checking explicitly: `static/` is not in the wheel, and a
container that resolved it wrongly serves every other page fine and 500s only there.

---

## Day one, before anybody else uses it

- Three org owners on `C2SM`, across at least two institutions.
- Branch protection on the plan repo's `main`.
- A nightly `git clone --mirror` of the plan somewhere off GitHub.
- The runtime service account holding `secretAccessor` on three secrets and nothing else.
- This file updated with the real service URL, so the next person does not have to
  reconstruct it.
