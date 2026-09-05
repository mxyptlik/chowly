/**
 * Chromium proof of the private complaint lifecycle.
 *
 * This uses the same browser-facing routes a diner and staff use. It deliberately
 * never serialises a QR URL, order capability, cookies, password, order id, or
 * customer contact data. The JSON output is safe to retain as release evidence.
 */
import { chromium } from "@playwright/test";
import { mkdir, writeFile } from "node:fs/promises";
import { resolve } from "node:path";

const base = "http://localhost:3000";
const password = "ChowlyDemo!2026";
const output = resolve(import.meta.dirname, "../../docs/verification/screenshots/09-management/complaint-lifecycle");
const resultPath = resolve(import.meta.dirname, "../../docs/verification/complaint-lifecycle-results.json");
const marker = `Complaint browser verification ${Date.now()}`;
const phone = `080${String(Date.now()).slice(-8)}`;
const results = {
  schema: "chowly.complaint-lifecycle.v1",
  executed_at: new Date().toISOString(),
  environment: { web: base, browser: "Playwright Chromium" },
  cases: [],
  artifacts: [
    "docs/verification/screenshots/09-management/complaint-lifecycle/01-bartender-line-ready.png",
    "docs/verification/screenshots/09-management/complaint-lifecycle/02-diner-private-complaint-sent.png",
    "docs/verification/screenshots/09-management/complaint-lifecycle/03-manager-complaint-resolved.png",
  ],
};

function record(name, pass, detail = {}) {
  results.cases.push({ name, pass, ...detail });
  if (!pass) throw new Error(`${name} failed`);
}

async function shot(page, filename) {
  await page.screenshot({ path: resolve(output, filename), fullPage: true });
}

async function staffPage(browser, email, expectedPath) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, colorScheme: "dark" });
  const page = await context.newPage();
  page.setDefaultTimeout(20_000);
  await page.goto(`${base}/login`, { waitUntil: "domcontentloaded" });
  await page.getByLabel("Work email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: /sign in to chowly/i }).click();
  await page.waitForURL(new RegExp(`${expectedPath.replace("/", "\\/")}(?:$|\\?)`), { timeout: 20_000 });
  return { context, page };
}

async function freshDailyMenuUrl(browser) {
  const { context, page } = await staffPage(browser, "pilot1.manager@demo.chowly.ng", "/ops");
  try {
    await page.goto(`${base}/manage/tables`, { waitUntil: "domcontentloaded" });
    const table = page.locator("article.admin-row").filter({ hasText: "Table 03" });
    await table.getByRole("button", { name: "Show QR" }).click();
    const menu = page.getByRole("link", { name: "Open menu" });
    await menu.waitFor();
    const url = await menu.getAttribute("href");
    if (!url) throw new Error("Table 03 did not expose its daily menu link.");
    record("manager generated a fresh Table 03 daily menu QR", true);
    return url;
  } finally {
    await context.close();
  }
}

try {
  await mkdir(output, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  try {
    const menuUrl = await freshDailyMenuUrl(browser);

    // Diner starts one independent QR order. The capability remains only in this
    // in-memory browser context for subsequent rating and complaint actions.
    const dinerContext = await browser.newContext({ viewport: { width: 390, height: 844 }, colorScheme: "dark" });
    const diner = await dinerContext.newPage();
    diner.setDefaultTimeout(25_000);
    await diner.goto(menuUrl, { waitUntil: "domcontentloaded" });
    await diner.getByRole("button", { name: /view hibiscus zobo fizz/i }).waitFor();
    await diner.getByRole("button", { name: /view hibiscus zobo fizz/i }).click();
    await diner.getByRole("button", { name: /add to this order/i }).click();
    await diner.getByRole("button", { name: /open order, 1 items/i }).click();
    await diner.getByLabel("Your name").fill(marker);
    await diner.getByLabel("Phone number").fill(phone);
    const submitResponse = diner.waitForResponse((response) => response.url().includes("/orders") && response.request().method() === "POST");
    await diner.getByRole("button", { name: "Send for staff acceptance" }).click();
    const submissionStatus = (await submitResponse).status();
    await diner.waitForURL(/\/order\/[^/]+/, { timeout: 25_000 });
    const orderId = new URL(diner.url()).pathname.split("/").at(-1);
    if (!orderId) throw new Error("Submitted order did not have a route id.");
    await diner.getByText("Order sent.").waitFor();
    record("diner submitted a separate Table 03 drink order", submissionStatus === 201, { submission_status: submissionStatus });

    // The waiter is permitted to see the customer data to choose the exact order;
    // no screenshot is taken in this workspace.
    const { context: waiterContext, page: waiter } = await staffPage(browser, "pilot1.waiter@demo.chowly.ng", "/ops");
    try {
      const card = waiter.locator(".order-card").filter({ hasText: marker });
      await card.waitFor();
      await card.click();
      const acceptResponse = waiter.waitForResponse((response) => response.url().includes(`/staff/orders/${orderId}/accept`) && response.request().method() === "POST");
      await waiter.getByRole("button", { name: "Accept" }).click();
      const acceptStatus = (await acceptResponse).status();
      await waiter.getByText("Acceptance confirmed.").waitFor();
      record("waiter accepted the diner order", acceptStatus === 200, { acceptance_status: acceptStatus });
    } finally {
      await waiterContext.close();
    }

    // Find the exact bar line through the browser's own prep response, then drive
    // its rendered card. This prevents another Table 03 test order being mistaken
    // for the order created above.
    const { context: bartenderContext, page: bartender } = await staffPage(browser, "pilot1.bartender@demo.chowly.ng", "/prep");
    try {
      const prepResponse = bartender.waitForResponse((response) => response.url().includes("/api/v1/staff/prep") && response.request().method() === "GET");
      await bartender.reload({ waitUntil: "domcontentloaded" });
      const queue = await (await prepResponse).json();
      const barLines = queue.filter((line) => line.queue_destination === "BAR");
      const lineIndex = barLines.findIndex((line) => line.order_id === orderId);
      if (lineIndex < 0) throw new Error("The accepted order was not present in the bartender queue.");
      const line = bartender.locator(".prep-card").nth(lineIndex);
      await line.waitFor();
      const claimResponse = bartender.waitForResponse((response) => response.url().includes(`/staff/lines/${barLines[lineIndex].line_id}/claim`) && response.request().method() === "POST");
      await line.getByRole("button", { name: "Claim line" }).click();
      const claimStatus = (await claimResponse).status();
      await bartender.getByText(/claimed Hibiscus Zobo Fizz/).waitFor();
      const readyResponse = bartender.waitForResponse((response) => response.url().includes(`/staff/lines/${barLines[lineIndex].line_id}/ready`) && response.request().method() === "POST");
      await bartender.locator(".prep-card").nth(lineIndex).getByRole("button", { name: "Mark ready" }).click();
      const readyStatus = (await readyResponse).status();
      await bartender.getByText("Hibiscus Zobo Fizz is ready for service.").waitFor();
      await shot(bartender, "01-bartender-line-ready.png");
      record("bartender claimed and marked the exact bar line ready", claimStatus === 200 && readyStatus === 200, { claim_status: claimStatus, ready_status: readyStatus });
    } finally {
      await bartenderContext.close();
    }

    const { context: serveContext, page: serve } = await staffPage(browser, "pilot1.waiter@demo.chowly.ng", "/ops");
    try {
      const card = serve.locator(".order-card").filter({ hasText: marker });
      await card.waitFor();
      await card.click();
      const serveResponse = serve.waitForResponse((response) => response.url().includes(`/staff/orders/${orderId}/serve`) && response.request().method() === "POST");
      await serve.getByRole("button", { name: "Mark served" }).click();
      const serveStatus = (await serveResponse).status();
      await serve.getByText("Service confirmed.").waitFor();
      record("waiter marked the ready order served", serveStatus === 200, { service_status: serveStatus });
    } finally {
      await serveContext.close();
    }

    // The diner receives the served state through the real app. A reload retains
    // only the in-browser secure capability and avoids falsely attributing polling
    // timing to the complaint test.
    await diner.reload({ waitUntil: "domcontentloaded" });
    await diner.getByRole("button", { name: "Rate overall order 1 out of 5" }).waitFor();
    const ratingResponse = diner.waitForResponse((response) => response.url().includes(`/public/orders/${orderId}/ratings/order`) && response.request().method() === "POST");
    await diner.getByRole("button", { name: "Rate overall order 1 out of 5" }).click();
    const ratingStatus = (await ratingResponse).status();
    await diner.getByLabel("What went wrong?").fill("Controlled browser test complaint");
    await diner.getByLabel("Tell the manager privately").fill("The service recovery workflow needs review.");
    const complaintResponse = diner.waitForResponse((response) => response.url().includes(`/public/orders/${orderId}/complaints`) && response.request().method() === "POST");
    await diner.getByRole("button", { name: "Send private complaint" }).click();
    const complaintStatus = (await complaintResponse).status();
    await diner.getByText("Your complaint was sent privately to the manager.").waitFor();
    const dinerBody = await diner.locator("body").innerText();
    const dinerSafe = !dinerBody.includes(phone) && !/access_token|realtime_token/i.test(dinerBody);
    await shot(diner, "02-diner-private-complaint-sent.png");
    record("diner low overall rating opens and sends a private complaint", ratingStatus === 201 && complaintStatus === 201 && dinerSafe, { rating_status: ratingStatus, complaint_status: complaintStatus, screenshot_safe: dinerSafe });
    await dinerContext.close();

    const { context: feedbackContext, page: feedback } = await staffPage(browser, "pilot1.manager@demo.chowly.ng", "/ops");
    try {
      await feedback.goto(`${base}/manage/feedback`, { waitUntil: "domcontentloaded" });
      const complaint = feedback.locator("article.admin-row").filter({ hasText: "Controlled browser test complaint" });
      await complaint.waitFor();
      const inboxBody = await feedback.locator("body").innerText();
      const managerSafe = !inboxBody.includes(phone) && !/access_token|realtime_token/i.test(inboxBody);
      record("manager sees the private complaint without customer contact data", managerSafe, { screenshot_safe: managerSafe });
      await feedback.getByLabel("Resolution note").fill("Resolved during deterministic Chromium verification.");
      const resolveResponse = feedback.waitForResponse((response) => response.url().includes("/complaints/") && response.url().endsWith("/resolve") && response.request().method() === "POST");
      await complaint.getByRole("button", { name: "Resolve" }).click();
      const resolveStatus = (await resolveResponse).status();
      await feedback.getByText("Complaint resolved.").waitFor();
      await feedback.locator("article.admin-row").filter({ hasText: "Controlled browser test complaint" }).getByText("RESOLVED").waitFor();
      await shot(feedback, "03-manager-complaint-resolved.png");
      record("manager resolved the private complaint with a note", resolveStatus === 200, { resolution_status: resolveStatus });
    } finally {
      await feedbackContext.close();
    }
  } finally {
    await browser.close();
  }
} catch (error) {
  results.error = error instanceof Error ? error.message : String(error);
} finally {
  await writeFile(resultPath, JSON.stringify(results, null, 2));
}

console.log(JSON.stringify(results, null, 2));
if (results.error || results.cases.some((entry) => !entry.pass)) process.exitCode = 1;
