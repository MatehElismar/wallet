# Wallet V2 Reconciliation Console

## Architecture

Two independently deployed services:

```
Browser (PWA) ──→ Firebase App Hosting (Next.js) ──→ Cloud Run (FastAPI) ──→ PostgreSQL
                  /api proxy (server-only)              private ingress
```

- **`web/`** — Next.js PWA, deployed to Firebase App Hosting. Mobile-first
  reconciliation console. Builds with `npm run build` (standalone output).
  Browser requests use relative `/api` paths; the Next.js server-side API
  route forwards them to Cloud Run. The Cloud Run URL is **never** compiled
  into browser assets.
- **`src/wallet_v2/api/`** — FastAPI service deployed separately to Cloud Run.
  The factory `create_app()` loads validated `WALLET_V2__*` settings from the
  environment and builds a PostgreSQL engine through
  `create_engine_from_settings`. Invalid or missing production configuration
  fails closed. There is no default/fallback to SQLite.

## Unauthenticated / Dry-Run Warning

**This is a temporary single-operator console. Authentication is explicitly
deferred.** The API records an `"unauthenticated"` initiator in every audit
event. All mutation endpoints enforce `IntegrationMode.DRY_RUN` — the service
will refuse to submit a live Wallet import.

Do not expose this API on the public internet beyond a trusted operator.

## Environment Variables

### FastAPI / Cloud Run

| Variable | Required | Description |
|---|---|---|
| `WALLET_V2__DATABASE__URL` | **Yes** | PostgreSQL connection string (e.g. `postgresql+psycopg://user:pass@host:5432/wallet_v2`) |
| `WALLET_V2__ENVIRONMENT` | **Yes** | `dev`, `staging`, or `prod` |
| `WALLET_V2__DATABASE__POOL_SIZE` | No | Connection pool size (default 5) |
| `WALLET_V2__DATABASE__MAX_OVERFLOW` | No | Max overflow connections (default 10) |

### Next.js / App Hosting (server-only)

| Variable | Required | Description |
|---|---|---|
| `WALLET_V2_API_URL` | **Yes** | Base URL of the Cloud Run FastAPI service. It is a runtime-only App Hosting secret, never a `NEXT_PUBLIC_` variable, and never appears in browser bundles. |
| `NODE_ENV` | **Yes** | Set to `production` by App Hosting. |

## Local Development

### 1. Database

```bash
docker compose up -d postgres
```

### 2. Run Migrations

```bash
alembic upgrade head
```

### 3. FastAPI

```bash
WALLET_V2__DATABASE__URL="postgresql+psycopg://wallet_v2:wallet_v2@localhost:5432/wallet_v2" \
WALLET_V2__ENVIRONMENT=dev \
python -m uvicorn wallet_v2.api.app:create_app --factory --reload
```

### 4. Next.js

```bash
cd web
WALLET_V2_API_URL="http://localhost:8000" npm run dev
```

### 5. Tests

```bash
# Python tests (hermetic — no database or network)
uv run pytest

# With coverage
uv run pytest --cov=src/wallet_v2 --cov-report=term
```

### 6. Build (verify)

```bash
cd web && npm run build
```

## Deployment

### API (Cloud Run)

Deploy the FastAPI service with private ingress:

```bash
gcloud run deploy wallet-v2-api \
  --source . \
  --region us-central1 \
  --no-allow-unauthenticated \
  --ingress=internal-and-cloud-load-balancing \
  --set-env-vars="WALLET_V2__DATABASE__URL=...,WALLET_V2__ENVIRONMENT=prod"
```

### IAM / Service Account Permissions

The Next.js proxy running on Firebase App Hosting calls Cloud Run using
Google Application Default Credentials and an identity token. Grant the
default App Hosting compute service account the Cloud Run Invoker role:

```bash
gcloud run services add-iam-policy-binding wallet-v2-api \
  --region=us-central1 \
  --member="serviceAccount:firebase-app-hosting-compute@<PROJECT_ID>.iam.gserviceaccount.com" \
  --role="roles/run.invoker"
```

Replace `<PROJECT_ID>` with your Firebase project ID. If the backend uses a
custom runtime service account, grant that account instead.

### Cloud Run Ingress

To keep the mutating API private, Cloud Run ingress must not be
`--allow-unauthenticated`. Use one of:
- `--ingress=internal-and-cloud-load-balancing` (preferred — reachable from
  App Hosting via Google's network)
- `--ingress=internal` (if the App Hosting VPC connector is configured)

### Console (Firebase App Hosting)

1. Run `firebase init apphosting` with Firebase CLI 14.4.0 or later and select
   `web/` as the App Hosting root directory. This records the project/backend
   choice in the uncommitted local `firebase.json` created by the CLI.
2. Create the required App Hosting secret, then grant the selected backend
   access to it:

   ```bash
   firebase apphosting:secrets:set walletV2ApiUrl --project <PROJECT_ID>
   firebase apphosting:secrets:grantaccess walletV2ApiUrl \
     --backend <BACKEND_ID> --project <PROJECT_ID> --location <REGION>
   ```

   Enter the private Cloud Run service URL (for example,
   `https://wallet-v2-api-xxxxx-uc.a.run.app`) as the secret value.
   `web/apphosting.yaml` maps that secret to runtime-only
   `WALLET_V2_API_URL`.
3. Do **not** set `NEXT_PUBLIC_API_BASE_URL` — the Cloud Run URL must never
   be compiled into browser assets.
4. Create a rollout through the Firebase console or run `firebase deploy`
   after the CLI initialization above.

### Reproducible Commands

```bash
# Python
uv sync --group dev
uv run pytest

# Next.js
cd web
npm ci
npm run build
```

## API Endpoints

### Health
```
GET /api/health → { "ok": true }
```

### Batches
```
GET /api/batches              → BatchSummaryList   (open review batches)
GET /api/batches/{batch_id}   → BatchDetail        (full batch with lines)
```

### Commands
```
POST /api/commands/resolve-line/{line_id}      → ResolveLineResponse
POST /api/commands/map-account/{account_id}     → MapAccountResponse
POST /api/commands/approve-batch/{batch_id}     → ApproveBatchResponse
POST /api/commands/dry-run-import/{event_id}    → DryRunImportResponse
```
