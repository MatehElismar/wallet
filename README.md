# Wallet V2 Foundation

Foundation for email-to-Wallet transaction ingestion. This milestone delivers the
safe V2 scaffolding only: typed configuration, domain primitives, a
PostgreSQL-first persistence schema with Alembic migrations, and an initial
test baseline.

**No live connectors are enabled.** There is no IMAP/Gmail client, no LLM
client, and no Wallet client in this codebase. There are no credentials, no
mock fallbacks, and no network calls.

## Requirements

- Python 3.12+
- PostgreSQL 15+ (for running migrations locally; not required to run the test
  suite, which is fully hermetic)

## Layout

```
src/wallet_v2/
    config.py            fail-closed typed settings
    domain/              value objects, enums, typed identifiers
    models/              SQLAlchemy 2.0 typed models for the 7 schema stages
    persistence/         engine/session factory (no implicit connection)
alembic/                 migration source of truth
tests/                   hermetic test baseline
docs/architecture.md     architecture and operational invariants
docker-compose.yml       local PostgreSQL service
```

## Workflow

```
source message -> processing attempt -> transaction candidate
                                       -> review task
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
Configuration is **fail-closed**: live integrations default to disabled, and
enabling one without supplying every required field raises `ConfigError` at
load time. There is no mock or test fallback mode.

See `src/wallet_v2/config.py` for the full variable reference.
