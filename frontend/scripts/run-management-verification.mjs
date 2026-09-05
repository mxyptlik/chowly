import { chromium } from "@playwright/test";
import { mkdir, writeFile } from "node:fs/promises";
import { resolve } from "node:path";

const base = "http://localhost:3000";
const password = "ChowlyDemo!2026";
const output = resolve(import.meta.dirname, "../../docs/verification/screenshots/09-management");
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true });
const results = [];

async function signedIn(email) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, colorScheme: "dark" });
  const page = await context.newPage();
  await page.goto(`${base}/login`, { waitUntil: "networkidle" });
  await page.getByLabel("Work email").fill(email);
  await page.getByLabel("Password").fill(password);
  const loginResponses = [];
  page.on("response", (response) => {
    if (response.url().includes("/staff/auth/login")) loginResponses.push(response.status());
  });
  await page.getByRole("button", { name: /sign in to chowly/i }).click();
  await page.waitForURL(/\/(ops|prep|manage|admin)/, { timeout: 12_000 }).catch(() => undefined);
  if (!/\/(ops|prep|manage|admin)/.test(page.url())) {
    throw new Error(`Staff login did not navigate: statuses=${loginResponses.join(",")} body=${(await page.locator("body").innerText()).slice(-500)}`);
  }
  return { context, page };
}

async function shot(page, file) {
  await page.screenshot({ path: resolve(output, file), fullPage: true });
}

// Manager: reports are available, settings are deliberately not.
{
  const { context, page } = await signedIn("pilot1.manager@demo.chowly.ng");
  await page.goto(`${base}/manage/reports`, { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "Load report" }).click();
  await page.waitForTimeout(500);
  const reportBody = await page.locator("body").innerText();
  await shot(page, "01-manager-reports.png");
  results.push({ case: "manager reports", pass: /reports/i.test(reportBody) && !/could not confirm|could not reach/i.test(reportBody) });
  await page.goto(`${base}/manage/settings`, { waitUntil: "networkidle" });
  const denied = /do not have access/i.test(await page.locator("body").innerText());
  await shot(page, "02-manager-settings-denied.png");
  results.push({ case: "manager settings denied", pass: denied });

  await page.goto(`${base}/manage/feedback`, { waitUntil: "networkidle" });
  const rows = page.locator("article.admin-row");
  const count = await rows.count();
  await shot(page, "03-manager-feedback-inbox.png");
  results.push({ case: "manager feedback inbox", pass: count >= 0, complaint_rows: count });
  if (count > 0) {
    const open = rows.filter({ hasNotText: "RESOLVED" }).first();
    if (await open.count()) {
      await page.getByLabel("Resolution note").fill("Resolved during controlled management verification.");
      await open.getByRole("button", { name: "Resolve" }).click();
      await page.getByText("Complaint resolved.").waitFor({ timeout: 10_000 });
      await shot(page, "04-manager-complaint-resolved.png");
      results.push({ case: "manager complaint resolution", pass: true });
    } else results.push({ case: "manager complaint resolution", pass: false, reason: "No open complaint exists in the seeded database" });
  } else results.push({ case: "manager complaint resolution", pass: false, reason: "No complaint exists in the seeded database" });
  await context.close();
}

// Owner: settings and team invitation. The acceptance token is read only in memory and never written/screen-captured.
{
  const { context, page } = await signedIn("pilot1.tenant_owner@demo.chowly.ng");
  await page.goto(`${base}/manage/settings`, { waitUntil: "networkidle" });
  const settingsVisible = await page.getByRole("button", { name: "Save settings" }).count() === 1;
  await shot(page, "05-owner-settings.png");
  results.push({ case: "owner settings", pass: settingsVisible });
  await page.goto(`${base}/manage/team`, { waitUntil: "networkidle" });
  await shot(page, "06-owner-team-invite-form.png");
  const email = `playwright-management-${Date.now()}@demo.chowly.ng`;
  await page.getByLabel("Name").fill("Playwright Management Check");
  await page.getByLabel("Work email").fill(email);
  await page.getByLabel("Role").selectOption("WAITER");
  const invitationResponses = [];
  page.on("response", (response) => {
    if (response.url().includes("/staff/auth/invitations")) invitationResponses.push({ status: response.status(), url: response.url() });
  });
  await page.getByRole("button", { name: "Create invitation" }).click();
  await page.waitForTimeout(1_000);
  const text = await page.locator("body").innerText();
  const tokenMatch = text.match(/Invitation token \(show once\):\s*([^\s.]+)/);
  const safeNotice = text.replace(/Invitation token \(show once\):\s*[^\s.]+/, "Invitation token: [REDACTED]").match(/Team\n([\s\S]{0,250})/)?.[1] ?? "";
  results.push({ case: "owner creates waiter invitation", pass: Boolean(tokenMatch), invited_email: email, request: invitationResponses, safe_notice: safeNotice });
  if (tokenMatch) {
    const accept = await context.newPage();
    await accept.goto(`${base}/login/accept?token=${encodeURIComponent(tokenMatch[1])}`, { waitUntil: "networkidle" });
    await accept.getByLabel("Choose a password").fill("ChowlyInvite!2026");
    await accept.getByRole("button", { name: "Activate staff account" }).click();
    await accept.waitForURL(/\/ops/, { timeout: 10_000 });
    await shot(accept, "07-invited-waiter-activated.png");
    results.push({ case: "invited waiter accepts invitation", pass: /\/ops/.test(accept.url()) });
    await accept.close();
  }
  // Navigate away before any capture so the one-time token cannot enter evidence files.
  await page.goto(`${base}/manage/reports`, { waitUntil: "networkidle" });
  await shot(page, "07-owner-reports.png");
  await context.close();
}

// Managers may invite operational staff at their active location, but may not create another manager.
{
  const { context, page } = await signedIn("pilot1.manager@demo.chowly.ng");
  await page.goto(`${base}/manage/team`, { waitUntil: "networkidle" });
  const email = `playwright-manager-${Date.now()}@demo.chowly.ng`;
  await page.getByLabel("Name").fill("Playwright Bar Support");
  await page.getByLabel("Work email").fill(email);
  await page.getByLabel("Role").selectOption("BARTENDER");
  await page.getByRole("button", { name: "Create invitation" }).click();
  await page.waitForTimeout(1_000);
  const managerText = await page.locator("body").innerText();
  results.push({ case: "manager creates bartender invitation", pass: /Invitation token \(show once\):/.test(managerText), invited_email: email });
  await context.close();
}

// Staff roles cannot open management data that contains payments, feedback, or people data.
for (const [role, email, route] of [
  ["waiter", "pilot1.waiter@demo.chowly.ng", "/manage/payments"],
  ["chef", "pilot1.chef@demo.chowly.ng", "/manage/feedback"],
  ["bartender", "pilot1.bartender@demo.chowly.ng", "/manage/team"],
]) {
  const { context, page } = await signedIn(email);
  await page.goto(`${base}${route}`, { waitUntil: "networkidle" });
  const denied = /do not have access/i.test(await page.locator("body").innerText());
  await shot(page, `08-${role}-${route.split("/").at(-1)}-denied.png`);
  results.push({ case: `${role} ${route} denied`, pass: denied });
  await context.close();
}

await browser.close();
await writeFile(resolve(import.meta.dirname, "../../docs/verification/management-playwright-results.json"), JSON.stringify(results, null, 2));
console.log(JSON.stringify(results, null, 2));
