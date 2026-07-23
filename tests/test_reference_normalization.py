"""Hermetic tests for canonical reference normalisation.

Covers:
- Qik leading-asterisk stripping (via registered StripAsteriskNormalizer)
- Fallback behaviour for non-matching issuers
- Edge cases (empty, whitespace, already-canonical)
- Registry: register_normalizer, StripPrefixNormalizer, prefix precedence
"""

import pytest

from wallet_v2.domain.reference import (
    canonical_external_reference,
    register_normalizer,
    StripAsteriskNormalizer,
    StripPrefixNormalizer,
)

# ── save/restore registry to keep tests isolated ────────────────────────


@pytest.fixture(autouse=True)
def _isolate_registry() -> None:
    from wallet_v2.domain.reference import _NORMALIZERS as registry

    saved = list(registry)
    yield
    registry.clear()
    registry.extend(saved)


class TestQikNormalization:
    def test_strips_leading_asterisks(self) -> None:
        assert canonical_external_reference("Qik", "*2197") == "2197"

    def test_strips_variable_length_masking(self) -> None:
        assert canonical_external_reference("Qik", "************2197") == "2197"

    def test_preserves_trailing_asterisks(self) -> None:
        assert canonical_external_reference("Qik", "2197*") == "2197*"

    def test_already_canonical(self) -> None:
        assert canonical_external_reference("Qik", "2197") == "2197"

    def test_handles_whitespace(self) -> None:
        assert canonical_external_reference("Qik", "  *2197  ") == "2197"

    def test_case_insensitive_issuer(self) -> None:
        assert canonical_external_reference("qik", "*2197") == "2197"
        assert canonical_external_reference("QIK", "*2197") == "2197"

    def test_legal_issuer_name_is_recognised(self) -> None:
        assert (
            canonical_external_reference(
                "Qik Banco Digital Dominicano S.A., Banco Múltiple",
                "************2197",
            )
            == "2197"
        )

    def test_empty_ref_stays_empty(self) -> None:
        assert canonical_external_reference("Qik", "") == ""

    def test_only_asterisks(self) -> None:
        assert canonical_external_reference("Qik", "****") == ""

    def test_alpha_suffix(self) -> None:
        assert canonical_external_reference("Qik", "****ABC123") == "ABC123"


class TestFallbackNormalization:
    def test_strips_whitespace(self) -> None:
        assert canonical_external_reference("SomeBank", "  ref-123  ") == "ref-123"

    def test_does_not_strip_leading_asterisks(self) -> None:
        assert canonical_external_reference("SomeBank", "*2197") == "*2197"

    def test_empty_ref(self) -> None:
        assert canonical_external_reference("SomeBank", "") == ""

    def test_reference_unchanged(self) -> None:
        assert canonical_external_reference("SomeBank", "ACCT-456") == "ACCT-456"


class TestRegisterNormalizer:
    def test_register_strip_prefix(self) -> None:
        register_normalizer("testbank", StripPrefixNormalizer("PRE-"))
        assert canonical_external_reference("TestBank", "PRE-00123") == "00123"
        assert canonical_external_reference("TestBank", "NOPE-00123") == "NOPE-00123"

    def test_register_overwrites_existing_prefix(self) -> None:
        register_normalizer("qik", StripPrefixNormalizer("Q-"))
        assert canonical_external_reference("Qik", "Q-2197") == "2197"
        register_normalizer("qik", StripAsteriskNormalizer())

    def test_register_new_bank(self) -> None:
        register_normalizer("otherbank", StripPrefixNormalizer("OTHER-"))
        assert canonical_external_reference("OtherBank S.A.", "OTHER-ABC") == "ABC"
        assert canonical_external_reference("OtherBank S.A.", "   OTHER-ABC   ") == "ABC"

    def test_unrelated_bank_not_affected(self) -> None:
        register_normalizer("bankx", StripPrefixNormalizer("X-"))
        assert canonical_external_reference("BankX", "X-123") == "123"
        assert canonical_external_reference("BankY", "X-123") == "X-123"
