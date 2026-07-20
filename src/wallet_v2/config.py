"""Fail-closed typed configuration for Wallet V2.

Settings are loaded from environment variables prefixed with ``WALLET_V2__``.
Every live integration (mailbox, LLM, Wallet) defaults to **disabled**, and
moving one to ``dry_run`` or ``live`` without supplying every required field
raises :class:`ConfigError` at load time.

Design rules enforced here:

* No mock / test fallback flag exists. Each integration can be disabled or
  configured for a controlled run. The execution-run mode is the authority
  for whether Wallet submissions are simulated (``dry_run``) or live.
* Mode parsing is strict: only the exact enum values (``disabled``,
  ``dry_run``, ``live``) are accepted. Anything else raises
  :class:`ConfigError` rather than being coerced.
* Boolean parsing is strict: only ``"true"`` and ``"false"`` (lowercase) are
  accepted. Anything else raises :class:`ConfigError` rather than being
  coerced.
* Required base settings (``environment``, ``database.url``) have no default
  and must be supplied explicitly.
* Secrets are tagged so they are never surfaced through ``repr``.
* The mailbox connector is read-only by design; ``readonly`` must be ``true``
  in every mode, including ``disabled``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Mapping, TypeVar

from wallet_v2.domain.enums import IntegrationMode

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


def _parse_mode(mapping: Mapping[str, str], key: str) -> IntegrationMode:
    """Parse a strict ``IntegrationMode`` env value, defaulting to disabled.

    Only exact enum values (``disabled``, ``dry_run``, ``live``) are
    accepted. Any other value raises :class:`ConfigError` to preserve the
    fail-closed contract — case variants such as ``LIVE`` or human-friendly
    synonyms such as ``on`` are rejected rather than coerced.
    """

    raw = mapping.get(key)
    if raw is None:
        return IntegrationMode.DISABLED
    try:
        return IntegrationMode(raw)
    except ValueError as exc:
        allowed = ", ".join(member.value for member in IntegrationMode)
        raise ConfigError(
            f"{key} must be one of: {allowed}; got {raw!r}"
        ) from exc


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
    """Mailbox connector settings (IMAP/Gmail). Disabled by default.

    ``mode`` selects whether the mailbox integration is loaded and whether
    it performs real I/O. The ``enabled`` property is preserved as a
    convenience for callers that previously checked the boolean flag; it is
    ``True`` for both ``dry_run`` and ``live`` modes.

    The mailbox connector is read-only by design: ``readonly`` must be
    ``True`` in every mode, including ``disabled``.
    """

    mode: IntegrationMode = IntegrationMode.DISABLED
    host: str | None = None
    port: int | None = None
    username: str | None = None
    password: str | None = None  # secret
    readonly: bool = True

    @property
    def enabled(self) -> bool:
        return self.mode != IntegrationMode.DISABLED

    def __repr__(self) -> str:
        return (
            f"MailboxSettings(mode={self.mode!r}, host={self.host!r}, "
            f"port={self.port}, username={self.username!r}, "
            f"password={_secret_repr(self.password)}, readonly={self.readonly})"
        )


@dataclass(frozen=True, slots=True)
class LlmSettings:
    """LLM extraction settings. Disabled by default.

    ``mode`` selects whether LLM extraction is available to an execution
    run. Extraction is a read operation against the configured provider; the
    run mode controls Wallet mutation, not whether an email is sent to the
    configured extractor. The ``enabled`` property is preserved as a
    convenience for callers that previously checked the boolean flag.
    """

    mode: IntegrationMode = IntegrationMode.DISABLED
    provider: str | None = None
    model: str | None = None
    api_key: str | None = None  # secret
    base_url: str | None = None
    timeout_seconds: float = 30.0

    @property
    def enabled(self) -> bool:
        return self.mode != IntegrationMode.DISABLED

    def __repr__(self) -> str:
        return (
            f"LlmSettings(mode={self.mode!r}, provider={self.provider!r}, "
            f"model={self.model!r}, api_key={_secret_repr(self.api_key)}, "
            f"base_url={self.base_url!r}, "
            f"timeout_seconds={self.timeout_seconds})"
        )


@dataclass(frozen=True, slots=True)
class WalletSettings:
    """Wallet API connector settings. Disabled by default.

    ``mode`` selects whether the Wallet connector runs and whether
    submissions are simulated (``dry_run``) or sent to the upstream
    provider (``live``). The ``enabled`` property is preserved as a
    convenience for callers that previously checked the boolean flag; it is
    ``True`` for both ``dry_run`` and ``live`` modes.
    """

    mode: IntegrationMode = IntegrationMode.DISABLED
    base_url: str | None = None
    api_key: str | None = None  # secret
    timeout_seconds: float = 30.0

    @property
    def enabled(self) -> bool:
        return self.mode != IntegrationMode.DISABLED

    def __repr__(self) -> str:
        return (
            f"WalletSettings(mode={self.mode!r}, base_url={self.base_url!r}, "
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
    mode = _parse_mode(env, f"{ENV_PREFIX}MAILBOX__MODE")
    host = _get(env, f"{ENV_PREFIX}MAILBOX__HOST")
    port = _parse_int(env, f"{ENV_PREFIX}MAILBOX__PORT")
    username = _get(env, f"{ENV_PREFIX}MAILBOX__USERNAME")
    password = _get(env, f"{ENV_PREFIX}MAILBOX__PASSWORD")
    readonly = _parse_bool(env, f"{ENV_PREFIX}MAILBOX__READONLY", default=True)
    if mode != IntegrationMode.DISABLED:
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
                f"mailbox mode={mode.value} but missing: " + ", ".join(missing)
            )
        if port is not None and not (1 <= port <= 65535):
            raise ConfigError("MAILBOX__PORT must be in 1..65535")
    if not readonly:
        # The V2 mailbox connector is read-only by design; allowing write mode
        # at the configuration level would violate the operational invariant.
        # This holds in every mode, including ``disabled``.
        raise ConfigError("MAILBOX__READONLY must be true; write mode is forbidden")
    return MailboxSettings(
        mode=mode,
        host=host,
        port=port,
        username=username,
        password=password,
        readonly=readonly,
    )


def _build_llm(env: Mapping[str, str]) -> LlmSettings:
    mode = _parse_mode(env, f"{ENV_PREFIX}LLM__MODE")
    provider = _get(env, f"{ENV_PREFIX}LLM__PROVIDER")
    model = _get(env, f"{ENV_PREFIX}LLM__MODEL")
    api_key = _get(env, f"{ENV_PREFIX}LLM__API_KEY")
    base_url = _get(env, f"{ENV_PREFIX}LLM__BASE_URL")
    timeout = _parse_float(env, f"{ENV_PREFIX}LLM__TIMEOUT_SECONDS", default=30.0)
    if mode != IntegrationMode.DISABLED:
        missing: list[str] = []
        if not provider:
            missing.append("LLM__PROVIDER")
        if not model:
            missing.append("LLM__MODEL")
        if not api_key:
            missing.append("LLM__API_KEY")
        if missing:
            raise ConfigError(
                f"llm mode={mode.value} but missing: " + ", ".join(missing)
            )
        if timeout <= 0:
            raise ConfigError("LLM__TIMEOUT_SECONDS must be > 0")
        if base_url and not base_url.startswith(("http://", "https://")):
            raise ConfigError("LLM__BASE_URL must be an http(s) URL")
    return LlmSettings(
        mode=mode,
        provider=provider,
        model=model,
        api_key=api_key,
        base_url=base_url,
        timeout_seconds=timeout,
    )


def _build_wallet(env: Mapping[str, str]) -> WalletSettings:
    mode = _parse_mode(env, f"{ENV_PREFIX}WALLET__MODE")
    base_url = _get(env, f"{ENV_PREFIX}WALLET__BASE_URL")
    api_key = _get(env, f"{ENV_PREFIX}WALLET__API_KEY")
    timeout = _parse_float(env, f"{ENV_PREFIX}WALLET__TIMEOUT_SECONDS", default=30.0)
    if mode != IntegrationMode.DISABLED:
        missing: list[str] = []
        if not base_url:
            missing.append("WALLET__BASE_URL")
        if not api_key:
            missing.append("WALLET__API_KEY")
        if missing:
            raise ConfigError(
                f"wallet mode={mode.value} but missing: " + ", ".join(missing)
            )
        if not base_url.startswith(("http://", "https://")):
            raise ConfigError("WALLET__BASE_URL must be an http(s) URL")
        if timeout <= 0:
            raise ConfigError("WALLET__TIMEOUT_SECONDS must be > 0")
    return WalletSettings(
        mode=mode,
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
        ConfigError: if any required value is missing or any integration
            whose mode is not ``disabled`` is incompletely configured.
    """

    source: Mapping[str, str] = (
        MappingProxyType(os.environ) if env is None else env
    )
    return _build_settings(source)
