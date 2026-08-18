#!/usr/bin/env bash
#
# Deploy openproj to Cloud Run. Step 4 of deploy/RUNBOOK.md, as one script.
#
# Fill in the block marked FILL IN, then run it from the repository root:
#
#     ./gcloud_deploy.sh
#
# Safe to run more than once. Everything it creates is checked for first, so a
# second run redeploys the current commit and leaves the secrets, the service
# account and the registry alone. Nothing here deletes anything.
#
# It does NOT put the OAuth client secret in this file. That one value is asked
# for at the prompt and piped straight into Secret Manager, so it is not on disk
# and not in your shell history. Everything else below is either public or a
# name.

set -euo pipefail

# ---------------------------------------------------------------------------
# FILL IN
# ---------------------------------------------------------------------------

# Your Google Cloud project ID — the short string, not the display name and not
# the number. `gcloud projects list` prints it under PROJECT_ID. If you have no
# project yet, make one: it is the billing and permission boundary for
# everything below, and a throwaway is fine to start.
#
#     gcloud projects create icon4py-plan-<something-unique> --name openproj
#
# Project IDs are globally unique across all of Google Cloud, so the plain names
# are long gone; add a suffix. It cannot be changed later, but the service can
# be redeployed into a different project in minutes, so this is not a decision
# to agonise over.
#
# The project also needs billing enabled — Cloud Run, Cloud Build and Artifact
# Registry all refuse without it, free tier included. A *billing account* cannot
# be created from the CLI at all; it takes a card, at
# https://console.cloud.google.com/billing. Once one exists:
#
#     gcloud billing accounts list                     # ID, not your email
#     gcloud billing projects link <project-id> --billing-account 01ABCD-EF2345-6789GH
#
# The flag wants that dashed ID. Given an email it answers `INVALID_ARGUMENT:
# Request contains an invalid argument` and names neither the field nor the
# format it wanted.
PROJECT="icon4py-plan-gcloud"

# Belgium, and Tier 1 — which is the reason it is not Zurich. Cloud Run's
# always-free monthly allowance is documented as applying to Tier 1 pricing
# regions, and europe-west6 is Tier 2, so the first deployment may have been
# billing from its first request rather than after an allowance. Nothing else
# distinguishes them for a service that scales to zero and holds no data: the
# plan lives on GitHub, not here.
#
# Changing this changes the service URL, so the OAuth App's redirect URIs change
# with it — and it leaves the old region's service running, because deleting one
# is not something a deploy script should do behind you. The runbook says how.
REGION="europe-west1"

# The GitHub App's private key, downloaded when you generated it in step 2. Read
# once, put in Secret Manager, and never referenced again — the file on your
# laptop can be deleted afterwards.
APP_KEY_FILE="/Users/jcanton/projects/openproj-icon4py.2026-08-17.private-key.pem"

# From the GitHub App's settings page (step 2). Neither is secret: the App ID is
# on the App's page, the installation ID is the number at the end of the URL
# when you click Configure on the installation.
APP_ID="4627892"
INSTALLATION_ID="154481476"

# From the OAuth App (step 3). The client ID is not secret and lives here; the
# client secret is asked for at the prompt.
OAUTH_CLIENT_ID="Ov23lisLaSCAwwru7ih3"

# The plan repository the service serves and pushes to, and the GitHub org whose
# membership decides who may write. These are already right.
REMOTE="https://github.com/jcanton/icon4py-plan.git"
ORG="C2SM"

# The Cloud Run service name, which becomes part of the URL.
SERVICE="openproj"

# ---------------------------------------------------------------------------
# From here down, nothing needs editing.
# ---------------------------------------------------------------------------

say() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
note() { printf '   %s\n' "$*"; }

missing=()
for name in PROJECT APP_ID INSTALLATION_ID OAUTH_CLIENT_ID; do
  [[ -n "${!name}" ]] || missing+=("$name")
done
if (( ${#missing[@]} )); then
  echo "Fill these in at the top of this script first: ${missing[*]}" >&2
  exit 2
fi
if [[ ! -r "$APP_KEY_FILE" ]]; then
  echo "Cannot read APP_KEY_FILE: $APP_KEY_FILE" >&2
  exit 2
fi
if [[ ! -f Dockerfile ]]; then
  echo "Run this from the openproj repository root (Dockerfile not found)." >&2
  exit 2
fi

RUNTIME_SA="${SERVICE}-run@${PROJECT}.iam.gserviceaccount.com"
IMAGE_REPO="${REGION}-docker.pkg.dev/${PROJECT}/${SERVICE}"

# --- sign in and select the project ----------------------------------------

say "Account and project"
if ! gcloud auth list --filter=status:ACTIVE --format='value(account)' | grep -q .; then
  gcloud auth login
fi
gcloud config set project "$PROJECT" >/dev/null
note "$(gcloud auth list --filter=status:ACTIVE --format='value(account)') → $PROJECT"

say "Enabling the four APIs this uses"
# Idempotent, and slow the first time — Google is provisioning each service.
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com

# --- secrets ----------------------------------------------------------------
#
# Three, and all three are in Secret Manager rather than in `--set-env-vars`,
# because a plain env var is in the revision's metadata: readable by anyone with
# roles/run.viewer, printed by `gcloud run services describe`, and kept in every
# past revision for ever. The App ID and installation ID are not secret and are
# passed as ordinary env vars further down.

secret_exists() { gcloud secrets describe "$1" >/dev/null 2>&1; }

say "Secrets"

if secret_exists openproj-app-key; then
  note "openproj-app-key exists — adding the key as a new version"
  gcloud secrets versions add openproj-app-key --data-file="$APP_KEY_FILE" >/dev/null
else
  gcloud secrets create openproj-app-key --data-file="$APP_KEY_FILE" >/dev/null
  note "openproj-app-key created"
fi

if secret_exists openproj-session-secret; then
  note "openproj-session-secret exists — left alone (rotating it signs everybody out)"
else
  python3 -c "import secrets; print(secrets.token_urlsafe(48))" \
    | gcloud secrets create openproj-session-secret --data-file=- >/dev/null
  note "openproj-session-secret created"
fi

if secret_exists openproj-oauth-client-secret; then
  note "openproj-oauth-client-secret exists — left alone"
else
  # Read here rather than stored above: this is the one value in this whole
  # script that is a credential, and -s keeps it off the screen while typing.
  # Piped straight in, so it never reaches a file or the history.
  printf '   OAuth App client secret (from step 3, not echoed): '
  read -rs OAUTH_CLIENT_SECRET
  printf '\n'
  [[ -n "$OAUTH_CLIENT_SECRET" ]] || { echo "empty — stopping" >&2; exit 2; }
  printf '%s' "$OAUTH_CLIENT_SECRET" \
    | gcloud secrets create openproj-oauth-client-secret --data-file=- >/dev/null
  unset OAUTH_CLIENT_SECRET
  note "openproj-oauth-client-secret created"
fi

# --- the runtime identity ---------------------------------------------------

say "Runtime service account"
if gcloud iam service-accounts describe "$RUNTIME_SA" >/dev/null 2>&1; then
  note "$RUNTIME_SA exists"
else
  gcloud iam service-accounts create "${SERVICE}-run" \
    --display-name "openproj Cloud Run runtime" >/dev/null
  note "$RUNTIME_SA created"
fi

# Read access to exactly these three secrets and nothing else. Re-running is
# harmless: the binding is a set, so adding one that is present changes nothing.
for name in openproj-session-secret openproj-oauth-client-secret openproj-app-key; do
  gcloud secrets add-iam-policy-binding "$name" \
    --member "serviceAccount:${RUNTIME_SA}" \
    --role roles/secretmanager.secretAccessor >/dev/null
done
note "secretAccessor on the three secrets"

# --- build ------------------------------------------------------------------

say "Image registry"
if gcloud artifacts repositories describe "$SERVICE" --location "$REGION" >/dev/null 2>&1; then
  note "${IMAGE_REPO} exists"
else
  gcloud artifacts repositories create "$SERVICE" \
    --repository-format=docker --location="$REGION" >/dev/null
  note "${IMAGE_REPO} created"
fi

# Tagged with the commit, so a revision can be traced to the source that built
# it. `-dirty` when the working tree has uncommitted changes, because an image
# built from something that is not in git is an image nobody can reproduce.
SHA="$(git rev-parse --short HEAD)"
git diff --quiet && git diff --cached --quiet || SHA="${SHA}-dirty"
IMAGE="${IMAGE_REPO}/${SERVICE}:${SHA}"

# The identity the BUILD runs as, which is not the identity the service runs as.
#
# `gcloud builds submit` with no --service-account defaults to the legacy
# `<project-number>@cloudbuild.gserviceaccount.com`, and since 2025 Google no
# longer creates that account for new projects. The binding is still seeded into
# the IAM policy, so the project looks correctly configured; the account behind it
# does not exist, and even the project owner gets PERMISSION_DENIED asking about
# it. The build then fails with
#
#     ERROR: (gcloud.builds.submit) PERMISSION_DENIED: The caller does not have
#     permission ... authenticated as <you>
#
# which points at you, the one identity in the picture that does have permission.
#
# So the build gets its own account, named, with three roles and no more: push the
# image, write the logs, read the uploaded source out of the staging bucket.
BUILD_SA="${SERVICE}-build@${PROJECT}.iam.gserviceaccount.com"

say "Build service account"
if gcloud iam service-accounts describe "$BUILD_SA" >/dev/null 2>&1; then
  note "$BUILD_SA exists"
else
  gcloud iam service-accounts create "${SERVICE}-build" \
    --display-name "openproj Cloud Build" >/dev/null
  note "$BUILD_SA created"
fi

# storage.admin and not the narrower objectAdmin, which was tried and is not
# enough. Cloud Build's regional log bucket —
# `gs://<project-number>-<region>-cloudbuild-logs` — does not exist until the
# first build, and the build is what creates it. Creating a bucket is a bucket
# permission, not an object one, so objectAdmin fails with
#
#     FAILED_PRECONDITION: service account ... does not have access to bucket
#     "gs://...-cloudbuild-logs". Please grant the service account
#     roles/storage.admin.
#
# and a bucket-scoped grant is impossible on a bucket that is not there yet.
# Project-wide is therefore the only shape this can take, and it is narrower than
# it sounds here: the only buckets this project has are the ones Cloud Build makes
# for itself. The plan is in git, not in GCS.
for role in roles/artifactregistry.writer roles/logging.logWriter roles/storage.admin; do
  gcloud projects add-iam-policy-binding "$PROJECT" \
    --member "serviceAccount:${BUILD_SA}" --role "$role" \
    --condition=None >/dev/null
done
note "artifactregistry.writer, logging.logWriter, storage.admin"

say "Building ${IMAGE}"
note "uploads this directory minus .gcloudignore, then builds ./Dockerfile"
# --default-buckets-behavior is not optional once --service-account is given:
# Cloud Build refuses a build that names a service account without also saying
# where its logs go, and a project-owned regional bucket is the answer that needs
# no further configuration.
gcloud builds submit \
  --tag "$IMAGE" \
  --region "$REGION" \
  --service-account "projects/${PROJECT}/serviceAccounts/${BUILD_SA}" \
  --default-buckets-behavior=regional-user-owned-bucket \
  .

# --- deploy -----------------------------------------------------------------
#
# The flags that are not decoration, in the order they appear:
#
#   --allow-unauthenticated   reads are public by design; the write gate is the
#                             session, checked per request inside the app.
#   --max-instances 1         one writer. The app takes a flock, so the lock is
#                             the real guard, but a second instance would spend
#                             its life losing races against the first.
#   --concurrency 80          the opposite of the usual instinct, and it is what
#                             keeps the instance count at one. Lowering it does
#                             not add safety, it destroys it.
#   --min-instances 0         one instance left running for a month is 14x the
#                             free tier.
#   --cpu 1                   below 1 vCPU Cloud Run forces concurrency to 1,
#                             which means one instance per in-flight request.
#   --cpu-boost               a cold start clones the plan; this makes that fast
#                             without paying for a warm instance.
#   --timeout 300             the request deadline, and a co-editing socket is a
#                             request — so every one of them is closed after five
#                             minutes, whoever is typing. Reconnection is the
#                             normal case rather than the exception, which is most
#                             of why the editor uses a CRDT: a room is kept warm
#                             for longer than this (coedit.LINGER_SECONDS) so a
#                             tab that comes back joins the room it left instead
#                             of being told to reload every five minutes.
#
# And never --no-cpu-throttling: two to three orders of magnitude more expensive,
# from a flag whose name mentions neither billing nor instances. Google's
# Recommender suggests it periodically. For a scale-to-zero service it is wrong.
#
# The two env-var secrets are pinned to version 1 on purpose. With :latest, two
# instances can hold different session keys and a cookie minted by one is
# rejected by the other. The PEM is a file mount instead, so rotating the App key
# needs no redeploy.

say "Deploying"
gcloud run deploy "$SERVICE" \
  --image "$IMAGE" \
  --region "$REGION" \
  --allow-unauthenticated \
  --service-account "$RUNTIME_SA" \
  --cpu 1 --memory 512Mi --cpu-boost \
  --concurrency 80 --min-instances 0 --max-instances 1 --timeout 300 \
  --set-env-vars "OPENPROJ_AUTH=github,OPENPROJ_ORG=${ORG}" \
  --set-env-vars "OPENPROJ_REMOTE=${REMOTE}" \
  --set-env-vars "OPENPROJ_CLIENT_ID=${OAUTH_CLIENT_ID}" \
  --set-env-vars "OPENPROJ_APP_ID=${APP_ID}" \
  --set-env-vars "OPENPROJ_INSTALLATION_ID=${INSTALLATION_ID}" \
  --set-env-vars "OPENPROJ_APP_KEY=/secrets/app-key.pem" \
  --set-secrets "OPENPROJ_SECRET=openproj-session-secret:1" \
  --set-secrets "OPENPROJ_CLIENT_SECRET=openproj-oauth-client-secret:1" \
  --set-secrets "/secrets/app-key.pem=openproj-app-key:latest"

URL="$(gcloud run services describe "$SERVICE" --region "$REGION" --format='value(status.url)')"

# --- verify -----------------------------------------------------------------
#
# Four checks, in this order, because each one can pass while the next fails.

say "Checking ${URL}"

# /api/health and NOT /healthz. Google's frontend answers /healthz itself, with
# its own 404 page, and the request never reaches the container — so the one
# check meant to prove the service is alive was the one URL that could not reach
# it, and it failed against a service that was working perfectly.
printf '   /api/health        '
curl -fsS --max-time 30 "$URL/api/health" || note "FAILED — see the logs below"
printf '\n'

# The one worth checking explicitly. static/ is not in the wheel, so a container
# that resolved it wrongly serves every other page perfectly and 500s only here.
printf '   /graph             %s (want 200)\n' \
  "$(curl -s -o /dev/null -w '%{http_code}' --max-time 30 "$URL/graph")"

# Writes are gated. A 401 here is the whole security model working.
printf '   PATCH an entity    %s (want 401)\n' \
  "$(curl -s -o /dev/null -w '%{http_code}' --max-time 30 \
       -X PATCH -H 'Content-Type: application/json' -d '{}' "$URL/api/entity/task-000000")"

# Proves the push credential worked on the cold start. If this line is missing
# and the service is up, it is serving an empty plan it made itself — which
# looks completely normal until the first save goes nowhere.
# Retried, because Cloud Logging ingests on its own schedule: the first run of
# this check reported NOT FOUND against a boot that had cloned perfectly well
# thirty seconds earlier, which is worse than no check — it accuses the one part
# of the stack that is hardest to re-test.
printf '   cloned on boot     '
cloned=""
for _ in 1 2 3 4 5 6; do
  if gcloud run services logs read "$SERVICE" --region "$REGION" --limit 50 2>/dev/null \
       | grep -q cloning; then
    cloned="yes"
    break
  fi
  sleep 5
done
if [[ -n "$cloned" ]]; then
  printf 'yes\n'
else
  printf 'not in the logs yet — check: gcloud run services logs read %s --region %s\n' \
    "$SERVICE" "$REGION"
fi

# Cloud Run answers on two hostnames — the one `describe` reports and the
# project-number one the deploy prints — and GitHub matches a redirect URI
# exactly. Registering only one means sign-in works or 404s depending on which
# link somebody followed, so both are printed and both should be registered.
ALT_URL="https://${SERVICE}-$(gcloud projects describe "$PROJECT" \
  --format='value(projectNumber)').${REGION}.run.app"

say "Deployed: ${URL}"
cat <<EOF

   One thing left, and sign-in fails until it is done. Add BOTH of these to the
   OAuth App's Redirect URIs at https://github.com/settings/developers —
   Cloud Run answers on both hostnames and GitHub matches them exactly:

     ${URL}/auth/callback
     ${ALT_URL}/auth/callback

   (Leave wildcard matching off. The app already holds the loopback URI, and it
   takes up to ten, so nothing has to be replaced.)

   Then open ${URL} and sign in.
EOF
