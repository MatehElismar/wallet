"""Alembic environment for Wallet V2.

The migration environment runs against the project's
:class:`~wallet_v2.persistence.base.Base.metadata` so autogeneration and
the hand-written migration target the same set of tables.

Two modes:

* **Online** — connects to the database specified by
  ``WALLET_V2__DATABASE__URL`` and runs migrations in a transaction.
* **Offline** — emits SQL to stdout without a live connection. Used by
  ``alembic upgrade head --sql`` for review.

No live network calls happen at import time. The engine is built only
when a migration command actually runs.
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from wallet_v2.persistence.base import Base
from wallet_v2.persistence.models import *  # noqa: F401,F403 - registers all models

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

_env_url = os.environ.get("WALLET_V2__DATABASE__URL")
if _env_url:
    config.set_main_option("sqlalchemy.url", _env_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Emit SQL to stdout without a live connection."""

    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live database."""

    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
