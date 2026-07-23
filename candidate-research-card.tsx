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

function formatMinor(minor: number, currency: string) {
  const major = minor / 100;
  return major.toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function buildRecordPayload(research: CandidateResearch): Record<string, unknown> | null {
  if (!research.selected_account_id) return null;
  return {
    accountId: research.selected_account_name || research.selected_account_id,
    categoryId: research.selected_category_name || research.selected_category_id || undefined,
    labelIds: research.selected_label_names.length ? research.selected_label_names : research.selected_label_ids.length ? research.selected_label_ids : undefined,
    paymentType: research.selected_payment_type || undefined,
    recordDate: research.transaction_date || undefined,
    amount: research.amount_minor != null && research.currency
      ? {
          value: (research.direction === "credit" ? 1 : -1) * (research.amount_minor / 100),
          currencyCode: research.currency,
        }
      : undefined,
    note: research.merchant || undefined,
  };
}

export function CandidateResearchCard({
  research,
}: {
  research: CandidateResearch;
}) {
  const [open, setOpen] = useState(false);
  const [showPayload, setShowPayload] = useState(false);
  const gradeText =
    GRADE_LABEL[research.evidence_grade] ?? research.evidence_grade;

  const hasSelections = research.selected_account_id || research.selected_category_id;

  const recordPayload = buildRecordPayload(research);

  return (
    <div>
      {" "}
      {hasSelections && (
        <div
          className="card"
          style={{ marginTop: "0.75rem", padding: "0.75rem" }}
        >
          <div className="card-header" style={{ marginBottom: "0.5rem" }}>
            <div className="card-title" style={{ fontSize: "0.8125rem" }}>
              Proposed Wallet Selection
            </div>
            <span className="badge badge-open" style={{ fontSize: "0.6875rem" }}>
              {gradeText}
            </span>
          </div>
          <div style={{ fontSize: "0.75rem", display: "flex", flexDirection: "column", gap: "0.25rem" }}>
            <div>
              Account:{" "}
              <code>{research.selected_account_name || research.selected_account_id || "—"}</code>
            </div>
            <div>
              Category:{" "}
              <code>{research.selected_category_name || research.selected_category_id || "—"}</code>
            </div>
            <div>
              Labels:{" "}
              <code>
                {research.selected_label_names.length
                  ? research.selected_label_names.join(", ")
                  : research.selected_label_ids.length
                    ? research.selected_label_ids.join(", ")
                    : "—"}
              </code>
            </div>
            <div>
              Payment:{" "}
              <code>{research.selected_payment_type || "—"}</code>
            </div>
          </div>
        </div>
      )}

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
              Evidence ({research.evidence.length} records)
            </div>
            <div className="card-subtitle" style={{ fontSize: "0.75rem" }}>
              Grade: <strong>{gradeText}</strong> · read-only, not finalizable
            </div>
          </div>
        </div>
        <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
          <button
            className="btn-small"
            style={{ marginTop: "0.25rem" }}
            onClick={() => setOpen((v) => !v)}
          >
            {open ? "Hide evidence" : "Evidence"}
          </button>
          {recordPayload && (
            <button
              className="btn-small"
              style={{ marginTop: "0.25rem" }}
              onClick={() => setShowPayload((v) => !v)}
            >
              {showPayload ? "Hide payload" : "Record preview"}
            </button>
          )}
        </div>
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
        {showPayload && recordPayload && (
          <pre
            style={{
              fontSize: "0.6875rem",
              background: "var(--bg-muted, #1b1b1f)",
              color: "var(--text)",
              padding: "0.5rem",
              borderRadius: "6px",
              overflowX: "auto",
              marginTop: "0.5rem",
            }}
          >
            {JSON.stringify(recordPayload, null, 2)}
          </pre>
        )}
      </div>
    </div>
  );
}
