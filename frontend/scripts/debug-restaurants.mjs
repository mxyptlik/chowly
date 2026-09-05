import { chromium } from "@playwright/test";

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage();
const requests = [];
const consoleMessages = [];
page.on("response", (response) => { if (response.status() >= 400 || response.url().includes("restaurants")) requests.push({ url: response.url(), status: response.status(), body: null }); });
page.on("console", (message) => consoleMessages.push({ type: message.type(), text: message.text() }));
page.on("pageerror", (error) => consoleMessages.push({ type: "pageerror", text: error.message }));
await page.goto("http://localhost:3000/restaurants", { waitUntil: "networkidle" });
console.log(JSON.stringify({ title: await page.title(), body: (await page.locator("body").innerText()).slice(0, 1000), requests, consoleMessages }, null, 2));
await browser.close();
