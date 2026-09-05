import type { StaffRole, StaffSession } from "./contracts";

export type AccessRequirement = {
  roles?: StaffRole[];
  tenantId?: string;
  locationId?: string;
};

export function canAccess(session: StaffSession | null, requirement: AccessRequirement = {}) {
  if (!session) return false;
  if (requirement.roles?.length && !requirement.roles.some((role) => session.roles.includes(role))) return false;
  if (requirement.tenantId) {
    const hasTenant = session.locations.some((location) => location.tenant_id === requirement.tenantId);
    if (!hasTenant && !session.roles.includes("PLATFORM_ADMIN")) return false;
  }
  if (requirement.locationId && !session.locations.some((location) => location.id === requirement.locationId)) return false;
  return true;
}

export function resolveActiveLocation(session: StaffSession | null) {
  if (!session) return undefined;
  return session.locations.find((location) => location.id === session.active_location_id) ?? session.locations[0];
}
