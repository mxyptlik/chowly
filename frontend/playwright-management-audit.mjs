import { chromium } from "@playwright/test";
import { mkdir, writeFile } from "node:fs/promises";

const base = "http://localhost:3000";
const captures = [
  ["tables", "/manage/tables"],
  ["menu", "/manage/menu"],
  ["reservations", "/manage/reservations"],
  ["payments", "/manage/payments"],
  ["feedback", "/manage/feedback"],
  ["team", "/manage/team"],
  ["reports", "/manage/reports"],
  ["settings", "/manage/settings"],
  ["admin", "/admin"],
];
const personas = [
  { name: "manager", email: "pilot1.manager@demo.chowly.ng", directory: "05-manager" },
  { name: "owner", email: "pilot1.tenant_owner@demo.chowly.ng", directory: "06-owner" },
];

await mkdir("../docs/verification/screenshots/05-manager", { recursive: true });
await mkdir("../docs/verification/screenshots/06-owner", { recursive: true });
const browser = await chromium.launch({ headless: true });
const findings = [];
for (const persona of personas) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  const page = await context.newPage();
  await page.goto(`${base}/login`, { waitUntil: "networkidle" });
  await page.getByLabel("Work email").fill(persona.email);
  await page.getByLabel("Password").fill("ChowlyDemo!2026");
  await page.getByRole("button", { name: "Sign in to Chowly" }).click();
  await page.waitForLoadState("networkidle");
  findings.push({ persona: persona.name, route: "login", finalUrl: page.url(), title: await page.locator("h1").first().textContent() });
  for (const [name, route] of captures) {
    await page.goto(`${base}${route}`, { waitUntil: "networkidle" });
    await page.waitForTimeout(250);
    const body = (await page.locator("body").innerText()).replace(/\s+/g, " ").trim();
    const nav = await page.locator('aside[aria-label="Staff navigation"] a').allTextContents();
    const target = `../docs/verification/screenshots/${persona.directory}/${persona.name}-${name}-loaded-dark-desktop.png`;
    await page.screenshot({ path: target, fullPage: true });
    findings.push({ persona: persona.name, route, finalUrl: page.url(), nav, excerpt: body.slice(0, 420), screenshot: target.replace("../", "") });
  }
  await context.close();
}
await browser.close();
await writeFile("../docs/verification/playwright-management-results.json", JSON.stringify(findings, null, 2));
