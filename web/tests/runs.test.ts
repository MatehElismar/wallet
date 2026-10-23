import test from "node:test";
import assert from "node:assert/strict";

import type { BatchSummary } from "../src/lib/api.ts";
import { coverageOf, summarizeBatches, toRunRows } from "../src/ui/runs.ts";

function batch(over: Partial<BatchSummary> = {}): BatchSummary {
  return {
    batch_id: "b1",
    statement_id: "s1",
    account_issuer: "Banco Popular",
    account_reference: "4111111111112727",
    statement_currency: "DOP",
    statement_date: "2025-01-31",
    period_start: "2025-01-01",
    period_end: "2025-01-31",
    line_count: 10,
    line_resolved_count: 8,
    ambiguous_count: 2,
    state: "open",
    created_at: "2025-02-01T10:00:00Z",
    ...over,
  };
}

test("coverage separates settled lines from merely-resolved lines", () => {
  // The API counts an ambiguous line as resolved; an operator cannot.
  const coverage = coverageOf(batch({ line_count: 10, line_resolved_count: 8, ambiguous_count: 2 }));
  assert.equal(coverage.lineCount, 10);
  assert.equal(coverage.resolvedCount, 8);
  assert.equal(coverage.settledCount, 6);
  assert.equal(coverage.ambiguousCount, 2);
  assert.equal(coverage.unreconciledCount, 2);
  assert.equal(coverage.coverageLabel, "60%");
});

test("coverage of an empty statement does not fabricate a percentage", () => {
  const coverage = coverageOf(batch({ line_count: 0, line_resolved_count: 0, ambiguous_count: 0 }));
  assert.equal(coverage.coverageLabel, "—");
  assert.equal(coverage.unreconciledCount, 0);
});

test("a run row carries account, period and attention state", () => {
  const [row] = toRunRows([batch()]);
  assert.equal(row.batchId, "b1");
  assert.equal(row.accountLabel, "Banco Popular · ••••2727");
  assert.equal(row.periodLabel, "Jan 1 – Jan 31, 2025");
  assert.equal(row.statementDateLabel, "Jan 31, 2025");
  assert.equal(row.needsAttention, true);
});

test("a fully settled statement needs no attention", () => {
  const [row] = toRunRows([
    batch({ line_count: 4, line_resolved_count: 4, ambiguous_count: 0 }),
  ]);
  assert.equal(row.needsAttention, false);
  assert.equal(row.coverage.coverageLabel, "100%");
});

test("run rows are newest period first, undated statements last", () => {
  const rows = toRunRows([
    batch({ batch_id: "older", period_end: "2024-11-30" }),
    batch({ batch_id: "undated", period_start: null, period_end: null }),
    batch({ batch_id: "newest", period_end: "2025-03-31" }),
  ]);
  assert.deepEqual(
    rows.map((r) => r.batchId),
    ["newest", "older", "undated"],
  );
});

test("the observed window aggregates every open batch", () => {
  const window = summarizeBatches([
    batch({
      batch_id: "b1",
      period_start: "2025-01-01",
      period_end: "2025-01-31",
      line_count: 10,
      line_resolved_count: 8,
      ambiguous_count: 2,
    }),
    batch({
      batch_id: "b2",
      account_reference: "5522000000001111",
      statement_currency: "USD",
      period_start: "2024-12-01",
      period_end: "2024-12-31",
      line_count: 5,
      line_resolved_count: 5,
      ambiguous_count: 0,
    }),
  ]);
  assert.equal(window.batchCount, 2);
  assert.equal(window.accountCount, 2);
  assert.equal(window.lineCount, 15);
  assert.equal(window.resolvedCount, 13);
  assert.equal(window.settledCount, 11);
  assert.equal(window.ambiguousCount, 2);
  assert.equal(window.unreconciledCount, 2);
  assert.deepEqual(window.currencies, ["DOP", "USD"]);
  assert.equal(window.periodStart, "2024-12-01");
  assert.equal(window.periodEnd, "2025-01-31");
  assert.equal(window.rangeLabel, "Dec 1, 2024 – Jan 31, 2025");
  assert.equal(window.attentionCount, 1);
});

test("the observed window counts one account per discovered identity", () => {
  const window = summarizeBatches([
    batch({ batch_id: "b1", period_end: "2025-01-31" }),
    batch({ batch_id: "b2", period_end: "2025-02-28" }),
  ]);
  assert.equal(window.batchCount, 2);
  assert.equal(window.accountCount, 1);
});

test("an empty window reports zeroes instead of an invented range", () => {
  const window = summarizeBatches([]);
  assert.equal(window.batchCount, 0);
  assert.equal(window.accountCount, 0);
  assert.equal(window.lineCount, 0);
  assert.equal(window.rangeLabel, "—");
  assert.equal(window.periodStart, null);
  assert.equal(window.periodEnd, null);
  assert.deepEqual(window.currencies, []);
});

test("the observed window ignores unknown currencies and periods", () => {
  const window = summarizeBatches([
    batch({ statement_currency: null, period_start: null, period_end: null }),
  ]);
  assert.deepEqual(window.currencies, []);
  assert.equal(window.rangeLabel, "—");
});
