import type { Metadata, Viewport } from "next";
import "./globals.css";
import { PushInitScript } from "./push-init";
import { NavBar } from "./nav-bar";

export const metadata: Metadata = {
  title: "Wallet V2 — Historical reconciliation",
  description: "A review-first historical ledger reconciliation console",
  manifest: "/manifest.json",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#10141f",
};

function ServiceWorkerRegistration() {
  return (
    <script
      dangerouslySetInnerHTML={{
        __html: `
if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  });
}
`,
      }}
    />
  );
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <a className="skip-link" href="#main-content">Skip to main content</a>
        <ServiceWorkerRegistration />
        <PushInitScript />
        <header className="app-header">
          <div className="container app-header-bar">
            <div>
              <h1>Wallet V2</h1>
              <p className="app-header-tagline">Historical reconciliation</p>
            </div>
            <div className="app-meta" role="status" aria-label="Operational status">
              <span className="chip chip-reconciliation">Statement evidence only</span>
              <span className="chip chip-muted">Canonical approval locked</span>
            </div>
          </div>
          <NavBar />
        </header>
        <main id="main-content" className="container app-main">{children}</main>
      </body>
    </html>
  );
}
