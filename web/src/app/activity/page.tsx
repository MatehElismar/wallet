import { NotAvailableYet, PageHeader, Section } from "@/components/ui";
import { AuthorityChip } from "@/components/authority";

export default function ActivityPage() {
  return (
    <>
      <PageHeader title="Activity" lede="A durable record of review, canonicalization, and controlled import outcomes. Approval and import are deliberately separate events." />
      <Section title="Controlled import boundary" note="An approved canonical event is an immutable accounting decision, not evidence that Wallet changed.">
        <div className="card authority-reference"><AuthorityChip tier="canonical" /><p className="card-copy">A future activity stream will show the authenticated reviewer, canonical-event identity, exact payload identity, idempotency key, and any unresolved external outcome. It must never offer a blind retry for an unknown Wallet result.</p></div>
      </Section>
      <NotAvailableYet title="Activity stream is not implemented" intro="Audit events and import commands exist in persistence, but the current API does not expose an operator activity feed." items={[{ label: "Attributable review decisions", reason: "Session-derived operator identity is a pilot prerequisite." }, { label: "Import command status", reason: "The current UI has no durable command-status query." }, { label: "Unknown outcome resolution", reason: "The planned resolver worker has not been implemented." }]} />
    </>
  );
}
