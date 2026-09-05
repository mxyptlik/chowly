import { ApiError, type ApiClient } from "../api";
import { deleteOutboxItem, listOutboxItems, putOutboxItem, type OutboxItem } from "./db";
import { isSafeMutationKind, routeForSafeMutation, type SafeMutationKind } from "./policy";
import { classifyReplayFailure } from "./replay-policy";

export type OutboxStore = {
  list: () => Promise<OutboxItem[]>;
  put: (item: OutboxItem) => Promise<void>;
  delete: (id: string) => Promise<void>;
};

export const indexedDbOutbox: OutboxStore = {
  list: listOutboxItems,
  put: putOutboxItem,
  delete: deleteOutboxItem,
};

export function createOutboxItem(input: {
  kind: SafeMutationKind;
  resourceId: string;
  payload: Record<string, unknown>;
}) {
  if (!isSafeMutationKind(input.kind)) throw new Error("This action must be confirmed online and cannot be queued.");
  const id = globalThis.crypto.randomUUID();
  return {
    ...input,
    id,
    idempotencyKey: globalThis.crypto.randomUUID(),
    state: "PENDING" as const,
    attempts: 0,
    createdAt: new Date().toISOString(),
  };
}

export async function queueSafeMutation(store: OutboxStore, input: Parameters<typeof createOutboxItem>[0]) {
  const item = createOutboxItem(input);
  await store.put(item);
  return item;
}

export async function replayOutbox(store: OutboxStore, client: ApiClient) {
  const results: { id: string; state: "SYNCED" | "PENDING" | "CONFLICT" }[] = [];
  for (const item of await store.list()) {
    if (item.state === "CONFLICT") continue;
    const syncing = { ...item, state: "SYNCING" as const, attempts: item.attempts + 1 };
    await store.put(syncing);
    try {
      await client.post(routeForSafeMutation(item.kind, item.resourceId), item.payload, {
        headers: { "Idempotency-Key": item.idempotencyKey },
      });
      await store.delete(item.id);
      results.push({ id: item.id, state: "SYNCED" });
    } catch (reason) {
      const failure = classifyReplayFailure(reason instanceof ApiError ? reason.status : 0);
      const updated: OutboxItem = {
        ...syncing,
        state: failure === "CONFLICT" ? "CONFLICT" : "PENDING",
        lastError: reason instanceof Error ? reason.message : "Sync failed",
      };
      await store.put(updated);
      results.push({ id: item.id, state: failure === "CONFLICT" ? "CONFLICT" : "PENDING" });
      if (failure !== "CONFLICT") break;
    }
  }
  return results;
}
