"""Tests for the fail-closed configuration loader."""

from __future__ import annotations

import pytest

from wallet_v2.config import ConfigError, load_settings


def _env(**overrides: str) -> dict[str, str]:
    base: dict[str, str] = {
        "WALLET_V2__ENVIRONMENT": "dev",
        "WALLET_V2__DATABASE__URL": (
            "postgresql+psycopg://wallet_v2:wallet_v2@localhost:5432/wallet_v2"
        ),
    }
    base.update(overrides)
    return base


class TestRequiredSettings:
    def test_missing_environment_raises(self) -> None:
        env = _env()
        del env["WALLET_V2__ENVIRONMENT"]
        with pytest.raises(ConfigError):
            load_settings(env)

    def test_missing_database_url_raises(self) -> None:
        env = _env()
        del env["WALLET_V2__DATABASE__URL"]
        with pytest.raises(ConfigError):
            load_settings(env)

    def test_invalid_environment_raises(self) -> None:
        with pytest.raises(ConfigError):
            load_settings(_env(**{"WALLET_V2__ENVIRONMENT": "production"}))

    def test_valid_environments(self) -> None:
        for value in ("dev", "staging", "prod"):
            s = load_settings(_env(**{"WALLET_V2__ENVIRONMENT": value}))
            assert s.environment == value


class TestDefaultDisabled:
    def test_all_integrations_disabled_by_default(self) -> None:
        s = load_settings(_env())
        assert s.mailbox.enabled is False
        assert s.llm.enabled is False
        assert s.wallet.enabled is False


class TestMailboxFailClosed:
    def _full_mailbox_env(self, **overrides: str) -> dict[str, str]:
        env = _env(
            **{
                "WALLET_V2__MAILBOX__ENABLED": "true",
                "WALLET_V2__MAILBOX__HOST": "imap.example.com",
                "WALLET_V2__MAILBOX__PORT": "993",
                "WALLET_V2__MAILBOX__USERNAME": "u",
                "WALLET_V2__MAILBOX__PASSWORD": "p",
            }
        )
        env.update(overrides)
        return env

    def test_enabled_without_host_raises(self) -> None:
        env = self._full_mailbox_env()
        del env["WALLET_V2__MAILBOX__HOST"]
        with pytest.raises(ConfigError):
            load_settings(env)

    def test_enabled_without_password_raises(self) -> None:
        env = self._full_mailbox_env()
        del env["WALLET_V2__MAILBOX__PASSWORD"]
        with pytest.raises(ConfigError):
            load_settings(env)

    def test_enabled_full_loads(self) -> None:
        s = load_settings(self._full_mailbox_env())
        assert s.mailbox.enabled is True
        assert s.mailbox.host == "imap.example.com"

    def test_readonly_must_be_true(self) -> None:
        env = self._full_mailbox_env(
            **{"WALLET_V2__MAILBOX__READONLY": "false"}
        )
        with pytest.raises(ConfigError):
            load_settings(env)

    def test_yes_not_accepted_as_bool(self) -> None:
        env = _env(**{"WALLET_V2__MAILBOX__ENABLED": "yes"})
        with pytest.raises(ConfigError):
            load_settings(env)


class TestLlmFailClosed:
    def test_enabled_without_api_key_raises(self) -> None:
        env = _env(
            **{
                "WALLET_V2__LLM__ENABLED": "true",
                "WALLET_V2__LLM__PROVIDER": "deepseek",
                "WALLET_V2__LLM__MODEL": "deepseek-v4-pro",
            }
        )
        with pytest.raises(ConfigError):
            load_settings(env)

    def test_enabled_full_loads(self) -> None:
        env = _env(
            **{
                "WALLET_V2__LLM__ENABLED": "true",
                "WALLET_V2__LLM__PROVIDER": "deepseek",
                "WALLET_V2__LLM__MODEL": "deepseek-v4-pro",
                "WALLET_V2__LLM__API_KEY": "sk-xxx",
            }
        )
        s = load_settings(env)
        assert s.llm.enabled is True
        assert s.llm.model == "deepseek-v4-pro"


class TestWalletFailClosed:
    def test_enabled_without_base_url_raises(self) -> None:
        env = _env(
            **{
                "WALLET_V2__WALLET__ENABLED": "true",
                "WALLET_V2__WALLET__API_KEY": "k",
            }
        )
        with pytest.raises(ConfigError):
            load_settings(env)

    def test_enabled_without_api_key_raises(self) -> None:
        env = _env(
            **{
                "WALLET_V2__WALLET__ENABLED": "true",
                "WALLET_V2__WALLET__BASE_URL": "https://wallet.example.com",
            }
        )
        with pytest.raises(ConfigError):
            load_settings(env)

    def test_enabled_non_http_url_raises(self) -> None:
        env = _env(
            **{
                "WALLET_V2__WALLET__ENABLED": "true",
                "WALLET_V2__WALLET__BASE_URL": "ftp://wallet.example.com",
                "WALLET_V2__WALLET__API_KEY": "k",
            }
        )
        with pytest.raises(ConfigError):
            load_settings(env)

    def test_enabled_full_loads(self) -> None:
        env = _env(
            **{
                "WALLET_V2__WALLET__ENABLED": "true",
                "WALLET_V2__WALLET__BASE_URL": "https://wallet.example.com",
                "WALLET_V2__WALLET__API_KEY": "k",
            }
        )
        s = load_settings(env)
        assert s.wallet.enabled is True
        assert s.wallet.base_url == "https://wallet.example.com"


class TestSecretRedaction:
    def test_mailbox_password_redacted_in_repr(self) -> None:
        env = _env(
            **{
                "WALLET_V2__MAILBOX__ENABLED": "true",
                "WALLET_V2__MAILBOX__HOST": "imap.example.com",
                "WALLET_V2__MAILBOX__PORT": "993",
                "WALLET_V2__MAILBOX__USERNAME": "u",
                "WALLET_V2__MAILBOX__PASSWORD": "super-secret",
            }
        )
        s = load_settings(env)
        repr_text = repr(s)
        assert "super-secret" not in repr_text
        assert "<redacted>" in repr_text

    def test_database_url_credentials_redacted(self) -> None:
        env = _env(
            **{
                "WALLET_V2__DATABASE__URL": (
                    "postgresql+psycopg://user:hunter2@host/db"
                ),
            }
        )
        s = load_settings(env)
        repr_text = repr(s)
        assert "hunter2" not in repr_text
        assert "***" in repr_text
