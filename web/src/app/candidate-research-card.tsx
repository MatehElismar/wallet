"use client";

import { useState } from "react";

import { AdvisoryBanner, AuthorityChip } from "@/components/authority";
import { Badge, Card, CardHeader, DataList } from "@/components/ui";
import type { CandidateResearch } from "@/lib/api";

export const GRADE_LABEL: Record<string, string> = {
  exact_recurrence: "Exact recurrence",
  merchant_history: "Merchant history",
  context_only: "Context only",
  no_recommendation: "No recommendation",
  operator_override: "Operator override",
};

export function CandidateResearchCard({ research }: { research: CandidateResearch }) {
  const [open, setOpen] = useState(false);
  const gradeText = GRADE_LABEL[research.evidence_grade] ?? research.evidence_grade;
  const hasSelections = research.selected_account_id || research.selected_category_id;

  return (
    <div className="stack-sm">
      <AdvisoryBanner />
      {hasSelections ? (
        <Card tone="advisory">
          <CardHeader title="Advisory classification" subtitle="A research proposal, not a Wallet payload" aside={<AuthorityChip tier="advisory" compact />} />
          <DataList items={[
            { label: "Suggested account", value: research.selected_account_name || research.selected_account_id || "—" },
            { label: "Suggested category", value: research.selected_category_name || research.selected_category_id || "—" },
            { label: "Suggested labels", value: research.selected_label_names.length ? research.selected_label_names.join(", ") : research.selected_label_ids.length ? research.selected_label_ids.join(", ") : "—" },
            { label: "Suggested payment type", value: research.selected_payment_type || "—" },
          ]} />
        </Card>
      ) : null}
      <Card>
        <CardHeader title={`Research evidence · ${research.evidence.length} records`} subtitle={`Evidence grade: ${gradeText}`} aside={<Badge tone="advisory">Read-only research</Badge>} />
        <p className="card-copy">This evidence may help an operator understand or link a posted statement line. It never creates a canonical proposal, import request, or Wallet-shaped payload.</p>
        <button type="button" className="btn btn-secondary btn-small" onClick={() => setOpen((value) => !value)} aria-expanded={open}>
          {open ? "Hide evidence data" : "View evidence data"}
        </button>
        {open ? <pre className="json-panel">{JSON.stringify(research.evidence, null, 2)}</pre> : null}
      </Card>
    </div>
  );
}
