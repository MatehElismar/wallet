"""Deterministic MCP advisory enrichment service (Phase B).

Two explicitly separate, advisory-only surfaces:

* :class:`CandidateResearchPreview` — for a notification
  ``TransactionCandidate``. It may cache bounded evidence and is **never**
  eligible for finalization or import. It exists to make the candidate
  display useful Wallet context before the relevant statement arrives.
* :class:`EnrichmentDecisionBuilder` — for a statement-confirmed
  ``FinancialEvent``. It produces a versioned, immutable proposal and is the
  only surface that can be operator-finalized into a dry-run payload.

The ranker is fully deterministic and explainable:

1. Exact recurrence first — a historical record whose merchant, signed
   amount, and currency all match the canonical event.
2. Normalized merchant history plus amount/date proximity — records sharing
   the canonical merchant (normalized) and a close signed amount and date.
3. A local vote among matching historical category/label/payment
   assignments.

Ties, weak support, malformed data, profile/sync failure, missing mapping,
or stale catalog choices become ``no recommendation`` with no selections.

Every supported output carries bounded evidence references (selected
record IDs and the fields used for scoring), query inputs, response
metadata, and a SHA-256 integrity hash — never an unbounded copy of
customer history. No numeric confidence is produced; the UI uses
transparent evidence grades instead.

Safety contract (defense in depth on top of the adapter allowlist):

* Only typed ``McpReadOnlyClient`` ``get_client_profile`` / ``get_records``
  are used. No write tools, no ``call_tool``.
* ``get_client_profile`` is called once per run and validates
  ``syncState=complete`` before any record query.
* The selected account comes only from the active validated mapping. MCP
  data never validates, creates, or mutates catalog entities.
* Finalized values are re-validated against the current REST catalog
  snapshots. A missing/archived/unknown catalog choice fails closed.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from wallet_v2.application.account_mapping import AccountMappingService, MappingError
from wallet_v2.application.catalog_sync import CatalogSyncService
from wallet_v2.application.contracts_mcp import (
    McpReadOnlyClient,
    McpRecord,
    McpRecordsResult,
)
from wallet_v2.domain.reference import canonical_external_reference
from wallet_v2.persistence.models import (
    AccountMapping,
    CatalogSyncSnapshot,
    EnrichmentDecision,
    FinancialEvent,
    McpProfileSnapshot,
    TransactionCandidate,
)
from wallet_v2.persistence.models.mcp import AdvisoryResearch
from wallet_v2.persistence.models.wallet_catalog import CatalogSyncCursor

# Bounding policy — never copy unbounded raw history.
_MAX_RECORDS_PER_QUERY = 200
_MAX_EVIDENCE_RECORDS = 25
_DATE_WINDOW_DAYS = 180
# Hard ceiling on pagination rounds so a misbehaving server (or a
# non-advancing next_offset) cannot loop the client indefinitely. The record
# cap above is the primary bound; this is the secondary safety net.
_MAX_PAGINATION_PAGES = 20

_EVIDENCE_GRADES = frozenset(
    {
        "exact_recurrence",
        "merchant_history",
        "context_only",
        "no_recommendation",
        "operator_override",
    }
)

# Grades that represent a concrete, finalizable selection rather than a
# fail-closed no-recommendation. A candidate research preview is never in
# this set (it cannot be finalized); an event decision becomes finalizable
# only with one of these grades.
_FINALIZABLE_GRADES = frozenset(
    {"exact_recurrence", "merchant_history", "operator_override"}
)


# ── normalization helpers ────────────────────────────────────────────────


def _normalize_merchant(merchant: str | None) -> str:
    """Return a normalized merchant key for fuzzy grouping.

    Lower-cased, punctuation/space-collapsed, and stripped of common
    transaction-noise suffixes. Deterministic and local.
    """
    if not merchant:
        return ""
    text = merchant.casefold()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = text.strip()
    text = re.sub(r"\s+", " ", text)
    return text


def _signed_amount_minor(amount_minor: int, direction: str) -> int:
    """Map a strictly-positive minor amount + direction to a signed minor.

    Debits are negative, credits are positive, matching the MCP record
    convention where expenses are negative values.
    """
    return -amount_minor if direction.casefold() == "debit" else amount_minor


def _amount_value_to_minor(amount_value: float) -> int:
    """Convert a signed decimal amount value to signed minor units exactly.

    Uses ``Decimal(str(amount_value))`` so the conversion is performed on the
    decimal string representation rather than via binary float
    multiplication (``amount_value * 100``), which is lossy. The result keeps
    the sign carried by the MCP amount (expenses are negative).
    """
    try:
        dec = Decimal(str(amount_value))
    except (InvalidOperation, ValueError, TypeError):
        return 0
    try:
        return int(dec.scaleb(2).to_integral_value(rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError):
        return 0


def _iso_date(value: date | None) -> str | None:
    return value.isoformat() if value else None


def _score_merchant_match(
    candidate_merchant_norm: str,
    record_merchant_norm: str,
) -> bool:
    if not candidate_merchant_norm or not record_merchant_norm:
        return False
    if candidate_merchant_norm == record_merchant_norm:
        return True
    # Token-set containment: either is a token-subset of the other so that
    # "online store" and "online store llc" group together deterministically.
    cand_tokens = set(candidate_merchant_norm.split())
    rec_tokens = set(record_merchant_norm.split())
    if not cand_tokens or not rec_tokens:
        return False
    return cand_tokens.issubset(rec_tokens) or rec_tokens.issubset(cand_tokens)


# ── integrity hash ───────────────────────────────────────────────────────


def compute_integrity_hash(*, query_inputs: dict[str, Any], evidence_ids: Sequence[str]) -> str:
    """Return a stable SHA-256 hash over query inputs and selected evidence.

    The hash binds a stored advisory row to the exact inputs and selected
    evidence IDs that produced it, so later tampering with stored JSON is
    detectable.
    """
    canonical = json.dumps(
        {
            "query_inputs": query_inputs,
            "evidence_ids": sorted(evidence_ids),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ── proposal value object ─────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class EnrichmentProposal:
    """A deterministic enrichment proposal (no numeric confidence).

    ``evidence_grade`` is one of the transparent grades. When the grade is
    ``no_recommendation`` all selection fields are ``None`` and
    ``recommendation`` is ``False``.
    """

    evidence_grade: str
    recommendation: bool
    selected_account_id: str | None = None
    selected_category_id: str | None = None
    selected_label_ids: tuple[str, ...] = ()
    selected_payment_type: str | None = None
    supporting_evidence_ids: tuple[str, ...] = ()
    rationale: str = ""

    @property
    def is_no_recommendation(self) -> bool:
        return not self.recommendation

    def to_decision_payload(self) -> dict[str, Any]:
        return {
            "evidence_grade": self.evidence_grade,
            "selected_account_id": self.selected_account_id,
            "selected_category_id": self.selected_category_id,
            "selected_label_ids": list(self.selected_label_ids),
            "selected_payment_type": self.selected_payment_type,
            "supporting_evidence_ids": list(self.supporting_evidence_ids),
            "rationale": self.rationale,
        }


# ── research preview (advisory only, never finalizable) ──────────────────


@dataclass(frozen=True, slots=True)
class CandidateResearchPreview:
    candidate_id: object
    evidence_grade: str
    query_inputs: dict[str, Any]
    response_metadata: dict[str, Any]
    evidence_ids: dict[str, Any]
    integrity_hash: str
    recommendation: bool
    selected_account_id: str | None = None
    selected_category_id: str | None = None
    selected_label_ids: tuple[str, ...] = ()
    selected_payment_type: str | None = None
    rationale: str = ""

    # Explicit advisory guard: a candidate preview can never finalize/import.
    @property
    def is_finalizable(self) -> bool:
        return False


# ── local ranking ────────────────────────────────────────────────────────


class _RankedRecord:
    __slots__ = ("record", "grade", "score")

    def __init__(self, record: McpRecord, grade: str, score: float) -> None:
        self.record = record
        self.grade = grade
        self.score = score


def _rank_records(
    *,
    records: Sequence[McpRecord],
    merchant_norm: str,
    signed_amount_minor: int,
    currency: str,
    event_date: date | None,
) -> list[_RankedRecord]:
    """Deterministically rank historical MCP records.

    Exact recurrence (exact merchant + signed amount + currency match) ranks
    first; then normalized merchant history with amount/date proximity.
    Records are returned sorted by (grade rank, score desc, id asc) so the
    ordering is fully reproducible.
    """
    ranked: list[_RankedRecord] = []
    for rec in records:
        rec_merchant_norm = _normalize_merchant(rec.counter_party)
        rec_signed = _amount_value_to_minor(rec.amount_value) if rec.amount_value else 0
        exact_merchant = rec_merchant_norm == merchant_norm and merchant_norm != ""
        exact_amount = rec_signed == signed_amount_minor
        exact_currency = (
            rec.currency.casefold() == currency.casefold() if rec.currency else False
        )

        if exact_merchant and exact_amount and exact_currency:
            ranked.append(_RankedRecord(rec, "exact_recurrence", 1_000_000.0))
            continue

        if _score_merchant_match(merchant_norm, rec_merchant_norm):
            score = 10_000.0
            if exact_amount and exact_currency:
                score += 5_000.0
            elif exact_currency:
                score += 1_000.0
            # Date proximity (within window): closer dates score higher.
            if event_date is not None and rec.record_date:
                try:
                    rec_date = date.fromisoformat(rec.record_date[:10])
                    delta = abs((rec_date - event_date).days)
                    score += max(0, _DATE_WINDOW_DAYS - delta)
                except ValueError:
                    pass
            ranked.append(_RankedRecord(rec, "merchant_history", score))
            continue

        # Context only: present in history but no merchant/amount relation.
        ranked.append(_RankedRecord(rec, "context_only", 0.0))

    grade_rank = {"exact_recurrence": 0, "merchant_history": 1, "context_only": 2}
    ranked.sort(key=lambda r: (grade_rank.get(r.grade, 9), -r.score, r.record.id))
    return ranked


def _majority_vote(items: Sequence[Any]) -> Any | None:
    """Return the most common non-None item, or ``None`` on an empty input.

    Returns ``None`` (not a tie-break winner) when the top items tie, so the
    caller fails closed to ``no recommendation`` rather than guessing.
    """
    present = [i for i in items if i is not None]
    if not present:
        return None
    counts = Counter(present)
    top_count = max(counts.values())
    top_items = [k for k, v in counts.items() if v == top_count]
    if len(top_items) > 1:
        return None
    return top_items[0]


# ── build query inputs from canonical facts ──────────────────────────────


@dataclass(frozen=True, slots=True)
class QueryPlan:
    financial_account_id: object
    remote_account_id: str
    date_from: str
    date_to: str
    merchant: str
    signed_amount_minor: int
    currency: str


def _build_query_plan(
    *,
    account_id: object,
    direction: str,
    amount_minor: int,
    currency: str,
    merchant: str | None,
    event_date: date | None,
    mapping_service: AccountMappingService,
) -> QueryPlan:
    """Build a bounded query plan from canonical local facts only.

    The remote account ID comes solely from the active validated mapping.
    The date window is bounded to ``_DATE_WINDOW_DAYS`` around the event
    date. No raw email, attachment, or statement text is ever sent to MCP.
    """
    remote_account_id = mapping_service.get_active_remote_account_id(account_id)
    if event_date is None:
        raise ValueError("event_date is required to bound the MCP query window")

    from datetime import timedelta

    start = event_date - timedelta(days=_DATE_WINDOW_DAYS)
    end = event_date + timedelta(days=_DATE_WINDOW_DAYS)
    return QueryPlan(
        financial_account_id=account_id,
        remote_account_id=remote_account_id,
        date_from=start.isoformat(),
        date_to=end.isoformat(),
        merchant=(merchant or "").strip(),
        signed_amount_minor=_signed_amount_minor(amount_minor, direction),
        currency=currency,
    )


# ── catalog snapshot validation ──────────────────────────────────────────


class CatalogValidationError(ValueError):
    """Raised when a proposed catalog choice is missing/archived/stale."""


def _current_catalog_items(
    session: Session, resource_kind: str
) -> dict[str, dict[str, Any]]:
    """Return a mapping of catalog item id -> item from the current snapshot."""
    cursor = CatalogSyncService.get_cursor(session, resource_kind)
    if cursor is None or cursor.current_snapshot_id is None:
        return {}
    snap = session.get(CatalogSyncSnapshot, cursor.current_snapshot_id)
    if snap is None:
        return {}
    items: list[dict[str, Any]] = snap.catalog_data.get("items", [])
    return {str(i.get("id")): i for i in items if isinstance(i, dict)}


def _validate_selections(
    session: Session,
    *,
    account_id: str,
    category_id: str | None,
    label_ids: tuple[str, ...],
) -> None:
    """Fail closed if any selected catalog item is missing or archived.

    The account must exist and be unarchived in the current accounts
    snapshot; a category (if proposed) must exist and be unarchived; every
    proposed label must exist and be unarchived.
    """
    accounts = _current_catalog_items(session, "accounts")
    if account_id not in accounts or accounts[account_id].get("archived", False):
        raise CatalogValidationError(
            f"selected account {account_id!r} is missing or archived in "
            f"current catalog snapshot"
        )
    if category_id is not None:
        categories = _current_catalog_items(session, "categories")
        if category_id not in categories or categories[category_id].get("archived", False):
            raise CatalogValidationError(
                f"selected category {category_id!r} is missing or archived"
            )
    if label_ids:
        labels = _current_catalog_items(session, "labels")
        for lid in label_ids:
            if lid not in labels or labels[lid].get("archived", False):
                raise CatalogValidationError(
                    f"selected label {lid!r} is missing or archived"
                )


# ── primary service ──────────────────────────────────────────────────────


class EnrichmentService:
    """Deterministic MCP advisory enrichment for candidates and events."""

    def __init__(
        self,
        session: Session,
        mcp: McpReadOnlyClient | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
        profile_snapshot_id: object | None = None,
    ) -> None:
        self._session = session
        self._mcp: McpReadOnlyClient | None = mcp
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._mapping_service = AccountMappingService(session)
        self._profile_snapshot_id = profile_snapshot_id

    def _require_mcp(self) -> McpReadOnlyClient:
        """Return the MCP client or fail closed when none is configured.

        Only the MCP-backed surfaces (``ensure_profile`` and the research /
        event-decision builders) require a client. The operator-only surfaces
        (override, finalize, dry-run preview) never touch MCP and are safe to
        construct without one, so those routes must not be forced to pass an
        invalid ``None`` in the client's place.
        """
        if self._mcp is None:
            raise ValueError(
                "MCP advisory client is required for this operation but is "
                "not configured"
            )
        return self._mcp

    # ── profile gate (once per run) ─────────────────────────────────────

    def ensure_profile(self) -> McpProfileSnapshot:
        """Call ``get_client_profile`` once, persist non-secret metadata.

        Persists ``syncState``, ``grantedScopes``, ``syncedAt`` and
        rate-limit metadata. Stores no secret material from the profile.

        Defense in depth: even if the injected client bypasses the adapter's
        own profile/scope gate, this service re-validates ``sync_state ==
        'complete'`` and the presence of the ``records.read`` scope before any
        record query. Raises ``ValueError``/``PermissionError`` on a failing
        gate so the caller can fail closed to a persisted
        ``no_recommendation``.
        """
        if self._profile_snapshot_id is not None:
            existing = self._session.get(
                McpProfileSnapshot, self._profile_snapshot_id
            )
            if existing is not None:
                # Re-validate the cached snapshot: an incomplete or
                # scope-less snapshot must never be reused to proceed.
                self._require_valid_profile(existing)
                return existing

        client = self._require_mcp()
        profile = client.get_client_profile()
        meta = client.last_response_meta
        synced_at: datetime | None = None
        if profile.synced_at:
            try:
                synced_at = datetime.fromisoformat(profile.synced_at.replace("Z", "+00:00"))
            except ValueError:
                synced_at = None
        snapshot = McpProfileSnapshot(
            sync_state=profile.sync_state,
            granted_scopes=list(profile.granted_scopes),
            synced_at=synced_at,
            rate_limit_metadata={
                "remaining": meta.rate_limit_remaining,
                "capacity": meta.rate_limit_capacity,
                "refill_per_minute": meta.rate_limit_refill_per_minute,
            },
        )
        self._session.add(snapshot)
        self._session.flush()
        self._profile_snapshot_id = snapshot.id
        self._require_valid_profile(snapshot)
        return snapshot

    @staticmethod
    def _require_valid_profile(snapshot: McpProfileSnapshot) -> None:
        """Service-level profile gate (independent of the adapter).

        Requires ``syncState == 'complete'`` and the ``records.read`` scope.
        This is the fail-closed check that must hold even when an injected
        client returns a profile that the adapter did not reject.
        """
        if snapshot.sync_state != "complete":
            raise ValueError(
                f"MCP profile sync_state is {snapshot.sync_state!r}, "
                f"expected 'complete'"
            )
        scopes = set(snapshot.granted_scopes or [])
        if "records.read" not in scopes:
            raise PermissionError(
                "MCP profile missing required scope 'records.read'; "
                f"granted scopes: {sorted(scopes)!r}"
            )

    def _profile_snapshot_for_failure(self) -> McpProfileSnapshot:
        """Return a usable profile snapshot for a fail-closed no-recording.

        Prefers an already-persisted snapshot (e.g. one captured before a
        validation failure). If none exists — the profile fetch itself failed
        upstream — a minimal audit snapshot is created so the persisted
        preview/decision still references a profile row.
        """
        if self._profile_snapshot_id is not None:
            existing = self._session.get(
                McpProfileSnapshot, self._profile_snapshot_id
            )
            if existing is not None:
                return existing
        snapshot = McpProfileSnapshot(
            sync_state="incomplete",
            granted_scopes=[],
            synced_at=None,
            rate_limit_metadata={},
        )
        self._session.add(snapshot)
        self._session.flush()
        self._profile_snapshot_id = snapshot.id
        return snapshot

    # ── candidate research preview (advisory only) ─────────────────────

    def build_candidate_preview(
        self, candidate: TransactionCandidate
    ) -> CandidateResearchPreview:
        """Produce a bounded, non-finalizable research preview for a candidate.

        Profiles once, queries bounded records for the mapped account, and
        computes an evidence grade. The result is persisted as an
        ``AdvisoryResearch`` row targeting the candidate and can never be
        finalized or imported.
        """
        try:
            profile_snapshot = self.ensure_profile()
        except (ValueError, PermissionError) as exc:
            # Fail closed: a missing/incomplete profile or missing
            # records.read scope must not escape — persist a no_recommendation
            # preview rather than proceeding to query or guess.
            profile_snapshot = self._profile_snapshot_for_failure()
            return self._no_rec_candidate(
                candidate, profile_snapshot, str(exc)
            )
        account_id = candidate.account_id
        if account_id is None:
            return self._no_rec_candidate(
                candidate, profile_snapshot,
                "candidate has no linked financial account",
            )

        plan = self._plan_for(
            account_id=account_id,
            direction=str(candidate.direction),
            amount_minor=candidate.amount_minor,
            currency=candidate.currency,
            merchant=candidate.merchant,
            event_date=candidate.transaction_date,
        )
        if plan is None:
            return self._no_rec_candidate(
                candidate, profile_snapshot,
                "no active validated mapping for financial account",
            )

        result = self._query_records(plan)
        if result is None:
            return self._no_rec_candidate(
                candidate, profile_snapshot,
                "record query failed or returned malformed data",
            )

        ranked = _rank_records(
            records=result.records,
            merchant_norm=_normalize_merchant(plan.merchant),
            signed_amount_minor=plan.signed_amount_minor,
            currency=plan.currency,
            event_date=candidate.transaction_date,
        )
        proposal = self._propose_from_ranked(ranked, plan.remote_account_id)

        evidence_ids = self._bounded_evidence(ranked)
        query_inputs = self._query_inputs(plan)
        integrity_hash = compute_integrity_hash(
            query_inputs=query_inputs,
            evidence_ids=[e["record_id"] for e in evidence_ids],
        )
        response_metadata = self._response_metadata()

        research = AdvisoryResearch(
            candidate_id=candidate.id,
            evidence_grade=proposal.evidence_grade,
            profile_snapshot_id=profile_snapshot.id,
            query_inputs=query_inputs,
            response_metadata=response_metadata,
            evidence_ids={"records": evidence_ids},
            integrity_hash=integrity_hash,
        )
        self._session.add(research)
        self._session.flush()

        return CandidateResearchPreview(
            candidate_id=candidate.id,
            evidence_grade=proposal.evidence_grade,
            query_inputs=query_inputs,
            response_metadata=response_metadata,
            evidence_ids={"records": evidence_ids},
            integrity_hash=integrity_hash,
            recommendation=proposal.recommendation,
            selected_account_id=proposal.selected_account_id,
            selected_category_id=proposal.selected_category_id,
            selected_label_ids=proposal.selected_label_ids,
            selected_payment_type=proposal.selected_payment_type,
            rationale=proposal.rationale,
        )

    # ── canonical-event enrichment decision ─────────────────────────────

    def build_event_decision(
        self, event: FinancialEvent, *, version: int = 1
    ) -> EnrichmentDecision:
        """Produce a versioned, immutable enrichment decision for an event.

        The account is taken from the active validated mapping. Historical
        records are ranked locally; category/label/payment come from a local
        majority vote. The proposal is re-validated against the current
        catalog snapshots before it is persisted. Weak/tie/error/stale input
        yields a ``no_recommendation`` decision with no selections.
        """
        try:
            profile_snapshot = self.ensure_profile()
        except (ValueError, PermissionError) as exc:
            # Fail closed: a missing/incomplete profile or missing
            # records.read scope must not escape — persist a no_recommendation
            # decision rather than proceeding to query or guess.
            profile_snapshot = self._profile_snapshot_for_failure()
            return self._persist_no_rec(
                event, profile_snapshot, version, str(exc)
            )
        plan = self._plan_for(
            account_id=event.account_id,
            direction=str(event.direction),
            amount_minor=event.amount_minor,
            currency=event.currency,
            merchant=event.merchant,
            event_date=event.transaction_date or event.posting_date,
        )
        if plan is None:
            return self._persist_no_rec(event, profile_snapshot, version,
                                        "no active validated mapping")

        result = self._query_records(plan)
        if result is None:
            return self._persist_no_rec(event, profile_snapshot, version,
                                        "record query failed or malformed")

        ranked = _rank_records(
            records=result.records,
            merchant_norm=_normalize_merchant(plan.merchant),
            signed_amount_minor=plan.signed_amount_minor,
            currency=plan.currency,
            event_date=event.transaction_date or event.posting_date,
        )
        proposal = self._propose_from_ranked(ranked, plan.remote_account_id)

        evidence_ids = self._bounded_evidence(ranked)
        query_inputs = self._query_inputs(plan)
        integrity_hash = compute_integrity_hash(
            query_inputs=query_inputs,
            evidence_ids=[e["record_id"] for e in evidence_ids],
        )
        response_metadata = self._response_metadata()

        if proposal.recommendation:
            try:
                _validate_selections(
                    self._session,
                    account_id=proposal.selected_account_id,  # type: ignore[arg-type]
                    category_id=proposal.selected_category_id,
                    label_ids=proposal.selected_label_ids,
                )
            except CatalogValidationError:
                return self._persist_no_rec(
                    event, profile_snapshot, version,
                    "selected catalog item missing or archived",
                )

        decision = EnrichmentDecision(
            financial_event_id=event.id,
            version=version,
            evidence_grade=proposal.evidence_grade,
            selected_account_id=proposal.selected_account_id,
            selected_category_id=proposal.selected_category_id,
            selected_label_ids=list(proposal.selected_label_ids),
            selected_payment_type=proposal.selected_payment_type,
            confidence=None,
            provenance={
                "mcp_evidence_grade": proposal.evidence_grade,
                "rationale": proposal.rationale,
                "profile_snapshot_id": str(profile_snapshot.id),
                "enrichment_service_version": "b1",
            },
            query_inputs=query_inputs,
            evidence_refs={"records": evidence_ids},
            catalog_snapshot_ids=self._current_snapshot_ids(),
            finalized=False,
        )
        self._session.add(decision)
        self._session.flush()
        return decision

    # ── finalization (re-validates against current catalog) ─────────────

    def finalize_decision(
        self, event: FinancialEvent, *, version: int
    ) -> EnrichmentDecision:
        """Finalize a stored, non-finalized decision, re-validating choices.

        Re-validates the selected account/category/labels against the
        *current* catalog snapshots. If the catalog advanced or an item is
        archived/missing, the finalization fails closed rather than carrying
        a stale choice forward.
        """
        decision = self._session.scalar(
            select(EnrichmentDecision).where(
                EnrichmentDecision.financial_event_id == event.id,
                EnrichmentDecision.version == version,
            )
        )
        if decision is None:
            raise ValueError(
                f"no enrichment decision for event {event.id!r} version {version}"
            )
        if decision.finalized:
            return decision
        if decision.evidence_grade not in _FINALIZABLE_GRADES:
            raise ValueError(
                f"cannot finalize a non-recommendation decision "
                f"(grade={decision.evidence_grade!r})"
            )

        try:
            _validate_selections(
                self._session,
                account_id=decision.selected_account_id,  # type: ignore[arg-type]
                category_id=decision.selected_category_id,
                label_ids=tuple(decision.selected_label_ids or ()),
            )
        except CatalogValidationError as exc:
            raise CatalogValidationError(
                "finalization blocked: current catalog no longer validates "
                f"the selected values ({exc})"
            ) from exc

        # Finalizing a newer version supersedes any previously finalized
        # decision for the same event. Atomically clear the prior finalized
        # flag(s) and flush *before* finalizing the target so the partial
        # unique index (one finalized row per event) never sees two finalized
        # rows in the same statement batch. The immutability intent is
        # preserved for every field except this single mutable finalization
        # state flag — an operator can only ever supersede a decision, not
        # rewrite its selections or evidence.
        prior_finalized = self._session.scalars(
            select(EnrichmentDecision).where(
                EnrichmentDecision.financial_event_id == event.id,
                EnrichmentDecision.finalized.is_(True),
                EnrichmentDecision.version != version,
            )
        ).all()
        if prior_finalized:
            for prior in prior_finalized:
                prior.finalized = False
            self._session.flush()

        decision.finalized = True
        self._session.flush()
        return decision

    # ── explicit operator override (new immutable version) ────────────

    def override_decision(
        self,
        event: FinancialEvent,
        *,
        account_id: str,
        category_id: str | None,
        label_ids: Sequence[str],
        payment_type: str | None,
        version: int | None = None,
    ) -> EnrichmentDecision:
        """Create a new immutable enrichment decision version from an explicit
        operator choice.

        Never mutates an existing version. The chosen account/category/labels
        are re-validated against the *current* REST catalog snapshots and the
        operation fails closed (``CatalogValidationError``) when any selected
        item is missing or archived. The new version is stored as
        ``operator_override`` (finalizable) and is not finalized.
        """

        try:
            _validate_selections(
                self._session,
                account_id=account_id,
                category_id=category_id,
                label_ids=tuple(label_ids or ()),
            )
        except CatalogValidationError as exc:
            raise CatalogValidationError(
                f"override blocked: current catalog no longer validates the "
                f"selected values ({exc})"
            ) from exc

        if version is None:
            current = self._session.scalar(
                select(func.max(EnrichmentDecision.version)).where(
                    EnrichmentDecision.financial_event_id == event.id
                )
            )
            version = (current or 0) + 1

        snapshot_ids = self._current_snapshot_ids()
        decision = EnrichmentDecision(
            financial_event_id=event.id,
            version=version,
            evidence_grade="operator_override",
            selected_account_id=account_id,
            selected_category_id=category_id,
            selected_label_ids=list(label_ids or ()),
            selected_payment_type=payment_type,
            confidence=None,
            provenance={
                "rationale": "operator override; validated against current "
                "catalog snapshot",
                "source": "operator_override",
                "catalog_snapshot_ids": snapshot_ids,
                "enrichment_service_version": "c1",
            },
            query_inputs={"override": True},
            evidence_refs={},
            catalog_snapshot_ids=snapshot_ids,
            finalized=False,
        )
        self._session.add(decision)
        self._session.flush()
        return decision

    # ── dry-run Wallet REST record payload preview ─────────────────────

    def build_dry_run_payload(
        self, event: FinancialEvent, decision: EnrichmentDecision
    ) -> dict[str, object]:
        """Return the exact Wallet REST create-record payload for a finalized
        decision — without performing any HTTP or Wallet write.

        Re-validates the selected account/category/labels against the current
        catalog snapshots; if the catalog advanced or an item is now
        missing/archived, the preview fails closed (``CatalogValidationError``)
        rather than returning a stale payload. The returned payload matches
        the authoritative :class:`~wallet_v2.application.contracts.CreateRecordRequest`
        shape used by the Wallet REST adapter.
        """

        if not decision.finalized:
            raise ValueError(
                "dry-run payload preview is only available for a finalized decision"
            )
        if decision.evidence_grade not in _FINALIZABLE_GRADES:
            raise ValueError(
                f"cannot preview a non-recommendation decision "
                f"(grade={decision.evidence_grade!r})"
            )

        try:
            _validate_selections(
                self._session,
                account_id=decision.selected_account_id,  # type: ignore[arg-type]
                category_id=decision.selected_category_id,
                label_ids=tuple(decision.selected_label_ids or ()),
            )
        except CatalogValidationError as exc:
            raise CatalogValidationError(
                "dry-run preview blocked: current catalog no longer validates "
                f"the selected values ({exc})"
            ) from exc

        from decimal import Decimal

        from wallet_v2.application.contracts import CreateRecordRequest

        amount_minor = event.amount_minor or 0
        value_major = float(Decimal(amount_minor) / Decimal(100))
        record_date = event.transaction_date or event.posting_date

        request = CreateRecordRequest(
            account_id=decision.selected_account_id,  # type: ignore[arg-type]
            amount_value=value_major,
            record_date=record_date.isoformat() if record_date else "",
            category_id=decision.selected_category_id,
            currency_code=event.currency,
            note=event.reference,
            counter_party=event.merchant,
            label_ids=tuple(decision.selected_label_ids or ()),
            payment_type=decision.selected_payment_type,
        )
        return request.as_payload()

    # ── internal helpers ────────────────────────────────────────────────

    def _plan_for(
        self,
        *,
        account_id: object,
        direction: str,
        amount_minor: int,
        currency: str,
        merchant: str | None,
        event_date: date | None,
    ) -> QueryPlan | None:
        try:
            return _build_query_plan(
                account_id=account_id,
                direction=direction,
                amount_minor=amount_minor,
                currency=currency,
                merchant=merchant,
                event_date=event_date,
                mapping_service=self._mapping_service,
            )
        except (MappingError, ValueError):
            return None

    def _query_records(self, plan: QueryPlan) -> Any | None:
        """Fetch historical records with bounded pagination.

        Pages through ``next_offset`` until either the server reports no next
        page, the accumulated record count reaches ``_MAX_RECORDS_PER_QUERY``,
        or ``_MAX_PAGINATION_PAGES`` rounds elapse. Every page is requested
        with ``limit=_MAX_RECORDS_PER_QUERY``; the merged result is capped at
        that bound so raw history is never copied unbounded.
        """
        client = self._require_mcp()
        collected: list[Any] = []
        offset = 0
        pages = 0
        while True:
            try:
                page = client.get_records(
                    account_id=plan.remote_account_id,
                    date_from=plan.date_from,
                    date_to=plan.date_to,
                    limit=_MAX_RECORDS_PER_QUERY,
                    offset=offset,
                )
            except (ValueError, PermissionError, TimeoutError, ConnectionError):
                return None
            if page is None:
                return None
            collected.extend(page.records)
            if len(collected) >= _MAX_RECORDS_PER_QUERY:
                break
            next_offset = page.next_offset
            if next_offset is None:
                break
            # Guard against a non-advancing or regressing offsets that would
            # otherwise loop forever.
            if not isinstance(next_offset, int) or next_offset <= offset:
                break
            offset = next_offset
            pages += 1
            if pages >= _MAX_PAGINATION_PAGES:
                break
        capped = collected[:_MAX_RECORDS_PER_QUERY]
        return McpRecordsResult(
            records=tuple(capped),
            total=len(capped),
            offset=0,
            limit=_MAX_RECORDS_PER_QUERY,
            next_offset=None,
        )

    def _propose_from_ranked(
        self, ranked: list[_RankedRecord], remote_account_id: str
    ) -> EnrichmentProposal:
        if not ranked:
            return EnrichmentProposal(
                evidence_grade="no_recommendation",
                recommendation=False,
                rationale="no historical records returned",
            )

        top = ranked[0]
        if top.grade == "exact_recurrence":
            # The category/label/payment vote must consider *only* the exact
            # recurrence rows. Weaker merchant-history rows that happen to
            # share the merchant must not contaminate the exact-match proposal.
            exact_records = [r for r in ranked if r.grade == "exact_recurrence"]
            proposal = self._vote_proposal(
                exact_records,
                remote_account_id,
                grade="exact_recurrence",
                rationale="exact recurrence match on merchant, amount, currency",
            )
            return proposal

        if top.grade == "merchant_history":
            merchant_records = [r for r in ranked if r.grade == "merchant_history"]
            proposal = self._vote_proposal(
                merchant_records,
                remote_account_id,
                grade="merchant_history",
                rationale="normalized merchant history with amount/date proximity",
            )
            if proposal.is_no_recommendation:
                return EnrichmentProposal(
                    evidence_grade="no_recommendation",
                    recommendation=False,
                    rationale="merchant history present but category/label/payment vote tied or weak",
                )
            return proposal

        # Context-only: history is present but no record relates to the
        # canonical event. This is a transparent non-recommendation grade —
        # it tells the operator that context existed, just nothing matchable —
        # distinct from ``no_recommendation`` (no history returned at all).
        return EnrichmentProposal(
            evidence_grade="context_only",
            recommendation=False,
            rationale="context records present but no merchant/amount relation",
        )

    def _vote_proposal(
        self,
        records: Sequence[_RankedRecord],
        remote_account_id: str,
        *,
        grade: str,
        rationale: str,
    ) -> EnrichmentProposal:
        categories: list[str] = []
        labels: list[str] = []
        payments: list[str] = []
        for r in records:
            rec = r.record
            if rec.category is not None:
                categories.append(rec.category.id)
            labels.extend(l.id for l in rec.labels)
            if rec.payment_type is not None:
                payments.append(rec.payment_type)

        category = _majority_vote(categories)
        label_vote = _majority_vote(labels)
        payment = _majority_vote(payments)

        # Fail closed on a tied or absent primary assignment (category or
        # payment). A single merchant-history window with no resolvable
        # category/payment, or with a tied category, is weak/conflicting
        # evidence and must not yield a guessed Wallet value.
        if category is None or payment is None:
            return EnrichmentProposal(
                evidence_grade="no_recommendation",
                recommendation=False,
                rationale=(
                    "category/payment vote tied or absent; "
                    "failing closed to no recommendation"
                ),
            )

        selected_labels: tuple[str, ...] = ()
        if label_vote is not None:
            selected_labels = (label_vote,)

        return EnrichmentProposal(
            evidence_grade=grade,
            recommendation=True,
            selected_account_id=remote_account_id,
            selected_category_id=category,
            selected_label_ids=selected_labels,
            selected_payment_type=payment,
            rationale=rationale,
        )

    def _bounded_evidence(
        self, ranked: Sequence[_RankedRecord]
    ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for r in ranked[:_MAX_EVIDENCE_RECORDS]:
            rec = r.record
            out.append(
                {
                    "record_id": rec.id,
                    "grade": r.grade,
                    "score": r.score,
                    "account_id": rec.account_id,
                    "record_date": rec.record_date,
                    "counter_party": rec.counter_party,
                    "amount_value": rec.amount_value,
                    "currency": rec.currency,
                    "category_id": rec.category.id if rec.category else None,
                    "label_ids": [l.id for l in rec.labels],
                    "payment_type": rec.payment_type,
                }
            )
        return out

    def _query_inputs(self, plan: QueryPlan) -> dict[str, Any]:
        return {
            "remote_account_id": plan.remote_account_id,
            "date_from": plan.date_from,
            "date_to": plan.date_to,
            "merchant": plan.merchant,
            "signed_amount_minor": plan.signed_amount_minor,
            "currency": plan.currency,
            "bound": {
                "max_records": _MAX_RECORDS_PER_QUERY,
                "max_evidence": _MAX_EVIDENCE_RECORDS,
                "window_days": _DATE_WINDOW_DAYS,
            },
        }

    def _response_metadata(self) -> dict[str, Any]:
        if self._mcp is None:
            return {}
        meta = self._mcp.last_response_meta
        return {
            "synced_at": meta.synced_at,
            "last_resource_change": meta.last_resource_change,
            "rate_limit_remaining": meta.rate_limit_remaining,
            "rate_limit_capacity": meta.rate_limit_capacity,
            "rate_limit_refill_per_minute": meta.rate_limit_refill_per_minute,
        }

    def _current_snapshot_ids(self) -> dict[str, Any]:
        ids: dict[str, Any] = {}
        for kind in ("accounts", "categories", "labels", "record_rules"):
            cursor = CatalogSyncService.get_cursor(self._session, kind)
            ids[kind] = (
                str(cursor.current_snapshot_id) if cursor else None
            )
        return ids

    def _no_rec_candidate(
        self,
        candidate: TransactionCandidate,
        profile_snapshot: McpProfileSnapshot,
        rationale: str,
    ) -> CandidateResearchPreview:
        query_inputs: dict[str, Any] = {"rationale": rationale}
        integrity_hash = compute_integrity_hash(
            query_inputs=query_inputs, evidence_ids=[]
        )
        research = AdvisoryResearch(
            candidate_id=candidate.id,
            evidence_grade="no_recommendation",
            profile_snapshot_id=profile_snapshot.id,
            query_inputs=query_inputs,
            response_metadata=self._response_metadata(),
            evidence_ids={"records": []},
            integrity_hash=integrity_hash,
        )
        self._session.add(research)
        self._session.flush()
        return CandidateResearchPreview(
            candidate_id=candidate.id,
            evidence_grade="no_recommendation",
            query_inputs=query_inputs,
            response_metadata=self._response_metadata(),
            evidence_ids={"records": []},
            integrity_hash=integrity_hash,
            recommendation=False,
            rationale=rationale,
        )

    def _persist_no_rec(
        self,
        event: FinancialEvent,
        profile_snapshot: McpProfileSnapshot,
        version: int,
        rationale: str,
    ) -> EnrichmentDecision:
        query_inputs = {"rationale": rationale}
        integrity_hash = compute_integrity_hash(
            query_inputs=query_inputs, evidence_ids=[]
        )
        decision = EnrichmentDecision(
            financial_event_id=event.id,
            version=version,
            evidence_grade="no_recommendation",
            selected_account_id=None,
            selected_category_id=None,
            selected_label_ids=None,
            selected_payment_type=None,
            confidence=None,
            provenance={
                "rationale": rationale,
                "profile_snapshot_id": str(profile_snapshot.id),
                "enrichment_service_version": "b1",
            },
            query_inputs=query_inputs,
            evidence_refs={"records": []},
            catalog_snapshot_ids=self._current_snapshot_ids(),
            finalized=False,
        )
        self._session.add(decision)
        self._session.flush()
        return decision
