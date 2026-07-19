"""Tests for lazy persistence runtime wiring."""

from __future__ import annotations

from wallet_v2.config import load_settings
from wallet_v2.persistence.session import (
    create_engine_from_settings,
    create_session_factory,
)


def _settings():
    return load_settings(
        {
            "WALLET_V2__ENVIRONMENT": "dev",
            "WALLET_V2__DATABASE__URL": "postgresql+psycopg://user:pass@localhost:5432/wallet_v2",
        }
    )


def test_create_engine_is_lazy_and_uses_configured_url() -> None:
    engine = create_engine_from_settings(_settings())
    try:
        assert engine.url.drivername == "postgresql+psycopg"
        assert engine.url.database == "wallet_v2"
    finally:
        engine.dispose()


def test_session_factory_does_not_connect_on_construction() -> None:
    engine = create_engine_from_settings(_settings())
    try:
        factory = create_session_factory(engine)
        session = factory()
        try:
            assert session.bind is engine
        finally:
            session.close()
    finally:
        engine.dispose()
