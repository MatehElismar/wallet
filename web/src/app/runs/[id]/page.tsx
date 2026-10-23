"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";

import { AuthorityChip, WalletMatchingCaveat } from "@/components/authority";
import {
  Alert,
  Badge,
  Card,
  CardHeader,
  ErrorState,
  LoadingState,
  PageHeader,
  ScrollRegion,
  Section,
  Stat,
  StatGrid,
} from "@/components/ui";
import { getReconciliationRun, type ReconciliationRunDetail } from "@/lib/api";
import { formatCount, formatDateRange } from "@/ui/format";

export default function ReconciliationRunDetailPage() {
  const params = useParams<{ id: string }>();
  const runId = params.id;
  const [run, setRun] = useState<ReconciliationRunDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    if (!runId) return;
    setLoading(true);
    setError(null);
    getReconciliationRun(runId)
      .then(setRun)
      .catch((reason: Error) => setError(reason.message || "Unable to load reconciliation run."))
      .finally(() => setLoading(false));
  }, [runId]);

  useEffect(() => { load(); }, [load]);

  if (loading) return <LoadingState label="Loading reconciliation run…" />;
  if (error || !run) return <ErrorState message={error || "Reconciliation run was not found."} onRetry={load} retryLabel="Reload run" />;

  const reviewEvidence = (coverage: ReconciliationRunDetail["account_coverages"][number]) =>
    coverage.unresolved_line_count + coverage.ambiguous_count + coverage.new_count;

  return (
    <>
      <p><Link href="/">← Reconciliation runs</Link></p>
      <PageHeader
        title={formatDateRange(run.period_start, run.period_end)}
        lede="Immutable snapshot across statement accounts discovered for this inclusive date range."
      />

      <Alert tone="info" title="Statement evidence only">
        This run is not a Wallet-history comparison. “Unmatched notification evidence” below is advisory evidence that did not match a statement line; it is not a missing Wallet entry.
      </Alert>

      <Section title="Run coverage">
        <Card tone="reconciliation">
          <CardHeader title="Materialized evidence snapshot" subtitle="Frozen after creation" aside={<AuthorityChip tier="reconciliation" compact />} />
          <StatGrid>
            <Stat label="Statement accounts" value={run.statement_account_count} hint="Discovered internally" />
            <Stat label="Included posted lines" value={run.included_statement_line_count} hint="Within the selected range" />
            <Stat label="Undated excluded" value={run.undated_excluded_line_count} hint="Not silently assigned to this range" tone={run.undated_excluded_line_count ? "warn" : undefined} />
            <Stat label="Evidence scope" value="Statements" hint="Wallet matching unavailable" />
          </StatGrid>
        </Card>
      </Section>

      <Section title="Discovered account coverage" note={`${formatCount(run.account_coverages.length, "account snapshot")}; rows cannot be changed after materialization.`}>
        <ScrollRegion label="Discovered account coverage">
          <table className="data-table run-table">
            <caption className="sr-only">Account coverage for this reconciliation run</caption>
            <thead><tr><th scope="col">Account</th><th scope="col">Statements</th><th scope="col">Included lines</th><th scope="col">Excluded</th><th scope="col">Review evidence</th></tr></thead>
            <tbody>
              {run.account_coverages.map((coverage) => {
                const reviewCount = reviewEvidence(coverage);
                return (
                  <tr key={coverage.financial_account_id}>
                    <th scope="row"><span className="table-primary">{coverage.issuer}</span><span className="table-secondary">{coverage.external_reference}</span></th>
                    <td>{coverage.statement_count}</td>
                    <td>{coverage.included_line_count}</td>
                    <td>{coverage.undated_excluded_line_count}</td>
                    <td>{reviewCount ? <Badge tone="warn">{reviewCount} need evidence review</Badge> : <Badge tone="settled">No flagged evidence</Badge>}<span className="table-secondary">{coverage.unresolved_line_count} unresolved · {coverage.ambiguous_count} ambiguous · {coverage.new_count} unmatched notifications</span></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </ScrollRegion>
      </Section>

      <WalletMatchingCaveat />
    </>
  );
}
