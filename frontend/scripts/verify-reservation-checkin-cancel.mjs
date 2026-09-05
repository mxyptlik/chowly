import { chromium } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import { resolve } from "node:path";

const base = "http://localhost:3000";
const evidence = resolve(import.meta.dirname, "../../docs/verification/screenshots/08-reservations");
await mkdir(evidence, { recursive: true });

function publicPath(path) { return `${base}${path}`; }
async function redactCustomerContact(page) {
  await page.locator("body").evaluate((body) => {
    const walker = document.createTreeWalker(body, NodeFilter.SHOW_TEXT);
    const nodes = []; while (walker.nextNode()) nodes.push(walker.currentNode);
    for (const node of nodes) node.textContent = node.textContent
      .replace(/Reservation Checkin Guest/g, "Guest")
      .replace(/Reservation Cancel Guest/g, "Guest")
      .replace(/0809\d{7}/g, "[redacted]");
  });
}

async function createReservation(page, name, phone, party) {
  await page.goto(publicPath("/r/mango-ash-hospitality/mango-ash-victoria-island/reserve"), { waitUntil: "networkidle" });
  await page.getByLabel("Your name").fill(name);
  await page.getByLabel("Phone number").fill(phone);
  await page.getByLabel("Party size").fill(String(party));
  await page.getByLabel("Preferred date and time").fill("2026-10-19T19:00");
  await page.getByRole("button", { name: "Request reservation" }).click();
  await page.waitForURL(/\/reserve\/success/);
  await page.getByText("You’re").waitFor();
  const token = new URL(page.url()).searchParams.get("token");
  if (!token) throw new Error("Expected private reservation capability after creation.");
  return token;
}

const browser = await chromium.launch({ headless: true });
const diner = await browser.newPage({ viewport: { width: 390, height: 844 } });
browser.on("disconnected", () => console.log("BROWSER:disconnected"));
diner.setDefaultTimeout(12_000);
const runId = String(Date.now()).slice(-6);
const checkinGuest = `Checkin Guest ${runId}`;
const cancelGuest = `Cancel Guest ${runId}`;
console.log("STEP:create-checkin-reservation");
const checkinToken = await createReservation(diner, checkinGuest, `0809${runId}0`, 2);
console.log("STEP:create-private-qr");
await diner.goto(publicPath(`/r/mango-ash-hospitality/mango-ash-victoria-island/reserve/confirmation?token=${encodeURIComponent(checkinToken)}`), { waitUntil: "domcontentloaded" });
const qrPassResponse = diner.waitForResponse((response) => response.url().includes("/qr-pass") && response.request().method() === "POST");
await diner.getByRole("button", { name: "Create check-in QR" }).click();
await diner.getByText("Your private check-in QR is ready.").waitFor();
const qrImage = diner.getByRole("img", { name: "Private reservation check-in QR code" });
await qrImage.waitFor();
const qrPassPayload = await (await qrPassResponse).json();
const checkinPass = qrPassPayload.qr_pass_token;
if (typeof checkinPass !== "string" || !checkinPass) throw new Error("QR pass endpoint did not return a capability.");

const manager = await browser.newPage({ viewport: { width: 1280, height: 900 } });
manager.setDefaultTimeout(12_000);
manager.on("pageerror", error => console.log("MANAGER_PAGE_ERROR", error.message));
manager.on("console", message => { if (message.type() === "error") console.log("MANAGER_CONSOLE_ERROR", message.text()); });
await manager.goto(publicPath("/login"), { waitUntil: "domcontentloaded" });
await manager.getByLabel("Work email").fill("pilot1.manager@demo.chowly.ng");
await manager.getByLabel("Password").fill("ChowlyDemo!2026");
await manager.getByRole("button", { name: /sign in to chowly/i }).click();
await manager.waitForURL("**/ops");
await manager.goto(publicPath("/manage/reservations"), { waitUntil: "networkidle" });
const checkinReservation = manager.locator(".admin-row").filter({ hasText: checkinGuest }).first();
console.log("STEP:manager-queue", JSON.stringify({ count: await manager.locator(".admin-row").count(), text: (await manager.locator("body").innerText()).slice(-1800) }));
await checkinReservation.waitFor();
await checkinReservation.getByRole("button", { name: "Confirm" }).click();
await manager.getByText("Reservation confirmed.").waitFor();

const waiter = await browser.newPage({ viewport: { width: 1280, height: 900 } });
waiter.setDefaultTimeout(12_000);
console.log("STEP:waiter-login");
await waiter.goto(publicPath("/login"), { waitUntil: "domcontentloaded" });
await waiter.getByLabel("Work email").fill("pilot1.waiter@demo.chowly.ng");
await waiter.getByLabel("Password").fill("ChowlyDemo!2026");
await waiter.getByRole("button", { name: /sign in to chowly/i }).click();
await waiter.waitForURL("**/ops");
await waiter.goto(publicPath("/ops/verify-reservation"), { waitUntil: "domcontentloaded" });
await waiter.getByLabel("Reservation QR pass or link").fill(`${base}/ops/verify-reservation?pass=${checkinPass}`);
await waiter.getByRole("button", { name: "Verify pasted pass" }).click();
await waiter.getByText("Pass verified. Check the arrival details before checking in.").waitFor();
await waiter.getByRole("button", { name: "Check in guest" }).click();
await waiter.getByText("Guest checked in. This action was recorded.").waitFor();
console.log("STEP:waiter-checked-in");
await redactCustomerContact(waiter);
await waiter.screenshot({ path: resolve(evidence, "04-waiter-qr-pass-checked-in.png"), fullPage: true });

const cancellationToken = await createReservation(diner, cancelGuest, `0808${runId}0`, 3);
console.log("STEP:created-cancellation-case");
await diner.goto(publicPath(`/r/mango-ash-hospitality/mango-ash-victoria-island/reserve/confirmation?token=${encodeURIComponent(cancellationToken)}`), { waitUntil: "domcontentloaded" });
await diner.getByRole("button", { name: "Cancel reservation" }).click();
await diner.getByText("Reservation cancelled.").waitFor();
await redactCustomerContact(diner);
await diner.screenshot({ path: resolve(evidence, "05-customer-cancelled-reservation.png"), fullPage: true });
console.log(JSON.stringify({ checkin: "verified-and-recorded", cancellation: "customer-cancelled", screenshots: 2 }, null, 2));
await browser.close();
