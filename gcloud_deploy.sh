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
#     gcloud billing projects link <that-id> --billing-account <your account>
#
# Project IDs are globally unique across all of Google Cloud, so the plain names
# are long gone; add a suffix. It cannot be changed later, but the service can
# be redeployed into a different project in minutes, so this is not a decision
# to agonise over.
PROJECT=""

# Zurich. europe-west1 (Belgium) is the alternative and is marginally cheaper;
# both are fine for a service that scales to zero.
REGION="europe-west6"

# The GitHub App's private key, downloaded when you generated it in step 2. Read
# once, put in Secret Manager, and never referenced again — the file on your
# laptop can be deleted afterwards.
APP_KEY_FILE="/Users/jcanton/projects/openproj-icon4py.2026-08-17.private-key.pem"

# From the GitHub App's settings page (step 2). Neither is secret: the App ID is
# on the App's page, the installation ID is the number at the end of the URL
# when you click Configure on the installation.
APP_ID=""
INSTALLATION_ID=""

# From the OAuth App (step 3). The client ID is not secret and lives here; the
# client secret is asked for at the prompt.
OAUTH_CLIENT_ID=""

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
if [[ ! -f deploy/Dockerfile ]]; then
  echo "Run this from the openproj repository root (deploy/Dockerfile not found)." >&2
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

say "Building ${IMAGE}"
note "uploads this directory minus .gcloudignore, then builds deploy/Dockerfile"
gcloud builds submit --tag "$IMAGE" --region "$REGION" .

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

printf '   /healthz           '
curl -fsS --max-time 30 "$URL/healthz" || note "FAILED — see the logs below"
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
printf '   cloned on boot     '
if gcloud run services logs read "$SERVICE" --region "$REGION" --limit 50 2>/dev/null \
     | grep -q cloning; then
  printf 'yes\n'
else
  printf 'NOT FOUND — check: gcloud run services logs read %s --region %s\n' "$SERVICE" "$REGION"
fi

say "Deployed: ${URL}"
cat <<EOF

   One thing left, and sign-in fails until it is done:

   add  ${URL}/auth/callback
   to the OAuth App's Redirect URIs at https://github.com/settings/developers

   (Leave wildcard matching off. The app already holds the loopback URI, and it
   takes up to ten, so nothing has to be replaced.)

   Then open ${URL} and sign in.
EOF
