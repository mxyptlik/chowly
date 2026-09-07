export type ModifierOption = { id: string; name: string; final_price_delta: number; available: boolean };

export type ModifierGroup = {
  id: string;
  name: string;
  minimum_selections: number;
  maximum_selections: number;
  options: ModifierOption[];
};

export type MenuItem = {
  id: string;
  name: string;
  description: string;
  category: { id: string; name: string };
  item_type: "FOOD" | "DRINK";
  final_base_price: number;
  available: boolean;
  sold_out_reason?: string | null;
  modifier_groups: ModifierGroup[];
};

export type PublicMenu = {
  table_id: string;
  table_label: string;
  location_id: string;
  location_name: string;
  currency: string;
  currently_open: boolean;
  manual_ordering_open: boolean;
  charge_disclosure: string;
  menu: MenuItem[];
};

export type PublicLine = {
  id: string;
  item_name: string;
  quantity: number;
  modifiers: { id: string; name: string; price_delta: number }[];
  special_instruction?: string | null;
  total_amount: number;
};

export type PublicOrder = {
  id: string;
  status: string;
  diner_status: string;
  service_mode: "DINE_IN" | "TAKEAWAY";
  table_label?: string | null;
  transfer_notice?: string | null;
  cancellation_reason?: string | null;
  estimated_wait_minutes?: number | null;
  delay_reason?: string | null;
  delayed_at?: string | null;
  total_amount: number;
  currency: string;
  version: string;
  lines: PublicLine[];
  cancelled_at?: string | null;
};

export type OrderCapability = { orderId: string; accessToken: string; realtimeToken?: string };

const capabilityKey = (orderId: string) => `chowly:order-capability:${orderId}`;

export function saveOrderCapability(capability: OrderCapability) {
  sessionStorage.setItem(capabilityKey(capability.orderId), JSON.stringify(capability));
}

export function loadOrderCapability(orderId: string): OrderCapability | null {
  try {
    const raw = sessionStorage.getItem(capabilityKey(orderId));
    if (!raw) return null;
    const item = JSON.parse(raw) as OrderCapability;
    return item.orderId === orderId && item.accessToken ? item : null;
  } catch {
    return null;
  }
}

export function money(value: number | string, currency = "NGN") {
  return new Intl.NumberFormat("en-NG", { style: "currency", currency, maximumFractionDigits: 0 }).format(Number(value));
}

export function newIdempotencyKey() {
  return globalThis.crypto?.randomUUID?.() ?? `web-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}
