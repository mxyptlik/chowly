"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { StaffRole } from "../lib/contracts";

export type ShellLink = { href: string; label: string; roles?: StaffRole[] };

export function AppShell({
  eyebrow,
  title,
  meta,
  links = [],
  roles = [],
  children,
}: {
  eyebrow: string;
  title: string;
  meta?: React.ReactNode;
  links?: ShellLink[];
  roles?: StaffRole[];
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  const available = links.filter((link) => !link.roles?.length || link.roles.some((role) => roles.includes(role)));
  return (
    <div className="workspace-shell">
      <header className="workspace-header">
        <Link href="/" className="wordmark" aria-label="Chowly home">CHOWLY<span aria-hidden="true">°</span></Link>
        {meta && <div className="workspace-meta">{meta}</div>}
      </header>
      {available.length > 0 && <nav className="workspace-nav" aria-label="Workspace">
        {available.map((link) => <Link key={link.href} href={link.href} aria-current={pathname === link.href ? "page" : undefined}>{link.label}</Link>)}
      </nav>}
      <div className="workspace-intro">
        <p className="eyebrow">{eyebrow}</p>
        <h1>{title}</h1>
      </div>
      {children}
    </div>
  );
}
