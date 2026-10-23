import test from "node:test";
import assert from "node:assert/strict";

import {
  formatAmount,
  formatCount,
  formatDate,
  formatDateRange,
  formatDateTime,
  formatPercent,
  formatSignedAmount,
  humanizeToken,
  shortId,
} from "../src/ui/format.ts";

test("formatAmount renders minor units with two decimals and a currency", () => {
  assert.equal(formatAmount(123456, "DOP"), "1,234.56 DOP");
  assert.equal(formatAmount(0, "USD"), "0.00 USD");
  assert.equal(formatAmount(5, "USD"), "0.05 USD");
});

test("formatAmount omits the currency when none is known", () => {
  assert.equal(formatAmount(123456, null), "1,234.56");
});

test("formatAmount renders an em dash for absent amounts", () => {
  assert.equal(formatAmount(null, "USD"), "—");
  assert.equal(formatAmount(undefined, "USD"), "—");
});

test("formatSignedAmount signs by statement direction", () => {
  assert.equal(formatSignedAmount(4230, "USD", "credit"), "+42.30 USD");
  assert.equal(formatSignedAmount(4230, "USD", "debit"), "−42.30 USD");
});

test("formatSignedAmount stays unsigned when the direction is unknown", () => {
  assert.equal(formatSignedAmount(4230, "USD", null), "42.30 USD");
  assert.equal(formatSignedAmount(4230, "USD", "weird"), "42.30 USD");
});

test("formatSignedAmount renders an em dash for absent amounts", () => {
  assert.equal(formatSignedAmount(null, "USD", "debit"), "—");
});

test("formatDate renders calendar dates without a timezone shift", () => {
  // A naive `new Date("2025-01-17").toLocaleDateString()` renders Jan 16 west
  // of UTC. Statement dates are calendar facts and must never drift.
  assert.equal(formatDate("2025-01-17"), "Jan 17, 2025");
  assert.equal(formatDate("2025-01-01T00:30:00Z"), "Jan 1, 2025");
  assert.equal(formatDate("2025-12-31T23:59:59+00:00"), "Dec 31, 2025");
});

test("formatDate rejects unusable values", () => {
  assert.equal(formatDate(null), "—");
  assert.equal(formatDate(""), "—");
  assert.equal(formatDate("not-a-date"), "—");
  assert.equal(formatDate("2025-13-01"), "—");
});

test("formatDateTime keeps the wall-clock parts the API reported", () => {
  assert.equal(formatDateTime("2025-01-17T04:05:00Z"), "Jan 17, 2025 · 04:05 UTC");
  assert.equal(formatDateTime("2025-01-17T04:05:00"), "Jan 17, 2025 · 04:05");
  assert.equal(formatDateTime("2025-01-17"), "Jan 17, 2025");
  assert.equal(formatDateTime(null), "—");
});

test("formatDateRange collapses a shared year", () => {
  assert.equal(formatDateRange("2025-01-01", "2025-12-31"), "Jan 1 – Dec 31, 2025");
});

test("formatDateRange keeps both years when they differ", () => {
  assert.equal(
    formatDateRange("2024-12-01", "2025-01-31"),
    "Dec 1, 2024 – Jan 31, 2025",
  );
});

test("formatDateRange describes open-ended ranges", () => {
  assert.equal(formatDateRange("2025-01-01", null), "From Jan 1, 2025");
  assert.equal(formatDateRange(null, "2025-01-31"), "Through Jan 31, 2025");
  assert.equal(formatDateRange(null, null), "—");
});

test("formatPercent rounds and refuses to divide by zero", () => {
  assert.equal(formatPercent(3, 4), "75%");
  assert.equal(formatPercent(1, 3), "33%");
  assert.equal(formatPercent(2, 3), "67%");
  assert.equal(formatPercent(0, 0), "—");
  assert.equal(formatPercent(5, 0), "—");
});

test("formatCount pluralizes and groups thousands", () => {
  assert.equal(formatCount(1, "line"), "1 line");
  assert.equal(formatCount(3, "line"), "3 lines");
  assert.equal(formatCount(0, "line"), "0 lines");
  assert.equal(formatCount(2, "entry", "entries"), "2 entries");
  assert.equal(formatCount(1200, "record"), "1,200 records");
});

test("shortId truncates long opaque identifiers", () => {
  assert.equal(shortId("a1b2c3d4e5f6"), "a1b2c3d4…");
  assert.equal(shortId("abc"), "abc");
  assert.equal(shortId(null), "—");
});

test("humanizeToken turns backend enum tokens into sentence case", () => {
  assert.equal(humanizeToken("exact_reference"), "Exact reference");
  assert.equal(humanizeToken("new"), "New");
  assert.equal(humanizeToken(null), "—");
});
