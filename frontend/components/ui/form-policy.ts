export function fieldAccessibility(id: string, hint?: string, error?: string) {
  const describedBy = [hint ? `${id}-hint` : undefined, error ? `${id}-error` : undefined].filter(Boolean).join(" ") || undefined;
  return { id, describedBy, invalid: Boolean(error) };
}
