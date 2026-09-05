import { chromium } from "@playwright/test";
import { mkdir, writeFile } from "node:fs/promises";
import { resolve } from "node:path";

const base = "http://localhost:3000";
const password = "ChowlyDemo!2026";
const roles = [
  { name: "waiter", email: "pilot1.waiter@demo.chowly.ng", folder: "02-waiter", routes: ["/ops", "/ops/verify-reservation", "/manage/tables"] },
  { name: "chef", email: "pilot1.chef@demo.chowly.ng", folder: "03-chef", routes: ["/prep", "/manage/menu"] },
  { name: "bartender", email: "pilot1.bartender@demo.chowly.ng", folder: "04-bartender", routes: ["/prep", "/manage/menu"] },
  { name: "manager", email: "pilot1.manager@demo.chowly.ng", folder: "05-manager", routes: ["/ops", "/manage/tables", "/manage/menu", "/manage/reservations", "/manage/payments", "/manage/feedback", "/manage/team", "/manage/reports", "/manage/settings"] },
  { name: "owner", email: "pilot1.tenant_owner@demo.chowly.ng", folder: "06-owner", routes: ["/manage/tables", "/manage/menu", "/manage/team", "/manage/reports", "/manage/settings"] },
];
const browser = await chromium.launch({ headless: true });
const summary = [];
for (const role of roles) {
  const folder = resolve(import.meta.dirname, `../../docs/verification/screenshots/${role.folder}`);
  await mkdir(folder, { recursive: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, colorScheme: "dark" });
  const page = await context.newPage();
  await page.goto(`${base}/login`, { waitUntil: "networkidle" });
  await page.getByLabel("Work email").fill(role.email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: /sign in to chowly/i }).click();
  await page.waitForTimeout(700);
  for (const route of role.routes) {
    await page.goto(`${base}${route}`, { waitUntil: "networkidle" });
    const body = await page.locator("body").innerText();
    const safe = route.replaceAll("/", "_").replace(/^_/, "") || "home";
    await page.screenshot({ path: `${folder}/${safe}-dark.png`, fullPage: true });
    summary.push({ role: role.name, route, url: page.url(), denied: /restricted|do not have access/i.test(body), loading: /checking staff access/i.test(body) });
  }
  await context.close();
}
await writeFile(resolve(import.meta.dirname, "../../docs/verification/playwright-role-capture.json"), JSON.stringify(summary, null, 2));
console.log(JSON.stringify(summary, null, 2));
await browser.close();
