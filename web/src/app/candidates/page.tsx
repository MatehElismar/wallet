"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { AdvisoryBanner, AuthorityChip } from "@/components/authority";
import { Badge, Card, CardHeader, EmptyState, ErrorState, LoadingState, PageHeader, Section, Stat, StatGrid } from "@/components/ui";
import { listCandidates, type CandidateResearch } from "@/lib/api";
import { formatDate, formatSignedAmount, humanizeToken } from "@/ui/format";
import { GRADE_LABEL } from "../candidate-research-card";

export default function CandidatesPage() {
  const [candidates, setCandidates] = useState<CandidateResearch[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => {
    setLoading(true); setError(null);
    listCandidates().then(setCandidates).catch((reason: Error) => setError(reason.message || "Unable to load notification observations.")).finally(() => setLoading(false));
  }, []);
  useEffect(() => { load(); }, [load]);

  return <>
    <PageHeader title="Notification observations" lede="Legacy email-derived context. It can support a statement review, but it cannot create a canonical proposal or change Wallet." />
    <AdvisoryBanner />
    {loading ? <LoadingState label="Loading notification observations…" /> : null}
    {error ? <ErrorState message={error} onRetry={load} retryLabel="Reload observations" /> : null}
    {!loading && !error && candidates.length === 0 ? <EmptyState title="No notification observations"><p>Email-derived observations appear here when the configured mailbox is processed. They remain separate from historical reconciliation coverage until corroborated by a posted statement line.</p></EmptyState> : null}
    {!loading && !error && candidates.length > 0 ? <Section title="Available advisory evidence" note="Research grades describe the available context; they do not express financial authority."><div className="card-grid">{candidates.map((candidate) => <Link key={candidate.candidate_id} href={`/candidates/${candidate.candidate_id}`} className="card-link"><Card tone="advisory"><CardHeader title={candidate.merchant || candidate.rationale || "Unidentified observation"} subtitle={candidate.sender || candidate.reference || "Source unavailable"} aside={<Badge tone="advisory">{GRADE_LABEL[candidate.evidence_grade] ?? candidate.evidence_grade ?? "Pending"}</Badge>} /><StatGrid><Stat label="Amount" value={formatSignedAmount(candidate.amount_minor, candidate.currency, candidate.direction)} /><Stat label="Observed date" value={formatDate(candidate.transaction_date)} /><Stat label="Status" value={humanizeToken(candidate.candidate_status)} /><Stat label="Authority" value={<AuthorityChip tier="advisory" compact />} /></StatGrid><p className="card-link-hint">Inspect advisory evidence <span aria-hidden="true">→</span></p></Card></Link>)}</div></Section> : null}
  </>;
}
