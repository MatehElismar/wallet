"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import {
  getBatchDetail,
  resolveLine,
  mapAccount,
  approveBatch,
  dryRunImport,
} from "@/lib/api";
import type {
  BatchDetail,
  StatementLineView,
  FinancialEventView,
  ObservationView,
} from "@/lib/api";

interface ResolveModal {
  lineId: string;
  lineIndex: number;
  merchant: string | null;
  externalRef: string | null;
  amount: number;
  currency: string;
  direction: string;
  eligibleObservations: ObservationView[];
}

interface DryRunResult {
  event_id: string;
  command_id: string;
}

export default function BatchDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const batchId = params.id;

  const [batch, setBatch] = useState<BatchDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const [mapModal, setMapModal] = useState(false);
  const [walletRef, setWalletRef] = useState("");

  const [resolveModal, setResolveModal] = useState<ResolveModal | null>(null);
  const [resolveOutcome, setResolveOutcome] = useState("new");
  const [resolveObservationId, setResolveObservationId] = useState("");
  const [resolveNote, setResolveNote] = useState("");

  const [approveReviewer, setApproveReviewer] = useState("operator");
  const [approving, setApproving] = useState(false);
  const [dryRunResults, setDryRunResults] = useState<DryRunResult[]>([]);
  const [approvedEvents, setApprovedEvents] = useState<FinancialEventView[]>([]);

  useEffect(() => {
    if (!batchId) return;
    getBatchDetail(batchId)
      .then(setBatch)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [batchId]);

  const refresh = () => {
    setLoading(true);
    getBatchDetail(batchId)
      .then(setBatch)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  };

  if (loading) {
    return (
      <div style={{ textAlign: "center", padding: "2rem" }}>
        <span className="spinner" />
      </div>
    );
  }

  if (error || !batch) {
    return (
      <div>
        <div className="alert alert-error">{error || "Batch not found"}</div>
        <button className="btn-primary" onClick={() => router.push("/")}>
          Back to batches
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
    });
  };

  const formatMinor = (minor: number, currency: string) => {
    const major = minor / 100;
    return major.toLocaleString("en-US", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
  };

  const allResolved = batch.lines.every(
    (l) => l.reconciliation && l.reconciliation.outcome !== "ambiguous"
  );
  const isApproved = batch.state === "approved";

  const handleResolve = async () => {
    if (!resolveModal) return;
    setActionError(null);
    try {
      await resolveLine(resolveModal.lineId, {
        outcome: resolveOutcome,
        observation_id: resolveOutcome === "matched" && resolveObservationId
          ? resolveObservationId
          : undefined,
        note: resolveNote || undefined,
      });
      setResolveModal(null);
      setResolveObservationId("");
      refresh();
    } catch (err: unknown) {
      setActionError(err instanceof Error ? err.message : "Resolve failed");
    }
  };

  const handleMapAccount = async () => {
    if (!batch.account) return;
    setActionError(null);
    try {
      await mapAccount(batch.account.account_id, {
        wallet_account_reference: walletRef,
      });
      setMapModal(false);
      refresh();
    } catch (err: unknown) {
      setActionError(err instanceof Error ? err.message : "Map failed");
    }
  };

  const handleApprove = async () => {
    setActionError(null);
    setApproving(true);
    try {
      const result = await approveBatch(batchId, {
        reviewer_id: approveReviewer,
      });
      setApprovedEvents(result.events);
      refresh();
    } catch (err: unknown) {
      setActionError(err instanceof Error ? err.message : "Approve failed");
    } finally {
      setApproving(false);
    }
  };

  const handleDryRun = async (event: FinancialEventView) => {
    setActionError(null);
    try {
      const result = await dryRunImport(event.event_id);
      setDryRunResults((prev) => [
        ...prev,
        { event_id: event.event_id, command_id: result.command_id },
      ]);
    } catch (err: unknown) {
      setActionError(err instanceof Error ? err.message : "Dry-run failed");
    }
  };

  const resolvedCount = batch.lines.filter(
    (l) => l.reconciliation && l.reconciliation.outcome !== "ambiguous"
  ).length;
  const ambiguousCount = batch.lines.filter(
    (l) => l.reconciliation?.outcome === "ambiguous"
  ).length;

  const upDirection = (d: string) =>
    d.charAt(0).toUpperCase() + d.slice(1);

  return (
    <div>
      <button
        className="btn-primary btn-small"
        onClick={() => router.push("/")}
        style={{ marginBottom: "1rem" }}
      >
        Back
      </button>

      {actionError && (
        <div className="alert alert-error">{actionError}</div>
      )}

      <div className="card">
        <div className="card-header">
          <div>
            <div className="card-title">
              {batch.account?.issuer || "Unknown"} —{" "}
              {batch.account?.external_reference || "Unknown"}
            </div>
            <div className="card-subtitle">
              {batch.statement_currency || "???"} |{" "}
              {formatDate(batch.statement_date)}
            </div>
          </div>
          <span
            className={`badge ${isApproved ? "badge-approved" : "badge-open"}`}
          >
            {batch.state}
          </span>
        </div>
        <div className="grid-2" style={{ marginBottom: "0.75rem" }}>
          <div className="stat">
            <div className="stat-label">Lines</div>
            <div className="stat-value">{batch.lines.length}</div>
          </div>
          <div className="stat">
            <div className="stat-label">Resolved</div>
            <div className="stat-value">
              {resolvedCount} / {batch.lines.length}
            </div>
          </div>
          <div className="stat">
            <div className="stat-label">Open Balance</div>
            <div className="stat-value">
              {batch.opening_balance_minor != null
                ? `${formatMinor(batch.opening_balance_minor, batch.statement_currency || "USD")} ${batch.statement_currency || ""}`
                : "—"}
            </div>
          </div>
          <div className="stat">
            <div className="stat-label">Close Balance</div>
            <div className="stat-value">
              {batch.closing_balance_minor != null
                ? `${formatMinor(batch.closing_balance_minor, batch.statement_currency || "USD")} ${batch.statement_currency || ""}`
                : "—"}
            </div>
          </div>
        </div>
        {batch.period_start && batch.period_end && (
          <div className="card-subtitle">
            Period: {formatDate(batch.period_start)} –{" "}
            {formatDate(batch.period_end)}
          </div>
        )}
      </div>

      {batch.account && (
        <div className="card">
          <div className="card-header">
            <div>
              <div className="card-title">Wallet Account Mapping</div>
              <div className="card-subtitle">
                {batch.account.wallet_account_reference || "Not mapped"}
              </div>
            </div>
            <button
              className="btn-primary btn-small"
              onClick={() => setMapModal(true)}
            >
              Map
            </button>
          </div>
        </div>
      )}

      <h3 style={{ fontSize: "0.9375rem", fontWeight: 600, margin: "1rem 0 0.5rem" }}>
        Statement Lines
      </h3>

      {batch.lines.map((line) => (
        <LineItem
          key={line.line_id}
          line={line}
          isApproved={isApproved}
          onResolve={(l) => {
            setResolveOutcome("new");
            setResolveObservationId("");
            setResolveNote("");
            setResolveModal({
              lineId: l.line_id,
              lineIndex: l.line_index,
              merchant: l.merchant,
              externalRef: l.external_reference,
              amount: l.amount_minor,
              currency: l.currency,
              direction: l.direction,
              eligibleObservations: l.eligible_observations,
            });
          }}
          onDryRun={handleDryRun}
          dryRunResult={dryRunResults.find(
            (r) => r.event_id === line.event_id
          )}
        />
      ))}

      {!isApproved && ambiguousCount > 0 && (
        <div className="alert alert-warn" style={{ marginTop: "1rem" }}>
          {ambiguousCount} ambiguous {ambiguousCount === 1 ? "line" : "lines"}{" "}
          must be resolved before approval.
        </div>
      )}

      {!isApproved && (
        <div
          className="card"
          style={{
            marginTop: "1rem",
            display: "flex",
            flexDirection: "column",
            gap: "0.75rem",
          }}
        >
          <div>
            <div className="card-title" style={{ marginBottom: "0.5rem" }}>
              Approve Batch
            </div>
            <div className="form-group">
              <label>Reviewer ID</label>
              <input
                value={approveReviewer}
                onChange={(e) => setApproveReviewer(e.target.value)}
              />
            </div>
          </div>
          <button
            className="btn-primary"
            disabled={!allResolved || approving}
            onClick={handleApprove}
          >
            {approving
              ? "Approving..."
              : allResolved
                ? "Approve All"
                : "Resolve all lines first"}
          </button>
        </div>
      )}

      {isApproved && (
        <div className="alert alert-info" style={{ marginTop: "1rem" }}>
          Batch approved. Issuing a dry-run import intent for each event will
          record an import command without submitting to Wallet.
        </div>
      )}

      {mapModal && batch.account && (
        <div className="modal-overlay" onClick={() => setMapModal(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>Map Wallet Account</h3>
            <div className="form-group">
              <label>Wallet Account Reference</label>
              <input
                autoFocus
                value={walletRef}
                onChange={(e) => setWalletRef(e.target.value)}
                placeholder="e.g. wallet-card-1"
              />
            </div>
            <div className="modal-actions">
              <button
                className="btn-small"
                onClick={() => setMapModal(false)}
              >
                Cancel
              </button>
              <button
                className="btn-primary btn-small"
                disabled={!walletRef.trim()}
                onClick={handleMapAccount}
              >
                Save
              </button>
            </div>
          </div>
        </div>
      )}

      {resolveModal && (
        <div
          className="modal-overlay"
          onClick={() => { setResolveModal(null); setResolveObservationId(""); }}
        >
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>
              Resolve Line #{resolveModal.lineIndex}
            </h3>
            <div
              style={{
                fontSize: "0.8125rem",
                color: "var(--text-muted)",
                marginBottom: "0.75rem",
              }}
            >
              {resolveModal.merchant || resolveModal.externalRef || "No description"} —{" "}
              {formatMinor(resolveModal.amount, resolveModal.currency)}{" "}
              {resolveModal.currency} ({upDirection(resolveModal.direction)})
            </div>
            <div className="form-group">
              <label>Outcome</label>
              <select
                value={resolveOutcome}
                onChange={(e) => {
                  setResolveOutcome(e.target.value);
                  if (e.target.value !== "matched") {
                    setResolveObservationId("");
                  }
                }}
              >
                <option value="new">New (no match)</option>
                <option value="ignored">Ignored</option>
                <option value="matched">Matched</option>
                <option value="ambiguous">Ambiguous</option>
              </select>
            </div>
            {resolveOutcome === "matched" && (
              <div className="form-group">
                <label>Observation (required)</label>
                {resolveModal.eligibleObservations.length === 0 ? (
                  <div style={{ fontSize: "0.75rem", color: "var(--text-muted)", marginTop: "0.25rem" }}>
                    No eligible observations available.
                  </div>
                ) : (
                  <select
                    value={resolveObservationId}
                    onChange={(e) => setResolveObservationId(e.target.value)}
                  >
                    <option value="">-- Select observation --</option>
                    {resolveModal.eligibleObservations.map((obs) => (
                      <option key={obs.observation_id} value={obs.observation_id}>
                        {obs.source_merchant || obs.source_reference || obs.observation_id.slice(0, 8)} —{" "}
                        {obs.amount_minor / 100} {obs.currency} ({obs.direction})
                      </option>
                    ))}
                  </select>
                )}
              </div>
            )}
            <div className="form-group">
              <label>Note</label>
              <textarea
                value={resolveNote}
                onChange={(e) => setResolveNote(e.target.value)}
                placeholder="Optional resolution note"
              />
            </div>
            <div className="modal-actions">
              <button
                className="btn-small"
                onClick={() => { setResolveModal(null); setResolveObservationId(""); }}
              >
                Cancel
              </button>
              <button
                className="btn-primary btn-small"
                disabled={
                  resolveOutcome === "matched" && !resolveObservationId.trim()
                }
                onClick={handleResolve}
              >
                Resolve
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function LineItem({
  line,
  isApproved,
  onResolve,
  onDryRun,
  dryRunResult,
}: {
  line: StatementLineView;
  isApproved: boolean;
  onResolve: (line: StatementLineView) => void;
  onDryRun: (event: FinancialEventView) => void;
  dryRunResult: DryRunResult | undefined;
}) {
  const link = line.reconciliation;
  const obs = line.observation;
  const isResolved = link && link.outcome !== "ambiguous";
  const isAmbiguous = link?.outcome === "ambiguous";

  const formatMinor = (minor: number, currency: string) => {
    const major = minor / 100;
    return major.toLocaleString("en-US", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
  };

  const upDirection = (d: string) =>
    d.charAt(0).toUpperCase() + d.slice(1);

  return (
    <div className="line-item">
      <div className="line-header">
        <div>
          <span style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>
            #{line.line_index}
          </span>{" "}
          <span style={{ fontSize: "0.8125rem" }}>
            {line.merchant || line.external_reference || line.description || "—"}
          </span>
        </div>
        <div className={`line-amount ${line.direction === "credit" ? "credit" : "debit"}`}>
          {line.direction === "credit" ? "+" : "−"}
          {formatMinor(line.amount_minor, line.currency)} {line.currency}
        </div>
      </div>
      <div className="line-detail">
        {upDirection(line.direction)} · {line.event_status}
        {line.transaction_date && ` · ${line.transaction_date}`}
        {line.posting_date && ` · posted ${line.posting_date}`}
      </div>
      <div className="reconciliation-status">
        {!link && (
          <span style={{ color: "var(--text-muted)" }}>
            ⏳ pending
          </span>
        )}
        {isAmbiguous && (
          <span className="badge badge-ambiguous">ambiguous</span>
        )}
        {isResolved && (
          <span style={{ color: "var(--success)", fontSize: "0.75rem" }}>
            resolved ({link.method})
            {obs &&
              ` → ${obs.source_merchant || obs.source_reference || "unknown"}`}
          </span>
        )}
      </div>
      {!isApproved && (!link || isAmbiguous) && (
        <div style={{ marginTop: "0.5rem" }}>
          <button
            className="btn-primary btn-small"
            onClick={() => onResolve(line)}
          >
            Resolve
          </button>
        </div>
      )}
      {isApproved && (
        <div style={{ marginTop: "0.5rem" }}>
          <button
            className="btn-primary btn-small"
            disabled={!line.event_id || !!dryRunResult}
            onClick={() => {
              if (!line.event_id) return;
              onDryRun({
                event_id: line.event_id,
                direction: line.direction,
                amount_minor: line.amount_minor,
                currency: line.currency,
                merchant: line.merchant,
                reference: line.external_reference,
                transaction_date: line.transaction_date,
                posting_date: line.posting_date,
                event_status: line.event_status,
              });
            }}
          >
            {dryRunResult ? "Dry-run noted" : "Dry-run intent"}
          </button>
          {dryRunResult && (
            <span
              style={{
                fontSize: "0.6875rem",
                color: "var(--text-muted)",
                marginLeft: "0.5rem",
              }}
            >
              cmd: {dryRunResult.command_id.slice(0, 8)}...
            </span>
          )}
        </div>
      )}
      {link?.note && (
        <div style={{ fontSize: "0.75rem", color: "var(--text-muted)", marginTop: "0.25rem" }}>
          Note: {link.note}
        </div>
      )}
    </div>
  );
}
