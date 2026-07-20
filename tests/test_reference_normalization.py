"""Hermetic tests for canonical reference normalisation.

Covers:
- Qik leading-asterisk stripping
- Fallback behaviour for non-Qik issuers
- Edge cases (empty, whitespace, already-canonical)
"""

from wallet_v2.domain.reference import canonical_external_reference


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
