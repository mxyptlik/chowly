/**
 * Browser proof for the customer payment/feedback paths that are not covered
 * by the primary diner-to-service lifecycle capture.  It deliberately writes
 * only method/outcome metadata: no session cookie, order capability, phone,
 * or invitation token is persisted in its result/evidence.
 */
import { chromium } from "@playwright/test";
import { mkdir, writeFile } from "node:fs/promises";
import { resolve } from "node:path";

const base = "http://localhost:3000";
const password = "ChowlyDemo!2026";
const evidence = resolve(import.meta.dirname, "../../docs/verification/screenshots/12-payments-feedback");
const resultPath = resolve(import.meta.dirname, "../../docs/verification/payments-feedback-results.json");
const results = { executed_at: new Date().toISOString(), cases: [] };

await mkdir(evidence, { recursive: true });

async function login(browser, email) {
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 }, colorScheme: "dark" });
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

async function dailyMenuUrl(manager) {
  await manager.goto(`${base}/manage/tables`, { waitUntil: "domcontentloaded" });
  await manager.getByRole("button", { name: "Show QR" }).first().click();
  const link = manager.getByRole("link", { name: "Open menu" });
  await link.waitFor();
  const href = await link.getAttribute("href");
  if (!href) throw new Error("The rendered table QR has no public menu URL.");
  return new URL(href, base).toString();
}

async function createDinerOrder(browser, menuUrl, label) {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, colorScheme: "dark" });
  const page = await context.newPage();
  page.setDefaultTimeout(20_000);
  await page.goto(menuUrl, { waitUntil: "domcontentloaded" });
  const card = page.locator(".store-card").filter({ hasText: "Yaji Chicken Suya" }).first();
  const chosen = await card.count() ? card : page.locator(".store-card").first();
  await chosen.locator(".store-card-hit").click();
  await page.getByRole("button", { name: /add to this order/i }).click();
  await page.getByRole("button", { name: /open order, 1 items/i }).click();
  await page.getByLabel("Your name").fill(label);
  await page.getByLabel("Phone number").fill(`080${String(Date.now()).slice(-8)}`);
  await page.getByRole("button", { name: "Send for staff acceptance" }).click();
  await page.waitForURL("**/order/*", { timeout: 20_000 });
  const orderId = new URL(page.url()).pathname.split("/").pop();
  if (!orderId) throw new Error("The diner order route had no order ID.");
  await page.getByText("Order sent.").waitFor();
  return { context, page, orderId, label };
}

async function serveOrder({ waiter, browser, orderId }) {
  const queued = await responseJson(waiter, "/api/v1/staff/orders");
  const order = Array.isArray(queued.body) ? queued.body.find((entry) => entry.id === orderId) : null;
  if (queued.status !== 200 || !order) throw new Error("Waiter could not find the newly submitted order.");
  const accepted = await responseJson(waiter, `/api/v1/staff/orders/${encodeURIComponent(orderId)}/accept`, {
    method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ estimated_wait_minutes: 15, expected_version: order.version }),
  });
  if (accepted.status !== 200) throw new Error(`Waiter acceptance failed (${accepted.status}).`);

  const destination = accepted.body?.lines?.[0]?.queue_destination;
  if (destination !== "KITCHEN" && destination !== "BAR") throw new Error("The accepted order has no recognized preparation destination.");
  const stationEmail = destination === "BAR" ? "pilot1.bartender@demo.chowly.ng" : "pilot1.chef@demo.chowly.ng";
  const { context: prepContext, page: prep } = await login(browser, stationEmail);
  try {
    const prepList = await responseJson(prep, "/api/v1/staff/prep");
    const line = Array.isArray(prepList.body) ? prepList.body.find((entry) => entry.order_id === orderId) : null;
    if (prepList.status !== 200 || !line) throw new Error("The accepted order did not reach the correct preparation queue.");
    const claimed = await responseJson(prep, `/api/v1/staff/lines/${encodeURIComponent(line.line_id)}/claim`, {
      method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ expected_version: line.order_version }),
    });
    if (claimed.status !== 200) throw new Error(`Station claim failed (${claimed.status}).`);
    const refreshed = await responseJson(prep, "/api/v1/staff/prep");
    const claimedLine = Array.isArray(refreshed.body) ? refreshed.body.find((entry) => entry.line_id === line.line_id) : null;
    if (!claimedLine) throw new Error("Claimed preparation line vanished.");
    const ready = await responseJson(prep, `/api/v1/staff/lines/${encodeURIComponent(line.line_id)}/ready`, {
      method: "POST", headers: { "content-type": "application/json", "Idempotency-Key": crypto.randomUUID() }, body: JSON.stringify({ expected_version: claimedLine.order_version }),
    });
    if (ready.status !== 200) throw new Error(`Station ready action failed (${ready.status}).`);
  } finally {
    await prepContext.close();
  }

  const readyList = await responseJson(waiter, "/api/v1/staff/orders");
  const readyOrder = Array.isArray(readyList.body) ? readyList.body.find((entry) => entry.id === orderId) : null;
  if (!readyOrder || readyOrder.status !== "READY_FOR_SERVICE") throw new Error("Order did not aggregate to READY_FOR_SERVICE.");
  const served = await responseJson(waiter, `/api/v1/staff/orders/${encodeURIComponent(orderId)}/serve`, {
    method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ expected_version: readyOrder.version }),
  });
  if (served.status !== 200) throw new Error(`Waiter service failed (${served.status}).`);
}

async function waitForDinerStatus(diner, buttonName) {
  await diner.getByRole("button", { name: buttonName }).waitFor({ timeout: 15_000 }).catch(async () => {
    await diner.reload({ waitUntil: "domcontentloaded" });
    await diner.getByRole("button", { name: buttonName }).waitFor({ timeout: 15_000 });
  });
}

const browser = await chromium.launch({ headless: true });
try {
  const { context: managerContext, page: manager } = await login(browser, "pilot1.manager@demo.chowly.ng");
  const { context: waiterContext, page: waiter } = await login(browser, "pilot1.waiter@demo.chowly.ng");
  const menuUrl = await dailyMenuUrl(manager);

  const card = await createDinerOrder(browser, menuUrl, `Payment feedback ${Date.now()}`);
  await serveOrder({ waiter, browser, orderId: card.orderId });
  await waitForDinerStatus(card.page, "Pay by card");
  await card.page.getByRole("button", { name: "Test declined retry" }).click();
  await card.page.getByText(/declined|not approved/i).waitFor();
  await card.page.getByRole("button", { name: "Pay by card" }).click();
  await card.page.getByText("Mock payment confirmed. Your receipt is ready.").waitFor();
  await card.page.getByText("Digital receipt").waitFor();
  await card.page.screenshot({ path: resolve(evidence, "01-card-declined-retry-and-receipt.png"), fullPage: true });
  results.cases.push({ name: "diner declined-card retry then successful card receipt", pass: true });

  await card.page.getByRole("button", { name: /Rate .* 1 out of 5/ }).first().click();
  await card.page.getByLabel("What went wrong?").fill("Automated meal-quality feedback");
  await card.page.getByLabel("Tell the manager privately").fill("Controlled browser verification of the complaint workflow.");
  await card.page.getByRole("button", { name: "Send private complaint" }).click();
  await card.page.getByText("Your complaint was sent privately to the manager.").waitFor();
  results.cases.push({ name: "diner low rating creates private complaint", pass: true });
  await card.context.close();

  await manager.goto(`${base}/manage/feedback`, { waitUntil: "domcontentloaded" });
  await manager.getByLabel("Resolution note").fill("Resolved in controlled browser verification.");
  const complaint = manager.locator("article.admin-row").filter({ hasText: "Automated meal-quality feedback" }).first();
  await complaint.getByRole("button", { name: "Resolve" }).click();
  await manager.getByText("Complaint resolved.").waitFor();
  await manager.screenshot({ path: resolve(evidence, "02-manager-complaint-resolved.png"), fullPage: true });
  results.cases.push({ name: "manager resolves customer complaint", pass: true });

  for (const [method, buttonName, screenshot] of [
    ["TRANSFER", "Bank transfer", "03-bank-transfer-receipt.png"],
    ["WALLET", "Wallet", "04-wallet-receipt.png"],
  ]) {
    const diner = await createDinerOrder(browser, menuUrl, `Payment ${method} ${Date.now()}`);
    await serveOrder({ waiter, browser, orderId: diner.orderId });
    await waitForDinerStatus(diner.page, buttonName);
    await diner.page.getByRole("button", { name: buttonName }).click();
    await diner.page.getByText("Mock payment confirmed. Your receipt is ready.").waitFor();
    await diner.page.screenshot({ path: resolve(evidence, screenshot), fullPage: true });
    results.cases.push({ name: `diner ${method.toLowerCase()} payment and receipt`, pass: true });
    await diner.context.close();
  }

  const cash = await createDinerOrder(browser, menuUrl, `Cash payment ${Date.now()}`);
  await serveOrder({ waiter, browser, orderId: cash.orderId });
  await waiter.goto(`${base}/ops`, { waitUntil: "domcontentloaded" });
  const cashOrder = waiter.locator(".order-card").filter({ hasText: cash.label }).first();
  await cashOrder.waitFor({ timeout: 15_000 });
  await cashOrder.click();
  await waiter.getByRole("button", { name: "Record cash" }).click();
  await waiter.getByText("Cash payment confirmed.").waitFor({ timeout: 15_000 });
  await waitForDinerStatus(cash.page, "Refresh receipt");
  await cash.page.getByRole("button", { name: "Refresh receipt" }).click();
  await cash.page.getByText("Digital receipt").waitFor();
  await cash.page.screenshot({ path: resolve(evidence, "05-staff-cash-receipt.png"), fullPage: true });
  results.cases.push({ name: "waiter records cash and diner sees receipt", pass: true });
  await cash.context.close();

  await waiterContext.close();
  await managerContext.close();
} catch (error) {
  results.error = error instanceof Error ? error.message : String(error);
} finally {
  await browser.close();
  await writeFile(resultPath, JSON.stringify(results, null, 2));
}

console.log(JSON.stringify(results, null, 2));
if (results.error || results.cases.some((entry) => !entry.pass)) process.exitCode = 1;
