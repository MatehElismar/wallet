"""Phase C operator review surfaces for MCP advisory enrichment.

Two distinct, advisory-only scopes are exposed:

* Candidate research previews (notification ``TransactionCandidate``) — read
  only, never finalizable, never importable. Surfaced with a disabled
  finalize/preview state in the PWA.
* Event enrichment decisions (statement-confirmed ``FinancialEvent``) — versioned
  immutable proposals. Operators may generate an MCP-backed proposal, submit an
  explicit override that creates a *new* immutable version (never mutating an
  old one), finalize a decision, and preview the exact Wallet REST record
  payload for a finalized decision. No endpoint here submits anything to Wallet.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from wallet_v2.api.deps import get_mcp_client, get_session
from wallet_v2.api.schemas import (
    CandidateResearchView,
    DryRunRecordPreview,
    EventEnrichmentView,
    EvidenceRecordView,
    OverrideDecisionRequest,
)
from wallet_v2.application.enrichment import (
    CatalogValidationError,
    EnrichmentService,
    _FINALIZABLE_GRADES,
)
from wallet_v2.domain.enums import ReconciliationOutcome
from wallet_v2.persistence.models import (
    BankStatementLine,
    FinancialEvent,
    StatementReviewBatch,
    TransactionCandidate,
    TransactionObservation,
)
from wallet_v2.persistence.models.mcp import AdvisoryResearch, EnrichmentDecision
from wallet_v2.persistence.models.source_message import SourceMessage

router = APIRouter(prefix="/enrichment", tags=["enrichment"])


# ── view builders ────────────────────────────────────────────────────────


def _candidate_source_info(research: AdvisoryResearch) -> dict[str, object]:
    candidate = research.candidate
    if candidate is None:
        return {}
    source_msg = candidate.source_message
    metadata = source_msg.content_metadata if source_msg is not None else None
    direction_val = candidate.direction.value if hasattr(candidate.direction, "value") else candidate.direction
    status_val = candidate.status.value if hasattr(candidate.status, "value") else candidate.status
    return {
        "merchant": candidate.merchant,
        "reference": candidate.reference,
        "amount_minor": candidate.amount_minor,
        "currency": candidate.currency,
        "direction": direction_val,
        "transaction_date": candidate.transaction_date,
        "candidate_status": status_val,
        "sender": metadata.sender if metadata else None,
        "subject": metadata.subject if metadata else None,
        "source_date": metadata.sent_at if metadata else None,
    }


def _evidence_records(research: AdvisoryResearch) -> list[EvidenceRecordView]:
    evidence_ids = research.evidence_ids or {}
    raw = evidence_ids.get("records") or []
    out: list[EvidenceRecordView] = []
    for r in raw:
        if not isinstance(r, dict):
            continue
        out.append(
            EvidenceRecordView(
                record_id=r.get("record_id"),
                grade=r.get("grade"),
                score=r.get("score"),
                account_id=r.get("account_id"),
                record_date=r.get("record_date"),
                counter_party=r.get("counter_party"),
                amount_value=r.get("amount_value"),
                currency=r.get("currency"),
                category_id=r.get("category_id"),
                label_ids=list(r.get("label_ids") or []),
                payment_type=r.get("payment_type"),
            )
        )
    return out


def _vote_from_evidence(records: list[dict[str, Any]], grade: str) -> dict[str, Any]:
    """Extract top-voted category, labels, and payment from evidence records."""
    matching = [r for r in records if r.get("grade") == grade]
    if not matching:
        matching = [r for r in records if r.get("grade") == "context_only"]
    if not matching:
        return {}

    from collections import Counter

    cat_votes = Counter(r.get("category_id") for r in matching if r.get("category_id"))
    pmt_votes = Counter(r.get("payment_type") for r in matching if r.get("payment_type"))
    label_votes: Counter[str] = Counter()
    for r in matching:
        for lid in r.get("label_ids") or []:
            label_votes[lid] += 1

    return {
        "category_id": cat_votes.most_common(1)[0][0] if cat_votes else None,
        "label_ids": [l for l, _ in label_votes.most_common(5)] if label_votes else [],
        "payment_type": pmt_votes.most_common(1)[0][0] if pmt_votes else None,
    }


def _research_to_view(research: AdvisoryResearch) -> CandidateResearchView:
    query_inputs = research.query_inputs or {}
    source = _candidate_source_info(research)
    evidence_ids = research.evidence_ids or {}
    raw_records: list[dict[str, Any]] = evidence_ids.get("records") or []
    vote = _vote_from_evidence(raw_records, "merchant_history") if raw_records else {}
    return CandidateResearchView(
        candidate_id=str(research.candidate_id),
        evidence_grade=research.evidence_grade,
        # Candidate research is advisory context only: it can never be
        # finalized or imported, so it never surfaces as a recommendation.
        recommendation=False,
        is_finalizable=False,
        selected_account_id=query_inputs.get("remote_account_id"),
        selected_category_id=vote.get("category_id"),
        selected_label_ids=vote.get("label_ids") or [],
        selected_payment_type=vote.get("payment_type"),
        rationale=research.evidence_grade + ": " + (query_inputs.get("rationale") or ""),
        integrity_hash=research.integrity_hash,
        query_inputs=research.query_inputs,
        response_metadata=research.response_metadata,
        evidence=_evidence_records(research),
        merchant=source.get("merchant"),
        reference=source.get("reference"),
        amount_minor=source.get("amount_minor"),
        currency=source.get("currency"),
        direction=source.get("direction"),
        transaction_date=source.get("transaction_date"),
        candidate_status=source.get("candidate_status"),
        sender=source.get("sender"),
        subject=source.get("subject"),
        source_date=source.get("source_date"),
    )


def _decision_to_view(decision: EnrichmentDecision) -> EventEnrichmentView:
    provenance = decision.provenance or {}
    return EventEnrichmentView(
        line_id=str(decision.statement_line_id),
        event_id=str(decision.financial_event_id) if decision.financial_event_id else None,
        version=decision.version,
        evidence_grade=decision.evidence_grade,
        recommendation=decision.evidence_grade in _FINALIZABLE_GRADES,
        finalized=decision.finalized,
        can_finalize=(
            not decision.finalized
            and decision.evidence_grade in _FINALIZABLE_GRADES
        ),
        selected_account_id=decision.selected_account_id,
        selected_category_id=decision.selected_category_id,
        selected_label_ids=list(decision.selected_label_ids or ()),
        selected_payment_type=decision.selected_payment_type,
        rationale=provenance.get("rationale", ""),
        query_inputs=decision.query_inputs,
        evidence_refs=decision.evidence_refs,
        catalog_snapshot_ids=decision.catalog_snapshot_ids,
        provenance=decision.provenance,
        created_at=decision.created_at,
    )


def _latest_decision(
    session: Session, event_id: UUID
) -> EnrichmentDecision | None:
    return session.scalar(
        select(EnrichmentDecision)
        .where(EnrichmentDecision.financial_event_id == event_id)
        .order_by(EnrichmentDecision.version.desc())
    )


def _next_version(session: Session, event_id: UUID) -> int:
    current = session.scalar(
        select(func.max(EnrichmentDecision.version)).where(
            EnrichmentDecision.financial_event_id == event_id
        )
    )
    return (current or 0) + 1


def _latest_line_decision(
    session: Session, line_id: UUID
) -> EnrichmentDecision | None:
    return session.scalar(
        select(EnrichmentDecision)
        .where(EnrichmentDecision.statement_line_id == line_id)
        .order_by(EnrichmentDecision.version.desc())
    )


def _next_line_version(session: Session, line_id: UUID) -> int:
    current = session.scalar(
        select(func.max(EnrichmentDecision.version)).where(
            EnrichmentDecision.statement_line_id == line_id
        )
    )
    return (current or 0) + 1


def _candidate_to_view(candidate: TransactionCandidate) -> CandidateResearchView:
    source_msg = candidate.source_message
    metadata = source_msg.content_metadata if source_msg is not None else None
    direction_val = candidate.direction.value if hasattr(candidate.direction, "value") else candidate.direction
    status_val = candidate.status.value if hasattr(candidate.status, "value") else candidate.status
    return CandidateResearchView(
        candidate_id=str(candidate.id),
        evidence_grade="pending",
        recommendation=False,
        is_finalizable=False,
        selected_account_id=None,
        rationale="Advisory research pending",
        integrity_hash=None,
        query_inputs=None,
        response_metadata=None,
        evidence=[],
        merchant=candidate.merchant,
        reference=candidate.reference,
        amount_minor=candidate.amount_minor,
        currency=candidate.currency,
        direction=direction_val,
        transaction_date=candidate.transaction_date,
        candidate_status=status_val,
        sender=metadata.sender if metadata else None,
        subject=metadata.subject if metadata else None,
        source_date=metadata.sent_at if metadata else None,
    )


# ── candidate advisory research (read-only, never finalizable) ───────────


@router.get("/candidates", response_model=list[CandidateResearchView])
def list_candidate_research(
    session: Session = Depends(get_session),
) -> list[CandidateResearchView]:
    """List all notification candidates and their advisory research, newest first."""
    candidates = session.scalars(
        select(TransactionCandidate)
        .options(
            joinedload(TransactionCandidate.source_message)
            .joinedload(SourceMessage.content_metadata),
        )
        .order_by(TransactionCandidate.created_at.desc())
    ).unique().all()
    out: list[CandidateResearchView] = []
    for cand in candidates:
        research = session.scalar(
            select(AdvisoryResearch)
            .where(AdvisoryResearch.candidate_id == cand.id)
            .order_by(AdvisoryResearch.created_at.desc())
        )
        if research is not None:
            out.append(_research_to_view(research))
        else:
            out.append(_candidate_to_view(cand))
    return out


@router.get("/candidates/{candidate_id}", response_model=CandidateResearchView)
def get_candidate_research(
    candidate_id: UUID,
    session: Session = Depends(get_session),
    mcp_client: McpReadOnlyClient | None = Depends(get_mcp_client),
) -> CandidateResearchView:
    candidate = session.get(TransactionCandidate, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="candidate not found")
    research = session.scalar(
        select(AdvisoryResearch)
        .where(AdvisoryResearch.candidate_id == candidate_id)
        .order_by(AdvisoryResearch.created_at.desc())
    )
    if research is None and mcp_client is not None:
        try:
            svc = EnrichmentService(session, mcp_client)
            svc.build_candidate_preview(candidate)
            session.commit()
            research = session.scalar(
                select(AdvisoryResearch)
                .where(AdvisoryResearch.candidate_id == candidate_id)
                .order_by(AdvisoryResearch.created_at.desc())
            )
        except Exception:
            pass
    if research is not None:
        return _research_to_view(research)
    return _candidate_to_view(candidate)


@router.get(
    "/candidates/account/{account_id}",
    response_model=list[CandidateResearchView],
)
def list_candidate_research_by_account(
    account_id: UUID,
    session: Session = Depends(get_session),
) -> list[CandidateResearchView]:
    """Read-only candidate research for an account — surfaced disabled in PWA."""

    rows = session.scalars(
        select(AdvisoryResearch)
        .options(
            joinedload(AdvisoryResearch.candidate)
            .joinedload(TransactionCandidate.source_message)
            .joinedload(SourceMessage.content_metadata),
        )
        .join(
            TransactionCandidate,
            AdvisoryResearch.candidate_id == TransactionCandidate.id,
        )
        .join(
            TransactionObservation,
            TransactionCandidate.id == TransactionObservation.candidate_id,
        )
        .where(TransactionObservation.account_id == account_id)
        .order_by(AdvisoryResearch.created_at.desc())
    ).unique().all()
    return [_research_to_view(r) for r in rows]


# ── event enrichment decisions ──────────────────────────────────────────


@router.get("/events/{event_id}", response_model=EventEnrichmentView)
def get_event_enrichment(
    event_id: UUID,
    session: Session = Depends(get_session),
) -> EventEnrichmentView:
    event = session.get(FinancialEvent, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="financial event not found")
    decision = _latest_decision(session, event_id)
    if decision is None:
        raise HTTPException(
            status_code=404, detail="no enrichment decision for event"
        )
    return _decision_to_view(decision)


@router.post("/events/{event_id}/generate", response_model=EventEnrichmentView)
def generate_event_decision(
    event_id: UUID,
    session: Session = Depends(get_session),
    mcp=Depends(get_mcp_client),
) -> EventEnrichmentView:
    """Generate an MCP-backed deterministic proposal as a new version.

    Creates a new immutable ``EnrichmentDecision`` version; never overwrites an
    existing one.
    """
    event = session.get(FinancialEvent, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="financial event not found")
    if mcp is None:
        raise HTTPException(
            status_code=503, detail="MCP advisory integration is disabled"
        )
    service = EnrichmentService(session, mcp)
    version = _next_version(session, event_id)
    try:
        decision = service.build_event_decision(event, version=version)
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail="enrichment decision version conflict; retry",
        ) from exc
    return _decision_to_view(decision)


@router.post("/events/{event_id}/override", response_model=EventEnrichmentView)
def override_event_decision(
    event_id: UUID,
    body: OverrideDecisionRequest,
    session: Session = Depends(get_session),
) -> EventEnrichmentView:
    """Create a new immutable override version from an explicit operator choice.

    Validates the selected account/category/labels against the current REST
    catalog snapshots; fails closed (422) when any item is missing/archived.
    Never mutates an existing version. This operator-only surface never touches
    MCP, so the service is constructed without an MCP client.
    """
    event = session.get(FinancialEvent, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="financial event not found")
    service = EnrichmentService(session)
    try:
        decision = service.override_decision(
            event,
            account_id=body.account_id,
            category_id=body.category_id,
            label_ids=body.label_ids,
            payment_type=body.payment_type,
        )
        session.commit()
    except CatalogValidationError as exc:
        session.rollback()
        raise HTTPException(status_code=422, detail=str(exc))
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail="enrichment decision version conflict; retry",
        ) from exc
    return _decision_to_view(decision)


@router.post("/events/{event_id}/finalize", response_model=EventEnrichmentView)
def finalize_event_decision(
    event_id: UUID,
    session: Session = Depends(get_session),
) -> EventEnrichmentView:
    """Finalize the current event decision, re-validating against the catalog.

    Only a finalizable event decision may be finalized; candidate research has
    no finalize endpoint. Finalizing a newer version supersedes any prior
    finalized decision for the event. Fails closed (409) when the decision is
    not finalizable or the catalog no longer validates the selected values.
    This operator-only surface never touches MCP.
    """
    event = session.get(FinancialEvent, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="financial event not found")
    decision = _latest_decision(session, event_id)
    if decision is None:
        raise HTTPException(
            status_code=404, detail="no enrichment decision for event"
        )
    service = EnrichmentService(session)
    try:
        finalized = service.finalize_decision(event, version=decision.version)
        session.commit()
    except (ValueError, CatalogValidationError) as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(exc))
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail="enrichment finalization conflict; retry",
        ) from exc
    return _decision_to_view(finalized)


@router.get(
    "/events/{event_id}/dry-run-preview",
    response_model=DryRunRecordPreview,
)
def dry_run_record_preview(
    event_id: UUID,
    session: Session = Depends(get_session),
) -> DryRunRecordPreview:
    """Return the exact Wallet REST create-record payload for a finalized valid
    decision — without performing any HTTP or Wallet write.

    Candidate research is never eligible. A non-finalized or catalog-invalid
    decision fails closed (409). This operator-only surface never touches MCP.
    """
    event = session.get(FinancialEvent, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="financial event not found")
    decision = _latest_decision(session, event_id)
    if decision is None:
        raise HTTPException(
            status_code=404, detail="no enrichment decision for event"
        )
    service = EnrichmentService(session)
    try:
        payload = service.build_dry_run_payload(event, decision)
    except (ValueError, CatalogValidationError) as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return DryRunRecordPreview(
        event_id=str(event.id),
        decision_version=decision.version,
        submitted=False,
        payload=payload,
        catalog_snapshot_ids=decision.catalog_snapshot_ids,
    )


# ── batch & line pre-enrichment proposals ─────────────────────────────────


@router.post(
    "/batches/{batch_id}/generate-proposals",
    response_model=list[EventEnrichmentView],
)
def generate_batch_proposals(
    batch_id: UUID,
    session: Session = Depends(get_session),
    mcp=Depends(get_mcp_client),
) -> list[EventEnrichmentView]:
    """Generate pre-enrichment proposals for every resolved line in the batch."""
    batch = session.get(StatementReviewBatch, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="batch not found")
    if mcp is None:
        raise HTTPException(
            status_code=503, detail="MCP advisory integration is disabled"
        )
    service = EnrichmentService(session, mcp)
    statement = batch.statement
    decisions = []
    for line in statement.lines:
        if line.resolution and line.resolution.outcome != ReconciliationOutcome.AMBIGUOUS:
            version = _next_line_version(session, line.id)
            decision = service.build_line_decision(line, version=version)
            decisions.append(decision)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail="enrichment proposal version conflict; retry",
        ) from exc
    return [_decision_to_view(d) for d in decisions]


@router.get("/lines/{line_id}", response_model=EventEnrichmentView)
def get_line_enrichment(
    line_id: UUID,
    session: Session = Depends(get_session),
) -> EventEnrichmentView:
    line = session.get(BankStatementLine, line_id)
    if line is None:
        raise HTTPException(status_code=404, detail="statement line not found")
    decision = _latest_line_decision(session, line_id)
    if decision is None:
        raise HTTPException(
            status_code=404, detail="no enrichment proposal for statement line"
        )
    return _decision_to_view(decision)


@router.post("/lines/{line_id}/override", response_model=EventEnrichmentView)
def override_line_decision(
    line_id: UUID,
    body: OverrideDecisionRequest,
    session: Session = Depends(get_session),
) -> EventEnrichmentView:
    """Create a new immutable override version for a statement line before approval."""
    line = session.get(BankStatementLine, line_id)
    if line is None:
        raise HTTPException(status_code=404, detail="statement line not found")
    service = EnrichmentService(session)
    try:
        decision = service.override_decision(
            line,
            account_id=body.account_id,
            category_id=body.category_id,
            label_ids=body.label_ids,
            payment_type=body.payment_type,
        )
        session.commit()
    except CatalogValidationError as exc:
        session.rollback()
        raise HTTPException(status_code=422, detail=str(exc))
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail="enrichment decision version conflict; retry",
        ) from exc
    return _decision_to_view(decision)
