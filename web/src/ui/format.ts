/**
 * Display formatting for operator-facing reconciliation data.
 *
 * Every helper is pure and dependency-free so it can be unit-tested with
 * `node --test` and reused by both server and client components.
 *
 * Two rules drive the design:
 *
 * 1. A calendar date reported by the API is a calendar fact. `new Date(...)`
 *    re-interprets `2025-01-17` as UTC midnight and renders `Jan 16` west of
 *    Greenwich, so dates are parsed and rendered textually instead.
 * 2. Absent data renders as an em dash. It never renders as `0`, `unknown`,
 *    or a fabricated placeholder value.
 */

export const EM_DASH = "—";

/** U+2212 MINUS SIGN — aligns with digits, unlike the ASCII hyphen. */
const MINUS = "−";

/** U+2013 EN DASH — the typographic range separator. */
const EN_DASH = "–";

const MONTH_NAMES = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
];

const CALENDAR_DATE_PATTERN = /^(\d{4})-(\d{2})-(\d{2})/;
const WALL_CLOCK_PATTERN = /^\d{4}-\d{2}-\d{2}[T ](\d{2}):(\d{2})/;
const UTC_OFFSET_PATTERN = /(Z|[+-]\d{2}:?\d{2})$/;

export interface CalendarDate {
  year: number;
  month: number;
  day: number;
}

function daysInMonth(year: number, month: number): number {
  // Day 0 of the next month is the last day of this one, computed in UTC so
  // the host timezone cannot shift it.
  return new Date(Date.UTC(year, month, 0)).getUTCDate();
}

/**
 * Read the leading `YYYY-MM-DD` of an API value as a calendar date.
 *
 * Returns `null` for anything that is not a real calendar date, so callers can
 * render an em dash instead of an "Invalid Date".
 */
export function parseCalendarDate(
  value: string | null | undefined,
): CalendarDate | null {
  if (typeof value !== "string") return null;
  const match = CALENDAR_DATE_PATTERN.exec(value.trim());
  if (!match) return null;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  if (month < 1 || month > 12) return null;
  if (day < 1 || day > daysInMonth(year, month)) return null;
  return { year, month, day };
}

/** The `YYYY-MM-DD` key of an API value, or `null` when it is not a date. */
export function calendarKey(value: string | null | undefined): string | null {
  const parsed = parseCalendarDate(value);
  if (!parsed) return null;
  const month = String(parsed.month).padStart(2, "0");
  const day = String(parsed.day).padStart(2, "0");
  return `${parsed.year}-${month}-${day}`;
}

function renderCalendarDate(date: CalendarDate, withYear = true): string {
  const head = `${MONTH_NAMES[date.month - 1]} ${date.day}`;
  return withYear ? `${head}, ${date.year}` : head;
}

function groupInteger(value: number): string {
  return new Intl.NumberFormat("en-US", {
    useGrouping: true,
    maximumFractionDigits: 0,
  }).format(value);
}

/**
 * Render minor units (cents) as a grouped major-unit amount.
 *
 * Integer arithmetic keeps the cents exact; dividing by 100 first would expose
 * binary-float rounding on large statement amounts.
 */
function renderMinorUnits(minor: number): string {
  const rounded = Math.round(minor);
  const negative = rounded < 0;
  const absolute = Math.abs(rounded);
  const whole = Math.trunc(absolute / 100);
  const cents = absolute % 100;
  const body = `${groupInteger(whole)}.${String(cents).padStart(2, "0")}`;
  return negative ? `${MINUS}${body}` : body;
}

/** `123456, "DOP"` renders as `1,234.56 DOP`; an absent amount as an em dash. */
export function formatAmount(
  minor: number | null | undefined,
  currency?: string | null,
): string {
  if (minor == null || !Number.isFinite(minor)) return EM_DASH;
  const amount = renderMinorUnits(minor);
  const code = currency?.trim();
  return code ? `${amount} ${code}` : amount;
}

/**
 * Render an amount signed by its statement direction rather than by the sign
 * of the stored integer, which is always positive in this schema.
 */
export function formatSignedAmount(
  minor: number | null | undefined,
  currency: string | null | undefined,
  direction: string | null | undefined,
): string {
  if (minor == null || !Number.isFinite(minor)) return EM_DASH;
  const amount = formatAmount(Math.abs(minor), currency);
  if (direction === "credit") return `+${amount}`;
  if (direction === "debit") return `${MINUS}${amount}`;
  return amount;
}

/** `2025-01-17` renders as `Jan 17, 2025` in every timezone. */
export function formatDate(value: string | null | undefined): string {
  const parsed = parseCalendarDate(value);
  return parsed ? renderCalendarDate(parsed) : EM_DASH;
}

/**
 * Render a timestamp using the wall-clock parts the API reported.
 *
 * The zone suffix is echoed, never converted: `04:05 UTC` means the API said
 * 04:05Z, not "04:05 in your browser's timezone".
 */
export function formatDateTime(value: string | null | undefined): string {
  const parsed = parseCalendarDate(value);
  if (!parsed) return EM_DASH;
  const date = renderCalendarDate(parsed);
  const clock = WALL_CLOCK_PATTERN.exec(String(value).trim());
  if (!clock) return date;
  const zone = UTC_OFFSET_PATTERN.exec(String(value).trim())?.[1];
  const suffix = zone == null ? "" : isUtcOffset(zone) ? " UTC" : ` ${zone}`;
  return `${date} · ${clock[1]}:${clock[2]}${suffix}`;
}

function isUtcOffset(zone: string): boolean {
  return zone === "Z" || /^[+-]00:?00$/.test(zone);
}

/** `Jan 1 – Dec 31, 2025` when the years match, and honest when open-ended. */
export function formatDateRange(
  start: string | null | undefined,
  end: string | null | undefined,
): string {
  const from = parseCalendarDate(start);
  const to = parseCalendarDate(end);
  if (!from && !to) return EM_DASH;
  if (from && !to) return `From ${renderCalendarDate(from)}`;
  if (!from && to) return `Through ${renderCalendarDate(to)}`;
  if (!from || !to) return EM_DASH;
  const sharedYear = from.year === to.year;
  return `${renderCalendarDate(from, !sharedYear)} ${EN_DASH} ${renderCalendarDate(to)}`;
}

/** A whole-number percentage, or an em dash when the denominator is empty. */
export function formatPercent(
  part: number | null | undefined,
  total: number | null | undefined,
): string {
  if (part == null || total == null) return EM_DASH;
  if (!Number.isFinite(part) || !Number.isFinite(total)) return EM_DASH;
  if (total <= 0) return EM_DASH;
  return `${Math.round((part / total) * 100)}%`;
}

/** `3, "line"` renders as `3 lines`; `1200, "record"` as `1,200 records`. */
export function formatCount(
  count: number,
  singular: string,
  plural?: string,
): string {
  const noun = count === 1 ? singular : (plural ?? `${singular}s`);
  return `${groupInteger(count)} ${noun}`;
}

/** Truncate an opaque identifier so it stays scannable in a dense table. */
export function shortId(value: string | null | undefined): string {
  if (typeof value !== "string" || value === "") return EM_DASH;
  return value.length > 8 ? `${value.slice(0, 8)}…` : value;
}

/** `exact_reference` becomes `Exact reference` for operator-facing copy. */
export function humanizeToken(value: string | null | undefined): string {
  if (typeof value !== "string") return EM_DASH;
  const words = value.trim().replace(/[_-]+/g, " ").toLowerCase();
  if (words === "") return EM_DASH;
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** Mask all but the last four characters of a bank account reference. */
export function maskReference(value: string | null | undefined): string | null {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  if (trimmed === "") return null;
  return `••••${trimmed.slice(-4)}`;
}
