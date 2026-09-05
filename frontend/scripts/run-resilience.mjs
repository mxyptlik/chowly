import { chromium } from "@playwright/test";
import { mkdir, writeFile } from "node:fs/promises";
import { resolve } from "node:path";

const base = "http://localhost:3000";
const evidence = resolve(import.meta.dirname, "../../docs/verification/screenshots/10-resilience");
const resultPath = resolve(import.meta.dirname, "../../docs/verification/resilience-results.json");
const password = "ChowlyDemo!2026";
const results = { executed_at: new Date().toISOString() };

async function login(page, email) {
  await page.goto(`${base}/login`, { waitUntil: "networkidle" });
  await page.getByLabel("Work email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: /sign in to chowly/i }).click();
  await page.waitForURL(/\/(ops|prep|manage\/tables)/, { timeout: 12_000 });
}

await mkdir(evidence, { recursive: true });
const browser = await chromium.launch({ headless: true });
try {
  // Obtain a rendered, current daily QR menu through the manager workspace.
  const managerContext = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const manager = await managerContext.newPage();
  await login(manager, "pilot1.manager@demo.chowly.ng");
  await manager.goto(`${base}/manage/tables`, { waitUntil: "networkidle" });
  await manager.getByRole("button", { name: "Show QR" }).first().click();
  const menuLink = manager.getByRole("link", { name: "Open menu" });
  await menuLink.waitFor({ timeout: 8_000 });
  const menuUrl = await menuLink.getAttribute("href");
  if (!menuUrl) throw new Error("Rendered QR did not expose a diner menu link.");

  // A public diner creates an order through the card/menu UI, retaining its browser-only capability.
  const dinerContext = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const diner = await dinerContext.newPage();
  await diner.goto(menuUrl, { waitUntil: "networkidle" });
  const menuButtons = diner.getByRole("button", { name: /view /i });
  await menuButtons.first().click();
  await diner.getByRole("button", { name: /add to this order/i }).click();
  await diner.getByRole("button", { name: /open order, 1 items/i }).click();
  await diner.getByLabel("Your name").fill("Realtime Browser Guest");
  await diner.getByLabel("Phone number").fill(`080${String(Date.now()).slice(-8)}`);
  await diner.getByRole("button", { name: "Send for staff acceptance" }).click();
  await diner.waitForURL("**/order/*", { timeout: 20_000 });
  const orderId = new URL(diner.url()).pathname.split("/").pop();
  if (!orderId) throw new Error("Diner order URL did not contain an order id.");
  await diner.getByText("Order sent.").waitFor({ timeout: 12_000 });

  // The state transition originates as an authenticated staff action, then must reach the open diner page.
  const waiterContext = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const waiter = await waiterContext.newPage();
  await login(waiter, "pilot1.waiter@demo.chowly.ng");
  const accept = await waiter.evaluate(async (id) => {
    const orders = await fetch("/api/v1/staff/orders").then(async response => ({ status: response.status, body: await response.json() }));
    const order = Array.isArray(orders.body) ? orders.body.find((entry) => entry.id === id) : null;
    if (orders.status !== 200 || !order) return { list_status: orders.status, found: Boolean(order), accept_status: null };
    const response = await fetch(`/api/v1/staff/orders/${encodeURIComponent(id)}/accept`, {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ estimated_wait_minutes: 15, expected_version: order.version }),
    });
    return { list_status: orders.status, found: true, accept_status: response.status };
  }, orderId);
  if (accept.accept_status !== 200) throw new Error(`Waiter acceptance did not succeed (${JSON.stringify(accept)}).`);

  await diner.getByText("The good part is underway.").waitFor({ timeout: 15_000 });
  const liveText = await diner.locator(".eyebrow").first().innerText();
  results.realtime = { waiter_action: accept, diner_status: liveText, updated_without_diner_refresh: /PREPARING/i.test(liveText) };
  await diner.screenshot({ path: resolve(evidence, "01-diner-realtime-preparing.png"), fullPage: true });

  // Deliberately go offline after the server-confirmed transition: page remains readable and warns that mutations are not sent.
  await dinerContext.setOffline(true);
  await diner.waitForTimeout(350);
  await diner.getByText("You are offline").waitFor({ timeout: 5_000 });
  results.offline = { warning_visible: true, status_readable: await diner.getByText("The good part is underway.").isVisible() };
  await diner.screenshot({ path: resolve(evidence, "02-diner-offline-status-safe.png"), fullPage: true });
  await dinerContext.setOffline(false);

  // A guessed order header must not disclose the just-created order. Do not write the opaque identifier/token to evidence.
  results.public_wrong_capability = await manager.evaluate(async (id) => {
    const response = await fetch(`/api/v1/public/orders/${encodeURIComponent(id)}`, { headers: { "X-Order-Access-Token": "guess" } });
    return { status: response.status, non_enumerating_not_found: response.status === 404 };
  }, orderId);

  // A tenant manager has no platform-provisioning authority.
  results.manager_platform_boundary = await manager.evaluate(async () => {
    const response = await fetch("/api/v1/platform/tenants/bootstrap", { method: "POST", headers: { "content-type": "application/json" }, body: "{}" });
    return { status: response.status, forbidden: response.status === 403 };
  });

  // Staff route guards also render as a user-facing restriction, not leaked data.
  const chefContext = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const chef = await chefContext.newPage();
  await login(chef, "pilot1.chef@demo.chowly.ng");
  await chef.goto(`${base}/manage/feedback`, { waitUntil: "networkidle" });
  const chefBody = await chef.locator("body").innerText();
  results.chef_feedback_boundary = { restricted: /restricted|do not have access/i.test(chefBody), customer_phone_absent: !/\b0\d{10}\b/.test(chefBody) };
  await chef.screenshot({ path: resolve(evidence, "03-chef-feedback-restricted.png"), fullPage: true });
  await chefContext.close();
  await waiterContext.close();
  await dinerContext.close();
  await managerContext.close();
} finally {
  await browser.close();
  await writeFile(resultPath, JSON.stringify(results, null, 2));
}

console.log(JSON.stringify(results, null, 2));
