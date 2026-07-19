"""Wallet V2 foundation package.

This package contains the safe V2 scaffolding only: domain primitives, typed
fail-closed configuration, SQLAlchemy 2.0 models, and a persistence session
factory. There are no live connectors, no network calls, no LLM client, and no
Wallet client in this milestone.
"""

from wallet_v2._version import __version__

__all__ = ["__version__"]
