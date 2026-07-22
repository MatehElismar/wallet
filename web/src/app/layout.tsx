import type { Metadata, Viewport } from "next";
import "./globals.css";
import { PushInitScript } from "./push-init";
import { NavBar } from "./nav-bar";

export const metadata: Metadata = {
  title: "Wallet V2 Reconciliation",
  description: "Statement reconciliation console",
  manifest: "/manifest.json",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#2563eb",
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

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>
        <ServiceWorkerRegistration />
        <PushInitScript />
        <header>
          <div className="container">
            <h1>Wallet V2</h1>
          </div>
          <NavBar />
        </header>
        <main className="container">{children}</main>
      </body>
    </html>
  );
}
