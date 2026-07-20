"""Operator-command parsing tests."""

from __future__ import annotations

import pytest

from wallet_v2.__main__ import _parse_uids, _parser


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
