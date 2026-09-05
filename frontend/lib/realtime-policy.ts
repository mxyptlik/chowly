export function reconnectDelay(attempt: number, minimum = 750, maximum = 30000, jitter = Math.random()) {
  const exponential = Math.min(maximum, minimum * 2 ** Math.max(0, attempt));
  return Math.round(exponential * (0.8 + jitter * 0.4));
}

export function nextSequence(current: number, incoming: number) {
  if (incoming <= current) return { action: "duplicate" as const, sequence: current };
  if (incoming > current + 1) return { action: "gap" as const, sequence: incoming };
  return { action: "accept" as const, sequence: incoming };
}
