import Link from "next/link";

import { AuthorityChip, WalletMatchingCaveat } from "@/components/authority";
import { Card, CardHeader, NotAvailableYet, PageHeader, Section } from "@/components/ui";

export default function ReviewPage() {
  return (
    <>
      <PageHeader title="Review" lede="Resolve the evidence that requires an operator decision. The pilot will organize this by reconciliation outcome, not by notification arrival." />
      <WalletMatchingCaveat />
      <Section title="What this queue will contain" note="The current backend has statement workspaces, but not a cross-account historical review queue.">
        <div className="card-grid">
          <Card tone="proposal"><CardHeader title="Missing in Wallet" subtitle="Statement-backed canonical proposals only" aside={<AuthorityChip tier="canonical_proposal" compact />} /><p className="card-copy">This will be the only queue whose approved items can create canonical financial events. It requires future Wallet-history matching.</p></Card>
          <Card tone="reconciliation"><CardHeader title="Duplicates, mismatches, and ambiguity" subtitle="Review findings, not Wallet mutation requests" aside={<AuthorityChip tier="reconciliation" compact />} /><p className="card-copy">The pilot records and explains these cases. Correction or deletion workflows are intentionally out of scope.</p></Card>
        </div>
      </Section>
      <NotAvailableYet title="Cross-account review queue is not implemented" intro="Use an open statement workspace today to resolve line-level reconciliation." items={[{ label: "Historical Wallet comparison", reason: "The backend does not yet read Wallet history as a baseline." }, { label: "Date-range run outcomes", reason: "There is no durable reconciliation-run endpoint yet." }, { label: "Canonical proposal decisions", reason: "Current approval remains all-at-once per statement batch." }]} />
      <p className="page-footer-link"><Link href="/">View available statement workspaces</Link></p>
    </>
  );
}
