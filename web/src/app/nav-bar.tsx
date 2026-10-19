"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const tabs = [
  { href: "/", label: "Runs" },
  { href: "/review", label: "Review" },
  { href: "/evidence", label: "Evidence" },
  { href: "/accounts", label: "Accounts" },
  { href: "/activity", label: "Activity" },
] as const;

export function NavBar() {
  const pathname = usePathname();
  const isActive = (href: string) =>
    href === "/" ? pathname === "/" : pathname === href || pathname.startsWith(`${href}/`);

  return (
    <nav className="container nav-tabs" aria-label="Primary navigation">
        {tabs.map((tab) => (
          <Link
            key={tab.href}
            href={tab.href}
            className="nav-tab"
            aria-current={isActive(tab.href) ? "page" : undefined}
          >
            {tab.label}
          </Link>
        ))}
    </nav>
  );
}
