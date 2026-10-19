# Wallet V2 — Historical Reconciliation UX

## Product focus

Wallet V2 is an operator tool for repairing historical Wallet coverage.

The operator starts with a **date range**, not an account. The system discovers
available bank/card accounts and Wallet accounts inside that range, reads the
existing ledger, ingests available evidence, and proposes the cases needing a
human decision.

```text
Choose date range
  -> discover accounts and source coverage
  -> ingest statements and read Wallet history
  -> reconcile every posted statement line
  -> review missing, duplicate, mismatch, ambiguous, and unmapped cases
  -> approve statement-backed canonical events
  -> use the separate controlled Wallet import path
```

## Authority model

The interface must make authority visible, not implied by confidence or color.

| Tier | Objects | Operator meaning | Permitted action |
|---|---|---|---|
| Advisory | email observations, notifications, LLM/MCP research | useful context; not proof of a ledger event | inspect, link as evidence, improve matching context |
| Reconciliation | statement lines, existing Wallet records, match proposals | the system is comparing two histories | resolve or mark ambiguous |
| Canonical proposal | statement-backed missing-in-Wallet entry | eligible for an attributable decision | approve or reject |
| Canonical | approved financial event | immutable accounting decision | controlled import only |

A notification, extracted field, match score, or enrichment proposal must never
render as an importable record. The UI should state what additional evidence or
approval is required to advance an item.

## Primary navigation

- **Runs** — date-range reconciliation runs, source coverage, and summary.
- **Review** — actionable queues: missing in Wallet, duplicates, mismatches,
  ambiguous matches, mapping exceptions, and advisory observations awaiting
  statement evidence.
- **Evidence** — statement documents, observations, matching rationale, and
  balance proof.
- **Accounts** — discovered accounts, mapping proposals, Wallet coverage, and
  per-account drill-down.
- **Activity** — approvals, canonical events, imports, unresolved external
  outcomes, and audit history.

Use **canonical proposals** for statement-backed items eligible for approval,
**reconciliation cases** for matching outcomes, and **notification
observations** for advisory email evidence. Notifications are supporting
evidence, not the primary workspace.

## Primary screens

### 1. Runs

The home screen is a list of historical reconciliation runs and a clear
"New run" action.

A run starts with:

- inclusive start and end dates; and
- all currently configured sources for the selected period. Any later rerun
  must display its source coverage prominently and cannot be described as
  complete-period coverage when sources were excluded.

It does not ask the operator to choose an account. Account discovery and mapping
happen during processing.

A completed run reports coverage before the operator opens any row:

```text
Jan 1–Dec 31, 2025

Accounts discovered: 8
  6 reconciled · 1 requires mapping review · 1 has no Wallet history

Posted statement lines: 2,418
  2,243 matched
  94 missing in Wallet
  31 possible duplicates
  18 ambiguous
  32 account mapping review required

Separate advisory evidence: 14 observations awaiting statement evidence
```

The run must also show evidence freshness, processing failures, and whether
statement balance proof is `proven`, `unprovable`, or `failed`.

### 2. Review queue

The default queue is **Missing in Wallet**, because it is the product's core
value. It is filterable by date, account, institution, currency, evidence state,
and review state; filters must live in the URL for a reviewable deep link.

Each row shows:

- posted date, amount, direction, and account context;
- statement evidence and balance-proof state;
- Wallet search result: no match, possible duplicate, mismatch, or ambiguous;
- supporting advisory evidence when it exists;
- the proposed action and its authority state.

Example:

```text
Missing in Wallet
Banco Popular · Credit Card ••••2727
Jan 17, 2025 · $42.30 debit · Grocery merchant

Evidence: posted statement line · statement balance proven
Wallet search: no reliable match among 184 records
Support: matching debit-alert observation

[Review proposal]
```

The queue must not use a primary action labelled "Import". Review creates or
rejects a canonical candidate; importing remains separately controlled.

### 3. Candidate review detail

A review detail is an evidence dossier, not a form that asks the operator to
trust a model. It contains:

1. **Conclusion** — missing, duplicate, mismatch, ambiguous, or unsupported.
2. **Statement record** — original posted line and document context.
3. **Wallet comparison** — considered matches, score/rationale, and why none
   was selected when the result is missing.
4. **Advisory evidence** — notifications, email extraction, and enrichment;
   visibly labelled as non-authoritative.
5. **Account mapping** — current validated mapping or a mapping-review block.
6. **Canonical proposal** — shown only for a statement-backed `missing in
   Wallet` conclusion; its fields would form the financial event.
7. **Review action** — missing-in-Wallet proposals can be approved, rejected,
   or deferred. Duplicate, mismatch, and ambiguous cases are resolved as
   review findings only in the pilot, with attributable identity and reason
   where required.

If the statement is `failed`, the detail blocks approval for the pilot. If it
is `unprovable`, ordinary approval is blocked and an authenticated reviewer may
use an explicit, audited override reason; resulting canonical events remain
visibly unproven. If account mapping is uncertain, it must show a proposal and
its rationale; it must not claim the record is mapped.

### 4. Approval confirmation

Approval is a two-step action. The confirmation view shows every selected
canonical proposal that will become a financial event, count and totals by
currency, statement coverage/balance state, and the authenticated operator
identity. Each proposal receives its own durable approval, rejection, or defer
decision even when reviewed in one confirmation session.

The UI must never accept a free-text reviewer identity. It must not imply that a
Wallet record has been created merely because a canonical event was approved.

### 5. Accounts

Accounts are a drill-down, not initial scope. This screen lists discovered
accounts and distinguishes:

- validated Wallet mapping;
- proposed mapping awaiting human confirmation;
- no Wallet account found;
- source account not yet identified;
- mapping conflict or cross-account anomaly.

The account page explains its contribution to a date-range run: statement lines,
matched records, missing candidates, exceptions, and coverage.

### 6. Activity

Activity is the trust surface for the system. It records who reviewed what,
canonical-event creation, controlled import status, and any `unknown` Wallet
outcome awaiting reconciliation. It must show the durable payload identity and
idempotency key, never invite a blind retry.

## UX safety requirements

- Persistent header shows environment and integration mode: `DISABLED`,
  `DRY-RUN`, or `LIVE`.
- Persistent header shows authenticated operator identity when mutation is
  available.
- Advisory, reconciliation, canonical-candidate, and canonical states use one
  shared component and terminology across every screen.
- Preview data for a possible Wallet import is server-generated from the exact
  same payload builder used for submission.
- Errors are inline, retryable where safe, and attached to the failed action;
  no full-screen dead ends.
- Modals are accessible dialogs with focus management and keyboard escape.
- Async loading, success, and error states are announced to assistive
  technology.
- Responsive layouts preserve readable amounts, account context, and primary
  review actions on narrow screens.

## Pilot backlog

### P0 — Ledger correctness and trustworthy review

1. One payload builder for preview and submission; preserve direction, date,
   currency, category, labels, and idempotency exactly.
2. Statement balance proof and approval gate.
3. Validated human account mapping; fuzzy matching is a proposal only.
4. Authentication and session-derived reviewer/audit identity.
5. Date-range reconciliation run with all-account discovery and coverage
   outcomes.
6. Read-only Wallet history ingestion and deterministic statement-to-Wallet
   matching.

### P1 — Pilot operator workflow

7. Runs dashboard and review queues for missing, duplicate, mismatch, ambiguous,
   unmapped, and advisory-awaiting-statement items.
8. Evidence dossier and two-step canonical approval.
9. Accounts drill-down and mapping review.
10. Activity/audit/import-status view, including unresolved `unknown` outcomes.
11. Accessible design-system extraction, error recovery, filters, deep links,
    and responsive layouts.

### P2 — Operations after the pilot loop works

12. Resolver worker for uncertain Wallet outcomes; no blind retries.
13. Scheduled catalog/history synchronization and freshness telemetry.
14. Structured logging, readiness probes, metrics, retention, and privacy
    controls.
15. Push notifications only for material run completion or review exceptions;
    notifications are not the primary operating model.

## Explicitly deferred

- Notification-first workflows and notification-driven record creation.
- Bulk auto-approval or unattended import.
- General-purpose budgeting/analytics features.
- Native mobile clients.
- Broad multi-tenant packaging before the pilot workflow is proven.
