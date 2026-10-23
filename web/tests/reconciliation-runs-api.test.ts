import test from "node:test";
import assert from "node:assert/strict";

import { createReconciliationRun } from "../src/lib/api.ts";

test("createReconciliationRun posts an inclusive date range to the run endpoint", async () => {
  const originalFetch = globalThis.fetch;
  let request: { input: RequestInfo | URL; init?: RequestInit } | undefined;
  globalThis.fetch = async (input, init) => {
    request = { input, init };
    return new Response(JSON.stringify({
      run_id: "run-1",
      period_start: "2026-01-01",
      period_end: "2026-01-31",
      state: "materialized",
      evidence_scope: "statement_evidence_only",
      statement_account_count: 0,
      included_statement_line_count: 0,
      undated_excluded_line_count: 0,
      created_at: "2026-02-01T12:00:00Z",
    }), { status: 201, headers: { "Content-Type": "application/json" } });
  };

  try {
    const run = await createReconciliationRun({
      period_start: "2026-01-01",
      period_end: "2026-01-31",
    });

    assert.equal(String(request?.input), "/api/reconciliation-runs");
    assert.equal(request?.init?.method, "POST");
    assert.equal(request?.init?.body, '{"period_start":"2026-01-01","period_end":"2026-01-31"}');
    assert.equal(run.run_id, "run-1");
  } finally {
    globalThis.fetch = originalFetch;
  }
});
