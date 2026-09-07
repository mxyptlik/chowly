import type { StaffSession } from "./contracts";

export type DemoPersona =
  | "WAITER"
  | "CHEF"
  | "BARTENDER"
  | "MANAGER"
  | "TENANT_OWNER";

export const DEMO_MODE_ENABLED =
  process.env.NEXT_PUBLIC_CHOWLY_DEMO_MODE === "true";

export const DEMO_PERSONAS: Array<{
  id: DemoPersona;
  label: string;
  eyebrow: string;
  description: string;
  home: string;
}> = [
  {
    id: "WAITER",
    label: "Waiter",
    eyebrow: "Service floor",
    description:
      "Accept orders, set wait times, serve guests and manage arrivals.",
    home: "/ops",
  },
  {
    id: "CHEF",
    label: "Chef",
    eyebrow: "Kitchen",
    description:
      "Claim kitchen lines and move food preparation to ready.",
    home: "/prep",
  },
  {
    id: "BARTENDER",
    label: "Bartender",
    eyebrow: "Bar",
    description:
      "Own drink preparation without seeing unnecessary customer data.",
    home: "/prep",
  },
  {
    id: "MANAGER",
    label: "Manager",
    eyebrow: "Operations",
    description:
      "Review service, reservations, payments, complaints and reports.",
    home: "/manage/reports",
  },
  {
    id: "TENANT_OWNER",
    label: "Restaurant owner",
    eyebrow: "Governance",
    description:
      "Manage restaurant policy, team access, settings and reporting.",
    home: "/manage/settings",
  },
];

export function demoPersonaHome(persona: DemoPersona) {
  return (
    DEMO_PERSONAS.find((entry) => entry.id === persona)?.home ??
    "/ops"
  );
}

export function defaultStaffHome(session: StaffSession) {
  if (
    session.roles.includes("PLATFORM_ADMIN") ||
    session.roles.includes("TENANT_OWNER")
  ) {
    return "/admin";
  }

  if (
    session.roles.includes("CHEF") ||
    session.roles.includes("BARTENDER")
  ) {
    return "/prep";
  }

  return "/ops";
}

export function activeDemoPersona(
  session: StaffSession | null,
): DemoPersona | "" {
  if (!session) return "";

  return (
    DEMO_PERSONAS.find((entry) =>
      session.roles.includes(entry.id),
    )?.id ?? ""
  );
}