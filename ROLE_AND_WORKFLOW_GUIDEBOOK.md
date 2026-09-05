# Chowly Role & Workflow Guidebook

**Audience:** restaurant operators, pilot testers, product/design teams, and implementation teams.

**Scope:** Chowly V1 — multi-tenant, multi-location restaurant QR ordering and operations. This is a product-operating guide, not a substitute for the backend permission checks.

## 1. How identity, URLs, and access work

Chowly does **not** put a user role, tenant ID, or staff ID in a URL. URLs identify a screen or public capability only:

| URL | Meaning | Authority source |
|---|---|---|
| `/login` | Staff sign-in | Email/password create a signed staff session. |
| `/ops` | Service-floor workspace | Signed-in role and assigned location. |
| `/prep` | Kitchen/bar workspace | Signed-in role and assigned location. |
| `/admin` | Administration workspace | Signed-in role, tenant, and assigned location. |
| `/dine/{daily-qr-token}` | Diner table menu | Opaque daily QR capability, not a staff role. |
| `/order/{order-id}` | Diner order view | Browser-held opaque order capability, not the order ID alone. |
| `/reserve` | Public reservation request | No diner account. |

The browser uses an HttpOnly staff session cookie. The backend resolves the authenticated Staff Account and verifies the role, tenant, and explicit Location assignment for each protected action. Changing a URL must never grant more data or authority. A foreign or guessed resource should be a non-enumerating `404`; a known-but-disallowed action should be a `403`.

## 2. Scope vocabulary

| Term | Meaning |
|---|---|
| Platform | Chowly as a whole, across Restaurant Tenants. |
| Restaurant Tenant | One independent restaurant business/customer. |
| Restaurant Location | One physical branch belonging to a Restaurant Tenant. |
| Staff Account | One signed-in employee identity. It may have more than one role and explicit location assignments. |
| Customer | Required internal record for every order; diners do not receive a Chowly account. |

Every restaurant role is limited to its Restaurant Tenant. Every operational view and write is also limited to its assigned Restaurant Location, unless a future role grant explicitly expands that scope.

## 3. Role matrix

| Role | Sees | Can do | Cannot do |
|---|---|---|---|
| **Platform Administrator** | Platform provisioning and approved retention controls; no ordinary restaurant operational data unless separately assigned. | Bootstrap a Restaurant Tenant, initial Location, operating hours, and optional Tenant Owner invitation; approve retention extensions beyond normal tenant limits. | Work a restaurant’s order queue, view diner contact/history, manage a restaurant menu, refund an order, or silently enter a tenant’s data. |
| **Tenant Owner** | Tenant-level staff/location assignments, tenant retention settings, and assigned-location administration/reporting. | Invite/manage staff role/location grants; manage assigned locations’ tables, menu, operating settings, reports; request retention changes. | See another tenant; resolve manager-only complaints; work prep queues unless also explicitly granted Chef/Bartender; impersonate Platform Admin. |
| **Manager** | Assigned-location orders, diner contact in the service context, reservations, complaints, payment/refund details, location reports, menus/tables. | Accept/reassign orders; update wait times; transfer/cancel with audit reasons; serve; record cash; issue one full refund with reason; manage menu/tables/hours; resolve complaints; invite staff. | Access another location/tenant; act as Platform Admin; change Tenant Owner role/location assignments; view prep-only operations without a prep role. |
| **Waiter** | Assigned-location service queue, order details, diner contact needed for service, table QR controls, reservations assigned to service. | Create manual fallback order; accept and own an order; set wait time; transfer/cancel with reason; serve; record cash; display/regenerate a table QR; confirm/seat/cancel reservations where assigned. | Refund; view/resolve complaints; see settlement detail; manage staff grants, retention, menu structure, tenant settings, or another location. |
| **Chef** | Assigned-location **food/kitchen** preparation lines: item, quantity, modifiers, special instructions, table label/status. | Claim food lines; mark their claimed food lines ready. | See customer name, phone, email, complaints, payments, refunds, full service queue, or bar-only lines; accept/serve/cancel orders. |
| **Bartender** | Assigned-location **drink/bar** preparation lines: item, quantity, modifiers, special instructions, table label/status. | Claim drink lines; mark their claimed drink lines ready. | See customer name, phone, email, complaints, payments, refunds, full service queue, or kitchen-only lines; accept/serve/cancel orders. |
| **Diner** *(not a staff role)* | Their QR menu and only the secure order/reservation state created on that browser/capability. | View menu; make a separate order using required name/phone and optional email; switch to takeaway/cancel before acceptance; pay after service; read receipt; rate; optionally complain; request reservation. | Create a Chowly account; see staff/other diners/orders; pay cash; issue refund; change an accepted order; access an order by guessing its ID. |

## 4. Workspaces and first destination after login

| Role | Current primary workspace | Current URL | Expected first task |
|---|---|---|---|
| Platform Administrator | Platform controls within administration | `/admin` | Create/approve tenant-level platform records. |
| Tenant Owner | Tenant governance within administration | `/admin` | Check tenant health, staff/location coverage, policy and reports. |
| Manager | Service floor, then location administration | `/ops`, `/admin` | Clear unaccepted orders and operating exceptions. |
| Waiter | Service floor | `/ops` | Accept/own service orders and keep diners updated. |
| Chef | Preparation board | `/prep` | Claim and complete kitchen lines. |
| Bartender | Preparation board | `/prep` | Claim and complete bar lines. |

### Current implementation note

The app currently has three shared staff routes: `/ops`, `/prep`, and `/admin`. Navigation and visible tabs are role-filtered; backend API authorization is the security boundary. Platform Administrators and Tenant Owners may need to type `/admin` directly after login because their dedicated landing redirect is not yet implemented.

## 5. Workflow by role

### Platform Administrator workflow

1. Sign in at `/login`.
2. Open `/admin`.
3. Open the Platform section.
4. Bootstrap a new Restaurant Tenant with its first Restaurant Location and operating hours.
5. Optionally generate a one-time Tenant Owner invitation.
6. Review/approve an exceptional retention request.
7. Sign out; do not perform ordinary restaurant operations as a Platform Administrator.

### Tenant Owner workflow

1. Sign in at `/login`, then open `/admin`.
2. Select the active Restaurant Location when the tenant has multiple locations.
3. Review reports, staff assignments, retention setting, and location administration.
4. Invite staff and assign their roles and allowed locations.
5. Configure menu, tables, operating hours, VAT/service charge, and QR availability for an assigned location.
6. Review reports and resolve policy-level exceptions.

### Manager workflow

1. Sign in at `/login`; begin in `/ops`.
2. Review submitted orders; accept one when ready to commit service capacity.
3. Set or revise the wait estimate, keeping the diner informed.
4. Reassign a waiter if operationally necessary, with a reason.
5. Monitor kitchen/bar readiness and mark a completed order served.
6. Use `/admin` for reservations, table/QR, menu availability, reports, refund, and complaint work.
7. Resolve a complaint with a recorded resolution note.
8. Sign out or switch only to an explicitly assigned location.

### Waiter workflow

1. Sign in at `/login`; begin in `/ops`.
2. Create a manual fallback order only when QR ordering cannot be used, or receive a diner’s QR order.
3. Accept and become the order owner; choose a recommended/manual wait time.
4. Communicate directly with the diner only when needed for service.
5. Coordinate the kitchen/bar; serve once all active lines are ready.
6. Record cash when paid in person, or let the diner use the secure online payment flow.
7. Use an audit-reasoned transfer/cancellation only when the real-world situation requires it.
8. Generate/re-generate a fresh table QR if a table’s existing QR must be invalidated.

### Chef workflow

1. Sign in at `/login`; go to `/prep`.
2. View only the kitchen/food queue for the active assigned location.
3. Claim a pending food line before beginning preparation.
4. Read quantity, modifiers, and special instruction.
5. Mark the line ready when physically ready for service.
6. Do not copy customer contact data; it is intentionally unavailable.

### Bartender workflow

1. Sign in at `/login`; go to `/prep`.
2. View only the bar/drink queue for the active assigned location.
3. Claim a pending drink line.
4. Prepare according to selected modifiers/instructions.
5. Mark the line ready when it can be served.
6. Do not access diner, payment, or complaint data.

### Diner workflow

1. Scan the physical table’s daily QR; this opens `/dine/{opaque-token}`.
2. Browse current, all-in prices; choose modifiers and an optional special instruction.
3. Enter required name and phone; email is optional and receipt-oriented.
4. Submit a **separate** order for the table.
5. Use the private order status page on the same browser.
6. Before acceptance only: cancel or switch to takeaway.
7. After service: pay via mock Card, Transfer, or Wallet; cash is staff-recorded.
8. Read the digital receipt, rate each item/order, and optionally submit a complaint.

## 6. Sensitive-data rules

- A diner’s name, phone, and optional email are visible only in the appropriate waiter/manager service context for the tenant/location that captured them.
- Chef and Bartender workspaces must never render customer contact data.
- Complaint content is manager-only; waiters receive no complaint inbox.
- Payment/refund detail is manager/owner-only. A diner sees only their own secure receipt/refund state.
- Platform administration does not imply tenant customer/order-data access.

## 7. Tenant Owner dashboard recommendation

**Recommendation: build a dedicated Tenant Owner workspace.** The current shared `/admin` page is a workable V1 control room, but it does not give an owner the right mental model.

Create a dedicated route such as `/owner` with a tenant-level overview:

1. **Today across locations:** order volume, revenue, payment/refund exceptions, wait time, cancellation rate, ratings, unresolved complaints.
2. **Location health:** open/closed status, active tables, live order load, kitchen/bar backlog, sold-out items.
3. **People and access:** staff invitations, role/location assignments, unassigned locations, inactive accounts.
4. **Governance:** retention policy, requested platform approvals, audit-log shortcuts.
5. **Configuration:** location switching, menus, charges/hours/tables—kept as deliberate management actions rather than the home screen.

The Owner dashboard should aggregate only locations assigned to that owner and should not collapse the Manager’s real-time service workspace into a generic “admin” dashboard.

## 8. Pilot test accounts

All development demo accounts use the password `ChowlyDemo!2026`.

| Role | Pilot 1 email |
|---|---|
| Platform Administrator | `platform.admin@demo.chowly.ng` |
| Tenant Owner | `pilot1.tenant_owner@demo.chowly.ng` |
| Manager | `pilot1.manager@demo.chowly.ng` |
| Waiter | `pilot1.waiter@demo.chowly.ng` |
| Chef | `pilot1.chef@demo.chowly.ng` |
| Bartender | `pilot1.bartender@demo.chowly.ng` |

Use `pilot2` through `pilot7` to test tenant isolation. Never use these deterministic accounts outside local development.

## 9. Implementation follow-ups

Before production release, complete these experience gaps:

- Dedicated Tenant Owner dashboard and post-login redirect.
- Dedicated Platform Administrator landing route and navigation item.
- Server-side route guards for every staff page in addition to existing backend API authorization.
- Browser E2E/accessibility proof for each role, including tenant/location isolation.
- Remove raw-ID entry from operational UI (e.g. assignment/table transfer) in favour of scoped searchable selections.

