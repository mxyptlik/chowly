import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const source = async (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");

test("a manager creating a manual order chooses an assigned waiter by name", async () => {
  const manualOrder = await source("components/staff/manual-order-builder.tsx");
  assert.match(manualOrder, /Assigned waiter/);
  assert.match(manualOrder, /\/staff\/members\?location_id=/);
  assert.match(manualOrder, /waiter_id/);
});

test("the service-floor amendment control uses the PATCH contract", async () => {
  const ops = await source("app/ops/page.tsx");
  assert.match(ops, /method:"PATCH"/);
  assert.match(ops, /Line amendment/);
});

test("camera scanning mounts its video before starting the stream", async () => {
  const scanner = await source("components/staff/reservation-pass-scanner.tsx");
  assert.match(scanner, /setState\("scanning"\);[\s\S]{0,500}videoRef\.current/);
  assert.match(scanner, /if \(!video\) \{[\s\S]{0,200}stopCamera/);
});

test("direct staff routes enforce their role boundaries before mounting workspace effects", async () => {
  const verifyReservation = await source("app/ops/verify-reservation/page.tsx");
  const admin = await source("app/admin/page.tsx");
  assert.match(verifyReservation, /RequireStaffAccess/);
  assert.match(verifyReservation, /roles=\{\["WAITER",\s*"MANAGER"\]\}/);
  assert.match(admin, /RequireStaffAccess/);
  assert.match(admin, /roles=\{\["PLATFORM_ADMIN"\]\}/);
  assert.match(admin, /Platform administration restricted/);
});

test("management screens match the backend's explicit role contracts", async () => {
  const chrome = await source("components/staff/staff-chrome.tsx");
  const reservations = await source("app/manage/reservations/page.tsx");
  const feedback = await source("app/manage/feedback/page.tsx");
  const workspaces = await source("components/staff/management-workspaces.tsx");
  assert.match(chrome, /href: "\/manage\/reservations", label: "Reservations", roles: \["WAITER", "MANAGER"\]/);
  assert.match(chrome, /href: "\/manage\/feedback", label: "Feedback", roles: \["MANAGER"\]/);
  assert.match(reservations, /roles=\{\["WAITER","MANAGER"\]\}/);
  assert.match(feedback, /roles=\{\["MANAGER"\]\}/);
  assert.match(workspaces, /const manager=session\?\.roles\.includes\("MANAGER"\)\?\?false/);
  assert.match(workspaces, /\{manager&&<>.*Issue full refund/s);
});

test("preparation staff can only publish and change inventory for their own station", async () => {
  const menu = await source("app/manage/menu/page.tsx");
  assert.match(menu, /const\s+stationItemType\s*=/);
  assert.match(menu, /item\.item_type===stationItemType/);
  assert.match(menu, /setItemType\(stationItemType\)/);
  assert.match(menu, /stationItemType==="FOOD"\?"Food · kitchen":"Drink · bar"/);
});
