export function classifyReplayFailure(status: number) {
  return status === 409 || status === 412 ? "CONFLICT" as const : "RETRY" as const;
}
