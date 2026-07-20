"""Canonical financial-account reference normalisation.

Masking-length variation (e.g. ``*2197`` vs ``************2197``) resolves to
a single canonical form so that duplicate FinancialAccounts are not created
on future ingestion.
"""

def canonical_external_reference(issuer: str, external_reference: str) -> str:
    """Return the canonical form of *external_reference* for *issuer*.

    Normalisation strategy is issuer-aware:

    * **Qik Banco** (case-insensitive, including its legal issuer name) — strips leading asterisk (``*``) masking
      characters so that ``*2197`` and ``************2197`` both resolve to
      ``2197``.
    * **fallback** — strips leading/trailing whitespace only.
    """
    ref = external_reference.strip()
    if issuer.casefold().lstrip().startswith("qik"):
        ref = ref.lstrip("*").strip()
    return ref
