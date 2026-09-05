import { chromium } from "@playwright/test";
import { writeFile } from "node:fs/promises";
import { resolve } from "node:path";
const base = "http://localhost:3000", password = "ChowlyDemo!2026";
const cases = [
  ["waiter", "pilot1.waiter@demo.chowly.ng", "/manage/payments"],
  ["chef", "pilot1.chef@demo.chowly.ng", "/manage/feedback"],
  ["bartender", "pilot1.bartender@demo.chowly.ng", "/manage/team"],
  ["owner", "pilot1.tenant_owner@demo.chowly.ng", "/ops"],
];
const browser = await chromium.launch({ headless: true }); const results=[];
for (const [role,email,route] of cases) { const context=await browser.newContext(); const page=await context.newPage(); await page.goto(`${base}/login`); await page.getByLabel("Work email").fill(email); await page.getByLabel("Password").fill(password); await page.getByRole("button", {name:/sign in to chowly/i}).click(); await page.waitForTimeout(500); await page.goto(`${base}${route}`,{waitUntil:"networkidle"}); const body=await page.locator("body").innerText(); results.push({role,route,blocked:/restricted|do not have access/i.test(body),url:page.url()}); await context.close(); }
await browser.close(); await writeFile(resolve(import.meta.dirname,"../../docs/verification/playwright-role-denials.json"),JSON.stringify(results,null,2)); console.log(JSON.stringify(results,null,2));
