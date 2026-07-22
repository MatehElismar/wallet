"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import type { CandidateResearch } from "@/lib/api";
import { getCandidateResearch } from "@/lib/api";
import { CandidateResearchCard, GRADE_LABEL } from "../../candidate-research-card";

export default function CandidateDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const candidateId = params.id;

  const [research, setResearch] = useState<CandidateResearch | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!candidateId) return;
    getCandidateResearch(candidateId)
      .then(setResearch)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [candidateId]);

  if (loading) {
    return (
      <div style={{ textAlign: "center", padding: "2rem" }}>
        <span className="spinner" />
      </div>
    );
  }

  if (error || !research) {
    return (
      <div>
        <div className="alert alert-error">
          {error || "Candidate not found"}
        </div>
        <button
          className="btn-primary btn-small"
          onClick={() => router.push("/candidates")}
        >
          Back to candidates
        </button>
      </div>
    );
  }

  const formatDate = (s: string | null) => {
    if (!s) return "—";
    return new Date(s).toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  };

  const formatMinor = (minor: number, currency: string) => {
    const major = minor / 100;
    return major.toLocaleString("en-US", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
  };

  const upDirection = (d: string) =>
    d.charAt(0).toUpperCase() + d.slice(1);

  const gradeText = GRADE_LABEL[research.evidence_grade] ?? research.evidence_grade;

  return (
    <div>
      <button
        className="btn-primary btn-small"
        onClick={() => router.push("/candidates")}
        style={{ marginBottom: "1rem" }}
      >
        Back
      </button>

      <div className="alert alert-warn" style={{ marginBottom: "1rem" }}>
        Advisory only — this notification candidate cannot be finalized or imported
        to Wallet.
      </div>

      <div className="card">
        <div className="card-header">
          <div>
            <div className="card-title">
              {research.merchant || research.rationale || "Unknown"}
            </div>
            <div className="card-subtitle">
              {research.candidate_id}
            </div>
          </div>
          <span className="badge badge-open">
            {gradeText}
          </span>
        </div>

        <div className="grid-2" style={{ marginBottom: "0.75rem" }}>
          <div className="stat">
            <div className="stat-label">Amount</div>
            <div
              className={`stat-value ${research.direction === "credit" ? "credit" : "debit"}`}
            >
              {research.amount_minor != null && research.currency
                ? `${research.direction === "credit" ? "+" : "−"}${formatMinor(research.amount_minor, research.currency)} ${research.currency}`
                : "—"}
            </div>
          </div>
          <div className="stat">
            <div className="stat-label">Direction</div>
            <div className="stat-value">
              {research.direction ? upDirection(research.direction) : "—"}
            </div>
          </div>
          <div className="stat">
            <div className="stat-label">Transaction Date</div>
            <div className="stat-value">
              {formatDate(research.transaction_date)}
            </div>
          </div>
          <div className="stat">
            <div className="stat-label">Candidate Status</div>
            <div className="stat-value">
              {research.candidate_status || "—"}
            </div>
          </div>
        </div>

        {research.reference && (
          <div className="card-subtitle" style={{ marginBottom: "0.5rem" }}>
            Reference: {research.reference}
          </div>
        )}
      </div>

      <h3
        style={{
          fontSize: "0.9375rem",
          fontWeight: 600,
          margin: "1rem 0 0.5rem",
        }}
      >
        Source Details
      </h3>

      <div className="card">
        <div className="grid-2">
          <div className="stat">
            <div className="stat-label">Sender</div>
            <div className="stat-value" style={{ wordBreak: "break-all" }}>
              {research.sender || "—"}
            </div>
          </div>
          <div className="stat">
            <div className="stat-label">Source Date</div>
            <div className="stat-value">
              {formatDate(research.source_date)}
            </div>
          </div>
        </div>
        {research.subject && (
          <div className="card-subtitle" style={{ marginTop: "0.5rem" }}>
            Subject: {research.subject}
          </div>
        )}
      </div>

      <h3
        style={{
          fontSize: "0.9375rem",
          fontWeight: 600,
          margin: "1rem 0 0.5rem",
        }}
      >
        Enrichment Research
        <span
          style={{
            fontWeight: 400,
            color: "var(--text-muted)",
            fontSize: "0.75rem",
            marginLeft: "0.5rem",
          }}
        >
          advisory only · never finalizable
        </span>
      </h3>

      <CandidateResearchCard research={research} />

      {research.evidence.length === 0 && (
        <div className="alert alert-info" style={{ marginTop: "0.5rem" }}>
          No evidence records available for this candidate.
        </div>
      )}
    </div>
  );
}
