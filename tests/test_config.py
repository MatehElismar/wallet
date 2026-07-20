"""Tests for the fail-closed configuration loader."""

from __future__ import annotations

import pytest

from wallet_v2.config import ConfigError, load_settings
from wallet_v2.domain.enums import IntegrationMode


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
        assert s.mailbox.mode is IntegrationMode.DISABLED
        assert s.llm.mode is IntegrationMode.DISABLED
        assert s.wallet.mode is IntegrationMode.DISABLED
        assert s.mcp.mode is IntegrationMode.DISABLED
        # enabled convenience property agrees with mode != disabled.
        assert s.mailbox.enabled is False
        assert s.llm.enabled is False
        assert s.wallet.enabled is False
        assert s.mcp.enabled is False

    def test_disabled_requires_no_credentials(self) -> None:
        # No mailbox/llm/wallet credentials supplied; disabled mode loads
        # without raising.
        s = load_settings(_env())
        assert s.mailbox.host is None
        assert s.mailbox.password is None
        assert s.llm.api_key is None
        assert s.wallet.base_url is None
        assert s.wallet.api_key is None

    def test_invalid_mode_raises(self) -> None:
        # "enabled" was the old boolean value; it must not be silently
        # accepted as a mode.
        env = _env(**{"WALLET_V2__MAILBOX__MODE": "enabled"})
        with pytest.raises(ConfigError):
            load_settings(env)

    def test_mode_is_case_sensitive(self) -> None:
        env = _env(**{"WALLET_V2__MAILBOX__MODE": "LIVE"})
        with pytest.raises(ConfigError):
            load_settings(env)

    def test_mode_strict_no_synonyms(self) -> None:
        for value in ("on", "yes", "1", "true"):
            env = _env(**{"WALLET_V2__MAILBOX__MODE": value})
            with pytest.raises(ConfigError):
                load_settings(env)


class TestMailboxFailClosed:
    def _full_mailbox_env(self, **overrides: str) -> dict[str, str]:
        env = _env(
            **{
                "WALLET_V2__MAILBOX__MODE": "live",
                "WALLET_V2__MAILBOX__HOST": "imap.example.com",
                "WALLET_V2__MAILBOX__PORT": "993",
                "WALLET_V2__MAILBOX__USERNAME": "u",
                "WALLET_V2__MAILBOX__PASSWORD": "p",
            }
        )
        env.update(overrides)
        return env

    @pytest.mark.parametrize("mode", ["dry_run", "live"])
    def test_non_disabled_without_host_raises(self, mode: str) -> None:
        env = self._full_mailbox_env(**{"WALLET_V2__MAILBOX__MODE": mode})
        del env["WALLET_V2__MAILBOX__HOST"]
        with pytest.raises(ConfigError):
            load_settings(env)

    @pytest.mark.parametrize("mode", ["dry_run", "live"])
    def test_non_disabled_without_password_raises(self, mode: str) -> None:
        env = self._full_mailbox_env(**{"WALLET_V2__MAILBOX__MODE": mode})
        del env["WALLET_V2__MAILBOX__PASSWORD"]
        with pytest.raises(ConfigError):
            load_settings(env)

    def test_live_full_loads(self) -> None:
        s = load_settings(self._full_mailbox_env())
        assert s.mailbox.mode is IntegrationMode.LIVE
        assert s.mailbox.enabled is True
        assert s.mailbox.host == "imap.example.com"

    def test_dry_run_full_loads(self) -> None:
        env = self._full_mailbox_env(
            **{"WALLET_V2__MAILBOX__MODE": "dry_run"}
        )
        s = load_settings(env)
        assert s.mailbox.mode is IntegrationMode.DRY_RUN
        assert s.mailbox.enabled is True

    def test_readonly_must_be_true_when_disabled(self) -> None:
        # The read-only invariant holds in every mode, including disabled.
        env = _env(**{"WALLET_V2__MAILBOX__READONLY": "false"})
        with pytest.raises(ConfigError):
            load_settings(env)

    def test_readonly_must_be_true_when_live(self) -> None:
        env = self._full_mailbox_env(
            **{"WALLET_V2__MAILBOX__READONLY": "false"}
        )
        with pytest.raises(ConfigError):
            load_settings(env)


class TestLlmFailClosed:
    @pytest.mark.parametrize("mode", ["dry_run", "live"])
    def test_non_disabled_without_api_key_raises(self, mode: str) -> None:
        env = _env(
            **{
                "WALLET_V2__LLM__MODE": mode,
                "WALLET_V2__LLM__PROVIDER": "deepseek",
                "WALLET_V2__LLM__MODEL": "deepseek-v4-pro",
            }
        )
        with pytest.raises(ConfigError):
            load_settings(env)

    def test_live_full_loads(self) -> None:
        env = _env(
            **{
                "WALLET_V2__LLM__MODE": "live",
                "WALLET_V2__LLM__PROVIDER": "deepseek",
                "WALLET_V2__LLM__MODEL": "deepseek-v4-pro",
                "WALLET_V2__LLM__API_KEY": "sk-xxx",
            }
        )
        s = load_settings(env)
        assert s.llm.mode is IntegrationMode.LIVE
        assert s.llm.enabled is True
        assert s.llm.model == "deepseek-v4-pro"

    def test_dry_run_full_loads(self) -> None:
        env = _env(
            **{
                "WALLET_V2__LLM__MODE": "dry_run",
                "WALLET_V2__LLM__PROVIDER": "deepseek",
                "WALLET_V2__LLM__MODEL": "deepseek-v4-pro",
                "WALLET_V2__LLM__API_KEY": "sk-xxx",
            }
        )
        s = load_settings(env)
        assert s.llm.mode is IntegrationMode.DRY_RUN
        assert s.llm.enabled is True

    def test_custom_base_url_loads_for_openai_compatible_provider(self) -> None:
        env = _env(
            **{
                "WALLET_V2__LLM__MODE": "dry_run",
                "WALLET_V2__LLM__PROVIDER": "glm",
                "WALLET_V2__LLM__MODEL": "glm-5",
                "WALLET_V2__LLM__API_KEY": "k",
                "WALLET_V2__LLM__BASE_URL": "https://glm.example.test/v1",
            }
        )
        assert load_settings(env).llm.base_url == "https://glm.example.test/v1"

    @pytest.mark.parametrize("provider", ["openai", "gemini", "deepseek"])
    def test_builtin_provider_needs_no_explicit_base_url(self, provider: str) -> None:
        env = _env(
            **{
                "WALLET_V2__LLM__MODE": "dry_run",
                "WALLET_V2__LLM__PROVIDER": provider,
                "WALLET_V2__LLM__MODEL": "test-model",
                "WALLET_V2__LLM__API_KEY": "k",
            }
        )
        assert load_settings(env).llm.base_url is None

    def test_custom_base_url_must_be_http(self) -> None:
        env = _env(
            **{
                "WALLET_V2__LLM__MODE": "dry_run",
                "WALLET_V2__LLM__PROVIDER": "glm",
                "WALLET_V2__LLM__MODEL": "glm-5",
                "WALLET_V2__LLM__API_KEY": "k",
                "WALLET_V2__LLM__BASE_URL": "ftp://glm.example.test/v1",
            }
        )
        with pytest.raises(ConfigError):
            load_settings(env)


class TestMcpFailClosed:
    @pytest.mark.parametrize("mode", ["dry_run", "live"])
    def test_non_disabled_without_base_url_raises(self, mode: str) -> None:
        env = _env(
            **{
                "WALLET_V2__MCP__MODE": mode,
                "WALLET_V2__MCP__API_KEY": "k",
            }
        )
        with pytest.raises(ConfigError):
            load_settings(env)

    @pytest.mark.parametrize("mode", ["dry_run", "live"])
    def test_non_disabled_without_api_key_raises(self, mode: str) -> None:
        env = _env(
            **{
                "WALLET_V2__MCP__MODE": mode,
                "WALLET_V2__MCP__BASE_URL": "https://mcp.example.com",
            }
        )
        with pytest.raises(ConfigError):
            load_settings(env)

    def test_live_non_http_url_raises(self) -> None:
        env = _env(
            **{
                "WALLET_V2__MCP__MODE": "live",
                "WALLET_V2__MCP__BASE_URL": "ftp://mcp.example.com",
                "WALLET_V2__MCP__API_KEY": "k",
            }
        )
        with pytest.raises(ConfigError):
            load_settings(env)

    def test_disabled_requires_no_credentials(self) -> None:
        s = load_settings(_env())
        assert s.mcp.mode is IntegrationMode.DISABLED
        assert s.mcp.base_url is None
        assert s.mcp.api_key is None

    def test_live_full_loads(self) -> None:
        env = _env(
            **{
                "WALLET_V2__MCP__MODE": "live",
                "WALLET_V2__MCP__BASE_URL": "https://mcp.example.com",
                "WALLET_V2__MCP__API_KEY": "k",
            }
        )
        s = load_settings(env)
        assert s.mcp.mode is IntegrationMode.LIVE
        assert s.mcp.enabled is True
        assert s.mcp.base_url == "https://mcp.example.com"

    def test_dry_run_full_loads(self) -> None:
        env = _env(
            **{
                "WALLET_V2__MCP__MODE": "dry_run",
                "WALLET_V2__MCP__BASE_URL": "https://mcp.example.com",
                "WALLET_V2__MCP__API_KEY": "k",
            }
        )
        s = load_settings(env)
        assert s.mcp.mode is IntegrationMode.DRY_RUN
        assert s.mcp.enabled is True

    def test_api_key_redacted_in_repr(self) -> None:
        env = _env(
            **{
                "WALLET_V2__MCP__MODE": "live",
                "WALLET_V2__MCP__BASE_URL": "https://mcp.example.com",
                "WALLET_V2__MCP__API_KEY": "super-secret-mcp-key",
            }
        )
        s = load_settings(env)
        repr_text = repr(s)
        assert "super-secret-mcp-key" not in repr_text
        assert "<redacted>" in repr_text


class TestWalletFailClosed:
    @pytest.mark.parametrize("mode", ["dry_run", "live"])
    def test_non_disabled_without_base_url_raises(self, mode: str) -> None:
        env = _env(
            **{
                "WALLET_V2__WALLET__MODE": mode,
                "WALLET_V2__WALLET__API_KEY": "k",
            }
        )
        with pytest.raises(ConfigError):
            load_settings(env)

    @pytest.mark.parametrize("mode", ["dry_run", "live"])
    def test_non_disabled_without_api_key_raises(self, mode: str) -> None:
        env = _env(
            **{
                "WALLET_V2__WALLET__MODE": mode,
                "WALLET_V2__WALLET__BASE_URL": "https://wallet.example.com",
            }
        )
        with pytest.raises(ConfigError):
            load_settings(env)

    def test_live_non_http_url_raises(self) -> None:
        env = _env(
            **{
                "WALLET_V2__WALLET__MODE": "live",
                "WALLET_V2__WALLET__BASE_URL": "ftp://wallet.example.com",
                "WALLET_V2__WALLET__API_KEY": "k",
            }
        )
        with pytest.raises(ConfigError):
            load_settings(env)

    def test_live_full_loads(self) -> None:
        env = _env(
            **{
                "WALLET_V2__WALLET__MODE": "live",
                "WALLET_V2__WALLET__BASE_URL": "https://wallet.example.com",
                "WALLET_V2__WALLET__API_KEY": "k",
            }
        )
        s = load_settings(env)
        assert s.wallet.mode is IntegrationMode.LIVE
        assert s.wallet.enabled is True
        assert s.wallet.base_url == "https://wallet.example.com"

    def test_dry_run_full_loads(self) -> None:
        env = _env(
            **{
                "WALLET_V2__WALLET__MODE": "dry_run",
                "WALLET_V2__WALLET__BASE_URL": "https://wallet.example.com",
                "WALLET_V2__WALLET__API_KEY": "k",
            }
        )
        s = load_settings(env)
        assert s.wallet.mode is IntegrationMode.DRY_RUN
        assert s.wallet.enabled is True


class TestSecretRedaction:
    def test_mailbox_password_redacted_in_repr(self) -> None:
        env = _env(
            **{
                "WALLET_V2__MAILBOX__MODE": "live",
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
