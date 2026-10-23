import { NotAvailableYet, PageHeader, Section } from "@/components/ui";
import { AuthorityChip } from "@/components/authority";

export default function AccountsPage() {
  return (
    <>
      <PageHeader title="Accounts" lede="Accounts are discovered while processing a period. They are review context, not the starting filter for a historical run." />
      <Section title="Mapping authority" note="A mapping proposal may improve matching; only a reviewed mapping may authorize a future canonical/import path.">
        <div className="card authority-reference"><AuthorityChip tier="reconciliation" /><p className="card-copy">Do not infer an import-authorizing account mapping from a fuzzy match, a notification, or an LLM extraction. This page will make proposed and reviewed mappings visibly distinct.</p></div>
      </Section>
      <NotAvailableYet title="Cross-run account inventory is not implemented" intro="The current API exposes an account only inside a statement batch. It has no all-accounts endpoint or mapping review queue." items={[{ label: "Discovered account coverage", reason: "Requires date-range reconciliation runs." }, { label: "Reviewed mapping proposal", reason: "Requires the planned account-mapping authority model." }, { label: "Wallet history coverage", reason: "Requires read-only Wallet-history ingestion." }]} />
    </>
  );
}
