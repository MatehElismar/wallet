const API_BASE = "/api";

export interface BatchSummary {
  batch_id: string;
  statement_id: string;
  account_issuer: string | null;
  account_reference: string | null;
  statement_currency: string | null;
  statement_date: string | null;
  period_start: string | null;
  period_end: string | null;
  line_count: number;
  line_resolved_count: number;
  ambiguous_count: number;
  state: string;
  created_at: string;
}

export interface BatchDetail {
  batch_id: string;
  statement_id: string;
  state: string;
  statement_status: string;
  statement_currency: string | null;
  statement_date: string | null;
  period_start: string | null;
  period_end: string | null;
  opening_balance_minor: number | null;
  closing_balance_minor: number | null;
  account: FinancialAccountView | null;
  lines: StatementLineView[];
  reviewer_id: string | null;
  decided_at: string | null;
  decision_note: string | null;
  created_at: string;
}

export interface FinancialAccountView {
  account_id: string;
  issuer: string;
  external_reference: string;
  wallet_account_reference: string | null;
}

export interface StatementLineView {
  line_id: string;
  line_index: number;
  direction: string;
  amount_minor: number;
  currency: string;
  merchant: string | null;
  external_reference: string | null;
  description: string | null;
  transaction_date: string | null;
  posting_date: string | null;
  running_balance_minor: number | null;
  event_status: string;
  event_id: string | null;
  reconciliation: ReconciliationLinkView | null;
  observation: ObservationView | null;
  eligible_observations: ObservationView[];
}

export interface ReconciliationLinkView {
  outcome: string;
  method: string;
  confidence: number | null;
  note: string | null;
}

export interface ObservationView {
  observation_id: string;
  source_merchant: string | null;
  source_reference: string | null;
  status: string;
  amount_minor: number;
  currency: string;
  direction: string;
  transaction_date: string | null;
}

export interface FinancialEventView {
  event_id: string;
  direction: string;
  amount_minor: number;
  currency: string;
  merchant: string | null;
  reference: string | null;
  transaction_date: string | null;
  posting_date: string | null;
  event_status: string;
}

async function fetchJSON<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(body.detail || res.statusText);
  }
  return res.json();
}

export async function listBatches(): Promise<{ batches: BatchSummary[] }> {
  return fetchJSON("/batches");
}

export async function getBatchDetail(
  batchId: string
): Promise<BatchDetail> {
  return fetchJSON(`/batches/${batchId}`);
}

export async function resolveLine(
  lineId: string,
  body: { outcome: string; observation_id?: string; note?: string }
): Promise<{
  link_id: string;
  outcome: string;
  method: string;
  note: string | null;
}> {
  return fetchJSON(`/commands/resolve-line/${lineId}`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function mapAccount(
  accountId: string,
  body: { wallet_account_reference: string }
): Promise<{ account_id: string; wallet_account_reference: string }> {
  return fetchJSON(`/commands/map-account/${accountId}`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function approveBatch(
  batchId: string,
  body: {
    reviewer_id: string;
    note?: string;
    enrichment_overrides?: Record<string, OverrideDecisionBody>;
  }
): Promise<{
  batch_id: string;
  event_count: number;
  events: FinancialEventView[];
}> {
  return fetchJSON(`/commands/approve-batch/${batchId}`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function dryRunImport(
  eventId: string
): Promise<{ command_id: string; event_id: string; status: string; issued_at: string }> {
  return fetchJSON(`/commands/dry-run-import/${eventId}`, {
    method: "POST",
  });
}

// ── Phase C: MCP advisory enrichment ──────────────────────────────────

export interface EvidenceRecord {
  record_id: string | null;
  grade: string | null;
  score: number | null;
  account_id: string | null;
  record_date: string | null;
  counter_party: string | null;
  amount_value: number | null;
  currency: string | null;
  category_id: string | null;
  label_ids: string[];
  payment_type: string | null;
}

export interface CandidateResearch {
  candidate_id: string;
  evidence_grade: string;
  recommendation: boolean;
  is_finalizable: boolean;
  selected_account_id: string | null;
  selected_category_id: string | null;
  selected_label_ids: string[];
  selected_payment_type: string | null;
  rationale: string;
  integrity_hash: string | null;
  query_inputs: Record<string, unknown> | null;
  response_metadata: Record<string, unknown> | null;
  evidence: EvidenceRecord[];
  merchant: string | null;
  reference: string | null;
  amount_minor: number | null;
  currency: string | null;
  direction: string | null;
  transaction_date: string | null;
  candidate_status: string | null;
  sender: string | null;
  subject: string | null;
  source_date: string | null;
}

export interface EventEnrichment {
  line_id?: string | null;
  event_id?: string | null;
  version: number;
  evidence_grade: string;
  recommendation: boolean;
  finalized: boolean;
  can_finalize: boolean;
  selected_account_id: string | null;
  selected_category_id: string | null;
  selected_label_ids: string[];
  selected_payment_type: string | null;
  rationale: string;
  query_inputs: Record<string, unknown> | null;
  evidence_refs: Record<string, unknown> | null;
  catalog_snapshot_ids: Record<string, unknown> | null;
  provenance: Record<string, unknown> | null;
  created_at: string | null;
}

export interface OverrideDecisionBody {
  account_id: string;
  category_id: string | null;
  label_ids: string[];
  payment_type: string | null;
}

export interface DryRunRecordPreview {
  event_id: string;
  decision_version: number;
  submitted: boolean;
  payload: Record<string, unknown>;
  catalog_snapshot_ids: Record<string, unknown> | null;
}

export async function getCandidateResearch(
  candidateId: string
): Promise<CandidateResearch> {
  return fetchJSON(`/enrichment/candidates/${candidateId}`);
}

export async function listCandidates(): Promise<CandidateResearch[]> {
  return fetchJSON("/enrichment/candidates");
}

export async function listCandidateResearchByAccount(
  accountId: string
): Promise<CandidateResearch[]> {
  return fetchJSON(`/enrichment/candidates/account/${accountId}`);
}

export async function generateBatchProposals(
  batchId: string
): Promise<EventEnrichment[]> {
  return fetchJSON(`/enrichment/batches/${batchId}/generate-proposals`, {
    method: "POST",
  });
}

export async function getLineEnrichment(
  lineId: string
): Promise<EventEnrichment> {
  return fetchJSON(`/enrichment/lines/${lineId}`);
}

export async function overrideLineDecision(
  lineId: string,
  body: OverrideDecisionBody
): Promise<EventEnrichment> {
  return fetchJSON(`/enrichment/lines/${lineId}/override`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function getEventEnrichment(
  eventId: string
): Promise<EventEnrichment> {
  return fetchJSON(`/enrichment/events/${eventId}`);
}

export async function generateEventDecision(
  eventId: string
): Promise<EventEnrichment> {
  return fetchJSON(`/enrichment/events/${eventId}/generate`, {
    method: "POST",
  });
}

export async function overrideEventDecision(
  eventId: string,
  body: OverrideDecisionBody
): Promise<EventEnrichment> {
  return fetchJSON(`/enrichment/events/${eventId}/override`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function finalizeEventDecision(
  eventId: string
): Promise<EventEnrichment> {
  return fetchJSON(`/enrichment/events/${eventId}/finalize`, {
    method: "POST",
  });
}

export async function getDryRunPreview(
  eventId: string
): Promise<DryRunRecordPreview> {
  return fetchJSON(`/enrichment/events/${eventId}/dry-run-preview`);
}
