# Wallet V2 — Historical Ledger Reconciliation Pilot

## Product decision

Wallet V2 is a **historical ledger-reconciliation tool**.

An operator selects a date range. Wallet V2 discovers the relevant bank and
Wallet accounts, reads existing Wallet history, ingests available statement and
mail evidence, and identifies what appears to be missing, duplicated, or
uncertain in Wallet.

The product proposes candidates for canonical financial events. It does not
silently repair a ledger and it does not treat email or LLM output as authority.

## Product promise

> Choose a period. Wallet V2 finds what Wallet missed, proves it against bank
> evidence where available, and lets an operator repair history without
> guessing.

## The reconciliation run

The primary unit of work is a **historical reconciliation run**, defined by:

- a required inclusive date range;
- the available configured sources for that period; and
- a durable execution record with the evidence, matching decisions, and
  operator actions it produced.

The operator does **not** select an account to start a run. Accounts are
internal matching and reporting dimensions:

1. Discover bank/card accounts from statements and account evidence.
2. Read Wallet history for the chosen period across available Wallet accounts.
3. Propose account mappings where identity is sufficiently clear; only a human
   review can validate a mapping for canonicalization or import.
4. Reconcile statement lines to Wallet entries within the validated mapped
   account. A possible cross-account match is an anomaly, not an automatic
   match.
5. Surface unmapped or ambiguous account identity as an exception, not as a
   reason to hide the rest of the period.

Cross-account matching must never happen silently. A possible cross-account
match is an explicit anomaly for operator review.

## Evidence and authority model

The system must make the source and authority of every conclusion visible.

| Evidence class | Meaning | May create a canonical candidate? | May create or update a Wallet record? |
|---|---|---:|---:|
| Posted statement line | Bank-issued posted activity | Yes, after reconciliation | Only after review approval and the controlled import gate |
| Existing Wallet entry | Current ledger baseline | No; it can satisfy or conflict with a statement line | No |
| Notification/email observation | Provisional context, timing, merchant clues | No on its own | Never |
| LLM/MCP enrichment | Advisory classification or matching support | No on its own | Never |
| Human review approval | Attributable acceptance of a statement-backed proposal | Creates canonical event | Enables the separately controlled import path |

The existing safety invariant remains non-negotiable:

```text
notification or LLM output -> advisory evidence only
posted statement line + human approval -> canonical financial event
approved canonical event + controlled import gate -> Wallet write
```

## Reconciliation outcomes

Each posted statement line in the selected period should reach one explicit
outcome:

- **matched** — a reliable existing Wallet entry already represents it;
- **missing in Wallet** — no reliable Wallet entry exists; propose a canonical
  candidate for operator review;
- **possible duplicate** — more than one Wallet entry may represent it;
- **mismatch** — a Wallet entry is present but differs materially in amount,
  date, direction, account, or other controlled fields; this is a review
  finding only in the pilot, not a Wallet-mutation request;
- **ambiguous** — the system cannot safely decide among plausible matches;
- **account mapping review required** — evidence exists but the source account
  cannot be safely linked to a Wallet account.

Uncorroborated advisory observations are tracked in a separate **awaiting
statement evidence** queue. They are excluded from statement-line coverage
math, cannot create canonical proposals, and cannot become Wallet writes.

A canonical proposal is not an import request. The system should show why it
was proposed, what evidence supports it, which Wallet records were considered,
and what human decision is needed. In the pilot, only a `missing in Wallet`
outcome can propose a new canonical event; duplicate and mismatch findings are
reviewable but their correction or deletion paths are explicitly out of scope.

## Operator workflow

```text
Choose date range
  -> discover sources and accounts
  -> ingest statements and read Wallet history
  -> reconcile all discovered accounts
  -> review coverage and exceptions
  -> review missing/mismatched/ambiguous candidates
  -> approve statement-backed candidates as canonical events
  -> use the separately controlled Wallet import path
```

The first screen for a run should answer:

```text
Jan 1–Dec 31, 2025

Accounts discovered: 8
  6 mapped and reconciled · 1 requires mapping review · 1 has no Wallet history

Posted statement lines: 2,418
  2,243 matched in Wallet
  94 missing in Wallet
  31 possible duplicates
  18 ambiguous
  32 account mapping review required

Separate advisory evidence: 14 observations awaiting statement evidence
```

Accounts remain available as drill-down and grouping context. They are not the
initial scope selector.

## Pilot scope

The pilot succeeds if a single operator can safely repair a chosen historical
period across all discovered accounts.

### In scope

- Date-range reconciliation runs across all discovered accounts.
- Read-only Wallet history ingestion and deterministic matching.
- Statement ingestion, statement completeness/balance proof, and account
  mapping proposals.
- Missing-entry, duplicate, mismatch, ambiguous, unmapped-account, and
  separate advisory-awaiting-statement queues.
- Evidence-rich canonical-candidate review.
- Human-approved canonical events and a separately controlled, idempotent
  Wallet import path. Import is a distinct authenticated action after
  canonical approval, gated by validated account mapping, finalized decision,
  `LIVE` mode, and the server-generated exact payload preview.
- Immutable audit trail and attributable operator decisions.

### Explicitly out of scope for the pilot

- Real-time notification-first operation.
- Notification-triggered financial writes.
- Unattended imports or auto-approval.
- General budgeting, spending analytics, or a replacement Wallet client.
- Native mobile clients and broad multi-tenant SaaS packaging.

## Product surface

The intended operator navigation is:

- **Runs** — date-range reconciliation coverage, state, and exceptions.
- **Review** — missing, duplicate, mismatch, ambiguous, mapping-exception,
  and advisory-awaiting-statement queues.
- **Evidence** — statements, observations, matching rationale, and balance
  proof.
- **Accounts** — discovered accounts, mappings, and coverage by account.
- **Activity** — approvals, import status, exceptions, and audit history.

Use distinct terms in product UI and documentation: **notification
observations** are supporting evidence, **reconciliation cases** are matching
outcomes, and **canonical proposals** are statement-backed items eligible for
approval. Notification observations must not be positioned as the main
workspace.

## Pilot acceptance criteria

The product is ready for pilot use only when it can demonstrate all of the
following for a selected date range:

1. It discovers and groups all available bank and Wallet accounts without
   requiring account-by-account setup before the run.
2. It records the coverage outcome of every ingested statement line.
3. It proves statement completeness when opening and closing balances are
   available, clearly distinguishes `proven`, `unprovable`, and `failed`, and
   refuses ordinary approval unless the result is `proven`.
4. It never presents an email-only or LLM-only item as importable.
5. It displays every missing-entry proposal with source evidence and its Wallet
   matching rationale.
6. An `unprovable` statement requires an authenticated reviewer, an explicit
   override reason, an audit event, and a visible unproven marker on every
   resulting canonical event; a `failed` statement cannot be overridden in the
   pilot.
7. It requires an attributable human approval before creating a canonical
   event, and only a reviewed mapping can authorize its account.
8. Wallet history ingestion is read-only; the baseline cannot be mutated by a
   reconciliation run.
9. It uses exactly one validated payload path for preview and Wallet
   submission, with deterministic idempotency and an explicit resolution path
   for uncertain external outcomes.
10. Canonical approval alone never creates a Wallet record: an authenticated
   operator must invoke the separately controlled import action under the
   documented import gates.
