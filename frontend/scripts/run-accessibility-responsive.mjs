import { chromium } from "@playwright/test";
import { mkdir, writeFile } from "node:fs/promises";
import { resolve } from "node:path";

const base = process.env.CHOWLY_BASE_URL ?? "http://localhost:3000";
const api = process.env.CHOWLY_API_URL ?? "http://localhost:8000/api/v1";
const password = "ChowlyDemo!2026";
const screenshots = resolve(import.meta.dirname, "../../docs/verification/screenshots/11-accessibility");
const resultFile = resolve(import.meta.dirname, "../../docs/verification/accessibility-responsive-results.json");
const results = { executed_at: new Date().toISOString(), base, pages: {}, keyboard: {}, dialogs: {}, responsive: {}, motion: {}, contrast: {} };

function verify(condition, message) {
  if (!condition) throw new Error(message);
}

async function json(path) {
  const response = await fetch(`${api}${path}`);
  verify(response.ok, `${path} returned ${response.status}`);
  return response.json();
}

async function settle(page, selector) {
  await page.waitForLoadState("domcontentloaded");
  if (selector) await page.locator(selector).first().waitFor({ state: "visible", timeout: 12_000 });
  await page.waitForTimeout(350);
}

async function inspectPage(page, key, path, selector, screenshot, redactUrl = false) {
  await page.goto(new URL(path, base).toString(), { waitUntil: "domcontentloaded" });
  await settle(page, selector);
  const audit = await page.evaluate((shouldRedactUrl) => {
    const visible = (element) => {
      const style = getComputedStyle(element);
      const rect = element.getBoundingClientRect();
      return style.visibility !== "hidden" && style.display !== "none" && rect.width > 0 && rect.height > 0;
    };
    const name = (element) => {
      const aria = element.getAttribute("aria-label")?.trim();
      if (aria) return aria;
      const labelledBy = element.getAttribute("aria-labelledby")?.trim();
      if (labelledBy) return labelledBy.split(/\s+/).map((id) => document.getElementById(id)?.textContent?.trim() ?? "").join(" ").trim();
      if (element.labels?.length) return [...element.labels].map((label) => label.textContent?.trim() ?? "").join(" ").trim();
      return element.textContent?.trim() ?? "";
    };
    const controls = [...document.querySelectorAll("input:not([type=hidden]), select, textarea")].filter(visible);
    const missingLabels = controls.filter((element) => !name(element)).map((element) => ({ tag: element.tagName, type: element.getAttribute("type"), outer: element.outerHTML.slice(0, 180) }));
    const buttons = [...document.querySelectorAll("button, [role=button]")].filter(visible);
    const unnamedButtons = buttons.filter((element) => !name(element)).map((element) => element.outerHTML.slice(0, 180));
    const imagesWithoutAlt = [...document.querySelectorAll("img")].filter((image) => !image.hasAttribute("alt")).map((image) => image.outerHTML.slice(0, 180));
    const ids = [...document.querySelectorAll("[id]")].map((element) => element.id).filter(Boolean);
    const duplicateIds = [...new Set(ids.filter((id, index) => ids.indexOf(id) !== index))];
    return {
      url: shouldRedactUrl ? "/dine/[daily-table-qr]" : location.pathname,
      horizontal_overflow: document.documentElement.scrollWidth > window.innerWidth + 1,
      viewport: { width: window.innerWidth, height: window.innerHeight, scroll_width: document.documentElement.scrollWidth },
      control_count: controls.length,
      missing_labels: missingLabels,
      unnamed_buttons: unnamedButtons,
      images_without_alt: imagesWithoutAlt,
      duplicate_ids: duplicateIds,
      live_regions: document.querySelectorAll("[aria-live], [role=status], [role=alert]").length,
      skip_link: Boolean(document.querySelector("a.skip-link[href='#main-content']")),
    };
  }, redactUrl);
  verify(!audit.horizontal_overflow, `${key} has horizontal overflow at ${audit.viewport.width}px`);
  verify(audit.missing_labels.length === 0, `${key} has unlabeled controls: ${JSON.stringify(audit.missing_labels)}`);
  verify(audit.unnamed_buttons.length === 0, `${key} has unnamed buttons: ${JSON.stringify(audit.unnamed_buttons)}`);
  verify(audit.images_without_alt.length === 0, `${key} has images without alt text`);
  verify(audit.duplicate_ids.length === 0, `${key} has duplicate IDs: ${audit.duplicate_ids.join(", ")}`);
  verify(audit.skip_link, `${key} is missing the main-content skip link`);
  results.pages[key] = audit;
  if (screenshot) await page.screenshot({ path: resolve(screenshots, screenshot), fullPage: true });
}

async function login(page, email) {
  await page.goto(new URL("/login", base).toString(), { waitUntil: "domcontentloaded" });
  await settle(page, "input[type=email]");
  await page.getByLabel("Work email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in to Chowly" }).click();
  await page.waitForURL(/\/(ops|prep|admin)/, { timeout: 15_000 });
}

function relative(url) {
  const parsed = new URL(url, base);
  return `${parsed.pathname}${parsed.search}`;
}

async function contrastSamples(page, key) {
  const samples = await page.evaluate(() => {
    const channel = (value) => {
      const match = value.match(/rgba?\(([^)]+)\)/);
      if (!match) return null;
      const parts = match[1].split(",").map((part) => Number(part.trim()));
      return parts.length >= 3 && (parts[3] ?? 1) >= 0.99 ? parts.slice(0, 3) : null;
    };
    const luminance = ([red, green, blue]) => [red, green, blue].map((value) => {
      const channelValue = value / 255;
      return channelValue <= 0.03928 ? channelValue / 12.92 : ((channelValue + 0.055) / 1.055) ** 2.4;
    }).reduce((total, value, index) => total + value * [0.2126, 0.7152, 0.0722][index], 0);
    const background = (element) => {
      let current = element;
      while (current) {
        const parsed = channel(getComputedStyle(current).backgroundColor);
        if (parsed) return parsed;
        current = current.parentElement;
      }
      return null;
    };
    const visible = (element) => {
      const style = getComputedStyle(element);
      const rect = element.getBoundingClientRect();
      return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
    };
    return [".action", ".control", ".notice", ".store-card .card-copy b", ".workspace-nav a"].flatMap((selector) => [...document.querySelectorAll(selector)].filter(visible).slice(0, 3).flatMap((element) => {
      const foreground = channel(getComputedStyle(element).color);
      const backdrop = background(element);
      if (!foreground || !backdrop) return [];
      const first = luminance(foreground);
      const second = luminance(backdrop);
      return [{ selector, text: element.textContent?.trim().slice(0, 55), ratio: Math.round((((Math.max(first, second) + 0.05) / (Math.min(first, second) + 0.05)) * 100)) / 100 }];
    }));
  });
  results.contrast[key] = samples;
}

await mkdir(screenshots, { recursive: true });
const browser = await chromium.launch({ headless: true });
try {
  const restaurants = await json("/public/restaurants");
  verify(Array.isArray(restaurants) && restaurants.length > 0, "The public restaurant directory did not return a restaurant.");
  const restaurant = restaurants.find((row) => row.locations?.length) ?? restaurants[0];
  const location = restaurant.locations[0];
  verify(location?.slug, "The selected restaurant has no public location.");
  const publicMenu = `/r/${encodeURIComponent(restaurant.slug)}/${encodeURIComponent(location.slug)}/menu`;

  const publicDesktop = await browser.newContext({ viewport: { width: 1440, height: 1000 }, colorScheme: "dark" });
  const publicPage = await publicDesktop.newPage();
  await inspectPage(publicPage, "public-home-desktop", "/", "h1", "01-public-home-desktop.png");
  await inspectPage(publicPage, "public-directory-desktop", "/restaurants", "input[aria-label='Search restaurants']", "02-public-directory-desktop.png");
  await inspectPage(publicPage, "public-menu-desktop", publicMenu, "h1", "03-public-menu-desktop.png");
  await contrastSamples(publicPage, "public-menu-dark");
  await publicDesktop.close();

  const reservationMobile = await browser.newContext({ viewport: { width: 390, height: 844 }, colorScheme: "light" });
  const reserve = await reservationMobile.newPage();
  await inspectPage(reserve, "reservation-mobile", "/reserve", "input[type=tel]", "04-reservation-mobile.png");
  await reserve.getByRole("button", { name: "Request reservation" }).click();
  const reservationError = reserve.getByRole("alert").filter({ hasText: "Choose a restaurant and location" });
  await reservationError.waitFor({ timeout: 5_000 });
  results.keyboard.reservation_error = {
    announced: /Choose a restaurant and location/.test(await reservationError.innerText()),
    role: await reservationError.getAttribute("role"),
  };
  verify(results.keyboard.reservation_error.announced, "Empty reservation submission did not present an accessible error.");
  await reserve.screenshot({ path: resolve(screenshots, "05-reservation-error-mobile.png"), fullPage: true });
  await reservationMobile.close();

  const keyboardContext = await browser.newContext({ viewport: { width: 1280, height: 900 }, colorScheme: "dark" });
  const keyboardPage = await keyboardContext.newPage();
  await keyboardPage.goto(new URL("/login", base).toString(), { waitUntil: "domcontentloaded" });
  await settle(keyboardPage, "input[type=email]");
  await keyboardPage.keyboard.press("Tab");
  await keyboardPage.waitForTimeout(220);
  results.keyboard.skip_link = await keyboardPage.evaluate(() => ({
    active: document.activeElement?.classList.contains("skip-link") ?? false,
    visible: (() => {
      const element = document.activeElement;
      const box = element?.getBoundingClientRect();
      const style = element ? getComputedStyle(element) : null;
      return Boolean(box && style && box.width > 0 && box.height > 0 && style.visibility !== "hidden" && style.translate === "0px");
    })(),
  }));
  verify(results.keyboard.skip_link.active && results.keyboard.skip_link.visible, "Skip link is not keyboard reachable and visible.");
  await keyboardPage.keyboard.press("Enter");
  results.keyboard.skip_target = await keyboardPage.evaluate(() => document.activeElement?.id === "main-content");
  verify(results.keyboard.skip_target, "Skip link did not focus the main content target.");
  await keyboardPage.getByLabel("Work email").focus();
  results.keyboard.focus_indicator = await keyboardPage.getByLabel("Work email").evaluate((element) => {
    const style = getComputedStyle(element);
    return { outline: style.outlineStyle, box_shadow: style.boxShadow };
  });
  verify(results.keyboard.focus_indicator.outline !== "none" || results.keyboard.focus_indicator.box_shadow !== "none", "Focused input lacks a visible focus indicator.");
  await keyboardContext.close();

  const managerContext = await browser.newContext({ viewport: { width: 768, height: 1024 }, colorScheme: "dark" });
  const manager = await managerContext.newPage();
  await login(manager, "pilot1.manager@demo.chowly.ng");
  await manager.goto(new URL("/manage/tables", base).toString(), { waitUntil: "domcontentloaded" });
  await settle(manager, "button");
  await manager.getByRole("button", { name: "Show QR" }).first().click();
  const dinerLink = manager.getByRole("link", { name: "Open menu" });
  await dinerLink.waitFor({ timeout: 10_000 });
  const dailyMenu = await dinerLink.getAttribute("href");
  verify(dailyMenu, "Table QR workspace did not expose a daily diner menu link.");
  await inspectPage(manager, "waiter-tablet", "/ops", "h1", "06-waiter-tablet.png");
  await contrastSamples(manager, "waiter-tablet-dark");
  await inspectPage(manager, "manager-reservations-tablet", "/manage/reservations", "table", "10-manager-reservations-tablet.png");
  results.keyboard.reservation_table = {
    caption: await manager.locator("table caption").innerText(),
    region_label: await manager.locator(".table-scroll").getAttribute("aria-label"),
    column_headers: await manager.getByRole("columnheader").allTextContents(),
  };
  verify(results.keyboard.reservation_table.caption === "Reservations", "Reservation table has no useful caption.");
  verify(/Reservations, scrollable table/.test(results.keyboard.reservation_table.region_label ?? ""), "Reservation table scroll region lacks an accessible name.");
  verify(results.keyboard.reservation_table.column_headers.length === 5, "Reservation table does not expose its column headers.");
  await managerContext.close();

  const dinerContext = await browser.newContext({ viewport: { width: 390, height: 844 }, colorScheme: "dark" });
  const diner = await dinerContext.newPage();
  await inspectPage(diner, "diner-menu-mobile", relative(dailyMenu), ".store-card", "07-diner-menu-mobile.png", true);
  await contrastSamples(diner, "diner-mobile-dark");
  const trigger = diner.getByRole("button", { name: /^View / }).first();
  const triggerName = await trigger.getAttribute("aria-label");
  verify(triggerName, "Diner menu card is missing an accessible name.");
  const itemName = triggerName.replace(/^View\s+/, "");
  await trigger.click();
  const itemDialog = diner.getByRole("dialog", { name: itemName });
  await itemDialog.waitFor({ timeout: 6_000 });
  results.dialogs.item = {
    named: true,
    initially_focused_within: await itemDialog.evaluate((element) => element.contains(document.activeElement)),
  };
  for (let index = 0; index < 10; index += 1) {
    await diner.keyboard.press("Tab");
    const stillInside = await itemDialog.evaluate((element) => element.contains(document.activeElement));
    verify(stillInside, "Keyboard focus escaped the open item dialog.");
  }
  await diner.keyboard.press("Escape");
  await diner.waitForFunction(() => !document.querySelector("dialog.product-dialog")?.open);
  results.dialogs.item.escape_closes = true;

  await diner.getByRole("button", { name: /^View / }).first().click();
  await diner.getByRole("button", { name: /Add to this order/ }).click();
  const cart = diner.getByRole("button", { name: /Open order, 1 items/ });
  await cart.waitFor({ timeout: 6_000 });
  await cart.click();
  const checkout = diner.getByRole("dialog", { name: "Ready when you are." });
  await checkout.waitFor({ timeout: 6_000 });
  await contrastSamples(diner, "diner-checkout-mobile-dark");
  results.dialogs.checkout = { named: true, initially_focused_within: await checkout.evaluate((element) => element.contains(document.activeElement)) };
  await checkout.getByRole("button", { name: "Send for staff acceptance" }).click();
  const checkoutStatus = checkout.getByRole("status");
  await checkoutStatus.waitFor({ timeout: 5_000 });
  results.keyboard.order_error = { announced: /provide your name and phone number/i.test(await checkoutStatus.innerText()), role: await checkoutStatus.getAttribute("role") };
  verify(results.keyboard.order_error.announced, "Empty diner checkout did not announce a validation error.");
  await diner.screenshot({ path: resolve(screenshots, "08-diner-checkout-validation-mobile.png"), fullPage: true });
  await dinerContext.close();

  const ownerContext = await browser.newContext({ viewport: { width: 1440, height: 1000 }, colorScheme: "dark" });
  const owner = await ownerContext.newPage();
  await login(owner, "pilot1.tenant_owner@demo.chowly.ng");
  await inspectPage(owner, "owner-admin-desktop", "/manage/settings", "h1", "09-owner-settings-desktop.png");
  await contrastSamples(owner, "owner-desktop-dark");
  await ownerContext.close();

  const motionContext = await browser.newContext({ viewport: { width: 1280, height: 900 }, reducedMotion: "reduce" });
  const motion = await motionContext.newPage();
  await motion.goto(new URL("/", base).toString(), { waitUntil: "domcontentloaded" });
  await settle(motion, "h1");
  results.motion.reduced_motion = await motion.locator(".ambient-glow-sun").evaluate((element) => getComputedStyle(element).animationDuration);
  verify(Number.parseFloat(results.motion.reduced_motion) <= 0.00002, `Reduced motion is not applied (${results.motion.reduced_motion}).`);
  await motionContext.close();
} catch (error) {
  results.failure = error instanceof Error ? error.message : String(error);
  throw error;
} finally {
  await browser.close();
  await writeFile(resultFile, `${JSON.stringify(results, null, 2)}\n`);
}

console.log(JSON.stringify(results, null, 2));
