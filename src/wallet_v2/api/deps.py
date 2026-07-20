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

from wallet_v2.application.service import WalletWorkflow
from wallet_v2.config import Settings
from wallet_v2.persistence.session import session_scope


def get_session(request: Request) -> Generator[Session, None, None]:
    factory: sessionmaker[Session] = request.app.state.session_factory
    with session_scope(factory) as session:
        yield session


class AppContext(Protocol):
    settings: Settings
    engine: Engine
    session_factory: sessionmaker[Session]

    def dispose(self) -> None: ...
