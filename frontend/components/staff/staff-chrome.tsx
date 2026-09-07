"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { ActionButton, FieldSelect } from "../ui";
import { useStaffAuth } from "../../lib/auth";
import { useConnectivity } from "../../lib/offline/connectivity";
import type { StaffRole } from "../../lib/contracts";
import {
  activeDemoPersona,
  DEMO_MODE_ENABLED,
  DEMO_PERSONAS,
  demoPersonaHome,
  type DemoPersona,
} from "../../lib/demo-personas";

type NavItem = { href: string; label: string; roles: StaffRole[] };

export function StaffChrome({ title, eyebrow, children }: { title: string; eyebrow: string; children: React.ReactNode }) {
  const { session, logout, selectLocation, demoLogin } = useStaffAuth();
  const { online, pendingCount, conflictCount } = useConnectivity();
  const router = useRouter(); const pathname = usePathname();
  const location = session?.locations.find((entry) => entry.id === session.active_location_id);
  const demoPersona = activeDemoPersona(session);
  const can = (roles: StaffRole[]) => roles.some((role) => session?.roles.includes(role));
  const links: NavItem[] = [
    { href: "/ops", label: "Service floor", roles: ["WAITER", "MANAGER"] as StaffRole[] },
    { href: "/ops/verify-reservation", label: "Reservation check-in", roles: ["WAITER", "MANAGER"] as StaffRole[] },
    { href: "/prep", label: "Kitchen & bar", roles: ["CHEF", "BARTENDER"] as StaffRole[] },
    { href: "/manage/tables", label: "Tables & QR", roles: ["WAITER", "MANAGER", "TENANT_OWNER"] as StaffRole[] },
    { href: "/manage/menu", label: "Menu", roles: ["MANAGER", "TENANT_OWNER", "CHEF", "BARTENDER"] as StaffRole[] },
    { href: "/manage/reservations", label: "Reservations", roles: ["WAITER", "MANAGER"] as StaffRole[] },
    { href: "/manage/payments", label: "Payments", roles: ["MANAGER", "TENANT_OWNER"] as StaffRole[] },
    { href: "/manage/feedback", label: "Feedback", roles: ["MANAGER"] as StaffRole[] },
    { href: "/manage/team", label: "Team", roles: ["MANAGER", "TENANT_OWNER"] as StaffRole[] },
    { href: "/manage/reports", label: "Reports", roles: ["MANAGER", "TENANT_OWNER"] as StaffRole[] },
    { href: "/manage/settings", label: "Settings", roles: ["TENANT_OWNER"] as StaffRole[] },
    { href: "/admin", label: "Platform administration", roles: ["PLATFORM_ADMIN"] as StaffRole[] },
  ].filter((link) => can(link.roles));
  async function leave() { await logout(); router.replace("/login"); }
  async function switchDemoPersona(
    persona: DemoPersona,
  ) {
    if (!persona ||persona === demoPersona) {
      return;
    }

    await demoLogin(persona);

    router.replace(
      demoPersonaHome(persona),
    );
  }

  return (
    <main className="workspace-shell">
      <aside className="workspace-sidebar" aria-label="Staff navigation">

        <header className="workspace-header">
          <Link className="wordmark" href="/">
            CHOWLY
            <span aria-hidden="true">°</span>
          </Link>

          <div className="workspace-meta">
            <b>{session?.name}</b>
            <small>{location?.name ?? "No location"}</small>
          </div>
        </header>

        <nav className="workspace-nav" aria-label="Staff workspace">
          <p>Workspace</p>

          {links.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              aria-current={pathname === link.href ? "page" : undefined}
            >
              {link.label}
              <span aria-hidden="true">→</span>
            </Link>
          ))}
        </nav>

        <section
          className="staff-context"
          aria-label="Signed-in workspace controls"
        >
          <span className={`connection-state ${online ? "" : "is-offline"}`}>
            <i className="connection-dot" />
            {online ? "Online" : "Offline"}
          </span>

          {pendingCount > 0 && (
            <span className="pill status-pending-sync">
              {pendingCount} pending sync
            </span>
          )}

          {conflictCount > 0 && (
            <span className="pill status-conflict">
              {conflictCount} conflicts
            </span>
          )}

          {DEMO_MODE_ENABLED && session && (
            <FieldSelect
              label="Demo persona"
              value={demoPersona}
              onChange={(event) =>
                void switchDemoPersona(
                  event.target.value as DemoPersona,
                )
              }
            >
              <option value="" disabled>
                Choose role
              </option>

              {DEMO_PERSONAS.map((entry) => (
                <option key={entry.id} value={entry.id}>
                  {entry.label}
                </option>
              ))}
            </FieldSelect>
          )}

          {session && session.locations.length > 1 && (
            <FieldSelect
              label="Active location"
              value={session.active_location_id ?? ""}
              onChange={(event) =>
                void selectLocation(event.target.value)
              }
            >
              <option value="" disabled>
                Select location
              </option>

              {session.locations.map((entry) => (
                <option key={entry.id} value={entry.id}>
                  {entry.name}
                </option>
              ))}
            </FieldSelect>
          )}
        </section>

        <div className="workspace-sidebar-foot">
          <Link href="/restaurants">
            Restaurant directory
          </Link>

          <ActionButton
            tone="quiet"
            onClick={() => void leave()}
          >
            Sign out
          </ActionButton>
        </div>
      </aside>

      <section className="workspace-content">
        <div className="workspace-intro">
          <p className="eyebrow">{eyebrow}</p>
          <h1>{title}</h1>
        </div>

        {children}
      </section>
    </main>
  );
}