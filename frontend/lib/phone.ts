/** Keep customer phone fields friendly without pretending to validate a number client-side. */
export function sanitizePhoneInput(value: string): string {
  const allowed = value.replace(/[^\d+()\s-]/g, "");
  return allowed.replace(/(?!^)\+/g, "");
}
