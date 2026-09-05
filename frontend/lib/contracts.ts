export type StaffRole =
  | "PLATFORM_ADMIN"
  | "TENANT_OWNER"
  | "MANAGER"
  | "WAITER"
  | "CHEF"
  | "BARTENDER";

export type StaffLocation = {
  id: string;
  tenant_id: string;
  name: string;
};

export type StaffSession = {
  staff_id: string;
  name: string;
  email: string;
  roles: StaffRole[];
  locations: StaffLocation[];
  active_tenant_id: string | null;
  active_location_id: string | null;
};

export type ApiErrorBody = {
  detail?: string | { message?: string };
  code?: string;
  request_id?: string;
  errors?: Record<string, string[]>;
};

export type RealtimeResourceKind =
  | "order"
  | "order_line"
  | "table"
  | "menu_availability"
  | "reservation"
  | "complaint"
  | "payment"
  | "receipt";

export type RealtimeEvent<TPayload = unknown> = {
  version: "1.0";
  id: string;
  sequence: number;
  type: `${RealtimeResourceKind}.changed`;
  occurred_at: string;
  scope: { tenant_id?: string; location_id?: string; order_id?: string };
  resource: { kind: RealtimeResourceKind; id: string };
  payload: TPayload;
};

export type HeartbeatEvent = { type: "system.heartbeat"; sent_at: string };
