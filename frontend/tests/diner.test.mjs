import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const root = new URL("../", import.meta.url);
const source = (path) => readFile(new URL(path, root), "utf8");

test("diner QR flow uses all-in prices, structured modifiers, instructions, and required contact fields", async () => {
  const menu = await source("components/diner/diner-menu.tsx");
  assert.match(menu, /final_base_price/);
  assert.match(menu, /final_price_delta/);
  assert.match(menu, /modifier_option_ids/);
  assert.match(menu, /special_instruction/);
  assert.match(menu, /autoComplete="name"/);
  assert.match(menu, /inputMode="tel"/);
  assert.match(menu, /No account or sign-in is created/);
  assert.match(menu, /!item\.available/);
});

test("diner order capability stays browser-local and public changes use its header", async () => {
  const contracts = await source("components/diner/contracts.ts");
  const journey = await source("components/diner/order-journey.tsx");
  assert.match(contracts, /sessionStorage/);
  assert.match(contracts, /accessToken/);
  assert.match(journey, /X-Order-Access-Token/);
  assert.match(journey, /publicOrderRealtimeUrl/);
  assert.match(journey, /This change needs a live connection/);
  assert.match(journey, /expected_version/);
  assert.match(journey, /cancellation_reason/);
});

test("restaurant discovery offers a standalone browse-only menu while QR keeps table-scoped ordering", async () => {
  const menu = await source("components/public/public-menu.tsx");
  const location = await source("components/public/public-restaurant.tsx");
  const dine = await source("components/diner/diner-menu.tsx");
  assert.match(menu, /Browse what is being served/);
  assert.doesNotMatch(menu, /\/orders/);
  assert.match(location, /\/menu/);
  assert.match(dine, /public\/tables\/\$\{encodeURIComponent\(code\)\}\/orders/);
});

test("diner journey gates online payment and feedback by service, with receipt and retry UI", async () => {
  const journey = await source("components/diner/order-journey.tsx");
  assert.match(journey, /shownStatus === "SERVED"/);
  assert.match(journey, /Idempotency-Key/);
  assert.match(journey, /Test declined retry/);
  assert.match(journey, /public\/orders\/\$\{orderId\}\/receipt/);
  assert.match(journey, /ratings\/\$\{kind/);
  assert.match(journey, /complaints/);
  assert.match(journey, /privately to the manager/);
});

test("reservation request stores only its opaque status capability and never renders contact in status", async () => {
  const reservation = await source("components/diner/reservation-form.tsx");
  assert.match(reservation, /reservation-access-token/);
  assert.match(reservation, /\/public\/reservations\/status/);
  assert.match(reservation, /autoComplete="tel"/);
  assert.match(reservation, /type Status = \{ id: string; status: string; requested_at: string \}/);
});
