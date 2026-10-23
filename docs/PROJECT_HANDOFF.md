# Wallet V2 — Agent Takeover Handoff

This document is the implementation checkpoint for agents taking over Wallet V2 after the historical-reconciliation work. It distinguishes the **target product** from the **currently implemented, locally deployed slice**.

**Snapshot:** 2026-10-19  
**Repository:** `MatehElismar/wallet`  
**Active feature branch:** `wallet-v2-historical-reconciliation-backend`  
**Head commit:** `0488a08304ea22652882ba74afd5fa11eb02d63b` (`feat: enable date-range reconciliation runs`)  
**Open PR:** #3, `feat: add historical reconciliation pilot`  
**PR base:** `wallet-v2-controlled-integrations`  

> Do not retarget this PR to `master` without deliberately reconciling history: the current feature lineage has no common ancestor with `master`. The intended review base is `wallet-v2-controlled-integrations`.

## 1. Product contract

Wallet V2 is becoming a **historical ledger-reconciliation tool**, not a notification-first ledger writer.

1. The operator selects an **inclusive date range**.
2. The system discovers all eligible statement accounts internally; there is no account picker.
3. Posted bank-statement activity is primary evidence.
4. Existing Wallet history is intended to be a read-only comparison baseline.
5. Notification/email, LLM, and MCP output remain advisory only.
6. Only reviewed, statement-backed canonical events may ever reach a controlled Wallet-import path.

The complete intended product is documented in [`product-vision.md`](product-vision.md). That document includes features that are **not implemented yet**; use the implementation checkpoint below before describing a capability as available.

## 2. What is implemented in this PR

### Historical reconciliation console

The Next.js console has a coherent operator shell:

- **Runs** — date-range snapshot creation, run list, and run detail.
- **Review**, **Evidence**, **Accounts**, **Activity** — truthful pilot shells; they must not fabricate Wallet matching, approval, or import capability.
- Header labels are intentionally explicit: **Statement evidence only** and **Canonical approval locked**.

The home page can now submit a date range to create a run. A successful response is synchronous: it returns a completed `materialized` snapshot; there is no background job state or progress worker for this operation.

### Durable statement-evidence runs

Migration `0012_reconciliation_runs` adds immutable reconciliation-run tables:

- `reconciliation_runs`
- `reconciliation_run_account_coverages`

Implemented behavior:

- `POST /reconciliation-runs` materializes one immutable statement-evidence snapshot for the requested inclusive range.
- `GET /reconciliation-runs` lists snapshots newest-first.
- `GET /reconciliation-runs/{run_id}` returns a snapshot and per-account coverage.
- The materializer discovers all eligible statement accounts itself; the request contains only `period_start` and `period_end`.
- Effective line date is `posting_date`, falling back to `transaction_date`.
- Lines without either date are counted as excluded only when their statement period overlaps the selected range.
- Only `open` and `approved` statement versions contribute. `superseded` and `rejected` statements are excluded to prevent double counting.
- API responses explicitly declare `evidence_scope: "statement_evidence_only"`.
- `new_count` is explicitly `unmatched_notification_evidence`; it must never be relabeled as a missing Wallet entry.

### Snapshot immutability

A run and every account-coverage row are append-only after materialization:

- no mutable `updated_at` column;
- SQLAlchemy update listeners reject ordinary ORM mutation;
- migration `0012` installs PostgreSQL `BEFORE UPDATE OR DELETE` triggers for both tables;
- regression tests cover ordinary ORM updates, SQLAlchemy bulk updates, and direct PostgreSQL updates.

Do not weaken this invariant to make editing convenient. Create a new snapshot instead.

### Financial-safety boundary

The following remain intentionally unavailable server-side:

- canonical approval: `POST /commands/approve-batch/{batch_id}`;
- Wallet import/dry-run import: `POST /commands/dry-run-import/{event_id}`.

Both currently return HTTP `503` before doing work because the API cannot derive a verified operator from a server-side authenticated session. The Next browser proxy independently blocks these mutation paths as defense in depth.

A date-range reconciliation run is allowed without that identity system because it only persists a non-financial evidence snapshot: it does not create canonical records, call Wallet, or write to Wallet.

## 3. Current local runtime

The active local stack is built from this feature branch and was healthy at handoff:

- Web: `http://localhost:3000/`
- API health: `http://localhost:8000/health`
- API schema: `http://localhost:8000/openapi.json`
- Database migration head: `0012_reconciliation_runs`

Start or rebuild it from the feature worktree:

```bash
docker compose up -d --build
docker compose ps
curl --fail http://localhost:8000/health
curl --fail http://localhost:8000/reconciliation-runs
```

`docker-compose.yml` deliberately configures mailbox, LLM, Wallet, and MCP integrations as `disabled` for the local stack. Configuration is fail-closed: present-but-empty integration settings are invalid.

The Compose file intentionally reuses an existing external development database volume instead of creating a branch-namespaced empty volume. Before changing Compose or rebuilding from another worktree, inspect the resolved volume and database mount. Do not assume a newly created Compose project points at the development ledger.

### Local data observed at handoff

These values are development-database state, not fixtures or product guarantees:

- 9 financial accounts;
- 4 open statements;
- 38 statement lines;
- effective statement-line dates from 2026-06-22 through 2026-10-19;
- one materialized zero-coverage run for 2026-01-01 through 2026-01-31.

That run is correctly empty because no source evidence exists in January. It is immutable by design. A useful local test run should use a period within the available statement date window.

## 4. Verification already performed

At the `0488a08` checkpoint:

```bash
uv run pytest -q        # 671 passed
cd web && npm test      # 44 passed
cd web && npm run build # passed
```

Also verified:

- `git diff --check` passed;
- a fresh PostgreSQL database migrated through `0012_reconciliation_runs` successfully;
- direct PostgreSQL mutation of immutable snapshot data was rejected by the migration trigger;
- local Docker API, web, and PostgreSQL services were healthy;
- an independent focused review found no remaining snapshot-immutability blocker.

No GitHub status checks were configured on PR #3 at handoff. Do not treat an empty check list as a CI pass; run the commands above.

## 5. Important files

### Product and operator UX

- `docs/product-vision.md` — target product contract and acceptance criteria.
- `docs/architecture.md` — architecture and invariants.
- `docs/ux-assessment.md` — intended information architecture.
- `web/src/app/page.tsx` — Runs page and date-range form.
- `web/src/app/runs/[id]/page.tsx` — immutable run detail and account coverage.
- `web/src/app/layout.tsx` — truthful global capability labels.
- `web/src/lib/api.ts` — browser API client.
- `web/src/lib/proxy-policy.ts` — browser-proxy financial-mutation blocklist.

### Reconciliation implementation

- `src/wallet_v2/application/reconciliation_runs.py` — snapshot materialization and evidence eligibility.
- `src/wallet_v2/api/routes/reconciliation_runs.py` — create/list/detail endpoints.
- `src/wallet_v2/api/schemas.py` — request/response semantics.
- `src/wallet_v2/persistence/models/reconciliation.py` — run/coverage models and ORM immutability protections.
- `alembic/versions/0012_reconciliation_runs.py` — schema, constraints, indexes, PostgreSQL triggers.
- `tests/test_reconciliation_runs.py` — materialization and immutability regression coverage.
- `tests/test_api.py` — run API coverage and command-safety expectations.
- `src/wallet_v2/api/routes/commands.py` — deliberate server-side `503` guards for approval/import.

## 6. Known limitations and next implementation order

The current slice is **not Wallet-history reconciliation yet**. It is a truthful, immutable snapshot of statement evidence.

Recommended next sequence:

1. **Available-evidence guidance in the Runs UI**
   - Show statement date coverage before submission so operators do not create accidental empty runs.
   - Do not infer coverage from account metadata; use actual eligible statement-line dates.

2. **Read-only Wallet-history ingestion/catalog baseline**
   - Persist source identity, retrieved range, raw/normalized fields, and a versioning/retrieval audit trail.
   - A reconciliation run must not mutate this baseline.

3. **Deterministic statement-to-Wallet matching**
   - Classify `matched`, `missing in Wallet`, `possible duplicate`, `mismatch`, `ambiguous`, and account-mapping exceptions.
   - Preserve matching inputs/rationale and never silently cross-match accounts.

4. **Statement completeness / balance proof**
   - Model `proven`, `unprovable`, and `failed` balance states.
   - Approval policy must require proof or a separately auditable authenticated override.

5. **Canonical proposal and authenticated approval**
   - Derive the operator from a server-side session; never trust `reviewer_id` request text.
   - Only statement-backed, reviewed proposals may become canonical.

6. **Controlled Wallet import**
   - Re-enable only after authenticated approval exists.
   - Use a single exact payload path for preview/submission, idempotency, and uncertain-outcome reconciliation.

## 7. Non-negotiable constraints

- Do not treat notification, email, LLM, or MCP output as financial authority.
- Do not add Wallet writes directly from notifications or advisory evidence.
- Do not relabel `new_count` as missing Wallet history.
- Do not expose secrets, API keys, tokens, passwords, or database URLs in source, logs, commits, or handoff material.
- Keep integration modes explicit: `disabled`, `dry_run`, or `live`; fail closed for incomplete configuration.
- Mailbox access must remain read-only and must not mark messages as read.
- Do not remove server-side financial-command guards merely because the browser UI hides controls.
- Preserve snapshot immutability at both ORM and database layers.
- Do not push changes to the feature branch without deliberately updating PR #3 and re-running its verification gates.

## 8. Git and branch context

The feature branch includes these commits beyond `wallet-v2-controlled-integrations`:

```text
97e1a3a fix: restore reproducible Wallet V2 verification
f47af6c fix: persist redacted message failure diagnostics
8b5ce96 docs: redefine Wallet V2 as historical reconciliation
ed8ca8a feat: reshape reconciliation console UI
35a1584 fix: start local stack with disabled integrations
1d16228 feat: add historical reconciliation run snapshots
860394e feat: show materialized reconciliation runs
0488a08 feat: enable date-range reconciliation runs
```

`PROJECT_STATUS.md` at repository root predates this checkpoint and should be treated as broad historical background, not the authoritative description of the current PR. This handoff plus `product-vision.md` are the intended takeover starting point.
