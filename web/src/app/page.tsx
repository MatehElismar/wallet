"use client";

import Link from "next/link";
import { type FormEvent, useCallback, useEffect, useState } from "react";

import { AuthorityChip, WalletMatchingCaveat } from "@/components/authority";
import {
  Alert,
  Badge,
  Card,
  CardHeader,
  EmptyState,
  ErrorState,
  LoadingState,
  PageHeader,
  ScrollRegion,
  Section,
} from "@/components/ui";
import {
  createReconciliationRun,
  listReconciliationRuns,
  type ReconciliationRunSummary,
} from "@/lib/api";
import { formatCount } from "@/ui/format";
import { toHistoricalRunRows } from "@/ui/historical-runs";

export default function RunsPage() {
  const [runs, setRuns] = useState<ReconciliationRunSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [periodStart, setPeriodStart] = useState("");
  const [periodEnd, setPeriodEnd] = useState("");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    listReconciliationRuns()
      .then((data) => setRuns(data.runs))
      .catch((reason: Error) => setError(reason.message || "Unable to load reconciliation runs."))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { load(); }, [load]);

  const createRun = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setCreateError(null);
    if (!periodStart || !periodEnd) {
      setCreateError("Choose both the start and end dates.");
      return;
    }
    if (periodStart > periodEnd) {
      setCreateError("The start date must be on or before the end date.");
      return;
    }

    setCreating(true);
    try {
      const run = await createReconciliationRun({
        period_start: periodStart,
        period_end: periodEnd,
      });
      setRuns((current) => [run, ...current]);
      setPeriodStart("");
      setPeriodEnd("");
    } catch (reason) {
      setCreateError(reason instanceof Error ? reason.message : "Unable to materialize the reconciliation run.");
    } finally {
      setCreating(false);
    }
  };

  const rows = toHistoricalRunRows(runs);

  return (
    <>
      <PageHeader
        title="Reconciliation runs"
        lede="Choose an inclusive date range. The tool discovers all eligible statement accounts internally and freezes an immutable evidence snapshot."
      />

      <Alert tone="info" title="Current evidence scope: statements only">
        Creating a run never creates canonical financial records or contacts Wallet. Wallet-history ingestion and statement-to-Wallet matching are not available yet, so no count below means “missing from Wallet.”
      </Alert>

      <Section title="Materialize a date range" note="No account picker: coverage includes every eligible statement account discovered within the selected range.">
        <Card tone="reconciliation">
          <CardHeader title="Create immutable statement-evidence coverage" subtitle="This is safe to run locally; it does not approve or import financial events." aside={<AuthorityChip tier="reconciliation" compact />} />
          <form onSubmit={createRun}>
            <div className="form-row">
              <div className="form-group">
                <label htmlFor="period-start">Start date</label>
                <input id="period-start" type="date" value={periodStart} onChange={(event) => setPeriodStart(event.target.value)} required disabled={creating} />
              </div>
              <div className="form-group">
                <label htmlFor="period-end">End date</label>
                <input id="period-end" type="date" value={periodEnd} onChange={(event) => setPeriodEnd(event.target.value)} required disabled={creating} />
              </div>
            </div>
            {createError ? <Alert tone="danger" title="Run not created">{createError}</Alert> : null}
            <div className="btn-row">
              <button className="btn btn-primary" type="submit" disabled={creating}>{creating ? "Materializing…" : "Create date-range run"}</button>
            </div>
          </form>
        </Card>
      </Section>

      {loading ? <LoadingState label="Loading reconciliation runs…" /> : null}
      {error ? <ErrorState message={error} onRetry={load} retryLabel="Reload runs" /> : null}

      {!loading && !error && rows.length === 0 ? (
        <EmptyState title="No materialized date-range runs">
          <p>Choose a date range above to record the statement evidence currently available. The resulting snapshot is immutable after creation.</p>
        </EmptyState>
      ) : null}

      {!loading && !error && rows.length > 0 ? (
        <>
          <Section title="Materialized date ranges" note={`${formatCount(rows.length, "immutable snapshot")} of eligible statement evidence.`}>
            <ScrollRegion label="Materialized reconciliation runs">
              <table className="data-table run-table">
                <caption className="sr-only">Materialized reconciliation runs</caption>
                <thead><tr><th scope="col">Date range</th><th scope="col">Accounts</th><th scope="col">Posted evidence</th><th scope="col">Scope</th><th scope="col"><span className="sr-only">Open</span></th></tr></thead>
                <tbody>
                  {rows.map((row) => (
                    <tr key={row.runId}>
                      <th scope="row"><span className="table-primary">{row.periodLabel}</span><span className="table-secondary">Immutable materialized snapshot</span></th>
                      <td>{row.accounts}</td>
                      <td><strong>{row.includedLines}</strong><span className="table-secondary">{row.undatedExcludedLines} undated excluded</span></td>
                      <td><Badge tone="reconciliation">{row.evidenceScopeLabel}</Badge></td>
                      <td><Link className="btn btn-secondary btn-small" href={`/runs/${row.runId}`}>Open run<span className="sr-only"> for {row.periodLabel}</span></Link></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </ScrollRegion>
          </Section>

          <WalletMatchingCaveat />
        </>
      ) : null}
    </>
  );
}
