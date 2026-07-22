"use client";

import { useState } from "react";
import type { CandidateResearch } from "@/lib/api";

export const GRADE_LABEL: Record<string, string> = {
  exact_recurrence: "Exact recurrence",
  merchant_history: "Merchant history",
  context_only: "Context only",
  no_recommendation: "No recommendation",
  operator_override: "Operator override",
};

export function CandidateResearchCard({
  research,
}: {
  research: CandidateResearch;
}) {
  const [open, setOpen] = useState(false);
  const gradeText =
    GRADE_LABEL[research.evidence_grade] ?? research.evidence_grade;
  return (
    <div
      className="card"
      style={{
        marginTop: "0.5rem",
        padding: "0.75rem",
        opacity: 0.92,
      }}
    >
      <div className="card-header" style={{ marginBottom: "0.25rem" }}>
        <div>
          <div className="card-title" style={{ fontSize: "0.8125rem" }}>
            {research.rationale || "Advisory research"}
          </div>
          <div className="card-subtitle" style={{ fontSize: "0.75rem" }}>
            Grade: <strong>{gradeText}</strong> · read-only, not finalizable
          </div>
        </div>
      </div>
      <button
        className="btn-small"
        disabled
        style={{ marginTop: "0.25rem" }}
        title="Candidate research can never be finalized or imported"
      >
        Finalize (disabled)
      </button>
      <button
        className="btn-small"
        disabled
        style={{ marginTop: "0.25rem", marginLeft: "0.5rem" }}
        title="Candidate research has no Wallet payload preview"
      >
        Dry-run preview (disabled)
      </button>
      <button
        className="btn-small"
        style={{ marginTop: "0.25rem", marginLeft: "0.5rem" }}
        onClick={() => setOpen((v) => !v)}
      >
        {open ? "Hide evidence" : "Evidence"}
      </button>
      {open && research.evidence.length > 0 && (
        <pre
          style={{
            fontSize: "0.6875rem",
            background: "var(--bg-muted, #1b1b1f)",
            color: "var(--text-muted)",
            padding: "0.5rem",
            borderRadius: "6px",
            overflowX: "auto",
            marginTop: "0.5rem",
          }}
        >
          {JSON.stringify(research.evidence, null, 2)}
        </pre>
      )}
    </div>
  );
}
