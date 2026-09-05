import { chromium } from "@playwright/test";

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage();
page.on("response", async response => {
  if (response.url().includes("/staff/locations/")) console.log("LOCATION_RESPONSE", response.status(), response.url(), await response.text());
});
await page.goto("http://localhost:3000/login");
await page.getByLabel("Work email").fill("pilot1.tenant_owner@demo.chowly.ng");
await page.getByLabel("Password").fill("ChowlyDemo!2026");
await page.getByRole("button", { name: /sign in to chowly/i }).click();
await page.waitForURL("**/admin");
await page.goto("http://localhost:3000/manage/settings", { waitUntil: "networkidle" });
const acceptOrders = page.getByLabel("Accept orders");
console.log("SETTINGS_LOADED", page.url(), await acceptOrders.count());
if (!await acceptOrders.isChecked()) await acceptOrders.check();
await page.getByRole("button", { name: "Save settings" }).click();
await page.getByLabel("Opens").fill("00:00");
await page.getByLabel("Closes").fill("23:59");
await page.getByRole("button", { name: "Save all days" }).click();
await page.waitForTimeout(1_000);
console.log(JSON.stringify({ url: page.url(), acceptOrders: await acceptOrders.isChecked(), text: (await page.locator("body").innerText()).slice(-1000) }));
await browser.close();
