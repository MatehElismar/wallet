# Wallet V2 Foundation

Foundation for review-first email-to-Wallet transaction ingestion. It includes
typed configuration, a PostgreSQL-first persistence schema, controlled IMAP,
LLM, and Wallet adapters, and an operator CLI. All integrations default to
disabled; credentials are never committed or logged.

## Requirements

- Python 3.12+
- PostgreSQL 15+ (for running migrations locally; not required to run the test
  suite, which is fully hermetic)

## Layout

```
src/wallet_v2/
    config.py            fail-closed typed settings
    domain/              value objects, enums, typed identifiers
    adapters/            read-only IMAP, OpenAI-compatible LLM, Wallet API
    application/         run-traceable review-first workflow
    persistence/         SQLAlchemy 2.0 models and session factory
    persistence/         engine/session factory (no implicit connection)
alembic/                 migration source of truth
tests/                   hermetic test baseline
docs/architecture.md     architecture and operational invariants
docker-compose.yml       local PostgreSQL service
```

## Workflow

```
notification: execution run -> source message -> processing attempt -> candidate -> observation
                                              -> review task
statement:    execution run -> source message -> processing attempt -> statement -> lines
                                                                    -> reconciliation links
                                                                    -> review batch -> financial event
                                                                                    -> import command
                                                                                    -> wallet attempt -> wallet receipt
```

Each stage is a separate table with immutable records for attempts, import
commands, and receipts. See `docs/architecture.md` for invariants.

## Local development

```bash
uv sync --extra dev
uv run pytest
```

To run migrations against a local database:

```bash
docker compose up -d postgres
uv run alembic upgrade head
```

## Configuration

Settings are loaded from environment variables prefixed with `WALLET_V2__`.
Configuration is **fail-closed**: every integration defaults to `disabled`,
and configuring one without its required fields raises `ConfigError` at load
time. Modes are `disabled`, `dry_run`, and `live`. Mailbox access is always
read-only; the adapter selects the folder read-only and fetches bodies with
`BODY.PEEK[]`, so it has no code path that marks messages as read.

`dry_run` is an execution-run mode: it may read the configured mailbox and use
the configured LLM to create notification observations or statement
reconciliation evidence, but it records Wallet import intent locally and
never makes a Wallet API request. `live` still requires statement-batch review
and an explicit account mapping before a Wallet import can be issued.

### Run up to five recent unread emails

After running the migrations, set only the credentials you intend to use. The
same extractor supports these built-in OpenAI-compatible provider aliases:

| Provider | Set `LLM__PROVIDER` | Endpoint handling |
|---|---|---|
| OpenAI | `openai` | built in |
| Gemini | `gemini` | built in through Google's OpenAI-compatibility endpoint |
| DeepSeek | `deepseek` | built in |
| OpenRouter | `openrouter` | built in |
| GLM or another compatible gateway | provider name of your choice | set `LLM__BASE_URL` |

To switch providers, change `LLM__PROVIDER`, `LLM__MODEL`, and
`LLM__API_KEY`; the workflow, extraction schema, and review path stay the
same. For a provider not in the table, set `LLM__BASE_URL` as well.

```bash
export WALLET_V2__ENVIRONMENT=dev
export WALLET_V2__DATABASE__URL='postgresql+psycopg://...'
export WALLET_V2__MAILBOX__MODE=dry_run
export WALLET_V2__MAILBOX__HOST='imap.example.com'
export WALLET_V2__MAILBOX__PORT=993
export WALLET_V2__MAILBOX__USERNAME='you@example.com'
export WALLET_V2__MAILBOX__PASSWORD='...'
export WALLET_V2__LLM__MODE=dry_run
export WALLET_V2__LLM__PROVIDER=gemini
export WALLET_V2__LLM__MODEL='gemini-3.5-flash'
export WALLET_V2__LLM__API_KEY='...'

uv run wallet-v2 run --mode dry_run --trigger test --label 'five-email-readonly-check' --limit 5
```

The JSON result includes the durable execution-run ID plus each consulted
message's IMAP coordinates, sender, subject, and Message-ID so the operator can
check exactly which five emails were read. Inspect it later with:

```bash
uv run wallet-v2 runs show <execution-run-id>
```

For a controlled historical pass, select every message on one IMAP calendar
date explicitly. This includes read and unread messages, remains read-only,
and is never an unbounded mailbox scan:

```bash
uv run wallet-v2 run \
  --mode dry_run \
  --trigger test \
  --label 'historical-candidate-check' \
  --on-date 2026-07-19
```

After a parser improvement, replay only named historical messages rather than
scanning the inbox again. This creates a fresh append-only processing attempt
and candidate version; it is still read-only and dry-run only:

```bash
uv run wallet-v2 run \
  --mode dry_run \
  --trigger test \
  --label 'targeted-mime-reprocess' \
  --uids 79148,79151,79168 \
  --reprocess
```

Periodic statements are bank-issued posted-activity evidence, not ordinary
notifications. They are stored with account identity, document version,
transaction and posting dates, and one immutable line record per completed
entry. The system proposes only conservative account-scoped matches to earlier
notification observations. A reviewer approves the statement as one batch;
that creates canonical financial events. Notification candidates remain
provisional and cannot be imported directly.

Statement identity is deterministic from the issuing account, statement-level
facts, and normalized line evidence, so the same statement delivered under a
different IMAP UID is ignored rather than becoming a second importable batch.
Statement lines can also be `posted`, `reversed`, or `cancelled`; a reversal
with an unambiguous original reference links to the prior canonical event.

Wallet submission is deliberately not exposed by this CLI yet: approval and a
separate import action are required before any Wallet API call.

See `src/wallet_v2/config.py` for the full variable reference.
