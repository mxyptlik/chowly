import type { SafeMutationKind } from "./policy";

const DB_NAME = "chowly-web";
const DB_VERSION = 1;
const SNAPSHOTS = "snapshots";
const OUTBOX = "outbox";

export type SnapshotKind = "PUBLIC_MENU" | "PUBLIC_ORDER";
export type CachedSnapshot<T = unknown> = {
  key: string;
  kind: SnapshotKind;
  data: T;
  cachedAt: string;
  expiresAt: string;
};

export type OutboxItem = {
  id: string;
  idempotencyKey: string;
  kind: SafeMutationKind;
  resourceId: string;
  payload: Record<string, unknown>;
  state: "PENDING" | "SYNCING" | "CONFLICT";
  attempts: number;
  createdAt: string;
  lastError?: string;
};

function requestResult<T>(request: IDBRequest<T>) {
  return new Promise<T>((resolve, reject) => {
    request.addEventListener("success", () => resolve(request.result));
    request.addEventListener("error", () => reject(request.error));
  });
}

function transactionDone(transaction: IDBTransaction) {
  return new Promise<void>((resolve, reject) => {
    transaction.addEventListener("complete", () => resolve());
    transaction.addEventListener("abort", () => reject(transaction.error));
    transaction.addEventListener("error", () => reject(transaction.error));
  });
}

function openDatabase() {
  if (!("indexedDB" in globalThis)) return Promise.reject(new Error("IndexedDB is unavailable."));
  const request = indexedDB.open(DB_NAME, DB_VERSION);
  request.addEventListener("upgradeneeded", () => {
    const database = request.result;
    if (!database.objectStoreNames.contains(SNAPSHOTS)) database.createObjectStore(SNAPSHOTS, { keyPath: "key" });
    if (!database.objectStoreNames.contains(OUTBOX)) {
      const outbox = database.createObjectStore(OUTBOX, { keyPath: "id" });
      outbox.createIndex("state", "state");
      outbox.createIndex("createdAt", "createdAt");
    }
  });
  return requestResult(request);
}

const PRIVATE_KEYS = new Set(["customer_name", "customer_phone", "customer_email", "phone", "email", "access_token"]);

export function sanitizePublicSnapshot(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(sanitizePublicSnapshot);
  if (!value || typeof value !== "object") return value;
  return Object.fromEntries(
    Object.entries(value as Record<string, unknown>)
      .filter(([key]) => !PRIVATE_KEYS.has(key.toLowerCase()))
      .map(([key, item]) => [key, sanitizePublicSnapshot(item)]),
  );
}

export async function putSnapshot<T>(snapshot: CachedSnapshot<T>) {
  const database = await openDatabase();
  const transaction = database.transaction(SNAPSHOTS, "readwrite");
  transaction.objectStore(SNAPSHOTS).put({ ...snapshot, data: sanitizePublicSnapshot(snapshot.data) });
  await transactionDone(transaction);
  database.close();
}

export async function getSnapshot<T>(key: string): Promise<CachedSnapshot<T> | undefined> {
  const database = await openDatabase();
  const transaction = database.transaction(SNAPSHOTS, "readonly");
  const snapshot = await requestResult(transaction.objectStore(SNAPSHOTS).get(key)) as CachedSnapshot<T> | undefined;
  await transactionDone(transaction);
  database.close();
  if (!snapshot || Date.parse(snapshot.expiresAt) <= Date.now()) return undefined;
  return snapshot;
}

export async function putOutboxItem(item: OutboxItem) {
  const database = await openDatabase();
  const transaction = database.transaction(OUTBOX, "readwrite");
  transaction.objectStore(OUTBOX).put(item);
  await transactionDone(transaction);
  database.close();
}

export async function listOutboxItems() {
  const database = await openDatabase();
  const transaction = database.transaction(OUTBOX, "readonly");
  const items = await requestResult(transaction.objectStore(OUTBOX).getAll()) as OutboxItem[];
  await transactionDone(transaction);
  database.close();
  return items.sort((left, right) => left.createdAt.localeCompare(right.createdAt));
}

export async function deleteOutboxItem(id: string) {
  const database = await openDatabase();
  const transaction = database.transaction(OUTBOX, "readwrite");
  transaction.objectStore(OUTBOX).delete(id);
  await transactionDone(transaction);
  database.close();
}
