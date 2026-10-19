import test from "node:test";
import assert from "node:assert/strict";

import {
  AUTHORITY_TIERS,
  RECONCILIATION_CASE_ORDER,
  WALLET_MATCHING_CAVEAT,
  describeAuthority,
  evidenceGradeLabel,
  reconciliationCase,
} from "../src/ui/authority.ts";

test("the authority ladder is ordered from least to most authority", () => {
  assert.deepEqual(AUTHORITY_TIERS, [
    "advisory",
    "reconciliation",
    "canonical_proposal",
    "canonical",
  ]);
});

test("no authority tier can write to Wallet on its own", () => {
  for (const tier of AUTHORITY_TIERS) {
    assert.equal(
      describeAuthority(tier).canWriteWallet,
      false,
      `${tier} must never claim a Wallet write`,
    );
  }
});

test("advisory evidence can never become canonical by itself", () => {
  const advisory = describeAuthority("advisory");
  assert.equal(advisory.canBecomeCanonical, false);
  assert.equal(advisory.walletWrite, "never");
});

test("advisory evidence never offers an import or approve affordance", () => {
  const advisory = describeAuthority("advisory");
  assert.ok(!/import/i.test(advisory.permittedAction));
  assert.ok(!/approve/i.test(advisory.permittedAction));
});

test("statement-backed tiers may lead to a canonical event", () => {
  assert.equal(describeAuthority("reconciliation").canBecomeCanonical, true);
  assert.equal(describeAuthority("canonical_proposal").canBecomeCanonical, true);
});

test("a canonical event still requires the separate controlled import", () => {
  const canonical = describeAuthority("canonical");
  assert.equal(canonical.walletWrite, "controlled-import-only");
  assert.equal(canonical.canWriteWallet, false);
});

test("an unknown tier falls back to the least authority", () => {
  assert.equal(describeAuthority("nonsense").tier, "advisory");
  assert.equal(describeAuthority(null).tier, "advisory");
  assert.equal(describeAuthority(undefined).tier, "advisory");
});

test("reconciliation outcomes map to the implemented observation cases", () => {
  assert.equal(reconciliationCase("matched").key, "matched_observation");
  assert.equal(reconciliationCase("new").key, "no_prior_observation");
  assert.equal(reconciliationCase("ambiguous").key, "ambiguous");
  assert.equal(reconciliationCase("ignored").key, "excluded");
});

test("an absent or unknown outcome reads as unreconciled", () => {
  assert.equal(reconciliationCase(null).key, "unreconciled");
  assert.equal(reconciliationCase(undefined).key, "unreconciled");
  assert.equal(reconciliationCase("something-else").key, "unreconciled");
  assert.equal(reconciliationCase(null).needsResolution, true);
});

test("no case claims a line is missing from Wallet", () => {
  // Wallet-history matching does not exist yet; the backend only compares
  // statement lines with notification observations.
  for (const outcome of ["matched", "new", "ambiguous", "ignored", null]) {
    const found = reconciliationCase(outcome);
    assert.ok(
      !/missing in wallet/i.test(`${found.label} ${found.description}`),
      `"${found.key}" must not claim Wallet absence`,
    );
  }
  assert.match(WALLET_MATCHING_CAVEAT, /not implemented/i);
});

test("only non-ignored resolved lines become canonical events on approval", () => {
  assert.equal(reconciliationCase("matched").becomesCanonicalEvent, true);
  assert.equal(reconciliationCase("new").becomesCanonicalEvent, true);
  assert.equal(reconciliationCase("ignored").becomesCanonicalEvent, false);
  assert.equal(reconciliationCase("ambiguous").becomesCanonicalEvent, false);
  assert.equal(reconciliationCase(null).becomesCanonicalEvent, false);
});

test("ambiguous lines are review findings that block approval", () => {
  const ambiguous = reconciliationCase("ambiguous");
  assert.equal(ambiguous.isReviewFinding, true);
  assert.equal(ambiguous.needsResolution, true);
});

test("review queues are ordered by what needs an operator first", () => {
  assert.deepEqual(RECONCILIATION_CASE_ORDER, [
    "ambiguous",
    "unreconciled",
    "no_prior_observation",
    "matched_observation",
    "excluded",
  ]);
});

test("evidence grades read as operator language", () => {
  assert.equal(evidenceGradeLabel("exact_recurrence"), "Exact recurrence");
  assert.equal(evidenceGradeLabel("no_recommendation"), "No recommendation");
  assert.equal(evidenceGradeLabel("some_new_grade"), "Some new grade");
  assert.equal(evidenceGradeLabel(null), "Not generated");
});
