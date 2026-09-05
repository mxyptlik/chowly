import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const root = new URL("../", import.meta.url);
const moduleAt = (path) => import(new URL(path, root).href);
const source = (path) => readFile(new URL(path, root), "utf8");

test("API errors retain server detail and use a safe fallback", async () => {
  const { ApiClient, ApiError, messageFromBody } = await moduleAt("lib/api.ts");
  assert.equal(messageFromBody({ detail: "Order is already accepted." }, 409), "Order is already accepted.");
  assert.equal(messageFromBody(undefined, 503), "Chowly is temporarily unavailable. Please try again.");

  const client = new ApiClient("/api/v1", async () => { throw new TypeError("Failed to fetch"); });
  await assert.rejects(
    () => client.post("/staff/auth/login", { email: "pilot@example.test", password: "password" }),
    (error) => error instanceof ApiError && error.status === 0 && error.message.includes("Failed to fetch"),
  );
});

test("browser API client binds native fetch to its global receiver", async () => {
  const api = await source("lib/api.ts");
  assert.match(api, /fetch\.bind\(globalThis\)/);
});

test("role and location guards reject mismatched access", async () => {
  const { canAccess } = await moduleAt("lib/auth-policy.ts");
  const session = { staff_id: "staff-1", name: "Ayo", email: "ayo@example.test", roles: ["WAITER"], locations: [{ id: "location-1", tenant_id: "tenant-1", name: "VI" }] };
  assert.equal(canAccess(session, { roles: ["WAITER"], locationId: "location-1" }), true);
  assert.equal(canAccess(session, { roles: ["MANAGER"] }), false);
  assert.equal(canAccess(session, { locationId: "location-2" }), false);
});

test("realtime sequence policy deduplicates and detects gaps", async () => {
  const { nextSequence, reconnectDelay } = await moduleAt("lib/realtime-policy.ts");
  assert.deepEqual(nextSequence(4, 4), { action: "duplicate", sequence: 4 });
  assert.deepEqual(nextSequence(4, 5), { action: "accept", sequence: 5 });
  assert.deepEqual(nextSequence(4, 7), { action: "gap", sequence: 7 });
  assert.equal(reconnectDelay(0, 1000, 30000, 0.5), 1000);
  assert.equal(reconnectDelay(10, 1000, 30000, 0.5), 30000);
});

test("offline policy allowlists safe work and classifies conflicts", async () => {
  const policy = await moduleAt("lib/offline/policy.ts");
  const replay = await moduleAt("lib/offline/replay-policy.ts");
  assert.equal(policy.isSafeMutationKind("SET_WAIT_TIME"), true);
  assert.equal(policy.isSafeMutationKind("PAYMENT_CREATE"), false);
  assert.equal(replay.classifyReplayFailure(409), "CONFLICT");
  assert.equal(replay.classifyReplayFailure(412), "CONFLICT");
  assert.equal(replay.classifyReplayFailure(0), "RETRY");
});

test("public snapshot cache removes private fields", async () => {
  const { sanitizePublicSnapshot } = await moduleAt("lib/offline/db.ts");
  assert.deepEqual(sanitizePublicSnapshot({ id: "order-1", customer_phone: "080", nested: { email: "x@y.z", status: "PREPARING" } }), { id: "order-1", nested: { status: "PREPARING" } });
});

test("field associations include hint and error descriptions", async () => {
  const { fieldAccessibility } = await moduleAt("components/ui/form-policy.ts");
  assert.deepEqual(fieldAccessibility("phone", "Use Nigerian format", "Required"), { id: "phone", describedBy: "phone-hint phone-error", invalid: true });
});

test("worker never caches API responses and manifest has both icon purposes", async () => {
  const worker = await readFile(new URL("public/sw.js", root), "utf8");
  const manifest = JSON.parse(await readFile(new URL("public/manifest.json", root), "utf8"));
  assert.match(worker, /url\.pathname\.startsWith\("\/api\/"\)/);
  assert.match(worker, /request\.headers\.has\("Authorization"\)/);
  assert.doesNotMatch(worker, /cache\.put\(request, copy\)/);
  assert.equal(manifest.display, "standalone");
  assert.ok(manifest.icons.some((icon) => icon.purpose === "any"));
  assert.ok(manifest.icons.some((icon) => icon.purpose === "maskable"));
});

test("shared forms use labels, descriptions, validation, and live regions", async () => {
  const form = await readFile(new URL("components/ui/form-controls.tsx", root), "utf8");
  const feedback = await readFile(new URL("components/ui/feedback.tsx", root), "utf8");
  assert.match(form, /htmlFor=\{id\}/);
  assert.match(form, /aria-describedby=\{describedBy\}/);
  assert.match(form, /aria-invalid=\{invalid/);
  assert.match(feedback, /aria-live=\{urgent \? "assertive" : "polite"\}/);
  assert.match(feedback, /tone: NoticeTone = "success"/);
  assert.match(feedback, /4200/);
  assert.match(feedback, /Dismiss notification/);
});

test("toast styling is top-right, green for success, and fades away", async () => {
  const styles = await readFile(new URL("app/globals.css", root), "utf8");
  assert.match(styles, /\.toast-stack \{ position: fixed;[^}]*top: 1\.25rem;[^}]*right: 1\.25rem;/);
  assert.match(styles, /\.toast \{[^}]*background: #146b43;[^}]*toast-out/);
  assert.match(styles, /@keyframes toast-out/);
});

test("staff workspaces derive authority from the P02 session and list named manager choices", async () => {
  const ops = await readFile(new URL("app/ops/page.tsx", root), "utf8");
  const prep = await readFile(new URL("app/prep/page.tsx", root), "utf8");
  const auth = await readFile(new URL("lib/auth.tsx", root), "utf8");
  const api = await readFile(new URL("lib/api.ts", root), "utf8");
  for (const source of [ops, prep]) {
    assert.match(source, /useStaffAuth\(\)/);
    assert.match(source, /RequireStaffAccess/);
  }
  assert.match(ops, /\/staff\/members\?location_id=/);
  assert.match(ops, /Choose an assigned waiter/);
  assert.doesNotMatch(ops, /Waiter ID/);
  assert.doesNotMatch(ops, /Table ID/);
  assert.match(auth, /\/staff\/auth\/session/);
  assert.match(auth, /\/staff\/auth\/active-location/);
  assert.match(api, /credentials: "include"/);
});

test("a manager invitation form offers operational roles but not manager escalation", async () => {
  const management = await readFile(new URL("components/staff/management-workspaces.tsx", root), "utf8");
  assert.match(management, /const inviteRoles=owner\?\["WAITER","CHEF","BARTENDER","MANAGER"\]:\["WAITER","CHEF","BARTENDER"\]/);
});
