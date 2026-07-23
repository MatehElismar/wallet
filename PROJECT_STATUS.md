# Wallet V2 — Project Status & Handoff

## Goal

Review-first email-to-Wallet transaction ingestion with operator-controlled reconciliation,
MCP-backed advisory enrichment, and immutable audit trail.

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
- [ ] Authentication (explicitly deferred — single-operator, unauthenticated audit initiator)
- [ ] Background reconciliation job (service layer exists, no worker)

### CLI
- [x] `wallet-v2 run` — fetch and create review tasks (dry_run/live, limit, date, uid, reprocess)
- [x] `wallet-v2 runs show` — inspect recorded execution runs
- [x] `wallet-v2 sync-catalog` — sync Wallet catalog to versioned snapshots
- [x] `wallet-v2 repair-qik` — merge duplicate Qik accounts

---

## What Remains

| # | Task | Priority | Effort |
|---|------|----------|--------|
| 1 | Production push provider (FCM/VAPID delivery) | High | 4–8h |
| 2 | Authentication (operator identity + audit attribution) | High | 8–16h |
| 3 | Background reconciliation worker (resolve `unknown` import states) | Medium | 16–24h |
| 4 | Catalog sync scheduling (periodic or webhook-driven) | Medium | 4–8h |
| 5 | Advanced filtering/search across batches/candidates | Low | 8–12h |
| 6 | Analytics/metrics dashboard | Low | 12–16h |
| 7 | Native mobile app (beyond PWA) | Low | 40–60h |

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
