"use client";

import { useState } from "react";

interface Milestone {
  label: string;
  done: boolean;
}

interface Phase {
  title: string;
  items: Milestone[];
}

const DATA: Phase[] = [
  {
    title: "Domain & Persistence",
    items: [
      { label: "Money / TransactionAmount value objects", done: true },
      { label: "MailboxCursor / MailboxSource", done: true },
      { label: "20+ status enums (all workflow states)", done: true },
      { label: "24 SQLAlchemy 2.0 models", done: true },
      { label: "11 hand-written Alembic migrations", done: true },
      { label: "Immutable-table invariant (no updated_at column)", done: true },
      { label: "Idempotency keys (processing_attempts, import_commands)", done: true },
      { label: "Fail-closed config (WALLET_V2__ prefix)", done: true },
      { label: "Hermetic test suite", done: true },
    ],
  },
  {
    title: "Adapters (Live Connectors)",
    items: [
      { label: "IMAP — read-only via EXAMINE + BODY.PEEK[]", done: true },
      { label: "LLM — OpenAI, Gemini, DeepSeek, OpenRouter, custom", done: true },
      { label: "Wallet API — full REST read + write", done: true },
      { label: "MCP Client — JSON-RPC 2.0, 5 allowlisted tools", done: true },
      { label: "Push provider — production FCM/VAPID delivery", done: false },
    ],
  },
  {
    title: "Application Services",
    items: [
      { label: "WalletWorkflow orchestrator", done: true },
      { label: "EnrichmentService (MCP advisory, immutable versions)", done: true },
      { label: "AccountMappingService (wallet-account mapping)", done: true },
      { label: "AccountRepairService (Qik duplicate merge)", done: true },
      { label: "CatalogSyncService (versioned snapshots)", done: true },
      { label: "OutboxService + OutboxWorker (idempotent notifications)", done: true },
    ],
  },
  {
    title: "API Endpoints (FastAPI)",
    items: [
      { label: "Health check", done: true },
      { label: "Batches list & detail", done: true },
      { label: "Commands — resolve-line / map-account / approve-batch / dry-run-import", done: true },
      { label: "Enrichment — candidates (list, detail, by-account)", done: true },
      { label: "Enrichment — events (get, generate, override, finalize, dry-run)", done: true },
      { label: "Enrichment — batches (generate-proposals)", done: true },
      { label: "Enrichment — lines (get, override)", done: true },
      { label: "Push — config, subscribe, disable, list", done: true },
    ],
  },
  {
    title: "Web PWA (Next.js)",
    items: [
      { label: "Batches list page (/)", done: true },
      { label: "Batch detail — reconciliation workspace (/batches/[id])", done: true },
      { label: "Candidates list page (/candidates)", done: true },
      { label: "Candidate detail — evidence view (/candidates/[id])", done: true },
      { label: "EnrichmentCard — grade, generate, override, finalize, preview", done: true },
      { label: "OverrideForm — manual account/category/labels/payment", done: true },
      { label: "CandidateResearchCard — proposed wallet selection + evidence", done: true },
      { label: "Account mapping modal", done: true },
      { label: "Line resolve modal with observation linking", done: true },
      { label: "API proxy — GCP identity token + header allowlisting", done: true },
      { label: "TypeScript API client (lib/api.ts)", done: true },
      { label: "PWA manifest + service worker (offline cache)", done: true },
      { label: "Push subscription init", done: true },
      { label: "Dark theme (globals.css)", done: true },
      { label: "Dockerfile (multi-stage standalone build)", done: true },
      { label: "Firebase App Hosting config (firebase.json + apphosting.yaml)", done: true },
    ],
  },
  {
    title: "Deployment & Operations",
    items: [
      { label: "deploy.sh — Docker Compose build + health checks", done: true },
      { label: "docs/architecture.md", done: true },
      { label: "docs/deployment.md", done: true },
      { label: "Progress page (this page)", done: true },
      { label: "Authentication (deferred)", done: false },
      { label: "Background reconciliation worker", done: false },
    ],
  },
  {
    title: "CLI",
    items: [
      { label: "wallet-v2 run (dry_run/live, limit, date, uid, reprocess)", done: true },
      { label: "wallet-v2 runs show", done: true },
      { label: "wallet-v2 sync-catalog", done: true },
      { label: "wallet-v2 repair-qik", done: true },
    ],
  },
  {
    title: "What's Left",
    items: [
      { label: "Production push provider (FCM/VAPID delivery) — High", done: false },
      { label: "Authentication (operator identity + audit attribution) — High", done: false },
      { label: "Background reconciliation worker (resolve unknown imports) — Medium", done: false },
      { label: "Catalog sync scheduling (periodic/webhook) — Medium", done: false },
      { label: "Advanced filtering / search — Low", done: false },
      { label: "Analytics / metrics dashboard — Low", done: false },
      { label: "Native mobile app (beyond PWA) — Low", done: false },
    ],
  },
];

export default function ProgressPage() {
  const [expanded, setExpanded] = useState<Record<string, boolean>>(() => {
    const initial: Record<string, boolean> = {};
    for (const p of DATA) {
      initial[p.title] = !p.items.every((i) => i.done);
    }
    return initial;
  });

  const toggle = (title: string) => {
    setExpanded((prev) => ({ ...prev, [title]: !prev[title] }));
  };

  const total = DATA.flatMap((p) => p.items).length;
  const done = DATA.flatMap((p) => p.items).filter((i) => i.done).length;
  const pct = Math.round((done / total) * 100);

  return (
    <div>
      <div className="card" style={{ marginBottom: "1.5rem" }}>
        <div className="card-header">
          <span className="card-title">Progress</span>
          <span className="badge badge-open">{done}/{total} ({pct}%)</span>
        </div>
        <div style={{ marginTop: "0.75rem" }}>
          <div
            style={{
              height: 8,
              borderRadius: 4,
              background: "var(--border)",
              overflow: "hidden",
            }}
          >
            <div
              style={{
                height: "100%",
                width: `${pct}%`,
                background: pct >= 90 ? "var(--success)" : "var(--accent)",
                borderRadius: 4,
                transition: "width 0.4s",
              }}
            />
          </div>
        </div>
      </div>

      {DATA.map((phase) => {
        const phaseDone = phase.items.filter((i) => i.done).length;
        const phaseTotal = phase.items.length;
        const isComplete = phaseDone === phaseTotal;
        const isOpen = expanded[phase.title];

        return (
          <div key={phase.title} className="card">
            <div
              className="card-header"
              onClick={() => toggle(phase.title)}
              style={{ cursor: "pointer", userSelect: "none" }}
            >
              <span style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                <span style={{ fontSize: "0.75rem" }}>
                  {isOpen ? "▾" : "▸"}
                </span>
                <span className="card-title" style={{ fontSize: "0.875rem" }}>
                  {phase.title}
                </span>
              </span>
              <span
                className={`badge ${isComplete ? "badge-approved" : "badge-ambiguous"}`}
              >
                {phaseDone}/{phaseTotal}
              </span>
            </div>
            {isOpen && (
              <ul style={{ listStyle: "none", marginTop: "0.5rem" }}>
                {phase.items.map((item) => (
                  <li
                    key={item.label}
                    style={{
                      display: "flex",
                      alignItems: "flex-start",
                      gap: "0.5rem",
                      padding: "0.3rem 0",
                      fontSize: "0.8125rem",
                      color: item.done ? "var(--text-muted)" : "var(--text)",
                    }}
                  >
                    <span
                      style={{
                        flexShrink: 0,
                        width: 20,
                        height: 20,
                        borderRadius: 4,
                        display: "inline-flex",
                        alignItems: "center",
                        justifyContent: "center",
                        fontSize: "0.6875rem",
                        fontWeight: 700,
                        background: item.done ? "#14532d" : "var(--border)",
                        color: item.done ? "#4ade80" : "var(--text-muted)",
                        marginTop: 1,
                      }}
                    >
                      {item.done ? "✓" : ""}
                    </span>
                    <span style={{ textDecoration: item.done ? "line-through" : "none" }}>
                      {item.label}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        );
      })}
    </div>
  );
}
