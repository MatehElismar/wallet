"""Issuer-aware external-reference normalisation.

Each bank can produce variant external references (masking, truncation,
prefix/suffix changes).  A normalizer derives a stable canonical form so that
duplicate ``FinancialAccount`` rows are never created during ingestion or
repair.

Normalizers are registered per issuer prefix (case-insensitive match against
``issuer.startswith``).  The first matching prefix wins, so register more
specific prefixes first.  If no normalizer matches, leading/trailing whitespace
is stripped as a safe default.
"""

from __future__ import annotations

from typing import Protocol


class ReferenceNormalizer(Protocol):
    """Derive a canonical external reference for a given bank/issuer.

    The normalizer receives the trimmed *reference* and must return a
    deterministic canonical form.  The issuer is provided for context but has
    already been used to select this normalizer.
    """

    def normalize(self, issuer: str, reference: str) -> str: ...


class StripAsteriskNormalizer:
    """Strip all leading ``*`` characters — used by Qik Banco."""

    def normalize(self, _issuer: str, reference: str) -> str:
        return reference.lstrip("*")


class StripPrefixNormalizer:
    """Strip a fixed prefix from the reference."""

    def __init__(self, prefix: str) -> None:
        self._prefix = prefix

    def normalize(self, _issuer: str, reference: str) -> str:
        if reference.startswith(self._prefix):
            return reference[len(self._prefix):]
        return reference


_NORMALIZERS: list[tuple[str, ReferenceNormalizer]] = [
    ("qik", StripAsteriskNormalizer()),
]


def register_normalizer(issuer_prefix: str, normalizer: ReferenceNormalizer) -> None:
    """Register a normalizer for an issuer prefix.

    ``issuer_prefix`` is matched case-insensitively via ``issuer.startswith``.
    Prepend more-specific prefixes before less-specific ones if both could
    match the same issuer.
    """
    key = issuer_prefix.casefold()
    for i, (existing_key, _) in enumerate(_NORMALIZERS):
        if existing_key.casefold() == key:
            _NORMALIZERS[i] = (issuer_prefix, normalizer)
            return
    _NORMALIZERS.append((issuer_prefix, normalizer))


def _resolve_normalizer(issuer: str) -> ReferenceNormalizer | None:
    folded = issuer.casefold().lstrip()
    for prefix, normalizer in _NORMALIZERS:
        if folded.startswith(prefix.casefold()):
            return normalizer
    return None


def canonical_external_reference(issuer: str, external_reference: str) -> str:
    """Return the canonical form of *external_reference* for *issuer*."""
    ref = external_reference.strip()
    normalizer = _resolve_normalizer(issuer)
    if normalizer is not None:
        return normalizer.normalize(issuer, ref)
    return ref
