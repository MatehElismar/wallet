"""Shared FastAPI dependencies: database session and workflow.

Session ownership follows the existing caller-owns-session pattern:
the route scopes the session to commit on success and rollback on error.
The engine and session factory are stored on ``app.state`` by the factory.
"""

from __future__ import annotations

from collections.abc import Generator
from typing import Protocol

from fastapi import Request
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from wallet_v2.application.contracts_mcp import McpReadOnlyClient
from wallet_v2.application.service import WalletWorkflow
from wallet_v2.config import Settings
from wallet_v2.persistence.session import session_scope


def get_session(request: Request) -> Generator[Session, None, None]:
    factory: sessionmaker[Session] = request.app.state.session_factory
    with session_scope(factory) as session:
        yield session


def get_mcp_client(request: Request) -> McpReadOnlyClient | None:
    """Resolve the read-only MCP client for advisory enrichment.

    A client explicitly stored on ``app.state.mcp_client`` (used by tests to
    inject a hermetic stand-in) takes precedence. Otherwise a real client is
    built from settings only when the MCP integration is enabled. When MCP is
    disabled the dependency yields ``None``: retrieval endpoints still work,
    and MCP-backed generation fails closed rather than reaching the network.
    """

    explicit = getattr(request.app.state, "mcp_client", None)
    if explicit is not None:
        return explicit
    settings: Settings = request.app.state.settings
    mcp = settings.mcp
    if not mcp.enabled:
        return None
    from wallet_v2.adapters.mcp_client import WalletMcpClient

    return WalletMcpClient(
        base_url=mcp.base_url,  # type: ignore[arg-type]
        api_key=mcp.api_key,  # type: ignore[arg-type]
        timeout_seconds=mcp.timeout_seconds,
    )


class AppContext(Protocol):
    settings: Settings
    engine: Engine
    session_factory: sessionmaker[Session]

    def dispose(self) -> None: ...
