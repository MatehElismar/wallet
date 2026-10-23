/**
 * The shared authority vocabulary for every reconciliation surface.
 *
 * `docs/product-vision.md` fixes one non-negotiable invariant:
 *
 * ```text
 * notification or LLM output -> advisory evidence only
 * posted statement line + human approval -> canonical financial event
 * approved canonical event + controlled import gate -> Wallet write
 * ```
 *
 * Nothing in the UI may imply a shortcut through that chain, so the labels,
 * permitted actions and gates live here once and are rendered everywhere.
 */

export type AuthorityTier =
  | "advisory"
  | "reconciliation"
  | "canonical_proposal"
  | "canonical";

/** Least authority first. Rendering order and escalation order are the same. */
export const AUTHORITY_TIERS: readonly AuthorityTier[] = Object.freeze([
  "advisory",
  "reconciliation",
  "canonical_proposal",
  "canonical",
]);

/** What still has to happen before this tier could reach a Wallet record. */
export type WalletWriteGate =
  | "never"
  | "after-approval-and-controlled-import"
  | "controlled-import-only";

export interface AuthorityDescriptor {
  tier: AuthorityTier;
  label: string;
  /** The concrete objects that carry this authority. */
  objects: string;
  /** What the operator should take the item to mean. */
  operatorMeaning: string;
  /** The only actions this tier offers. Advisory never offers import/approve. */
  permittedAction: string;
  walletWrite: WalletWriteGate;
  /**
   * Always `false`. No tier writes to Wallet by itself: even an approved
   * canonical event needs the separate controlled import command.
   */
  canWriteWallet: false;
  /** Whether evidence at this tier can still lead to a canonical event. */
  canBecomeCanonical: boolean;
  /** The next gate, phrased for an operator reading the chip. */
  nextStep: string;
  /** CSS modifier used by the shared chip component. */
  tone: "advisory" | "reconciliation" | "proposal" | "canonical";
}

const DESCRIPTORS: Record<AuthorityTier, AuthorityDescriptor> = {
  advisory: {
    tier: "advisory",
    label: "Advisory",
    objects: "Email observations, notifications, LLM/MCP research",
    operatorMeaning: "Useful context; not proof of a ledger event",
    permittedAction: "Inspect, link as evidence, enrich matching context",
    walletWrite: "never",
    canWriteWallet: false,
    canBecomeCanonical: false,
    nextStep:
      "Needs a posted statement line before it can carry any ledger authority.",
    tone: "advisory",
  },
  reconciliation: {
    tier: "reconciliation",
    label: "Reconciliation",
    objects: "Statement lines, observations, match proposals",
    operatorMeaning: "The system is comparing two histories",
    permittedAction: "Resolve or mark ambiguous",
    walletWrite: "after-approval-and-controlled-import",
    canWriteWallet: false,
    canBecomeCanonical: true,
    nextStep:
      "Every line in the statement needs an outcome before the batch can be approved.",
    tone: "reconciliation",
  },
  canonical_proposal: {
    tier: "canonical_proposal",
    label: "Canonical proposal",
    objects: "Statement-backed lines queued for an approval decision",
    operatorMeaning: "Eligible for an attributable decision",
    permittedAction: "Approve or reject",
    walletWrite: "after-approval-and-controlled-import",
    canWriteWallet: false,
    canBecomeCanonical: true,
    nextStep: "Needs an attributable human approval of the statement batch.",
    tone: "proposal",
  },
  canonical: {
    tier: "canonical",
    label: "Canonical",
    objects: "Approved financial events",
    operatorMeaning: "Immutable accounting decision",
    permittedAction: "Controlled import only",
    walletWrite: "controlled-import-only",
    canWriteWallet: false,
    // It already is a canonical event; the remaining gate is the import.
    canBecomeCanonical: false,
    nextStep:
      "A Wallet record still requires the separate controlled import command on a mapped account.",
    tone: "canonical",
  },
};

/**
 * Own-property lookup.
 *
 * A plain `table[token]` would resolve inherited keys, so a backend token of
 * `toString` or `constructor` would hand back a function instead of falling
 * through to the safe default.
 */
function lookup<T>(table: Record<string, T>, token: unknown): T | undefined {
  if (typeof token !== "string") return undefined;
  return Object.prototype.hasOwnProperty.call(table, token)
    ? table[token]
    : undefined;
}

/**
 * Describe a tier, defaulting to the least authority.
 *
 * An unrecognised token must never be rendered as more trustworthy than the
 * weakest evidence class, so the fallback is `advisory` rather than an error.
 */
export function describeAuthority(
  tier: string | null | undefined,
): AuthorityDescriptor {
  return lookup(DESCRIPTORS, tier) ?? DESCRIPTORS.advisory;
}

export const AUTHORITY_LADDER: readonly AuthorityDescriptor[] = Object.freeze(
  AUTHORITY_TIERS.map((tier) => DESCRIPTORS[tier]),
);

/**
 * What the backend can actually conclude today.
 *
 * `WalletWorkflow._propose_reconciliation` compares a statement line with
 * *notification observations* scoped to the same financial account. It never
 * reads Wallet history, so "missing in Wallet" is not a conclusion this system
 * can currently reach, and no screen may claim it.
 */
export const WALLET_MATCHING_CAVEAT =
  "Statement lines are compared with notification observations only. " +
  "Matching against existing Wallet history is not implemented, so no screen " +
  "here can report whether a line is already present in Wallet.";

export type ReconciliationCaseKey =
  | "ambiguous"
  | "unreconciled"
  | "no_prior_observation"
  | "matched_observation"
  | "excluded";

/** Queue order: whatever needs an operator first is listed first. */
export const RECONCILIATION_CASE_ORDER: readonly ReconciliationCaseKey[] =
  Object.freeze([
    "ambiguous",
    "unreconciled",
    "no_prior_observation",
    "matched_observation",
    "excluded",
  ]);

export interface ReconciliationCase {
  key: ReconciliationCaseKey;
  /** The backend `ReconciliationOutcome` token, or `null` when unresolved. */
  outcome: string | null;
  label: string;
  description: string;
  /** The operator still has to act on this line. */
  needsResolution: boolean;
  /** The pilot records this as a finding; it has no correction path yet. */
  isReviewFinding: boolean;
  /** Approving the batch turns this line into a canonical financial event. */
  becomesCanonicalEvent: boolean;
  tone: "warn" | "neutral" | "proposal" | "settled" | "muted";
}

const CASES: Record<ReconciliationCaseKey, ReconciliationCase> = {
  ambiguous: {
    key: "ambiguous",
    outcome: "ambiguous",
    label: "Ambiguous",
    description:
      "Several observations could represent this line. The whole statement " +
      "stays unapprovable until an operator records a different outcome.",
    needsResolution: true,
    isReviewFinding: true,
    becomesCanonicalEvent: false,
    tone: "warn",
  },
  unreconciled: {
    key: "unreconciled",
    outcome: null,
    label: "Unreconciled",
    description:
      "No reconciliation outcome has been recorded for this line yet.",
    needsResolution: true,
    isReviewFinding: false,
    becomesCanonicalEvent: false,
    tone: "neutral",
  },
  no_prior_observation: {
    key: "no_prior_observation",
    outcome: "new",
    label: "No prior observation",
    description:
      "No notification observation matched this line. Approving the batch " +
      "still turns the posted statement line into a canonical event.",
    needsResolution: false,
    isReviewFinding: false,
    becomesCanonicalEvent: true,
    tone: "proposal",
  },
  matched_observation: {
    key: "matched_observation",
    outcome: "matched",
    label: "Matched observation",
    description:
      "A notification observation on the same account, amount, currency and " +
      "direction is linked to this line as supporting evidence.",
    needsResolution: false,
    isReviewFinding: false,
    becomesCanonicalEvent: true,
    tone: "settled",
  },
  excluded: {
    key: "excluded",
    outcome: "ignored",
    label: "Excluded",
    description:
      "An operator excluded this line from the approval. It produces no " +
      "canonical event.",
    needsResolution: false,
    isReviewFinding: false,
    becomesCanonicalEvent: false,
    tone: "muted",
  },
};

const CASE_BY_OUTCOME: Record<string, ReconciliationCaseKey> = {
  matched: "matched_observation",
  new: "no_prior_observation",
  ambiguous: "ambiguous",
  ignored: "excluded",
};

/**
 * Map a backend reconciliation outcome onto the operator-facing case.
 *
 * An absent or unrecognised outcome reads as `unreconciled` — the state that
 * still demands an operator — rather than being silently treated as settled.
 */
export function reconciliationCase(
  outcome: string | null | undefined,
): ReconciliationCase {
  const key = lookup(CASE_BY_OUTCOME, outcome);
  return key ? CASES[key] : CASES.unreconciled;
}

/** The cases in queue order, for legends and filter controls. */
export const RECONCILIATION_CASES: readonly ReconciliationCase[] = Object.freeze(
  RECONCILIATION_CASE_ORDER.map((key) => CASES[key]),
);

const EVIDENCE_GRADE_LABELS: Record<string, string> = {
  exact_recurrence: "Exact recurrence",
  merchant_history: "Merchant history",
  context_only: "Context only",
  no_recommendation: "No recommendation",
  operator_override: "Operator override",
};

/**
 * Label an MCP evidence grade.
 *
 * An absent grade means no advisory decision has been generated at all, which
 * is different from a grade the UI has not seen before.
 */
export function evidenceGradeLabel(grade: string | null | undefined): string {
  if (typeof grade !== "string" || grade.trim() === "") return "Not generated";
  const known = lookup(EVIDENCE_GRADE_LABELS, grade);
  if (known) return known;
  const words = grade.trim().replace(/[_-]+/g, " ").toLowerCase();
  return words.charAt(0).toUpperCase() + words.slice(1);
}
