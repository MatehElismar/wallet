/**
 * Authority and reconciliation-state chips.
 *
 * `docs/ux-assessment.md` requires one shared component and one vocabulary for
 * advisory / reconciliation / canonical-proposal / canonical state across every
 * screen, so that authority is visible rather than implied by colour.
 */

import type { ReactNode } from "react";

import {
  AUTHORITY_LADDER,
  WALLET_MATCHING_CAVEAT,
  describeAuthority,
  reconciliationCase,
} from "@/ui/authority";
import type { AuthorityTier } from "@/ui/authority";
import { Alert, Badge } from "./ui";

/**
 * The authority of an object, with its gate in the tooltip.
 *
 * The chip always carries the tier name as text. Colour alone never encodes
 * authority, because colour is exactly what an operator misreads under time
 * pressure.
 */
export function AuthorityChip({
  tier,
  compact = false,
}: {
  tier: AuthorityTier | string | null | undefined;
  compact?: boolean;
}) {
  const authority = describeAuthority(tier);
  return (
    <Badge
      tone={authority.tone}
      title={`${authority.operatorMeaning}. ${authority.nextStep}`}
    >
      {compact ? authority.label : `${authority.label} · ${authority.permittedAction}`}
    </Badge>
  );
}

/** The reconciliation outcome of a statement line, in operator language. */
export function ReconciliationChip({
  outcome,
}: {
  outcome: string | null | undefined;
}) {
  const found = reconciliationCase(outcome);
  return (
    <Badge tone={found.tone} title={found.description}>
      {found.label}
    </Badge>
  );
}

/**
 * The standing banner for any notification-derived or model-derived surface.
 *
 * It states the ceiling (`never` a Wallet write) rather than a soft caveat,
 * and it never offers an import or approve affordance.
 */
export function AdvisoryBanner({ children }: { children?: ReactNode }) {
  const advisory = describeAuthority("advisory");
  return (
    <Alert tone="advisory" title="Advisory evidence — not a ledger record">
      <p>
        {advisory.operatorMeaning}. Permitted here: {advisory.permittedAction.toLowerCase()}.
      </p>
      <p>{advisory.nextStep} It can never create or update a Wallet record.</p>
      {children}
    </Alert>
  );
}

/** The caveat every coverage number on this console depends on. */
export function WalletMatchingCaveat() {
  return (
    <Alert tone="warn" title="Wallet-history matching is not implemented">
      {WALLET_MATCHING_CAVEAT}
    </Alert>
  );
}

/** The full ladder, rendered as a reference table on the Evidence screen. */
export function AuthorityLadder() {
  return (
    <div className="scroll-region" role="region" aria-label="Authority ladder" tabIndex={0}>
      <table className="data-table">
        <caption className="sr-only">
          Evidence tiers from least to most authority, with the action each
          permits and the gate before a Wallet write.
        </caption>
        <thead>
          <tr>
            <th scope="col">Tier</th>
            <th scope="col">Objects</th>
            <th scope="col">Operator meaning</th>
            <th scope="col">Permitted action</th>
            <th scope="col">Wallet write</th>
          </tr>
        </thead>
        <tbody>
          {AUTHORITY_LADDER.map((tier) => (
            <tr key={tier.tier}>
              <th scope="row">
                <Badge tone={tier.tone}>{tier.label}</Badge>
              </th>
              <td>{tier.objects}</td>
              <td>{tier.operatorMeaning}</td>
              <td>{tier.permittedAction}</td>
              <td>
                {tier.walletWrite === "never"
                  ? "Never"
                  : tier.walletWrite === "controlled-import-only"
                    ? "Controlled import command only"
                    : "Only after approval and the controlled import command"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
