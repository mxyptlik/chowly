/**
 * Browser proof for service-workspace corrections. It keeps IDs, capabilities,
 * cookies, and test phone numbers in memory; the result file contains only
 * scenario names and outcomes.
 */
import { chromium } from "@playwright/test";
import { mkdir, writeFile } from "node:fs/promises";
import { resolve } from "node:path";

const base = "http://localhost:3000";
const password = "ChowlyDemo!2026";
const evidence = resolve(import.meta.dirname, "../../docs/verification/screenshots/13-service-corrections");
const resultPath = resolve(import.meta.dirname, "../../docs/verification/service-corrections-results.json");
const results = { executed_at: new Date().toISOString(), cases: [] };

await mkdir(evidence, { recursive: true });

function verify(value, detail) {
  if (!value) throw new Error(detail);
}

async function login(browser, email, options = {}) {
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 }, colorScheme: "dark", ...options });
  const page = await context.newPage();
  page.setDefaultTimeout(20_000);
  await page.goto(`${base}/login`, { waitUntil: "domcontentloaded" });
  await page.getByLabel("Work email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: /sign in to chowly/i }).click();
  await page.waitForURL(/\/(ops|prep|manage|admin)/, { timeout: 20_000 });
  return { context, page };
}

async function responseJson(page, path, options = {}) {
  return page.evaluate(async ({ path, options }) => {
    const response = await fetch(path, options);
    const body = await response.json().catch(() => null);
    return { status: response.status, body };
  }, { path, options });
}

async function createManualOrder(page, label, { manager = false } = {}) {
  await page.goto(`${base}/ops`, { waitUntil: "domcontentloaded" });
  await page.getByRole("button", { name: "Create manual order" }).click();
  await page.getByLabel("Customer name").waitFor();
  await page.getByLabel("Customer name").fill(label);
  await page.getByLabel("Customer phone").fill(`080${String(Date.now()).slice(-8)}`);
  if (manager) {
    const waiter = page.getByLabel("Assigned waiter");
    await waiter.waitFor();
    await waiter.locator("option").nth(1).waitFor({ state: "attached" });
    verify(await waiter.locator("option").count() > 1, "Manager manual order has no assigned waiter choice.");
    await waiter.selectOption({ index: 1 });
  }
  const table = page.getByLabel("Table");
  await table.waitFor();
  await table.locator("option").nth(1).waitFor({ state: "attached" });
  verify(await table.locator("option").count() > 1, "Manual order has no active table choice.");
  await table.selectOption({ index: 1 });
  const card = page.locator(".manual-menu .store-card").first();
  await card.waitFor();
  await card.locator(".store-card-hit").click();
  await page.getByRole("dialog").getByRole("button", { name: /Add to order/ }).click();
  const created = page.waitForResponse((response) => response.url().includes("/api/v1/staff/orders/manual") && response.request().method() === "POST");
  await page.getByRole("button", { name: /Create order/ }).click();
  const response = await created;
  verify(response.status() === 201, `Manual order returned ${response.status()} instead of 201.`);
  const order = await response.json();
  verify(order?.id && order?.lines?.[0]?.id, "Manual order response did not contain an order and line.");
  await page.getByText("Manual order created and accepted. It is now in preparation.").waitFor();
  return { id: order.id, lineId: order.lines[0].id, queueDestination: order.lines[0].queue_destination, label };
}

async function claimFirstLine(browser, order) {
  const email = order.queueDestination === "BAR" ? "pilot1.bartender@demo.chowly.ng" : "pilot1.chef@demo.chowly.ng";
  const { context, page } = await login(browser, email);
  try {
    const prep = await responseJson(page, "/api/v1/staff/prep");
    const line = Array.isArray(prep.body) ? prep.body.find((entry) => entry.order_id === order.id && entry.line_id === order.lineId) : null;
    verify(prep.status === 200 && line, "The manual order did not reach its expected preparation queue.");
    const claimed = await responseJson(page, `/api/v1/staff/lines/${encodeURIComponent(order.lineId)}/claim`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ expected_version: line.order_version }),
    });
    verify(claimed.status === 200, `Preparation claim returned ${claimed.status}.`);
  } finally {
    await context.close();
  }
}

async function assertRoleGuards(browser) {
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 }, colorScheme: "dark" });
  const page = await context.newPage();
  page.setDefaultTimeout(20_000);
  try {
    await page.goto(`${base}/ops/verify-reservation`, { waitUntil: "domcontentloaded" });
    await page.getByText("Reservation check-in restricted").waitFor();
    verify(await page.getByRole("button", { name: "Use camera" }).count() === 0, "Anonymous visitor can see the reservation scanner.");
    await page.goto(`${base}/admin`, { waitUntil: "domcontentloaded" });
    await page.getByText("Platform administration restricted").waitFor();
    verify(await page.getByRole("tablist").count() === 0, "Anonymous visitor can see platform administration tabs.");
    results.cases.push({ name: "anonymous direct staff routes are client-gated", pass: true });
  } finally {
    await context.close();
  }
}

async function assertScannerLifecycle(browser) {
  const { context, page } = await login(browser, "pilot1.waiter@demo.chowly.ng");
  try {
    await page.addInitScript(() => {
      window.__chowlyCameraStops = 0;
      window.BarcodeDetector = class { async detect() { return []; } };
      const stream = new MediaStream();
      Object.defineProperty(stream, "getTracks", { value: () => [{ stop: () => { window.__chowlyCameraStops += 1; } }] });
      Object.defineProperty(navigator.mediaDevices, "getUserMedia", { configurable: true, value: async () => stream });
      HTMLMediaElement.prototype.play = () => Promise.resolve();
    });
    await page.goto(`${base}/ops/verify-reservation`, { waitUntil: "domcontentloaded" });
    await page.getByRole("button", { name: "Use camera" }).click();
    const camera = page.getByLabel("Camera view for reservation QR scanning");
    await camera.waitFor();
    await page.screenshot({ path: resolve(evidence, "04-reservation-camera-started.png"), fullPage: true });
    await page.getByRole("button", { name: "Stop camera" }).click();
    await page.waitForFunction(() => window.__chowlyCameraStops === 1);
    results.cases.push({ name: "reservation camera mounts before stream and stops tracks cleanly", pass: true });
  } finally {
    await context.close();
  }
}

const browser = await chromium.launch({ headless: true });
try {
  await assertRoleGuards(browser);

  const { context: managerContext, page: manager } = await login(browser, "pilot1.manager@demo.chowly.ng");
  await createManualOrder(manager, `Manager manual ${Date.now()}`, { manager: true });
  await manager.screenshot({ path: resolve(evidence, "01-manager-manual-order.png"), fullPage: true });
  results.cases.push({ name: "manager creates a manual order through named waiter and table choices", pass: true });

  const { context: waiterContext, page: waiter } = await login(browser, "pilot1.waiter@demo.chowly.ng");
  const amendmentOrder = await createManualOrder(waiter, `Waiter amendment ${Date.now()}`);
  const amendmentCard = waiter.locator(".order-card").filter({ hasText: amendmentOrder.label }).first();
  await amendmentCard.waitFor();
  await amendmentCard.click();
  waiter.once("dialog", (dialog) => dialog.accept("2"));
  const [amendment] = await Promise.all([
    waiter.waitForResponse((response) => response.url().includes(`/api/v1/staff/orders/${encodeURIComponent(amendmentOrder.id)}/lines/${encodeURIComponent(amendmentOrder.lineId)}`) && response.request().method() === "PATCH"),
    waiter.getByRole("button", { name: "Amend", exact: true }).click(),
  ]);
  verify(amendment.status() === 200, "Waiter amendment did not use the successful PATCH contract.");
  await waiter.getByText("Line amendment confirmed.").waitFor();
  await waiter.screenshot({ path: resolve(evidence, "02-waiter-amendment.png"), fullPage: true });
  results.cases.push({ name: "waiter amendment uses PATCH and updates an accepted line", pass: true });

  const cancellationOrder = await createManualOrder(waiter, `Manager line cancellation ${Date.now()}`);
  await claimFirstLine(browser, cancellationOrder);
  await manager.goto(`${base}/ops`, { waitUntil: "domcontentloaded" });
  const cancellationCard = manager.locator(".order-card").filter({ hasText: cancellationOrder.label }).first();
  await cancellationCard.waitFor();
  await cancellationCard.click();
  await manager.getByLabel("Reason (transfer or cancellation)").fill("Controlled manager line cancellation");
  manager.once("dialog", (dialog) => dialog.accept());
  const [cancellation] = await Promise.all([
    manager.waitForResponse((response) => response.url().includes(`/api/v1/staff/orders/${encodeURIComponent(cancellationOrder.id)}/lines/${encodeURIComponent(cancellationOrder.lineId)}`) && response.request().method() === "PATCH"),
    manager.getByRole("button", { name: "Cancel line", exact: true }).click(),
  ]);
  verify(cancellation.status() === 200, "Manager cancellation of claimed line did not succeed.");
  await manager.getByText("Line cancellation confirmed.").waitFor();
  await manager.screenshot({ path: resolve(evidence, "03-manager-claimed-line-cancelled.png"), fullPage: true });
  results.cases.push({ name: "manager cancels a claimed preparation line with an audited reason", pass: true });

  await managerContext.close();
  await waiterContext.close();
  await assertScannerLifecycle(browser);

  const { context: chefContext, page: chef } = await login(browser, "pilot1.chef@demo.chowly.ng");
  await chef.goto(`${base}/manage/menu`, { waitUntil: "domcontentloaded" });
  await chef.getByRole("heading", { name: "Kitchen menu" }).waitFor();
  verify(await chef.getByRole("button", { name: "Drinks" }).count() === 0, "Chef can switch to the bar inventory UI.");
  await chef.screenshot({ path: resolve(evidence, "05-chef-kitchen-menu.png"), fullPage: true });
  await chefContext.close();

  const { context: bartenderContext, page: bartender } = await login(browser, "pilot1.bartender@demo.chowly.ng");
  await bartender.goto(`${base}/manage/menu`, { waitUntil: "domcontentloaded" });
  await bartender.getByRole("heading", { name: "Bar menu" }).waitFor();
  verify(await bartender.getByRole("button", { name: "Food" }).count() === 0, "Bartender can switch to the kitchen inventory UI.");
  await bartender.screenshot({ path: resolve(evidence, "06-bartender-bar-menu.png"), fullPage: true });
  await bartenderContext.close();
  results.cases.push({ name: "chef and bartender see only their station inventory workspace", pass: true });

  const { context: ownerContext, page: owner } = await login(browser, "pilot1.tenant_owner@demo.chowly.ng");
  await owner.goto(`${base}/manage/payments`, { waitUntil: "domcontentloaded" });
  await owner.getByText("Settlement details are read-only for tenant owners.").waitFor();
  verify(await owner.getByRole("button", { name: "Issue full refund" }).count() === 0, "Tenant owner sees the manager-only refund action.");
  await owner.goto(`${base}/manage/feedback`, { waitUntil: "domcontentloaded" });
  await owner.getByText("You do not have access to this workspace.").waitFor();
  results.cases.push({ name: "tenant owner sees settlement read-only and no manager-only feedback", pass: true });
  await ownerContext.close();
} catch (error) {
  results.error = error instanceof Error ? error.message : String(error);
} finally {
  await browser.close();
  await writeFile(resultPath, `${JSON.stringify(results, null, 2)}\n`);
}

console.log(JSON.stringify(results, null, 2));
if (results.error || results.cases.some((entry) => !entry.pass)) process.exitCode = 1;
