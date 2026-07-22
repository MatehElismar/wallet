"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import type { CandidateResearch } from "@/lib/api";
import { listCandidates } from "@/lib/api";
import { GRADE_LABEL } from "../candidate-research-card";

export default function CandidatesPage() {
  const [candidates, setCandidates] = useState<CandidateResearch[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listCandidates()
      .then(setCandidates)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div style={{ textAlign: "center", padding: "2rem" }}>
        <span className="spinner" />
        <span style={{ marginLeft: "0.5rem", color: "var(--text-muted)" }}>
          Loading candidates...
        </span>
      </div>
    );
  }

  if (error) {
    return <div className="alert alert-error">{error}</div>;
  }

  if (candidates.length === 0) {
    return (
      <div className="alert alert-info">
        No notification candidates. Candidates appear when transactional
        notifications (e.g. Banco Santa Cruz debits, BHD transfers) are
        extracted from email.
      </div>
    );
  }

  const formatDate = (s: string | null) => {
    if (!s) return "—";
    return new Date(s).toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
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

  const bankLabel = (c: CandidateResearch) => {
    if (c.sender) return c.sender;
    if (c.reference) return c.reference;
    return "—";
  };

  return (
    <div>
      <h2 style={{ fontSize: "1rem", fontWeight: 600, marginBottom: "1rem" }}>
        Notification Candidates
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
      </h2>

      {candidates.map((c) => (
        <Link
          key={c.candidate_id}
          href={`/candidates/${c.candidate_id}`}
          style={{ color: "inherit", textDecoration: "none" }}
        >
          <div className="card" style={{ cursor: "pointer" }}>
            <div className="card-header">
              <div>
                <div className="card-title">
                  {c.merchant || c.rationale || "Unknown"}
                </div>
                <div className="card-subtitle">
                  {bankLabel(c)}
                </div>
              </div>
              <span className="badge badge-open">
                {c.evidence_grade
                  ? GRADE_LABEL[c.evidence_grade] ?? c.evidence_grade
                  : "pending"}
              </span>
            </div>
            <div className="grid-2">
              <div className="stat">
                <div className="stat-label">Amount</div>
                <div
                  className={`stat-value ${c.direction === "credit" ? "credit" : "debit"}`}
                >
                  {c.amount_minor != null && c.currency
                    ? `${c.direction === "credit" ? "+" : "−"}${formatMinor(c.amount_minor, c.currency)} ${c.currency}`
                    : "—"}
                </div>
              </div>
              <div className="stat">
                <div className="stat-label">Direction</div>
                <div className="stat-value">
                  {c.direction ? upDirection(c.direction) : "—"}
                </div>
              </div>
              <div className="stat">
                <div className="stat-label">Date</div>
                <div className="stat-value">
                  {formatDate(c.transaction_date)}
                </div>
              </div>
              <div className="stat">
                <div className="stat-label">Status</div>
                <div className="stat-value">
                  {c.candidate_status || "—"}
                </div>
              </div>
            </div>
            {c.subject && (
              <div
                className="card-subtitle"
                style={{ marginTop: "0.5rem" }}
              >
                {c.subject}
              </div>
            )}
          </div>
        </Link>
      ))}
    </div>
  );
}
