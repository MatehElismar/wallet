/**
 * Shared presentational primitives for the reconciliation console.
 *
 * Every screen composes these instead of hand-rolling inline styles, so the
 * accessibility and responsive behaviour is written once:
 *
 * - async states are announced (`role="status"` / `role="alert"`);
 * - errors are inline and retryable rather than full-screen dead ends;
 * - layout is driven by CSS classes, so media queries can reflow it.
 */

import type { ReactNode } from "react";

export type Tone =
  | "neutral"
  | "info"
  | "warn"
  | "danger"
  | "settled"
  | "advisory"
  | "reconciliation"
  | "proposal"
  | "canonical"
  | "muted";

export function PageHeader({
  title,
  lede,
  actions,
}: {
  title: string;
  lede?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="page-header">
      <div className="page-header-main">
        <h2 className="page-title">{title}</h2>
        {lede ? <p className="page-lede">{lede}</p> : null}
      </div>
      {actions ? <div className="page-header-actions">{actions}</div> : null}
    </div>
  );
}

export function Section({
  title,
  note,
  actions,
  children,
}: {
  title: string;
  note?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="section" aria-label={title}>
      <div className="section-heading">
        <div>
          <h3 className="section-title">{title}</h3>
          {note ? <p className="section-note">{note}</p> : null}
        </div>
        {actions ? <div className="section-actions">{actions}</div> : null}
      </div>
      {children}
    </section>
  );
}

export function Card({
  children,
  className = "",
  tone,
}: {
  children: ReactNode;
  className?: string;
  tone?: Tone;
}) {
  const toneClass = tone ? ` card-${tone}` : "";
  return <div className={`card${toneClass} ${className}`.trim()}>{children}</div>;
}

export function CardHeader({
  title,
  subtitle,
  aside,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  aside?: ReactNode;
}) {
  return (
    <div className="card-header">
      <div className="card-header-main">
        <div className="card-title">{title}</div>
        {subtitle ? <div className="card-subtitle">{subtitle}</div> : null}
      </div>
      {aside ? <div className="card-header-aside">{aside}</div> : null}
    </div>
  );
}

/** A responsive grid of labelled figures, marked up as a definition list. */
export function StatGrid({ children }: { children: ReactNode }) {
  return <dl className="stat-grid">{children}</dl>;
}

export function Stat({
  label,
  value,
  hint,
  tone,
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  tone?: Tone;
}) {
  return (
    <div className="stat">
      <dt className="stat-label">{label}</dt>
      <dd className={`stat-value${tone ? ` stat-${tone}` : ""}`}>{value}</dd>
      {hint ? <dd className="stat-hint">{hint}</dd> : null}
    </div>
  );
}

export function Badge({
  tone = "neutral",
  children,
  title,
}: {
  tone?: Tone;
  children: ReactNode;
  title?: string;
}) {
  return (
    <span className={`chip chip-${tone}`} title={title}>
      {children}
    </span>
  );
}

/** A key/value block that stays readable when it wraps on a narrow screen. */
export function DataList({
  items,
}: {
  items: { label: string; value: ReactNode }[];
}) {
  return (
    <dl className="data-list">
      {items.map((item) => (
        <div className="data-list-row" key={item.label}>
          <dt>{item.label}</dt>
          <dd>{item.value}</dd>
        </div>
      ))}
    </dl>
  );
}

export function Alert({
  tone = "info",
  title,
  children,
  actions,
}: {
  tone?: "info" | "warn" | "danger" | "advisory";
  title?: ReactNode;
  children?: ReactNode;
  actions?: ReactNode;
}) {
  // Only a failure interrupts a screen reader; advisory context waits its turn.
  const assertive = tone === "danger";
  return (
    <div
      className={`alert alert-${tone}`}
      role={assertive ? "alert" : "status"}
      aria-live={assertive ? "assertive" : "polite"}
    >
      {title ? <strong className="alert-title">{title}</strong> : null}
      {children ? <div className="alert-body">{children}</div> : null}
      {actions ? <div className="alert-actions">{actions}</div> : null}
    </div>
  );
}

export function LoadingState({ label }: { label: string }) {
  return (
    <div className="loading-state" role="status" aria-live="polite">
      <span className="spinner" aria-hidden="true" />
      <span>{label}</span>
    </div>
  );
}

export function EmptyState({
  title,
  children,
}: {
  title: string;
  children?: ReactNode;
}) {
  return (
    <div className="empty-state">
      <p className="empty-state-title">{title}</p>
      {children ? <div className="empty-state-body">{children}</div> : null}
    </div>
  );
}

/**
 * An inline, retryable failure.
 *
 * The screen keeps its navigation and any data already loaded; the error is
 * attached to the action that failed.
 */
export function ErrorState({
  message,
  onRetry,
  retryLabel = "Try again",
}: {
  message: string;
  onRetry?: () => void;
  retryLabel?: string;
}) {
  return (
    <Alert
      tone="danger"
      title="That request failed"
      actions={
        onRetry ? (
          <button type="button" className="btn btn-secondary btn-small" onClick={onRetry}>
            {retryLabel}
          </button>
        ) : null
      }
    >
      {message}
    </Alert>
  );
}

/**
 * The honest half of a pilot screen: what this surface cannot show yet, and
 * why. Keeping it a component stops each page from inventing its own wording
 * for the same missing capability.
 */
export function NotAvailableYet({
  title = "Not available in the pilot backend",
  intro,
  items,
}: {
  title?: string;
  intro?: ReactNode;
  items: { label: string; reason: ReactNode }[];
}) {
  return (
    <section className="gap-panel" aria-label={title}>
      <h3 className="gap-title">{title}</h3>
      {intro ? <p className="gap-intro">{intro}</p> : null}
      <ul className="gap-list">
        {items.map((item) => (
          <li key={item.label}>
            <span className="gap-item-label">{item.label}</span>
            <span className="gap-item-reason">{item.reason}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

/** Horizontal scroll container so wide rows stay reachable on a phone. */
export function ScrollRegion({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <div className="scroll-region" role="region" aria-label={label} tabIndex={0}>
      {children}
    </div>
  );
}
