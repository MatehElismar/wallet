"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";

import { AdvisoryBanner, AuthorityChip } from "@/components/authority";
import { Card, CardHeader, DataList, ErrorState, LoadingState, PageHeader, Section } from "@/components/ui";
import { getCandidateResearch, type CandidateResearch } from "@/lib/api";
import { formatDate, formatDateTime, formatSignedAmount, humanizeToken, shortId } from "@/ui/format";
import { CandidateResearchCard, GRADE_LABEL } from "../../candidate-research-card";

export default function CandidateDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const [research, setResearch] = useState<CandidateResearch | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => { if (!params.id) return; setLoading(true); setError(null); getCandidateResearch(params.id).then(setResearch).catch((reason: Error) => setError(reason.message || "Observation not found.")).finally(() => setLoading(false)); }, [params.id]);
  useEffect(() => { load(); }, [load]);

  if (loading) return <LoadingState label="Loading notification observation…" />;
  if (error || !research) return <ErrorState message={error || "Notification observation not found."} onRetry={load} retryLabel="Try again" />;
  const grade = GRADE_LABEL[research.evidence_grade] ?? research.evidence_grade;
  return <>
    <button type="button" className="btn btn-secondary btn-small" onClick={() => router.push("/candidates")}>Back to observations</button>
    <PageHeader title={research.merchant || research.rationale || "Notification observation"} lede={`Observation ${shortId(research.candidate_id)} · ${grade || "Evidence pending"}`} />
    <AdvisoryBanner />
    <Section title="Observed context" note="This reflects an email-derived observation, not a posted ledger transaction."><Card tone="advisory"><CardHeader title="Observation details" aside={<AuthorityChip tier="advisory" compact />} /><DataList items={[{ label: "Amount", value: formatSignedAmount(research.amount_minor, research.currency, research.direction) }, { label: "Observed date", value: formatDate(research.transaction_date) }, { label: "Status", value: humanizeToken(research.candidate_status) }, { label: "Reference", value: research.reference || "—" }]} /></Card></Section>
    <Section title="Source evidence" note="Source information remains available for review without treating it as authority."><Card><DataList items={[{ label: "Sender", value: research.sender || "—" }, { label: "Source date", value: formatDateTime(research.source_date) }, { label: "Subject", value: research.subject || "—" }]} /></Card></Section>
    <Section title="Advisory research" note="The proposal below may guide evidence review. It does not produce a record payload."><CandidateResearchCard research={research} /></Section>
  </>;
}
