"""FastAPI reconciliation console over :class:`WalletWorkflow`.

This package provides a read/command API surface for the operator console.
Every command route enforces ``IntegrationMode.DRY_RUN`` and records an
``unauthenticated`` initiator in audit evidence.

Production apps must be created via ``create_app()`` which loads validated
settings from the environment. Tests must use ``create_test_app()`` which
wires an in-memory SQLite engine.
"""

from wallet_v2.api.app import create_app, create_test_app

__all__ = ["create_app", "create_test_app"]
