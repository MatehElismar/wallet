/**
 * Derived views over the statement batches the API actually returns.
 *
 * `GET /batches` lists *open* statement review batches and nothing else. There
 * is no date-range run engine behind it, so everything here is deliberately
 * named after what it really is: an **observed window** assembled from the
 * open batches, not a reconciliation run report.
 *
 * The one piece of arithmetic worth stating plainly: the API counts an
 * ambiguous line as `line_resolved_count`, because a `ReconciliationLink` row
 * exists for it. An operator cannot treat it as resolved — approval of the
 * whole statement is blocked while any ambiguous line remains. So coverage is
 * reported on *settled* lines (resolved minus ambiguous), never on the raw
 * resolved count.
 */

import type { BatchSummary } from "../lib/api";
import {
  EM_DASH,
  calendarKey,
  formatDate,
  formatDateRange,
  formatPercent,
  maskReference,
} from "./format";

export interface CoverageSummary {
  /** Posted statement lines in the batch. */
  lineCount: number;
  /** Lines with any reconciliation link, ambiguous ones included. */
  resolvedCount: number;
  /** Lines an operator can consider done: resolved minus ambiguous. */
  settledCount: number;
  ambiguousCount: number;
  /** Lines with no reconciliation link at all. */
  unreconciledCount: number;
  /** Settled share of the statement, or an em dash for an empty statement. */
  coverageLabel: string;
}

function clamp(value: number | null | undefined, max: number): number {
  if (typeof value !== "number" || !Number.isFinite(value)) return 0;
  return Math.min(Math.max(Math.trunc(value), 0), max);
}

function nonNegative(value: number | null | undefined): number {
  if (typeof value !== "number" || !Number.isFinite(value)) return 0;
  return Math.max(Math.trunc(value), 0);
}

export function coverageOf(batch: BatchSummary): CoverageSummary {
  const lineCount = nonNegative(batch.line_count);
  const resolvedCount = clamp(batch.line_resolved_count, lineCount);
  const ambiguousCount = clamp(batch.ambiguous_count, resolvedCount);
  const settledCount = resolvedCount - ambiguousCount;
  return {
    lineCount,
    resolvedCount,
    settledCount,
    ambiguousCount,
    unreconciledCount: lineCount - resolvedCount,
    coverageLabel: formatPercent(settledCount, lineCount),
  };
}

function emptyCoverage(): CoverageSummary {
  return {
    lineCount: 0,
    resolvedCount: 0,
    settledCount: 0,
    ambiguousCount: 0,
    unreconciledCount: 0,
    coverageLabel: EM_DASH,
  };
}

function addCoverage(
  total: CoverageSummary,
  next: CoverageSummary,
): CoverageSummary {
  const lineCount = total.lineCount + next.lineCount;
  const resolvedCount = total.resolvedCount + next.resolvedCount;
  const ambiguousCount = total.ambiguousCount + next.ambiguousCount;
  const settledCount = total.settledCount + next.settledCount;
  return {
    lineCount,
    resolvedCount,
    settledCount,
    ambiguousCount,
    unreconciledCount: lineCount - resolvedCount,
    coverageLabel: formatPercent(settledCount, lineCount),
  };
}

/** A bank/card account is identified by its issuer and external reference. */
function accountKeyOf(batch: BatchSummary): string {
  const issuer = (batch.account_issuer ?? "").trim().toLowerCase();
  const reference = (batch.account_reference ?? "").trim().toLowerCase();
  return `${issuer}|${reference}`;
}

/** `Banco Popular · ••••2727`, with the account number masked. */
export function accountLabelOf(
  issuer: string | null | undefined,
  reference: string | null | undefined,
): string {
  const name = issuer?.trim() || null;
  const masked = maskReference(reference);
  if (name && masked) return `${name} · ${masked}`;
  return name ?? masked ?? "Unidentified account";
}

export interface RunRow {
  batchId: string;
  statementId: string;
  state: string;
  issuer: string | null;
  reference: string | null;
  accountKey: string;
  accountLabel: string;
  currency: string | null;
  /** `YYYY-MM-DD`, or `null` when the statement carries no period. */
  periodStart: string | null;
  periodEnd: string | null;
  periodLabel: string;
  statementDateLabel: string;
  coverage: CoverageSummary;
  /** Something in this statement still needs an operator. */
  needsAttention: boolean;
}

function toRunRow(batch: BatchSummary): RunRow {
  const coverage = coverageOf(batch);
  return {
    batchId: batch.batch_id,
    statementId: batch.statement_id,
    state: batch.state,
    issuer: batch.account_issuer,
    reference: batch.account_reference,
    accountKey: accountKeyOf(batch),
    accountLabel: accountLabelOf(batch.account_issuer, batch.account_reference),
    currency: batch.statement_currency,
    periodStart: calendarKey(batch.period_start),
    periodEnd: calendarKey(batch.period_end),
    periodLabel: formatDateRange(batch.period_start, batch.period_end),
    statementDateLabel: formatDate(batch.statement_date),
    coverage,
    needsAttention:
      coverage.ambiguousCount > 0 || coverage.unreconciledCount > 0,
  };
}

/**
 * Compare by period end, newest first, with undated statements last.
 *
 * A statement without a period is not "old"; its position is unknown. Sorting
 * it by `statement_date` or `created_at` instead would silently invent an
 * ordering the data does not support, so it sinks to the bottom.
 */
function byNewestPeriod(a: RunRow, b: RunRow): number {
  if (a.periodEnd && b.periodEnd) {
    // Plain ordinal comparison: `YYYY-MM-DD` sorts correctly as text, and
    // `localeCompare` could treat the hyphens as ignorable punctuation.
    if (a.periodEnd === b.periodEnd) return 0;
    return a.periodEnd < b.periodEnd ? 1 : -1;
  }
  if (a.periodEnd) return -1;
  if (b.periodEnd) return 1;
  return 0;
}

export function toRunRows(batches: readonly BatchSummary[]): RunRow[] {
  return batches.map(toRunRow).sort(byNewestPeriod);
}

export interface ObservedWindow {
  batchCount: number;
  /** Distinct issuer + reference pairs seen across the batches. */
  accountCount: number;
  lineCount: number;
  resolvedCount: number;
  settledCount: number;
  ambiguousCount: number;
  unreconciledCount: number;
  /** Batches with at least one ambiguous or unreconciled line. */
  attentionCount: number;
  /** Sorted, de-duplicated currency codes; unknown currencies are dropped. */
  currencies: string[];
  periodStart: string | null;
  periodEnd: string | null;
  rangeLabel: string;
  coverageLabel: string;
}

/**
 * Aggregate the open batches into the window they actually cover.
 *
 * The window is observed, not requested: it reports the span of the statements
 * that happen to be open, and an empty list reports zeroes rather than a
 * fabricated date range.
 */
export function summarizeBatches(
  batches: readonly BatchSummary[],
): ObservedWindow {
  const rows = toRunRows(batches);
  const accounts = new Set<string>();
  const currencies = new Set<string>();
  let coverage = emptyCoverage();
  let periodStart: string | null = null;
  let periodEnd: string | null = null;
  let attentionCount = 0;

  for (const row of rows) {
    accounts.add(row.accountKey);
    const currency = row.currency?.trim();
    if (currency) currencies.add(currency);
    coverage = addCoverage(coverage, row.coverage);
    if (row.needsAttention) attentionCount += 1;
    if (row.periodStart && (!periodStart || row.periodStart < periodStart)) {
      periodStart = row.periodStart;
    }
    if (row.periodEnd && (!periodEnd || row.periodEnd > periodEnd)) {
      periodEnd = row.periodEnd;
    }
  }

  return {
    batchCount: rows.length,
    accountCount: accounts.size,
    lineCount: coverage.lineCount,
    resolvedCount: coverage.resolvedCount,
    settledCount: coverage.settledCount,
    ambiguousCount: coverage.ambiguousCount,
    unreconciledCount: coverage.unreconciledCount,
    attentionCount,
    currencies: [...currencies].sort(),
    periodStart,
    periodEnd,
    rangeLabel: formatDateRange(periodStart, periodEnd),
    coverageLabel: coverage.coverageLabel,
  };
}

export interface AccountRow {
  accountKey: string;
  issuer: string | null;
  reference: string | null;
  accountLabel: string;
  currencies: string[];
  statementCount: number;
  periodStart: string | null;
  periodEnd: string | null;
  periodLabel: string;
  coverage: CoverageSummary;
  needsAttention: boolean;
  batchIds: string[];
  /** Newest open batch for this account — the deep link for its mapping. */
  latestBatchId: string;
}

/**
 * Group the open batches by discovered account.
 *
 * Only what the batch list carries is reported here. Whether an account has a
 * validated Wallet mapping lives on the batch detail payload, so the Accounts
 * page fetches that separately rather than guessing it from the summary.
 */
export function toAccountRows(batches: readonly BatchSummary[]): AccountRow[] {
  const byAccount = new Map<string, AccountRow>();

  for (const row of toRunRows(batches)) {
    const existing = byAccount.get(row.accountKey);
    if (!existing) {
      byAccount.set(row.accountKey, {
        accountKey: row.accountKey,
        issuer: row.issuer,
        reference: row.reference,
        accountLabel: row.accountLabel,
        currencies: row.currency ? [row.currency] : [],
        statementCount: 1,
        periodStart: row.periodStart,
        periodEnd: row.periodEnd,
        periodLabel: row.periodLabel,
        coverage: row.coverage,
        needsAttention: row.needsAttention,
        batchIds: [row.batchId],
        latestBatchId: row.batchId,
      });
      continue;
    }
    existing.statementCount += 1;
    existing.batchIds.push(row.batchId);
    existing.coverage = addCoverage(existing.coverage, row.coverage);
    existing.needsAttention = existing.needsAttention || row.needsAttention;
    if (row.currency && !existing.currencies.includes(row.currency)) {
      existing.currencies.push(row.currency);
    }
    if (
      row.periodStart &&
      (!existing.periodStart || row.periodStart < existing.periodStart)
    ) {
      existing.periodStart = row.periodStart;
    }
    if (
      row.periodEnd &&
      (!existing.periodEnd || row.periodEnd > existing.periodEnd)
    ) {
      existing.periodEnd = row.periodEnd;
    }
    existing.periodLabel = formatDateRange(
      existing.periodStart,
      existing.periodEnd,
    );
  }

  return [...byAccount.values()].map((account) => ({
    ...account,
    currencies: [...account.currencies].sort(),
  }));
}
