/**
 * Deterministic, isolated Chromium proof for staff-management workflows.
 * It deliberately never serialises raw invitation capabilities, passwords,
 * session cookies, or customer contact data into screenshots or result files.
 */
import { chromium } from "@playwright/test";
import { mkdir, writeFile } from "node:fs/promises";
import { resolve } from "node:path";

const base = "http://localhost:3000";
const password = "ChowlyDemo!2026";
const invitedPassword = "ChowlyInvite!2026";
const output = resolve(import.meta.dirname, "../../docs/verification/screenshots/09-management");
const resultPath = resolve(import.meta.dirname, "../../docs/verification/management-execution-results.json");
const runLabel = `Management verification ${Date.now()}`;
const invitedEmail = `management-${Date.now()}@demo.chowly.ng`;
const results = { executed_at: new Date().toISOString(), cases: [] };

await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true });

function record(name, pass, detail = {}) {
  results.cases.push({ name, pass, ...detail });
  if (!pass) throw new Error(`${name} failed: ${JSON.stringify(detail)}`);
}

async function signedIn(email) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, colorScheme: "dark" });
  const page = await context.newPage();
  page.setDefaultTimeout(15_000);
  await page.goto(`${base}/login`, { waitUntil: "domcontentloaded" });
  await page.getByLabel("Work email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: /sign in to chowly/i }).click();
  await page.waitForURL(/\/(ops|prep|manage|admin)/, { timeout: 15_000 });
  return { context, page };
}

async function screenshot(page, filename) {
  await page.screenshot({ path: resolve(output, filename), fullPage: true });
}

try {
  const { context: managerContext, page: manager } = await signedIn("pilot1.manager@demo.chowly.ng");

  await manager.goto(`${base}/manage/reports`, { waitUntil: "domcontentloaded" });
  await manager.getByRole("button", { name: "Load report" }).click();
  await manager.locator("dl.report-grid").waitFor();
  const reportValues = await manager.locator("dl.report-grid > div").count();
  record("manager loads assigned-location operations report", reportValues > 0, { report_values: reportValues });
  await screenshot(manager, "10-manager-reports-loaded.png");

  await manager.goto(`${base}/manage/settings`, { waitUntil: "domcontentloaded" });
  await manager.getByText("You do not have access to this workspace.").waitFor();
  const managerSettingsText = await manager.locator("body").innerText();
  const managerSettingsDenied = /do not have access to this workspace/i.test(managerSettingsText)
    && await manager.getByRole("button", { name: "Save settings" }).count() === 0;
  record("manager cannot open owner-only settings", managerSettingsDenied);
  await screenshot(manager, "11-manager-settings-restricted.png");

  await manager.goto(`${base}/manage/team`, { waitUntil: "domcontentloaded" });
  await manager.getByRole("heading", { name: "Invite a team member" }).waitFor();
  const managerAssignmentHidden = await manager.getByRole("heading", { name: "Staff assignments" }).count() === 0;
  record("manager cannot list or replace tenant assignments", managerAssignmentHidden);
  await screenshot(manager, "12-manager-team-operational-invite-only.png");

  await manager.getByLabel("Name").fill(runLabel);
  await manager.getByLabel("Work email").fill(invitedEmail);
  await manager.getByLabel("Role").selectOption("BARTENDER");
  const invitationResponse = manager.waitForResponse((response) => response.url().includes("/staff/auth/invitations") && response.request().method() === "POST");
  await manager.getByRole("button", { name: "Create invitation" }).click();
  const invitationStatus = (await invitationResponse).status();
  await manager.getByText(/Invitation token \(show once\):/).waitFor();
  const invitationText = await manager.locator("body").innerText();
  const token = invitationText.match(/Invitation token \(show once\):\s*([^\s.]+)/)?.[1];
  record("manager invites an operational bartender", invitationStatus === 201 && Boolean(token), { invitation_status: invitationStatus });

  // Move away before the next capture so the one-time capability never appears in evidence.
  await manager.goto(`${base}/manage/reports`, { waitUntil: "domcontentloaded" });
  await managerContext.close();

  const acceptanceContext = await browser.newContext({ viewport: { width: 1280, height: 900 }, colorScheme: "dark" });
  const acceptance = await acceptanceContext.newPage();
  acceptance.setDefaultTimeout(15_000);
  await acceptance.goto(`${base}/login/accept?token=${encodeURIComponent(token)}`, { waitUntil: "domcontentloaded" });
  await acceptance.getByLabel("Choose a password").fill(invitedPassword);
  await acceptance.getByRole("button", { name: "Activate staff account" }).click();
  await acceptance.waitForURL(/\/prep/, { timeout: 15_000 });
  record("invited bartender accepts one-time invitation", /\/prep/.test(acceptance.url()));
  await screenshot(acceptance, "13-invited-bartender-prep.png");
  await acceptanceContext.close();

  const { context: ownerContext, page: owner } = await signedIn("pilot1.tenant_owner@demo.chowly.ng");
  await owner.goto(`${base}/manage/settings`, { waitUntil: "domcontentloaded" });
  await owner.getByRole("button", { name: "Save settings" }).waitFor();
  const settingsResponse = owner.waitForResponse((response) => response.url().includes("/staff/locations/") && response.request().method() === "PATCH");
  await owner.getByRole("button", { name: "Save settings" }).click();
  const settingsStatus = (await settingsResponse).status();
  await owner.getByText("Location settings saved.").waitFor();
  record("tenant owner saves location settings", settingsStatus === 200, { settings_status: settingsStatus });
  await screenshot(owner, "14-owner-settings-saved.png");

  await owner.goto(`${base}/manage/team`, { waitUntil: "domcontentloaded" });
  const memberSelect = owner.getByLabel("Staff member");
  await memberSelect.waitFor();
  const invitedOption = memberSelect.locator("option").filter({ hasText: runLabel }).first();
  await invitedOption.waitFor({ state: "attached", timeout: 15_000 });
  const invitedValue = await invitedOption.getAttribute("value");
  record("owner sees newly invited staff in tenant roster", Boolean(invitedValue));
  await memberSelect.selectOption(invitedValue);
  const bartender = owner.getByRole("checkbox", { name: "BARTENDER" });
  const waiter = owner.getByRole("checkbox", { name: "WAITER" });
  await bartender.uncheck();
  await waiter.check();
  const assignmentResponse = owner.waitForResponse((response) => response.url().includes("/assignments") && response.request().method() === "PUT");
  await owner.getByRole("button", { name: "Save assignments" }).click();
  const assignmentStatus = (await assignmentResponse).status();
  await owner.getByText("Staff roles and locations saved.").waitFor();
  record("tenant owner replaces invited staff role assignment", assignmentStatus === 200, { assignment_status: assignmentStatus });
  await screenshot(owner, "15-owner-staff-assignment-saved.png");
  await ownerContext.close();

  const reassignedContext = await browser.newContext({ viewport: { width: 1280, height: 900 }, colorScheme: "dark" });
  const reassigned = await reassignedContext.newPage();
  reassigned.setDefaultTimeout(15_000);
  await reassigned.goto(`${base}/login`, { waitUntil: "domcontentloaded" });
  await reassigned.getByLabel("Work email").fill(invitedEmail);
  await reassigned.getByLabel("Password").fill(invitedPassword);
  await reassigned.getByRole("button", { name: /sign in to chowly/i }).click();
  await reassigned.waitForURL(/\/ops/, { timeout: 15_000 });
  await reassigned.getByRole("heading", { name: "Keep the room in motion." }).waitFor();
  record("new login receives owner-updated waiter workspace", /\/ops/.test(reassigned.url()));
  await screenshot(reassigned, "16-reassigned-staff-waiter-workspace.png");
  await reassignedContext.close();
} catch (error) {
  results.error = error instanceof Error ? error.message : String(error);
} finally {
  await browser.close();
  await writeFile(resultPath, JSON.stringify(results, null, 2));
}

console.log(JSON.stringify(results, null, 2));
if (results.error || results.cases.some((entry) => !entry.pass)) process.exitCode = 1;
