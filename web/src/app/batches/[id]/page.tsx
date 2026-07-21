"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import {
  getBatchDetail,
  resolveLine,
  mapAccount,
  approveBatch,
  dryRunImport,
  getEventEnrichment,
  generateEventDecision,
  overrideEventDecision,
  finalizeEventDecision,
  getDryRunPreview,
  listCandidateResearchByAccount,
} from "@/lib/api";
import type {
  BatchDetail,
  StatementLineView,
  FinancialEventView,
  ObservationView,
  EventEnrichment,
  CandidateResearch,
  DryRunRecordPreview,
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

  const [enrichmentByEvent, setEnrichmentByEvent] = useState<
    Record<string, EventEnrichment | null>
  >({});
  const [candidateResearch, setCandidateResearch] = useState<CandidateResearch[]>(
    []
  );
  const [enrichActionError, setEnrichActionError] = useState<string | null>(null);

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

  useEffect(() => {
    if (!batch) return;
    const eventIds = batch.lines
      .map((l) => l.event_id)
      .filter((id): id is string => Boolean(id));
    if (eventIds.length === 0 && !batch.account) return;
    Promise.all(
      eventIds.map((id) =>
        getEventEnrichment(id)
          .then((e) => [id, e] as const)
          .catch(() => [id, null] as const)
      )
    )
      .then((pairs) => {
        const next: Record<string, EventEnrichment | null> = {};
        for (const [id, e] of pairs) next[id] = e;
        setEnrichmentByEvent(next);
      })
      .catch(() => {});
    if (batch.account) {
      listCandidateResearchByAccount(batch.account.account_id)
        .then(setCandidateResearch)
        .catch(() => {});
    }
  }, [batch]);

  const refreshEnrichment = (eventId: string) => {
    getEventEnrichment(eventId)
      .then((e) =>
        setEnrichmentByEvent((prev) => ({ ...prev, [eventId]: e }))
      )
      .catch(() =>
        setEnrichmentByEvent((prev) => ({ ...prev, [eventId]: null }))
      );
  };

  const handleGenerate = async (eventId: string) => {
    setEnrichActionError(null);
    try {
      await generateEventDecision(eventId);
      refreshEnrichment(eventId);
    } catch (err: unknown) {
      setEnrichActionError(err instanceof Error ? err.message : "Generate failed");
    }
  };

  const handleOverride = async (
    eventId: string,
    body: { account_id: string; category_id: string | null; label_ids: string[]; payment_type: string | null }
  ) => {
    setEnrichActionError(null);
    try {
      await overrideEventDecision(eventId, body);
      refreshEnrichment(eventId);
    } catch (err: unknown) {
      setEnrichActionError(err instanceof Error ? err.message : "Override failed");
    }
  };

  const handleFinalize = async (eventId: string) => {
    setEnrichActionError(null);
    try {
      await finalizeEventDecision(eventId);
      refreshEnrichment(eventId);
    } catch (err: unknown) {
      setEnrichActionError(err instanceof Error ? err.message : "Finalize failed");
    }
  };

  const handleDryRunPreview = async (
    eventId: string
  ): Promise<DryRunRecordPreview | null> => {
    setEnrichActionError(null);
    try {
      return await getDryRunPreview(eventId);
    } catch (err: unknown) {
      setEnrichActionError(
        err instanceof Error ? err.message : "Dry-run preview failed"
      );
      return null;
    }
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

      {enrichActionError && (
        <div className="alert alert-error">{enrichActionError}</div>
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
          enrichment={
            line.event_id ? enrichmentByEvent[line.event_id] : undefined
          }
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
          onGenerate={handleGenerate}
          onOverride={handleOverride}
          onFinalize={handleFinalize}
          onDryRunPreview={handleDryRunPreview}
        />
      ))}

      {!isApproved && ambiguousCount > 0 && (
        <div className="alert alert-warn" style={{ marginTop: "1rem" }}>
          {ambiguousCount} ambiguous {ambiguousCount === 1 ? "line" : "lines"}{" "}
          must be resolved before approval.
        </div>
      )}

      {candidateResearch.length > 0 && (
        <div style={{ marginTop: "1.5rem" }}>
          <h3 style={{ fontSize: "0.9375rem", fontWeight: 600, margin: "0 0 0.5rem" }}>
            Notification Candidate Research
            <span style={{ fontWeight: 400, color: "var(--text-muted)", fontSize: "0.75rem", marginLeft: "0.5rem" }}>
              advisory only · never finalizable
            </span>
          </h3>
          {candidateResearch.map((c) => (
            <CandidateResearchCard key={c.candidate_id} research={c} />
          ))}
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
  enrichment,
  onResolve,
  onDryRun,
  dryRunResult,
  onGenerate,
  onOverride,
  onFinalize,
  onDryRunPreview,
}: {
  line: StatementLineView;
  isApproved: boolean;
  enrichment?: EventEnrichment | null;
  onResolve: (line: StatementLineView) => void;
  onDryRun: (event: FinancialEventView) => void;
  dryRunResult: DryRunResult | undefined;
  onGenerate: (eventId: string) => void;
  onOverride: (
    eventId: string,
    body: {
      account_id: string;
      category_id: string | null;
      label_ids: string[];
      payment_type: string | null;
    }
  ) => void;
  onFinalize: (eventId: string) => void;
  onDryRunPreview: (
    eventId: string
  ) => Promise<DryRunRecordPreview | null>;
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
      {isApproved && line.event_id && (
        <EnrichmentCard
          eventId={line.event_id}
          enrichment={enrichment}
          onGenerate={onGenerate}
          onOverride={onOverride}
          onFinalize={onFinalize}
          onDryRunPreview={onDryRunPreview}
        />
      )}
      {link?.note && (
        <div style={{ fontSize: "0.75rem", color: "var(--text-muted)", marginTop: "0.25rem" }}>
          Note: {link.note}
        </div>
      )}
    </div>
  );
}

const GRADE_LABEL: Record<string, string> = {
  exact_recurrence: "Exact recurrence",
  merchant_history: "Merchant history",
  context_only: "Context only",
  no_recommendation: "No recommendation",
  operator_override: "Operator override",
};

function OverrideForm({
  onOverride,
  eventId,
}: {
  eventId: string;
  onOverride: (
    eventId: string,
    body: {
      account_id: string;
      category_id: string | null;
      label_ids: string[];
      payment_type: string | null;
    }
  ) => void;
}) {
  const [accountId, setAccountId] = useState("");
  const [categoryId, setCategoryId] = useState("");
  const [labels, setLabels] = useState("");
  const [paymentType, setPaymentType] = useState("");

  const submit = () => {
    if (!accountId.trim()) return;
    onOverride(eventId, {
      account_id: accountId.trim(),
      category_id: categoryId.trim() || null,
      label_ids: labels
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean),
      payment_type: paymentType.trim() || null,
    });
  };

  return (
    <div
      style={{
        marginTop: "0.5rem",
        display: "flex",
        flexDirection: "column",
        gap: "0.4rem",
      }}
    >
      <div className="form-group" style={{ margin: 0 }}>
        <label>Wallet account ID *</label>
        <input value={accountId} onChange={(e) => setAccountId(e.target.value)} />
      </div>
      <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
        <div className="form-group" style={{ margin: 0, flex: 1 }}>
          <label>Category ID</label>
          <input value={categoryId} onChange={(e) => setCategoryId(e.target.value)} />
        </div>
        <div className="form-group" style={{ margin: 0, flex: 1 }}>
          <label>Payment type</label>
          <input
            value={paymentType}
            onChange={(e) => setPaymentType(e.target.value)}
            placeholder="e.g. debit_card"
          />
        </div>
      </div>
      <div className="form-group" style={{ margin: 0 }}>
        <label>Label IDs (comma-separated)</label>
        <input value={labels} onChange={(e) => setLabels(e.target.value)} />
      </div>
      <button
        className="btn-primary btn-small"
        disabled={!accountId.trim()}
        onClick={submit}
      >
        Save override (new version)
      </button>
    </div>
  );
}

function EnrichmentCard({
  eventId,
  enrichment,
  onGenerate,
  onOverride,
  onFinalize,
  onDryRunPreview,
}: {
  eventId: string;
  enrichment?: EventEnrichment | null;
  onGenerate: (eventId: string) => void;
  onOverride: (
    eventId: string,
    body: {
      account_id: string;
      category_id: string | null;
      label_ids: string[];
      payment_type: string | null;
    }
  ) => void;
  onFinalize: (eventId: string) => void;
  onDryRunPreview: (
    eventId: string
  ) => Promise<DryRunRecordPreview | null>;
}) {
  const [showOverride, setShowOverride] = useState(false);
  const [showEvidence, setShowEvidence] = useState(false);
  const [preview, setPreview] = useState<DryRunRecordPreview | null>(null);

  const grade = enrichment?.evidence_grade;
  const gradeText = grade ? (GRADE_LABEL[grade] ?? grade) : "Not generated";

  const handlePreview = async () => {
    const result = await onDryRunPreview(eventId);
    if (result) setPreview(result);
  };

  return (
    <div
      className="card"
      style={{ marginTop: "0.75rem", padding: "0.75rem" }}
    >
      <div className="card-header" style={{ marginBottom: "0.5rem" }}>
        <div>
          <div className="card-title" style={{ fontSize: "0.8125rem" }}>
            Wallet Enrichment
          </div>
          <div className="card-subtitle" style={{ fontSize: "0.75rem" }}>
            Evidence grade: <strong>{gradeText}</strong>
            {enrichment && ` · v${enrichment.version}`}
            {enrichment?.finalized && (
              <span className="badge badge-approved" style={{ marginLeft: "0.5rem" }}>
                finalized
              </span>
            )}
          </div>
        </div>
      </div>

      {!enrichment && (
        <button
          className="btn-primary btn-small"
          onClick={() => onGenerate(eventId)}
        >
          Generate proposal
        </button>
      )}

      {enrichment && (
        <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
          <div style={{ fontSize: "0.75rem" }}>
            <div>
              Account:{" "}
              <code>{enrichment.selected_account_id ?? "—"}</code>
            </div>
            <div>
              Category:{" "}
              <code>{enrichment.selected_category_id ?? "—"}</code>
            </div>
            <div>
              Labels:{" "}
              <code>
                {enrichment.selected_label_ids.length
                  ? enrichment.selected_label_ids.join(", ")
                  : "—"}
              </code>
            </div>
            <div>
              Payment:{" "}
              <code>{enrichment.selected_payment_type ?? "—"}</code>
            </div>
            {enrichment.rationale && (
              <div style={{ color: "var(--text-muted)", marginTop: "0.25rem" }}>
                {enrichment.rationale}
              </div>
            )}
          </div>

          <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
            <button
              className="btn-primary btn-small"
              disabled={!enrichment.can_finalize}
              onClick={() => onFinalize(eventId)}
              title={
                enrichment.can_finalize
                  ? "Finalize this decision"
                  : "Only a recommendation/override can be finalized"
              }
            >
              {enrichment.finalized ? "Finalized" : "Finalize"}
            </button>
            <button
              className="btn-small"
              onClick={() => setShowOverride((v) => !v)}
            >
              Override
            </button>
            <button
              className="btn-small"
              onClick={() => setShowEvidence((v) => !v)}
            >
              {showEvidence ? "Hide evidence" : "Evidence"}
            </button>
            <button
              className="btn-small"
              disabled={!enrichment.finalized}
              onClick={handlePreview}
              title={
                enrichment.finalized
                  ? "Preview exact Wallet REST payload"
                  : "Finalize first to preview the payload"
              }
            >
              Dry-run preview
            </button>
          </div>

          {showOverride && (
            <OverrideForm onOverride={onOverride} eventId={eventId} />
          )}

          {showEvidence && (
            <pre
              style={{
                fontSize: "0.6875rem",
                background: "var(--bg-muted, #1b1b1f)",
                color: "var(--text-muted)",
                padding: "0.5rem",
                borderRadius: "6px",
                overflowX: "auto",
              }}
            >
              {JSON.stringify(
                enrichment.evidence_refs ?? enrichment.query_inputs ?? {},
                null,
                2
              )}
            </pre>
          )}

          {preview && (
            <div>
              <div
                style={{
                  fontSize: "0.6875rem",
                  color: "var(--text-muted)",
                  marginBottom: "0.25rem",
                }}
              >
                Exact Wallet REST record payload (not submitted · submitted=
                {String(preview.submitted)})
              </div>
              <pre
                style={{
                  fontSize: "0.6875rem",
                  background: "var(--bg-muted, #1b1b1f)",
                  color: "var(--text)",
                  padding: "0.5rem",
                  borderRadius: "6px",
                  overflowX: "auto",
                }}
              >
                {JSON.stringify(preview.payload, null, 2)}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function CandidateResearchCard({ research }: { research: CandidateResearch }) {
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
