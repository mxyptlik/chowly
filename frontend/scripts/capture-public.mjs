import { chromium } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import { resolve } from "node:path";

const base = "http://localhost:3000";
const output = resolve(import.meta.dirname, "../../docs/verification/screenshots/01-public");
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, colorScheme: "dark" });

async function capture(path, file) {
  await page.goto(`${base}${path}`, { waitUntil: "networkidle" });
  await page.screenshot({ path: `${output}/${file}`, fullPage: true });
}

await capture("/", "01-home-dark.png");
await page.getByRole("button", { name: /switch to light mode/i }).click();
await page.waitForTimeout(150);
await page.screenshot({ path: `${output}/02-home-light.png`, fullPage: true });
await capture("/restaurants", "03-restaurants-light.png");
await page.getByRole("button", { name: /switch to dark mode/i }).click();
await page.waitForTimeout(150);
await page.screenshot({ path: `${output}/04-restaurants-dark.png`, fullPage: true });
await capture("/login", "05-login-dark.png");
await browser.close();
