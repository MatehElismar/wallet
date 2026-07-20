"""Operator-command parsing tests."""

from __future__ import annotations

import json
from typing import Sequence

import pytest
from sqlalchemy import create_engine, event

from wallet_v2.__main__ import _parse_uids, _parser, _sync_catalog
from wallet_v2.application.contracts import (
    WalletAccount,
    WalletBalance,
    WalletCategory,
    WalletLabel,
    WalletRecordRule,
)
from wallet_v2.config import ConfigError, DatabaseSettings, Settings, WalletSettings
from wallet_v2.domain.enums import IntegrationMode
from wallet_v2.persistence.base import Base


class _FakeCatalogClient:
    def __init__(self) -> None:
        self._revision = '"v2"'
        self.accounts: Sequence[WalletAccount] = (
            WalletAccount(
                id="a1", name="Cash",
                balance=WalletBalance(currency_code="USD", value=1000.0),
            ),
        )
        self.categories: Sequence[WalletCategory] = (
            WalletCategory(id="c1", name="Food"),
        )
        self.labels: Sequence[WalletLabel] = (
            WalletLabel(id="l1", name="Business"),
        )
        self.record_rules: Sequence[WalletRecordRule] = ()

    def get_accounts(self) -> Sequence[WalletAccount]:
        return self.accounts

    def get_categories(self) -> Sequence[WalletCategory]:
        return self.categories

    def get_labels(self) -> Sequence[WalletLabel]:
        return self.labels

    def get_record_rules(self) -> Sequence[WalletRecordRule]:
        return self.record_rules

    def last_revision(self) -> str | None:
        return self._revision


def test_explicit_uids_and_reprocess_are_parsed() -> None:
    args = _parser().parse_args(
        [
            "run",
            "--label",
            "targeted-replay",
            "--mode",
            "dry_run",
            "--uids",
            "79148,79151,79168",
            "--reprocess",
        ]
    )

    assert args.uids == (79148, 79151, 79168)
    assert args.reprocess is True


@pytest.mark.parametrize("value", ["", "0", "1,nope", "-1"])
def test_explicit_uids_must_be_positive_integers(value: str) -> None:
    with pytest.raises(Exception):
        _parse_uids(value)


def test_date_and_explicit_uids_are_mutually_exclusive() -> None:
    with pytest.raises(SystemExit):
        _parser().parse_args(
            [
                "run",
                "--label",
                "invalid-selection",
                "--mode",
                "dry_run",
                "--on-date",
                "2026-07-18",
                "--uids",
                "79148",
            ]
        )


def test_sync_catalog_parses_with_no_args() -> None:
    args = _parser().parse_args(["sync-catalog"])
    assert args.command == "sync-catalog"


def test_repair_qik_requires_explicit_identity_and_target() -> None:
    args = _parser().parse_args(
        [
            "repair-qik",
            "--issuer",
            "Qik Banco Digital Dominicano S.A., Banco Múltiple",
            "--raw-references",
            "*2197",
            "************2197",
            "--wallet-account-id",
            "37c86c4f-5370-466b-a36b-40b533f6cf31",
        ]
    )

    assert args.issuer == "Qik Banco Digital Dominicano S.A., Banco Múltiple"
    assert args.wallet_account_id == "37c86c4f-5370-466b-a36b-40b533f6cf31"


def test_sync_catalog_rejects_disabled_wallet_mode() -> None:
    args = _parser().parse_args(["sync-catalog"])
    settings = Settings(
        environment="test",
        database=DatabaseSettings(url="sqlite:///:memory:"),
        wallet=WalletSettings(mode=IntegrationMode.DISABLED),
    )
    with pytest.raises(ConfigError, match="must not be disabled"):
        _sync_catalog(args, _settings=settings)


def test_sync_catalog_dry_run_output(capsys: pytest.CaptureFixture[str]) -> None:
    engine = create_engine("sqlite:///:memory:")
    event.listen(engine, "connect", lambda c, _: c.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)

    args = _parser().parse_args(["sync-catalog"])
    settings = Settings(
        environment="test",
        database=DatabaseSettings(url="sqlite:///:memory:"),
        wallet=WalletSettings(
            mode=IntegrationMode.DRY_RUN,
            base_url="http://fake.test",
            api_key="test-key",
        ),
    )
    client = _FakeCatalogClient()
    exit_code = _sync_catalog(args, _settings=settings, _client=client, _engine=engine)

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["mode"] == "dry_run"
    assert output["provider_revision"] == '"v2"'
    assert set(output["snapshots"].keys()) == {
        "accounts", "categories", "labels", "record_rules",
    }
    for kind, data in output["snapshots"].items():
        assert isinstance(data["snapshot_id"], str)
        assert isinstance(data["snapshot_version"], int)
        assert isinstance(data["item_count"], int)
