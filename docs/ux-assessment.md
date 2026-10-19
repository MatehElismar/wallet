# Wallet V2 Console — UX Assessment & User Flow

## Current Focus vs. Deferred

| Stream | Status | Flow |
|--------|--------|------|
| **Notifications → advisory enrichment** | In progress | Notification arrives → enrichment → operator review → statement corroboration |
| **Statements → batch review** | Deferred | Monthly statement matching against notifications, bulk reconciliation |

---

## User Journey (Current Focus: Notifications)

### 1. Authentication → Candidates (Primary Workspace)

- Operator opens the PWA, logs in.
- Lands on **Candidates** — the main workspace.
- Each card shows: merchant, amount, direction (credit/debit coloring), date, evidence grade, sender.
- This is where the work happens — not a read-only sidebar.

**Gap today:** Unauthenticated.

### 2. Candidate Detail (Core Workflow)

The operator opens a candidate and works through the enrichment pipeline:

1. **Candidate metadata** — merchant, amount, direction, transaction date, source (sender, email subject, date).
2. **Enrichment evidence** — MCP-backed research showing proposed account, category, labels, payment type, with evidence records and grade (exact_recurrence, merchant_history, context_only).
3. **Override** — operator can change the MCP proposal (different account/category/labels/payment). Creates a new immutable version.
4. **Finalize** — locks in the decision. Re-validates against the current Wallet catalog.
5. **Dry-run preview** — shows the exact Wallet REST payload that will be submitted.
6. **Statement handoff** — the candidate remains advisory evidence until a
   posted statement line is reviewed and approved as a canonical financial event.

**UX concerns:**

| Issue | Severity | What's wrong |
|-------|----------|-------------|
| **Statement handoff is unclear** | High | Candidate detail is advisory by policy, but it does not clearly explain that statement confirmation is required before a Wallet import is possible. |
| **Candidates list has no action items** | High | List page is browse-only. Operator has to click into each candidate individually. No bulk enrich, no batch import, no status filter. |
| **Enrichment is on the batch page, not candidates** | Medium | The Generate/Override/Finalize buttons live in `batches/[id]`, but the candidate workflow should be self-contained on the candidate detail page. |
| **No notification of new candidates** | Medium | New notifications arrive silently. Operator has to manually refresh the candidates list. Push notifications would solve this. |
| **Evidence grade not actionable** | Low | A candidate with `no_recommendation` still shows up in the list. Needs filter/sort by grade so the operator can triage. |

### 3. Statements (Deferred)

Monthly bank documents. When implemented:

- Statement arrives → system auto-matches lines to previously recorded notifications
- Operator reviews matches, resolves ambiguous lines
- Bulk enrichment + approval → creates financial events → import

Not blocking the current notification-enrichment flow.

### 4. Push Notifications (Partial)

- Service worker and PushInit exist.
- Push provider is a stub — no production FCM/VAPID delivery.
- When completed: operator gets notified when new candidates arrive, import succeeds/fails.

### 5. Progress Page (Handoff)

- Collapsible checklist showing build state (~90%).
- Static data — manually updated when features ship.

---

## Critical UX Gaps for Current Focus (Priority Order)

### P0 — Before testing the advisory-notification flow

1. **Authentication** — login, session, operator identity in audit trail.

2. **Make the safety boundary explicit** — candidate pages must retain their
   advisory-only status and explain that a posted statement line, review, and
   approved canonical financial event are required before import. Candidate
   enrichment must not create an import command or bypass statement review.

3. **Candidates list triage** — keep the advisory label but add clearer
   statuses for pending enrichment, enriched, and corroborated-by-statement.

### P1 — Before production use

4. **Push notifications for new candidates** — production FCM/VAPID delivery.
5. **Live import mode for approved canonical events** — switch from dry-run to live Wallet submissions only after the existing statement-review gate.

### P2 — Quality of life

7. **Auto-populate reviewer ID** from auth session.
8. **Candidate detail → enrichment actions** currently require navigating to the batch page. Advisory enrichment actions should be available on the candidate detail page.
9. **Bulk enrich candidates** from the list page.
10. **Notification preferences** — per-event-type opt-in/out.

### P3 — Polish

11. **Progress page → feature links** — clickable items that navigate to relevant setup.
12. **Dark/light theme toggle**.

---

## Concrete State of Each Page (Current vs. Needed)

### Candidates List (`/candidates`)

| Aspect | Current | Needed |
|--------|---------|--------|
| Page heading | "advisory only · never finalizable" | Keep the advisory boundary; clarify the statement-confirmation handoff and show count. |
| Cards | Clickable, show merchant/amount/grade/status | Same, add bulk-select checkboxes |
| Filters | None | Sort by date, grade, status, amount |
| Actions | None (click-through only) | Bulk enrich only; no candidate import action |
| Status badges | Grade only | Add: pending, enriched, corroborated-by-statement |

### Candidate Detail (`/candidates/[id]`)

| Aspect | Current | Needed |
|--------|---------|--------|
| Warning banner | "cannot be finalized or imported to Wallet" | Retain and clarify the statement-confirmation requirement |
| Metadata card | ✓ merchant, amount, direction, date, status | ✓ good |
| Source details | ✓ sender, date, subject | ✓ good |
| Enrichment | Read-only CandidateResearchCard | Advisory Generate/Override actions without import authority |
| Evidence | Expandable JSON | ✓ good |
| Record preview | Expandable JSON toggle | ✓ good |
| Import | None | No candidate import; link to the approved statement-event path when available |
| Back button | ✓ | ✓ good |

### Batch Detail (`/batches/[id]`)

| Aspect | Current | Needed |
|--------|---------|--------|
| EnrichmentCard | Generate, Override, Finalize, Preview | Keep but also expose on candidate detail |
| Candidate evidence | Shows candidates for the account inline | Keep — useful when statement matching is built |
| Import | Dry-run only for approved events | Add live mode toggle after authentication and operational controls |

---

## Recommended User Flow (Current Focus)

```
Login
  │
  ▼
Candidates List (primary workspace)
  │
  ├─ Filter/sort by: grade, status, date, merchant
  ├─ Select candidates → bulk enrich
  │
  ▼
Candidate Detail
  │
  ├─ Metadata: merchant, amount, direction, source
  ├─ Enrichment panel
  │   ├─ [Generate] — get MCP proposal
  │   ├─ [Override] — change account/category/labels/payment
  │   └─ [Finalize] — only where it remains advisory and auditable
  ├─ Evidence + record preview (expandable)
  └─ Statement handoff — wait for posted-statement confirmation and approval
```

---

## What Needs to Change in Code

| Change | Layer | Files affected |
|--------|-------|---------------|
| Auth — login + middleware | Web | New: `login/page.tsx`, middleware. Modify: layout, nav-bar |
| Explain candidate → statement handoff | Web | `candidates/[id]/page.tsx`, `candidates/page.tsx`, `candidate-research-card.tsx` |
| Add safe advisory enrichment actions to candidate detail | Web | `candidates/[id]/page.tsx` — preserve no-import policy |
| Add filter/sort to candidates list | Web | `candidates/page.tsx` |
| Push notification delivery | API | `push_provider.py` — implement FCM/VAPID |
| Live import mode | API | Config + `service.py` — switch from dry_run to live |
