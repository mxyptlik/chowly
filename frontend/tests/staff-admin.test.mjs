import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const source = async (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");

test("staff operations preserve server-owned identity and versioned transitions", async () => {
  const ops = await source("app/ops/page.tsx");
  const manualOrder = await source("components/staff/manual-order-builder.tsx");
  assert.match(manualOrder, /\/staff\/orders\/manual/);
  assert.match(manualOrder, /\/manual-order-catalog/);
  assert.match(manualOrder, /Choose a table/);
  assert.match(manualOrder, /store-card-grid/);
  assert.match(manualOrder, /<Dialog open=\{Boolean\(active\)\}/);
  assert.match(manualOrder, /Add to order/);
  assert.doesNotMatch(manualOrder, /Menu item ID|Table ID/);
  assert.match(ops, /Destination table/);
  assert.doesNotMatch(ops, /Destination table ID/);
  assert.match(ops, /\/staff\/members\?location_id=/);
  assert.match(ops, /Eligible waiter/);
  assert.doesNotMatch(ops, /Eligible waiter staff ID/);
  assert.match(ops, /expected_version/);
  assert.match(ops, /Idempotency-Key/);
  assert.match(ops, /This action needs a confirmed connection/);
  assert.match(ops, /allowOffline=false/);
  assert.match(ops, /payments\/cash[\s\S]*"Cash payment",\{idempotent:true\}/);
  assert.match(ops, /const canSetWait=selected\?\.status==="PREPARING"\|\|selected\?\.status==="READY_FOR_SERVICE"/);
  assert.match(ops, /Accept this order before changing its wait time/);
  assert.doesNotMatch(ops, /staff_id/);
  assert.doesNotMatch(ops, /waiter_id/);
});

test("staff chrome provides role-aware sidebar navigation and marks the current workspace", async () => {
  const chrome = await source("components/staff/staff-chrome.tsx");
  assert.match(chrome, /workspace-sidebar/);
  assert.match(chrome, /usePathname/);
  assert.match(chrome, /Service floor/);
  assert.match(chrome, /Reservation check-in/);
  assert.match(chrome, /Kitchen & bar/);
  assert.match(chrome, /Tables & QR/);
  assert.match(chrome, /\/manage\/tables/);
  assert.match(chrome, /\/manage\/menu/);
  assert.match(chrome, /aria-current=\{pathname === link\.href \? "page" : undefined\}/);
});

test("tables and menu are independent operational workspaces", async () => {
  const tables = await source("app/manage/tables/page.tsx");
  const menu = await source("app/manage/menu/page.tsx");
  assert.match(tables, /\/tables\/\$\{encodeURIComponent\(table.id\)\}\/qr/);
  assert.match(tables, /QRCode\.toDataURL/);
  assert.match(tables, /Copy menu link/);
  assert.match(menu, /\/menu\/categories/);
  assert.match(menu, /\/menu\/items/);
  assert.match(menu, /store-card-grid/);
  assert.doesNotMatch(menu, /Menu item ID/);
});

test("preparation and complaint surfaces keep contact data in the correct role room", async () => {
  const prep = await source("app/prep/page.tsx");
  const admin = await source("app/admin/page.tsx");
  assert.doesNotMatch(prep, /phone|email|customer_name/i);
  assert.match(admin, /Manager complaint inbox/);
  assert.match(admin, /\/complaints\/\$\{row.id\}\/resolve/);
});

test("administration wires table QR, reservations, menu structure, hours, retention, and reporting", async () => {
  const admin = await source("app/admin/page.tsx");
  for (const route of [
    "/tables/${table.id}/qr/regenerate",
    "/reservations/${row.id}/confirm",
    "/menu/categories",
    "/modifier-groups",
    "/operating-hours",
    "/staff/tenant/retention",
    "/reports/operations?start_date=",
    "/platform/tenants/${tenantId}/retention/approve",
  ]) assert.ok(admin.includes(route), `missing ${route}`);
  assert.match(admin, /This decision requires a confirmed connection/);
});

test("owner settlement, member assignment, and platform bootstrap use their protected contracts", async () => {
  const admin = await source("app/admin/page.tsx");
  for (const route of [
    "/staff/orders/${id}/payment-details",
    "/staff/auth/members",
    "/staff/auth/members/${selected}/assignments",
    "/platform/tenants/bootstrap",
  ]) assert.ok(admin.includes(route), `missing ${route}`);
  assert.match(admin, /receipt_delivery/);
  assert.match(admin, /location_ids/);
  assert.match(admin, /owner_invitation/);
  assert.doesNotMatch(admin, /staff_id/);
  assert.doesNotMatch(admin, /waiter_id/);
});

test("manager workflows are independent guarded workspaces with list-driven selection", async () => {
  const routes = ["reservations", "payments", "feedback", "team", "reports", "settings"];
  for (const route of routes) {
    const page = await source(`app/manage/${route}/page.tsx`);
    assert.match(page, /RequireStaffAccess/);
    assert.match(page, /StaffChrome/);
  }
  const workspaces = await source("components/staff/management-workspaces.tsx");
  assert.match(workspaces, /\/staff\/orders/);
  assert.match(workspaces, /Choose an authorized order/);
  assert.match(workspaces, /\/staff\/locations\/\$\{locationId\}\/reservations/);
  assert.match(workspaces, /\/reports\/operations\?start_date=/);
  assert.match(workspaces, /key !== "location_id"/);
  assert.doesNotMatch(workspaces, /Served order ID|Menu item ID|Table ID/);
});

test("the standalone owner team workspace can list and replace staff assignments", async () => {
  const management = await source("components/staff/management-workspaces.tsx");
  assert.match(management, /\/staff\/auth\/members/);
  assert.match(management, /\/staff\/auth\/members\/\$\{selectedMember\}\/assignments/);
  assert.match(management, /Staff assignments/);
  assert.match(management, /Save assignments/);
});
