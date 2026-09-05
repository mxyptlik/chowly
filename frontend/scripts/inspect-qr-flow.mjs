import { chromium } from "@playwright/test";
const browser=await chromium.launch({headless:true}); const page=await browser.newPage();
await page.goto("http://localhost:3000/login"); await page.getByLabel("Work email").fill("pilot1.manager@demo.chowly.ng"); await page.getByLabel("Password").fill("ChowlyDemo!2026"); await page.getByRole("button",{name:/sign in to chowly/i}).click(); await page.waitForURL("**/ops"); await page.goto("http://localhost:3000/manage/tables",{waitUntil:"networkidle"}); await page.getByRole("button",{name:"Show QR"}).nth(1).click();
const menuLink=page.getByRole("link",{name:"Open menu"}); await menuLink.waitFor();
console.log(JSON.stringify({url:page.url(),menuUrl:await menuLink.getAttribute("href"),table:await page.locator("text=Table 02").first().textContent()},null,2)); await browser.close();
