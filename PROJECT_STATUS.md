# Wallet V2 — Project Status & Handoff

## Goal

Historical ledger reconciliation across a user-selected date range: discover all
available accounts, compare posted bank-statement activity with existing Wallet
history, and propose evidence-backed missing, duplicate, mismatch, and
ambiguous cases for operator review. Statement-backed, human-approved events
are the only route to canonical records; email, LLM, and MCP output remain
advisory evidence.

---

## Progress Checklist

### Domain & Persistence
- [x] Value objects: Money, TransactionAmount, MailboxCursor, MailboxSource
- [x] Enums: 20+ status enums covering all workflow states
- [x] 24 SQLAlchemy 2.0 models across the full pipeline
- [x] 11 hand-written Alembic migrations (PostgreSQL-specific)
- [x] Immutable-table invariant (no `updated_at` for append-only tables)
- [x] Idempotency keys on processing attempts and import commands
- [x] Fail-closed config system (`WALLET_V2__` prefix, all integrations default disabled)
- [x] Bank-agnostic reference normalization (`ReferenceNormalizer` protocol + registry)
- [x] Hermetic test suite (no network or database required)

### Adapters (Live Connectors)
- [x] IMAP (`ImapMailboxReader`) — read-only via EXAMINE + BODY.PEEK[], PDF extraction
- [x] LLM (`OpenAICompatibleExtractor`) — OpenAI, Gemini, DeepSeek, OpenRouter, custom
- [x] Wallet API (`BudgetBakersWalletClient`) — full REST read + write
- [x] MCP (`WalletMcpClient`) — JSON-RPC 2.0, 5 allowlisted read-only tools, profile/scope gating
- [ ] Push provider — stub only (`DisabledPushProvider`), no production FCM/VAPID delivery

### Application Services
- [x] `WalletWorkflow` — primary orchestrator (ingest, extract, review, approve, import)
- [x] `EnrichmentService` — deterministic MCP advisory enrichment with versioned immutable decisions
- [x] `AccountMappingService` — validated financial-account → Wallet-account mappings
- [x] `AccountRepairService` — transactional duplicate merge for Qik accounts
- [x] `CatalogSyncService` — versioned Wallet catalog snapshots (accounts, categories, labels, rules)
- [x] `OutboxService` — idempotent notification outbox per subscription
- [x] `OutboxWorker` — polling worker with `SELECT ... FOR UPDATE SKIP LOCKED`

### API (FastAPI on Cloud Run)
- [x] `GET /health`
- [x] `GET /batches`, `GET /batches/{id}`
- [x] `POST /commands/resolve-line/{id}`, `/map-account/{id}`, `/approve-batch/{id}`, `/dry-run-import/{id}`
- [x] `GET /enrichment/candidates`, `/enrichment/candidates/{id}`, `/enrichment/candidates/account/{id}`
- [x] `GET /enrichment/events/{id}` + `POST` generate / override / finalize
- [x] `GET /enrichment/events/{id}/dry-run-preview`
- [x] `POST /enrichment/batches/{id}/generate-proposals`
- [x] `GET /enrichment/lines/{id}` + `POST /enrichment/lines/{id}/override`
- [x] Push subscription endpoints (`/push/config`, `/push/subscriptions`)
- [x] Pydantic schemas for all request/response types

### Web PWA (Next.js on Firebase App Hosting)
- [x] Batches list page (`/`)
- [x] Batch detail page with reconciliation workspace (`/batches/[id]`)
- [x] Candidates list page (`/candidates`)
- [x] Candidate detail page with evidence (`/candidates/[id]`)
- [x] `EnrichmentCard` — grade display, generate/override/finalize/preview actions
- [x] `OverrideForm` — manual account/category/labels/payment selection
- [x] `CandidateResearchCard` — proposed wallet selection + evidence + record preview
- [x] Account mapping modal
- [x] Line resolve modal with observation linking
- [x] API proxy with GCP identity-token injection + header allowlisting
- [x] TypeScript API client (`lib/api.ts`) covering all endpoints
- [x] PWA manifest + service worker with offline cache
- [x] Push subscription init (PushInit component + push-config utilities)
- [x] Dark theme CSS (`globals.css`)
- [x] Dockerfile (multi-stage Node 20 Alpine standalone build)
- [x] `firebase.json` / `apphosting.yaml` for Firebase App Hosting

### Deployment & Operations
- [x] `deploy.sh` — Docker Compose build + health checks (API :8000, Web :3000)
- [x] `docs/architecture.md` — invariants, schema reference, non-goals
- [x] `docs/deployment.md` — Cloud Run + Firebase App Hosting setup
- [ ] Authentication and identity-backed audit attribution (not yet implemented; P0 for the pilot)
- [ ] Background reconciliation job for `unknown` Wallet outcomes (not yet implemented; P1 for the pilot)

### CLI
- [x] `wallet-v2 run` — fetch and create review tasks (dry_run/live, limit, date, uid, reprocess)
- [x] `wallet-v2 runs show` — inspect recorded execution runs
- [x] `wallet-v2 sync-catalog` — sync Wallet catalog to versioned snapshots
- [x] `wallet-v2 repair-qik` — merge duplicate Qik accounts

---

## What Remains — Historical Reconciliation Pilot

| # | Task | Priority | Notes |
|---|------|----------|-------|
| 1 | Repair the controlled ledger write path | P0 | One preview/submission payload, correct signed direction, finalized-decision and posted-event gates |
| 2 | Statement balance proof | P0 | Persist `proven`, `unprovable`, or `failed`; ordinary approval requires `proven`, `unprovable` needs an audited override, and `failed` is blocked |
| 3 | Human-validated account mappings | P0 | Fuzzy discovery proposes only; an explicit reviewed mapping authorizes the account |
| 4 | Authentication and attributable audit identity | P0 | Reviewer and initiator must derive from a verified session, not request text |
| 5 | Date-range reconciliation run | P0 | Discover all accounts, read Wallet history, and classify every statement line |
| 6 | Read-only Wallet-history matching | P0 | Deterministic matching for matched, missing, duplicate, mismatch, ambiguous, and mapping-review outcomes |
| 7 | Runs and review UI | P1 | Coverage dashboard, evidence dossier, canonical-candidate review, and two-step approval |
| 8 | Accounts and activity UI | P1 | Mapping review, account drill-down, audit/import status, and visible `unknown` queue |
| 9 | Background resolver for `unknown` Wallet outcomes | P1 | Out-of-band reconciliation; never blind retry |
| 10 | Operational controls | P2 | Catalog scheduling, structured logs, metrics, retention, readiness checks |
| 11 | Push notifications | P2 | Material run/review exceptions only; not a primary workflow |

The detailed pilot definition and acceptance criteria live in
[`docs/product-vision.md`](docs/product-vision.md).

---

## Root-Level Files to Clean Up

These untracked files at the repo root are **duplicates** of files already integrated:

| Root file | Duplicate of |
|-----------|-------------|
| `candidate-research-card.tsx` | `web/src/app/candidate-research-card.tsx` |
| `enrichment.py` | `src/wallet_v2/api/routes/enrichment.py` |
| `schemas.py` | `src/wallet_v2/api/schemas.py` |

They should be deleted unless they contain divergent changes worth merging.

---

**Last updated:** 2026-07-22  
**Branch:** `wallet-v2-controlled-integrations`
