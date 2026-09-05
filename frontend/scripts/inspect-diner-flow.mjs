import { chromium } from "@playwright/test";

const menuUrl = process.argv[2];
if (!menuUrl) throw new Error("Pass the daily QR menu URL as the first argument.");
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
await page.goto(menuUrl, { waitUntil: "networkidle" });
console.log(JSON.stringify({
  url: page.url(),
  inputs: await page.locator("input, textarea, select").evaluateAll(rows => rows.map(row => ({
    tag: row.tagName, name: row.getAttribute("name"), type: row.getAttribute("type"),
    label: row.getAttribute("aria-label"), placeholder: row.getAttribute("placeholder")
  }))),
  buttons: await page.getByRole("button").allTextContents(),
  links: await page.getByRole("link").allTextContents(),
  text: (await page.locator("body").innerText()).slice(0, 5000)
}, null, 2));
await browser.close();
