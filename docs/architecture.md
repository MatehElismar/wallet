# Wallet V2 — Architecture

This document describes the safe V2 foundation: the workflow stages, the
domain primitives, the persistence schema, and the operational invariants
that hold across them. It is the canonical reference for the code in
`src/wallet_v2/` and the migration in `alembic/versions/0001_initial.py`.

## Scope of this milestone

The foundation delivers scaffolding only. There are **no live
connectors** in this codebase:

- No IMAP / Gmail client.
- No LLM client.
- No Wallet API client.
- No credentials, no mock fallbacks, no network calls.

Every external adapter is dependency-injected by the (future) application
layer. The foundation's job is to define the durable shape those adapters
will populate: domain primitives, a PostgreSQL-first schema, and the
invariants that keep the financial path safe.

## Workflow

```
inbox (mailbox source)
  └── source_message  ── hash-only, no raw MIME
        └── processing_attempt  ── immutable, append-only
              └── transaction_candidate  ── versioned
                    └── review_task ── review_decisions (immutable)
                          └── import_command  ── immutable, deterministic idempotency
                                └── wallet_attempt  ── immutable, append-only
                                      └── wallet_receipt  ── nullable until confirmed
```

Every arrow is a foreign key with `ondelete="RESTRICT"` unless the child
is purely descriptive (e.g. `message_content_metadata` cascades with its
parent `source_message`). Audit events hang off the side as a soft-FK
append-only log.

## Domain primitives

`src/wallet_v2/domain/` — pure Python, no SQLAlchemy, no I/O.

### Money

`Money` is an **unsigned** magnitude in integer minor units plus an
ISO 4217 currency code:

- `minor: int` — non-negative, no `bool`, no `float`, no `Decimal`.
- `currency: str` — exactly 3 uppercase ASCII letters.
- Rejects negative `minor`, non-`int` types, malformed currency codes.
- Addition and comparison raise `CurrencyMismatch` across currencies.
- `is_zero()` / `is_positive()` are the only sanctioned predicates.

`Money` is zero-capable on purpose: a fee component that was not assessed
is legitimately `Money(0, "USD")`. A *transaction* is not.

### TransactionAmount

`TransactionAmount` wraps `Money` and enforces a **strictly positive**
magnitude at construction. The domain layer uses this type wherever a
transaction is modelled (candidates, import commands, receipts). The
sign of a transaction is encoded separately by `TransactionDirection`
(`debit` / `credit`), never by a negative amount.

### MailboxCursor

`MailboxCursor(uid_validity, last_seen_uid)` is the monotonic read
position for a mailbox source:

- Both fields are positive integers (`>= 1`).
- Equality is on the pair `(uid_validity, last_seen_uid)`.
- Ordering across different `uid_validity` epochs raises
  `CursorEpochMismatch` — epochs must be handled explicitly, never by
  silent arithmetic.
- `advance(other)` returns the max of two same-epoch cursors.
- `is_strictly_after(other)` is the monotonic-forward check.

### MailboxSource

`MailboxSource(provider, account_fingerprint, folder, status, cursor)` is the
durable identity of a mailbox account/folder:

- `provider` — lowercase, ≤32 chars.
- `account_fingerprint` — exactly 64 lowercase hex chars (SHA-256).
- `folder` — non-empty provider folder name, preserved exactly (for example,
  the IMAP standard `INBOX`).
- `status` — `MailboxSourceStatus` (`active | paused | drained | revoked`).
- `cursor` — last-committed `MailboxCursor`, or `None`.
- Identity is `(provider, account_fingerprint, folder)`; cursor and status are
  operational state and do not contribute to equality or hashing.
- `with_cursor(...)` refuses silent cross-epoch replacement.
- `reset_cursor(...)` is the explicit operation for a UIDVALIDITY epoch reset.

## Configuration

`src/wallet_v2/config.py` loads settings from environment variables
prefixed `WALLET_V2__`. It is **fail-closed**:

- Every live integration (`mailbox`, `llm`, `wallet`) defaults to
  `enabled=false`.
- Enabling one requires every required field for that integration to be
  set to a non-empty value; otherwise `ConfigError` is raised at load
  time.
- Booleans parse only the lowercase `"true"` / `"false"`; anything else
  raises `ConfigError`.
- `WALLET_V2__DATABASE__URL` and `WALLET_V2__ENVIRONMENT` (one of
  `dev | staging | prod`) have no defaults and are required.
- Secrets (`password`, `api_key`) are redacted in `repr`.
- The mailbox connector is forced read-only: `WALLET_V2__MAILBOX__READONLY`
  must be `true`.

There is no mock or test fallback mode.

## Persistence schema

`src/wallet_v2/persistence/` — SQLAlchemy 2.0 typed declarative models.
Twelve tables, grouped by workflow stage:

| Table | Stage | Mutable? | Key invariant |
|---|---|---|---|
| `inboxes` | source identity | yes | unique `(provider, account_fingerprint, folder)` |
| `inbox_cursor_history` | cursor audit | **no** | append-only cursor advances |
| `source_messages` | source message | yes | unique `(inbox_id, uid_validity, message_uid)` |
| `message_content_metadata` | content | yes | 1:1 with `source_messages`, PII-scoped |
| `processing_attempts` | attempt | **no** | unique `idempotency_key`, no `updated_at` |
| `transaction_candidates` | candidate | yes | unique `(source_message_id, candidate_version)` |
| `review_tasks` | review | yes | 1:1 with candidate |
| `review_decisions` | decision | **no** | append-only, no `updated_at` |
| `import_commands` | import | **no** | unique `idempotency_key`, no `updated_at` |
| `wallet_attempts` | wallet submit | **no** | unique `(import_command_id, attempt_index)` |
| `wallet_receipts` | receipt | yes | 1:1 with `import_commands`, nullable until confirmed |
| `audit_events` | audit | **no** | append-only, soft FK |

### Money in the schema

Monetary amounts are stored as a pair of columns: `amount_minor`
(`BIGINT`, integer minor units — never `float` or `Decimal`) and
`currency` (`CHAR(3)` ISO 4217). A `CHECK` constraint enforces
`amount_minor >= 0`; the strictly-positive invariant for *transactions*
is enforced at the application layer via `TransactionAmount`. This keeps
`Money` zero-capable for fees and adjustments while still rejecting
malformed rows at the database boundary.

### Idempotency

Two tables carry a unique `idempotency_key`:

- `processing_attempts.idempotency_key` — a crashed retry that re-issues
  the same key loses the race with a unique-constraint violation rather
  than creating a duplicate attempt.
- `import_commands.idempotency_key` — deterministic per candidate. The
  Wallet provider must honour it for exactly-once semantics; a retry with
  the same key returns the existing transaction, never a duplicate.

### Import command state machine

```
queued -> in_flight -> succeeded | failed | unknown
unknown -> succeeded | failed        (resolved by reconciliation)
succeeded -> reconciled              (receipt matched)
failed    -> reconciled              (terminal reconciliation note)
```

`unknown` is the post-timeout hold state: the Wallet provider may have
applied the transaction but the response was lost. Resolving `unknown`
requires an out-of-band reconciliation query — **never a blind retry**
with a new idempotency key. The `ImportCommand` row is immutable after
insert; transitions are recorded as `audit_events` rows, not by mutating
the command.

### Immutability signal

Tables that use the `Immutable` mixin (`processing_attempts`,
`review_decisions`, `import_commands`, `wallet_attempts`,
`audit_events`, `inbox_cursor_history`) have **no `updated_at` column**.
The absence of `updated_at` is a schema-level signal of the immutability
invariant: any code that tries to add an `updated_at` column to one of
those tables is breaking the invariant, not extending the schema.

## Alembic

`alembic/` — hand-written initial migration (`0001_initial`), per the
DeepSeek V4 review's recommendation (section 9.3) that the initial
migration be reviewable rather than autogenerated. The migration is
PostgreSQL-specific: it uses `UUID`, `JSONB`, `TIMESTAMPTZ`,
`gen_random_uuid()` defaults, and explicit `CHECK` constraints.

Run locally:

```bash
docker compose up -d postgres
WALLET_V2__DATABASE__URL=postgresql+psycopg://wallet_v2:wallet_v2@localhost:5432/wallet_v2 \
  uv run alembic upgrade head
```

## Tests

`tests/` — hermetic; no network, no database required. The test suite
exercises:

- `Money` construction, addition, comparison, currency mismatch,
  round-trip serialization, zero-capable magnitude.
- `TransactionAmount` strictly-positive invariant.
- `MailboxCursor` / `MailboxSource` identity, epoch mismatch, monotonic
  advance.
- Configuration fail-closed behaviour for every integration.
- Source identity constraints (inbox unique triple, source message
  unique triple).
- Attempt and import-command idempotency constraints (unique keys).
- Import-command `unknown` state is representable and reachable.

Run with:

```bash
uv run pytest
```

## Non-goals (this milestone)

- No migration of legacy data or credentials.
- No live IMAP, Gmail, LLM, or Wallet API calls.
- No automatic import functionality.
- No reconciliation job implementation (schema and states are in place;
  the job is a near-term follow-up).
