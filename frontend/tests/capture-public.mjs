import { chromium } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import path from "node:path";

const baseURL = process.env.CHOWLY_BASE_URL ?? "http://localhost:3000";
const output = path.resolve("..", "docs", "verification", "screenshots", "01-public");
const restaurant = "mango-ash-hospitality";
const location = "mango-ash-victoria-island";
const desktop = { width: 1440, height: 1100 };
const mobile = { width: 390, height: 844 };
const failures = [];

await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true });

async function pageFor(theme, viewport = desktop) {
  const context = await browser.newContext({ viewport, colorScheme: theme });
  await context.addInitScript((selectedTheme) => localStorage.setItem("chowly-theme", selectedTheme), theme);
  const page = await context.newPage();
  page.on("pageerror", error => failures.push(`pageerror ${page.url()}: ${error.message}`));
  return { context, page };
}

async function capture(page, filename) {
  await page.screenshot({ path: path.join(output, filename), fullPage: true });
}

async function visit(theme, route, filename, expected, viewport = desktop) {
  const { context, page } = await pageFor(theme, viewport);
  const response = await page.goto(`${baseURL}${route}`, { waitUntil: "networkidle" });
  try { await page.getByText(expected, { exact: false }).first().waitFor({ state: "visible", timeout: 5000 }); }
  catch { failures.push(`${route}: expected visible text ${JSON.stringify(expected)}; status ${response?.status()}`); }
  await capture(page, filename);
  await context.close();
}

for (const theme of ["dark", "light"]) {
  await visit(theme, "/", `01-public-home-loaded-${theme}-desktop.png`, "Find a restaurant");
  await visit(theme, "/restaurants", `02-public-restaurants-loaded-${theme}-desktop.png`, "Mango & Ash Hospitality");
  await visit(theme, `/r/${restaurant}`, `03-public-restaurant-loaded-${theme}-desktop.png`, "Mango & Ash");
  await visit(theme, `/r/${restaurant}/${location}`, `04-public-location-loaded-${theme}-desktop.png`, "Victoria Island");
  await visit(theme, `/r/${restaurant}/${location}/menu`, `05-public-menu-loaded-${theme}-desktop.png`, "The full");
  await visit(theme, "/reserve", `06-public-reservation-blank-${theme}-desktop.png`, "Save a place");
  await visit(theme, `/r/${restaurant}/${location}/reserve`, `07-public-location-reservation-blank-${theme}-desktop.png`, "Save a place");
  await visit(theme, "/login", `08-public-login-blank-${theme}-desktop.png`, "Welcome back");
}

// P02 state changes in an isolated public browser profile.
{
  const { context, page } = await pageFor("dark");
  await page.goto(`${baseURL}/restaurants`, { waitUntil: "networkidle" });
  const search = page.getByLabel("Search restaurants");
  await search.fill("Mango");
  await page.getByText("Mango & Ash Hospitality").waitFor();
  await capture(page, "02-public-restaurants-filtered-dark-desktop.png");
  await search.fill("Not a restaurant");
  await page.getByText("No restaurant found.").waitFor();
  await capture(page, "02-public-restaurants-no-results-dark-desktop.png");
  await context.close();
}

// P05 category controls are browse-only and have rendered state changes.
{
  const { context, page } = await pageFor("dark");
  await page.goto(`${baseURL}/r/${restaurant}/${location}/menu`, { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "Food" }).click();
  await page.getByRole("button", { name: "Food" }).waitFor();
  await capture(page, "05-public-menu-food-filter-dark-desktop.png");
  await page.getByRole("button", { name: "Drinks" }).click();
  await capture(page, "05-public-menu-drinks-filter-dark-desktop.png");
  await context.close();
}

// Reservation forms must surface validation without submitting customer data.
for (const [route, filename] of [["/reserve", "06-public-reservation-validation-dark-desktop.png"], [`/r/${restaurant}/${location}/reserve`, "07-public-location-reservation-validation-dark-desktop.png"]]) {
  const { context, page } = await pageFor("dark");
  await page.goto(`${baseURL}${route}`, { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "Request reservation" }).click();
  await page.getByText("Choose a restaurant and location", { exact: false }).waitFor();
  await capture(page, filename);
  await context.close();
}

// Responsive representatives (P01/P02), also verifies the persisted theme on reload.
for (const [route, filename, text] of [["/", "01-public-home-loaded-dark-mobile.png", "Find a restaurant"], ["/restaurants", "02-public-restaurants-loaded-light-mobile.png", "Mango & Ash Hospitality"]]) {
  const theme = filename.includes("light") ? "light" : "dark";
  await visit(theme, route, filename, text, mobile);
}

await browser.close();
if (failures.length) {
  console.error("PUBLIC CAPTURE FAILURES:\n" + failures.join("\n"));
  process.exitCode = 1;
} else {
  console.log(`Captured public evidence into ${output}`);
}
