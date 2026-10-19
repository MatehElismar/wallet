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
import { listBatches, type BatchSummary } from "@/lib/api";
import { formatCount } from "@/ui/format";
import { summarizeBatches, toRunRows } from "@/ui/runs";

export default function RunsPage() {
  const [batches, setBatches] = useState<BatchSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    listBatches()
      .then((data) => setBatches(data.batches))
      .catch((reason: Error) => setError(reason.message || "Unable to load open statement batches."))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { load(); }, [load]);

  const window = summarizeBatches(batches);
  const rows = toRunRows(batches);

  return (
    <>
      <PageHeader
        title="Reconciliation runs"
        lede={
          <>Review the statement windows currently available to the console. A true date-range run across Wallet history is the next pilot capability; this screen does not pretend that it already exists.</>
        }
        actions={<button className="btn btn-primary" type="button" disabled title="Date-range runs need the planned backend support.">New date-range run <span aria-hidden="true">↗</span></button>}
      />

      <Alert tone="info" title="Current data model: open statement batches">
        The backend currently exposes open statement batches, not historical reconciliation runs or a read-only Wallet-history comparison. Coverage below describes statement-line resolution only.
      </Alert>

      {loading ? <LoadingState label="Loading open statement batches…" /> : null}
      {error ? <ErrorState message={error} onRetry={load} retryLabel="Reload batches" /> : null}

      {!loading && !error && batches.length === 0 ? (
        <EmptyState title="No open statement batches">
          <p>When an available statement is ingested, it will appear here as an observed statement window. The planned date-range run will discover accounts automatically; it will not begin with an account picker.</p>
        </EmptyState>
      ) : null}

      {!loading && !error && batches.length > 0 ? (
        <>
          <Section title="Observed statement window" note={`Derived from ${formatCount(window.batchCount, "open batch")}; it is not a complete-period coverage claim.`}>
            <Card tone="reconciliation">
              <CardHeader title={window.rangeLabel} subtitle="Open statement evidence currently available" aside={<AuthorityChip tier="reconciliation" compact />} />
              <StatGrid>
                <Stat label="Accounts observed" value={window.accountCount} hint="Grouped after ingestion" />
                <Stat label="Posted lines" value={window.lineCount} hint={window.currencies.length ? window.currencies.join(" · ") : "Currency unavailable"} />
                <Stat label="Settled lines" value={window.settledCount} hint={`${window.coverageLabel} of observed lines`} tone="settled" />
                <Stat label="Needs resolution" value={window.unreconciledCount + window.ambiguousCount} hint={`${window.ambiguousCount} ambiguous`} tone={window.attentionCount ? "warn" : "settled"} />
              </StatGrid>
            </Card>
          </Section>

          <WalletMatchingCaveat />

          <Section title="Open statement workspaces" note="Each row is a statement workspace, grouped by its discovered account context.">
            <ScrollRegion label="Open statement workspaces">
              <table className="data-table run-table">
                <caption className="sr-only">Open statement review batches</caption>
                <thead><tr><th scope="col">Statement window</th><th scope="col">Account</th><th scope="col">Coverage</th><th scope="col">Attention</th><th scope="col"><span className="sr-only">Open</span></th></tr></thead>
                <tbody>
                  {rows.map((row) => (
                    <tr key={row.batchId}>
                      <th scope="row"><span className="table-primary">{row.periodLabel}</span><span className="table-secondary">Statement date {row.statementDateLabel}</span></th>
                      <td>{row.accountLabel}</td>
                      <td><strong>{row.coverage.coverageLabel}</strong><span className="table-secondary">{row.coverage.settledCount} settled · {row.coverage.lineCount} lines</span></td>
                      <td>{row.needsAttention ? <Badge tone="warn">{row.coverage.ambiguousCount + row.coverage.unreconciledCount} need review</Badge> : <Badge tone="settled">Ready for batch review</Badge>}</td>
                      <td><Link className="btn btn-secondary btn-small" href={`/batches/${row.batchId}`}>Open statement<span className="sr-only"> for {row.accountLabel}</span></Link></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </ScrollRegion>
          </Section>
        </>
      ) : null}
    </>
  );
}
