import test from "node:test";
import assert from "node:assert/strict";

import type { ReconciliationRunSummary } from "../src/lib/api.ts";
import { toHistoricalRunRows } from "../src/ui/historical-runs.ts";

function run(over: Partial<ReconciliationRunSummary> = {}): ReconciliationRunSummary {
  return {
    run_id: "run-1",
    period_start: "2026-01-01",
    period_end: "2026-01-31",
    state: "materialized",
    evidence_scope: "statement_evidence_only",
    statement_account_count: 2,
    included_statement_line_count: 18,
    undated_excluded_line_count: 1,
    created_at: "2026-02-01T12:00:00Z",
    ...over,
  };
}

test("historical run rows keep the API's statement-evidence-only scope visible", () => {
  const [row] = toHistoricalRunRows([run()]);

  assert.equal(row.runId, "run-1");
  assert.equal(row.periodLabel, "Jan 1 – Jan 31, 2026");
  assert.equal(row.evidenceScopeLabel, "Statement evidence only");
  assert.equal(row.accounts, 2);
  assert.equal(row.includedLines, 18);
  assert.equal(row.undatedExcludedLines, 1);
});

test("historical runs sort newest materialization first", () => {
  const rows = toHistoricalRunRows([
    run({ run_id: "older", created_at: "2026-01-05T12:00:00Z" }),
    run({ run_id: "newer", created_at: "2026-02-05T12:00:00Z" }),
  ]);

  assert.deepEqual(rows.map((row) => row.runId), ["newer", "older"]);
});
