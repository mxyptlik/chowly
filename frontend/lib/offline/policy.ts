export const SAFE_MUTATION_ROUTES = {
  SET_WAIT_TIME: (resourceId: string) => `/staff/orders/${encodeURIComponent(resourceId)}/wait-time`,
  MARK_PREP_LINE_READY: (resourceId: string) => `/staff/lines/${encodeURIComponent(resourceId)}/ready`,
} as const;

export type SafeMutationKind = keyof typeof SAFE_MUTATION_ROUTES;

export const ONLINE_ONLY_MUTATIONS = [
  "ORDER_ACCEPT",
  "ORDER_SERVE",
  "ORDER_CANCEL",
  "ORDER_TRANSFER",
  "PAYMENT_CREATE",
  "CASH_RECORD",
  "REFUND_CREATE",
  "QR_REGENERATE",
  "COMPLAINT_RESOLVE",
] as const;

export function isSafeMutationKind(value: string): value is SafeMutationKind {
  return Object.hasOwn(SAFE_MUTATION_ROUTES, value);
}

export function routeForSafeMutation(kind: SafeMutationKind, resourceId: string) {
  return SAFE_MUTATION_ROUTES[kind](resourceId);
}
