"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

export function NavBar() {
  const pathname = usePathname();

  const tabs = [
    { href: "/", label: "Batches" },
    { href: "/candidates", label: "Candidates" },
    { href: "/progress", label: "Progress" },
  ];

  const isActive = (href: string) => {
    if (href === "/") return pathname === "/";
    return pathname.startsWith(href);
  };

  return (
    <div className="container">
      <nav
        style={{
          display: "flex",
          gap: "0",
          marginTop: "0.5rem",
          borderBottom: "1px solid var(--border)",
        }}
      >
        {tabs.map((tab) => (
          <Link
            key={tab.href}
            href={tab.href}
            style={{
              padding: "0.5rem 1rem",
              fontSize: "0.8125rem",
              fontWeight: isActive(tab.href) ? 600 : 400,
              color: isActive(tab.href) ? "var(--accent)" : "var(--text-muted)",
              borderBottom: isActive(tab.href)
                ? "2px solid var(--accent)"
                : "2px solid transparent",
              textDecoration: "none",
              transition: "color 0.15s, border-color 0.15s",
            }}
          >
            {tab.label}
          </Link>
        ))}
      </nav>
    </div>
  );
}
