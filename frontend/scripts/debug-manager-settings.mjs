import { chromium } from "@playwright/test";

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
const page = await context.newPage();
await page.goto("http://localhost:3000/login", { waitUntil: "domcontentloaded" });
await page.getByLabel("Work email").fill("pilot1.manager@demo.chowly.ng");
await page.getByLabel("Password").fill("ChowlyDemo!2026");
await page.getByRole("button", { name: /sign in to chowly/i }).click();
await page.waitForURL(/\/(ops|prep|manage|admin)/, { timeout: 15_000 });
const session = await page.evaluate(async () => {
  const response = await fetch("/api/v1/staff/auth/session");
  const body = await response.json();
  return { status: response.status, roles: body.roles, active_location_id: body.active_location_id };
});
await page.goto("http://localhost:3000/manage/settings", { waitUntil: "domcontentloaded" });
await page.waitForTimeout(300);
console.log(JSON.stringify({
  session,
  final_url: page.url(),
  has_save_settings: await page.getByRole("button", { name: "Save settings" }).count(),
  restricted: /do not have access to this workspace/i.test(await page.locator("body").innerText()),
  body_excerpt: (await page.locator("body").innerText()).slice(-800),
}, null, 2));
await context.close();
await browser.close();
