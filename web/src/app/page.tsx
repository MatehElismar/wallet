"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

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
  Stat,
  StatGrid,
} from "@/components/ui";
import { listReconciliationRuns, type ReconciliationRunSummary } from "@/lib/api";
import { formatCount } from "@/ui/format";
import { toHistoricalRunRows } from "@/ui/historical-runs";

export default function RunsPage() {
  const [runs, setRuns] = useState<ReconciliationRunSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    listReconciliationRuns()
      .then((data) => setRuns(data.runs))
      .catch((reason: Error) => setError(reason.message || "Unable to load reconciliation runs."))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { load(); }, [load]);

  const rows = toHistoricalRunRows(runs);

  return (
    <>
      <PageHeader
        title="Reconciliation runs"
        lede="Each materialized run is an immutable, inclusive date-range snapshot across every statement account discovered by the tool."
        actions={<button className="btn btn-primary" type="button" disabled title="Creating a run requires a server-derived authenticated operator identity.">New date-range run <span aria-hidden="true">↗</span></button>}
      />

      <Alert tone="info" title="Current evidence scope: statements only">
        These runs describe eligible posted statement evidence. Wallet-history ingestion and statement-to-Wallet matching are not available yet, so no count below means “missing from Wallet.”
      </Alert>

      {loading ? <LoadingState label="Loading reconciliation runs…" /> : null}
      {error ? <ErrorState message={error} onRetry={load} retryLabel="Reload runs" /> : null}

      {!loading && !error && rows.length === 0 ? (
        <EmptyState title="No materialized date-range runs">
          <p>Runs will discover available statement accounts internally. Creation remains unavailable in this console until the server can derive and audit the operator identity.</p>
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
