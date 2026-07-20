"""FastAPI application factory for the reconciliation console.

Produces a FastAPI app wired to the existing ``WalletWorkflow`` service.

Production usage calls ``create_app()`` with no arguments; it loads
validated settings from the environment and builds a PostgreSQL engine
through ``create_engine_from_settings``. Missing or invalid production
configuration fails closed via :class:`ConfigError`.

Tests inject an explicit in-memory SQLite engine through
``create_test_app`` so they never touch the environment or a network
database.

The app carries ``app.state.engine``, ``app.state.session_factory``, and
``app.state.settings`` for dependency injection.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from wallet_v2.api.routes import batches, commands, health, push_notifications
from wallet_v2.config import Settings, load_settings
from wallet_v2.persistence.session import (
    create_engine_from_settings,
    create_session_factory,
)


def _build_sqlite_engine_and_factory(database_url: str) -> tuple[object, sessionmaker[Session]]:
    engine = create_engine(
        database_url,
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    return engine, factory


def _create_app_from_settings(settings: Settings) -> FastAPI:
    engine = create_engine_from_settings(settings)
    factory = create_session_factory(engine)

    @asynccontextmanager
    async def lifespan(app: FastAPI):  # pragma: no cover
        app.state.engine = engine
        app.state.session_factory = factory
        app.state.settings = settings
        try:
            yield
        finally:
            engine.dispose()

    app = FastAPI(
        title="Wallet V2 Reconciliation Console",
        version="0.1.0",
        description=(
            "Temporary single-operator console for statement reconciliation. "
            "Unauthenticated and dry-run-only."
        ),
        lifespan=lifespan,
    )
    app.state.engine = engine
    app.state.session_factory = factory
    app.state.settings = settings

    app.include_router(health.router)
    app.include_router(batches.router)
    app.include_router(commands.router)
    app.include_router(push_notifications.router)

    return app


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the FastAPI application from validated settings.

    If *settings* is omitted the factory calls :func:`load_settings`,
    which reads from the environment and fails closed on missing or
    invalid configuration. Production deployments must not pass a
    ``database_url`` — that path is reserved for the test helper.
    """

    resolved = settings if settings is not None else load_settings()
    return _create_app_from_settings(resolved)


def create_test_app(database_url: str = "sqlite:///:memory:") -> FastAPI:
    """Return an app wired to an in-memory SQLite engine for testing.

    This is the **only** path that permits SQLite. It bypasses
    ``load_settings`` and ``create_engine_from_settings`` so tests can
    remain hermetic.
    """

    engine, factory = _build_sqlite_engine_and_factory(database_url)
    from wallet_v2.config import DatabaseSettings

    settings = Settings(
        environment="test",
        database=DatabaseSettings(url=database_url),
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):  # pragma: no cover
        app.state.engine = engine
        app.state.session_factory = factory
        app.state.settings = settings
        try:
            yield
        finally:
            engine.dispose()

    app = FastAPI(
        title="Wallet V2 Reconciliation Console (test)",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.engine = engine
    app.state.session_factory = factory
    app.state.settings = settings

    app.include_router(health.router)
    app.include_router(batches.router)
    app.include_router(commands.router)
    app.include_router(push_notifications.router)

    return app
