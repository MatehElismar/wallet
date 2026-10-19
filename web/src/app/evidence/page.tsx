import Link from "next/link";

import { AdvisoryBanner, AuthorityLadder } from "@/components/authority";
import { NotAvailableYet, PageHeader, Section } from "@/components/ui";

export default function EvidencePage() {
  return (
    <>
      <PageHeader title="Evidence" lede="Wallet V2 separates context from authority so a plausible notification never becomes an unreviewed ledger record." />
      <AdvisoryBanner />
      <Section title="Authority ladder" note="Every object has a visible ceiling on what it can do."><AuthorityLadder /></Section>
      <NotAvailableYet title="Evidence dossier is not implemented" intro="Statement-line evidence is available inside current statement workspaces. This future surface will join it with Wallet comparison rationale and source coverage." items={[{ label: "Balance proof", reason: "Opening/closing balance verification is planned but not computed by the current backend." }, { label: "Wallet matching rationale", reason: "Existing Wallet history is not read by the current reconciliation workflow." }, { label: "Source coverage", reason: "Date-range runs and source-exclusion reporting need new backend support." }]} />
      <p className="page-footer-link"><Link href="/candidates">Open legacy notification observations</Link> <span aria-hidden="true">·</span> They remain advisory evidence only.</p>
    </>
  );
}
