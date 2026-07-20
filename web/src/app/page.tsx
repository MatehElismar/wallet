"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import type { BatchSummary } from "@/lib/api";
import { listBatches } from "@/lib/api";

export default function HomePage() {
  const [batches, setBatches] = useState<BatchSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listBatches()
      .then((data) => setBatches(data.batches))
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div style={{ textAlign: "center", padding: "2rem" }}>
        <span className="spinner" />
        <span style={{ marginLeft: "0.5rem", color: "var(--text-muted)" }}>
          Loading batches...
        </span>
      </div>
    );
  }

  if (error) {
    return <div className="alert alert-error">{error}</div>;
  }

  if (batches.length === 0) {
    return (
      <div className="alert alert-info">
        No open statement batches. Ingest a statement to begin reconciliation.
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

  return (
    <div>
      <h2 style={{ fontSize: "1rem", fontWeight: 600, marginBottom: "1rem" }}>
        Open Batches
      </h2>
      {batches.map((batch) => (
        <Link
          key={batch.batch_id}
          href={`/batches/${batch.batch_id}`}
          style={{ color: "inherit", textDecoration: "none" }}
        >
          <div className="card" style={{ cursor: "pointer" }}>
            <div className="card-header">
              <div>
                <div className="card-title">
                  {batch.account_issuer || "Unknown"} —{" "}
                  {batch.account_reference || "Unknown"}
                </div>
                <div className="card-subtitle">
                  {batch.statement_currency || "???"}{" "}
                  {batch.statement_date
                    ? formatDate(batch.statement_date)
                    : "No date"}
                </div>
              </div>
              <span className="badge badge-open">{batch.state}</span>
            </div>
            <div className="grid-2">
              <div className="stat">
                <div className="stat-label">Lines</div>
                <div className="stat-value">{batch.line_count}</div>
              </div>
              <div className="stat">
                <div className="stat-label">Resolved</div>
                <div className="stat-value">
                  {batch.line_resolved_count} / {batch.line_count}
                </div>
              </div>
            </div>
            {batch.ambiguous_count > 0 && (
              <div
                style={{ marginTop: "0.5rem" }}
                className="badge badge-ambiguous"
              >
                {batch.ambiguous_count} ambiguous
              </div>
            )}
            {batch.period_start && batch.period_end && (
              <div
                className="card-subtitle"
                style={{ marginTop: "0.5rem" }}
              >
                {formatDate(batch.period_start)} –{" "}
                {formatDate(batch.period_end)}
              </div>
            )}
          </div>
        </Link>
      ))}
    </div>
  );
}
