import type { ReconciliationRunSummary } from "../lib/api";
import { formatDateRange } from "./format";

export interface HistoricalRunRow {
  runId: string;
  periodLabel: string;
  evidenceScopeLabel: "Statement evidence only";
  accounts: number;
  includedLines: number;
  undatedExcludedLines: number;
  createdAt: string;
}

export function toHistoricalRunRows(
  runs: readonly ReconciliationRunSummary[],
): HistoricalRunRow[] {
  return [...runs]
    .sort((left, right) => right.created_at.localeCompare(left.created_at))
    .map((run) => ({
      runId: run.run_id,
      periodLabel: formatDateRange(run.period_start, run.period_end),
      evidenceScopeLabel: "Statement evidence only",
      accounts: run.statement_account_count,
      includedLines: run.included_statement_line_count,
      undatedExcludedLines: run.undated_excluded_line_count,
      createdAt: run.created_at,
    }));
}
