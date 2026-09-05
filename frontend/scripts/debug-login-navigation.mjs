/**
 * Narrow, deterministic reproduction of a staff-login response that does not
 * transition into the role workspace. Kept under scripts/ as an explicitly
 * named debug harness until the browser regression is permanently covered.
 */
import { chromium } from "@playwright/test";
import { writeFile } from "node:fs/promises";
import { resolve } from "node:path";

const resultPath = resolve(import.meta.dirname, "../../docs/verification/debug-login-navigation.json");
let browser;
let context;
let page;
const evidence = { step: "starting", console: [], page_errors: [], requests: [], url_before: null, url_after: null };
const persist = () => writeFile(resultPath, JSON.stringify(evidence, null, 2));

try {
  browser = await chromium.launch({ headless: true });
  context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  page = await context.newPage();
  page.setDefaultTimeout(15_000);
  page.on("console", (message) => {
    if (message.type() === "error" || message.type() === "warning") {
      evidence.console.push({ type: message.type(), text: message.text() });
    }
  });
  page.on("pageerror", (error) => evidence.page_errors.push(error.message));
  page.on("response", (response) => {
    if (response.status() >= 400 || response.url().includes("/staff/auth/login")) {
      evidence.requests.push({ url: response.url(), status: response.status() });
    }
  });

  evidence.step = "loading_login"; await persist();
  await page.goto("http://localhost:3000/login", { waitUntil: "domcontentloaded" });
  evidence.step = "filling_login"; await persist();
  await page.getByLabel("Work email").fill("pilot1.manager@demo.chowly.ng");
  await page.getByLabel("Password").fill("ChowlyDemo!2026");
  evidence.url_before = page.url();
  evidence.step = "submitting_login"; await persist();
  await page.getByRole("button", { name: /sign in to chowly/i }).click();
  evidence.step = "waiting_for_workspace"; await persist();
  await page.waitForURL(/\/(ops|prep|manage|admin)/, { timeout: 15_000 });
  evidence.url_after = page.url();
  evidence.body_tail = (await page.locator("body").innerText()).slice(-800);
  evidence.step = "complete";
} catch (error) {
  evidence.error = error instanceof Error ? error.message : String(error);
  evidence.step = "failed";
} finally {
  await persist();
  await context?.close();
  await browser?.close();
}

console.log(JSON.stringify(evidence, null, 2));
if (evidence.error) process.exitCode = 1;
