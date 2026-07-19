"""SQLAlchemy 2.0 persistence layer for Wallet V2.

This package contains:

* :mod:`wallet_v2.persistence.base` — declarative base and timestamp mixins
* :mod:`wallet_v2.persistence.types` — project-specific column types
* :mod:`wallet_v2.persistence.models` — typed table models for the 10
  schema stages
* :mod:`wallet_v2.persistence.session` — engine and session factory

No live connections are established on import. The session factory builds
engines on demand from a :class:`~wallet_v2.config.Settings` instance.
"""
