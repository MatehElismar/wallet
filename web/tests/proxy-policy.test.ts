import test from "node:test";
import assert from "node:assert/strict";

import { isBlockedFinancialMutation } from "../src/lib/proxy-policy.ts";

test("blocks unauthenticated canonicalization and import-command proxy paths", () => {
  assert.equal(isBlockedFinancialMutation("POST", ["commands", "approve-batch", "batch-1"]), true);
  assert.equal(isBlockedFinancialMutation("POST", ["commands", "dry-run-import", "event-1"]), true);
});

test("keeps non-financial reconciliation commands available to the existing shell", () => {
  assert.equal(isBlockedFinancialMutation("POST", ["commands", "resolve-line", "line-1"]), false);
  assert.equal(isBlockedFinancialMutation("POST", ["commands", "map-account", "account-1"]), false);
  assert.equal(isBlockedFinancialMutation("GET", ["commands", "approve-batch", "batch-1"]), false);
});
