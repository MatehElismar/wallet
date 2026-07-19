"""Fail-closed typed configuration for Wallet V2.

Settings are loaded from environment variables prefixed with ``WALLET_V2__``.
Every live integration (mailbox, LLM, Wallet) defaults to **disabled**, and
enabling one without supplying every required field raises
:class:`ConfigError` at load time.

Design rules enforced here:

* No mock / test fallback flag exists. The application either runs against
  real integrations or against nothing.
* Boolean parsing is strict: only ``"true"`` and ``"false"`` (lowercase) are
  accepted. Anything else raises :class:`ConfigError` rather than being
  coerced.
* Required base settings (``environment``, ``database.url``) have no default
  and must be supplied explicitly.
* Secrets are tagged so they are never surfaced through ``repr``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Mapping, TypeVar

__all__ = [
    "ConfigError",
    "DatabaseSettings",
    "LlmSettings",
    "MailboxSettings",
    "Settings",
    "WalletSettings",
    "load_settings",
    "ENV_PREFIX",
]

ENV_PREFIX = "WALLET_V2__"

_TRUE = "true"
_FALSE = "false"


class ConfigError(ValueError):
    """Raised when configuration fails closed."""


T = TypeVar("T")


def _get(mapping: Mapping[str, str], key: str) -> str | None:
    value = mapping.get(key)
    if value is None:
        return None
    if value == "":
        raise ConfigError(f"{key} is set but empty; unset it or provide a value")
    return value


def _require(mapping: Mapping[str, str], key: str) -> str:
    value = _get(mapping, key)
    if value is None:
        raise ConfigError(f"required environment variable {key} is not set")
    return value


def _parse_bool(mapping: Mapping[str, str], key: str, default: bool) -> bool:
    raw = mapping.get(key)
    if raw is None:
        return default
    if raw == _TRUE:
        return True
    if raw == _FALSE:
        return False
    raise ConfigError(
        f"{key} must be exactly 'true' or 'false' (lowercase), got {raw!r}"
    )


def _parse_int(mapping: Mapping[str, str], key: str) -> int | None:
    raw = mapping.get(key)
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{key} must be an integer, got {raw!r}") from exc


def _parse_float(mapping: Mapping[str, str], key: str, default: float) -> float:
    raw = mapping.get(key)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ConfigError(f"{key} must be a float, got {raw!r}") from exc


def _secret_repr(value: str | None) -> str:
    return "<redacted>" if value else "<unset>"


def _redact_url(url: str) -> str:
    """Strip credentials from a SQLAlchemy URL for safe logging."""

    if "://" not in url:
        return url
    scheme, rest = url.split("://", 1)
    if "@" not in rest:
        return f"{scheme}://{rest}"
    creds, host_part = rest.split("@", 1)
    return f"{scheme}://***@{host_part}"


@dataclass(frozen=True, slots=True)
class DatabaseSettings:
    """PostgreSQL connection settings.

    ``url`` is required and has no default; the application cannot start
    without an explicit database target.
    """

    url: str
    echo: bool = False
    pool_size: int = 5
    max_overflow: int = 10

    def __repr__(self) -> str:
        safe_url = _redact_url(self.url)
        return (
            f"DatabaseSettings(url={safe_url!r}, echo={self.echo}, "
            f"pool_size={self.pool_size}, max_overflow={self.max_overflow})"
        )


@dataclass(frozen=True, slots=True)
class MailboxSettings:
    """Mailbox connector settings (IMAP/Gmail). Disabled by default."""

    enabled: bool = False
    host: str | None = None
    port: int | None = None
    username: str | None = None
    password: str | None = None  # secret
    readonly: bool = True

    def __repr__(self) -> str:
        return (
            f"MailboxSettings(enabled={self.enabled}, host={self.host!r}, "
            f"port={self.port}, username={self.username!r}, "
            f"password={_secret_repr(self.password)}, readonly={self.readonly})"
        )


@dataclass(frozen=True, slots=True)
class LlmSettings:
    """LLM extraction settings. Disabled by default."""

    enabled: bool = False
    provider: str | None = None
    model: str | None = None
    api_key: str | None = None  # secret
    timeout_seconds: float = 30.0

    def __repr__(self) -> str:
        return (
            f"LlmSettings(enabled={self.enabled}, provider={self.provider!r}, "
            f"model={self.model!r}, api_key={_secret_repr(self.api_key)}, "
            f"timeout_seconds={self.timeout_seconds})"
        )


@dataclass(frozen=True, slots=True)
class WalletSettings:
    """Wallet API connector settings. Disabled by default."""

    enabled: bool = False
    base_url: str | None = None
    api_key: str | None = None  # secret
    timeout_seconds: float = 30.0

    def __repr__(self) -> str:
        return (
            f"WalletSettings(enabled={self.enabled}, base_url={self.base_url!r}, "
            f"api_key={_secret_repr(self.api_key)}, "
            f"timeout_seconds={self.timeout_seconds})"
        )


@dataclass(frozen=True, slots=True)
class Settings:
    """Root settings for Wallet V2."""

    environment: str
    database: DatabaseSettings
    mailbox: MailboxSettings = field(default_factory=lambda: MailboxSettings())
    llm: LlmSettings = field(default_factory=lambda: LlmSettings())
    wallet: WalletSettings = field(default_factory=lambda: WalletSettings())

    def __repr__(self) -> str:
        return (
            f"Settings(environment={self.environment!r}, "
            f"database={self.database!r}, mailbox={self.mailbox!r}, "
            f"llm={self.llm!r}, wallet={self.wallet!r})"
        )

    def with_overrides(self, **changes: object) -> "Settings":
        """Return a new ``Settings`` with the given fields replaced.

        Used by tests to construct deterministic settings without rebuilding
        the full env mapping. Production code should use :func:`load_settings`.
        """

        return replace(self, **changes)  # type: ignore[arg-type]


def _build_database(env: Mapping[str, str]) -> DatabaseSettings:
    url = _require(env, f"{ENV_PREFIX}DATABASE__URL")
    echo = _parse_bool(env, f"{ENV_PREFIX}DATABASE__ECHO", default=False)
    pool_size = _parse_int(env, f"{ENV_PREFIX}DATABASE__POOL_SIZE") or 5
    max_overflow = _parse_int(env, f"{ENV_PREFIX}DATABASE__MAX_OVERFLOW") or 10
    if pool_size < 1:
        raise ConfigError("DATABASE__POOL_SIZE must be >= 1")
    if max_overflow < 0:
        raise ConfigError("DATABASE__MAX_OVERFLOW must be >= 0")
    return DatabaseSettings(
        url=url, echo=echo, pool_size=pool_size, max_overflow=max_overflow
    )


def _build_mailbox(env: Mapping[str, str]) -> MailboxSettings:
    enabled = _parse_bool(env, f"{ENV_PREFIX}MAILBOX__ENABLED", default=False)
    host = _get(env, f"{ENV_PREFIX}MAILBOX__HOST")
    port = _parse_int(env, f"{ENV_PREFIX}MAILBOX__PORT")
    username = _get(env, f"{ENV_PREFIX}MAILBOX__USERNAME")
    password = _get(env, f"{ENV_PREFIX}MAILBOX__PASSWORD")
    readonly = _parse_bool(env, f"{ENV_PREFIX}MAILBOX__READONLY", default=True)
    if enabled:
        missing: list[str] = []
        if not host:
            missing.append("MAILBOX__HOST")
        if port is None:
            missing.append("MAILBOX__PORT")
        if not username:
            missing.append("MAILBOX__USERNAME")
        if not password:
            missing.append("MAILBOX__PASSWORD")
        if missing:
            raise ConfigError(
                "mailbox enabled but missing: " + ", ".join(missing)
            )
        if port is not None and not (1 <= port <= 65535):
            raise ConfigError("MAILBOX__PORT must be in 1..65535")
    if not readonly:
        # The V2 mailbox connector is read-only by design; allowing write mode
        # at the configuration level would violate the operational invariant.
        raise ConfigError("MAILBOX__READONLY must be true; write mode is forbidden")
    return MailboxSettings(
        enabled=enabled,
        host=host,
        port=port,
        username=username,
        password=password,
        readonly=readonly,
    )


def _build_llm(env: Mapping[str, str]) -> LlmSettings:
    enabled = _parse_bool(env, f"{ENV_PREFIX}LLM__ENABLED", default=False)
    provider = _get(env, f"{ENV_PREFIX}LLM__PROVIDER")
    model = _get(env, f"{ENV_PREFIX}LLM__MODEL")
    api_key = _get(env, f"{ENV_PREFIX}LLM__API_KEY")
    timeout = _parse_float(env, f"{ENV_PREFIX}LLM__TIMEOUT_SECONDS", default=30.0)
    if enabled:
        missing: list[str] = []
        if not provider:
            missing.append("LLM__PROVIDER")
        if not model:
            missing.append("LLM__MODEL")
        if not api_key:
            missing.append("LLM__API_KEY")
        if missing:
            raise ConfigError("llm enabled but missing: " + ", ".join(missing))
        if timeout <= 0:
            raise ConfigError("LLM__TIMEOUT_SECONDS must be > 0")
    return LlmSettings(
        enabled=enabled,
        provider=provider,
        model=model,
        api_key=api_key,
        timeout_seconds=timeout,
    )


def _build_wallet(env: Mapping[str, str]) -> WalletSettings:
    enabled = _parse_bool(env, f"{ENV_PREFIX}WALLET__ENABLED", default=False)
    base_url = _get(env, f"{ENV_PREFIX}WALLET__BASE_URL")
    api_key = _get(env, f"{ENV_PREFIX}WALLET__API_KEY")
    timeout = _parse_float(env, f"{ENV_PREFIX}WALLET__TIMEOUT_SECONDS", default=30.0)
    if enabled:
        missing: list[str] = []
        if not base_url:
            missing.append("WALLET__BASE_URL")
        if not api_key:
            missing.append("WALLET__API_KEY")
        if missing:
            raise ConfigError("wallet enabled but missing: " + ", ".join(missing))
        if not base_url.startswith(("http://", "https://")):
            raise ConfigError("WALLET__BASE_URL must be an http(s) URL")
        if timeout <= 0:
            raise ConfigError("WALLET__TIMEOUT_SECONDS must be > 0")
    return WalletSettings(
        enabled=enabled,
        base_url=base_url,
        api_key=api_key,
        timeout_seconds=timeout,
    )


def _build_settings(env: Mapping[str, str]) -> Settings:
    environment = _require(env, f"{ENV_PREFIX}ENVIRONMENT").lower()
    if environment not in {"dev", "staging", "prod"}:
        raise ConfigError(
            "ENVIRONMENT must be one of: dev, staging, prod; "
            f"got {environment!r}"
        )
    return Settings(
        environment=environment,
        database=_build_database(env),
        mailbox=_build_mailbox(env),
        llm=_build_llm(env),
        wallet=_build_wallet(env),
    )


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    """Load settings from environment variables.

    By default reads from :data:`os.environ`. Tests should pass an explicit
    mapping to keep themselves hermetic.

    Raises:
        ConfigError: if any required value is missing or any enabled
            integration is incompletely configured.
    """

    source: Mapping[str, str] = (
        MappingProxyType(os.environ) if env is None else env
    )
    return _build_settings(source)
