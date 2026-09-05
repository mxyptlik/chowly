# Chowly workspace and list-contract overhaul

## Decision

Chowly will use **one primary operational purpose per route**. A route may use
small local panels, filters, drawers, and dialogs, but it must not hide several
unrelated operational areas behind a single administration tab.

The frontend must never ask a staff member to supply a database ID. UI controls
show names, labels, and cards; the browser sends the opaque ID selected from a
server-authorized list to the API.

## What exists today

- The database has table, menu, order, reservation, staff, payment, feedback,
  location, tenant, and QR models with scoped routers.
- Tables already have a list endpoint and daily QR presentation/regeneration
  endpoints.
- Menu categories and menu items have individual list and mutation endpoints.
- Orders, preparation lines, reservations, staff members, locations and public
  restaurants already have some list endpoints.
- `/admin` currently groups tables/QR, reservations, menu, finance, feedback,
  team, reports, and platform actions in one page. This is the main UX problem.
- SQLAlchemy already enables connection validation with `pool_pre_ping=True`.
  Pool size, overflow, recycle and timeout are not explicitly configured yet.

## Non-negotiable API rule

Every staff-facing domain collection receives a **role- and location-scoped
list endpoint** with one shared query contract:

```
GET /api/v1/staff/...?...&limit=25&cursor=<opaque-next-cursor>
```

Responses use:

```
{
  "items": [...],
  "next_cursor": "... | null",
  "total": 123
}
```

- Default `limit`: 25; maximum: 100.
- A cursor, never offset pagination, is used for large mutable collections.
- Filters are explicit named query parameters and validated by Pydantic.
- Sorts are allow-listed, stable, and end with an ID tie-breaker.
- A list returns only data that the authenticated role may see. It never leaks
  another tenant/location's objects merely because an ID is guessed.
- "Delete" is not universal. Orders, payments, audit events, and customer
  history use their approved lifecycle action (cancel, refund, retain/archive),
  not destructive deletion.

## Startup and readiness design

1. **Migrations first.** `alembic upgrade head` owns schema creation; the API
   never calls `Base.metadata.create_all`.
2. **Startup checks.** FastAPI lifespan checks PostgreSQL with `SELECT 1` and
   Redis with `PING`, then logs a structured `application_ready` event only
   after both succeed.
3. **Daily QR availability.** Startup runs an idempotent `ensure_daily_qrs`
   job for enabled tables at each active location. It creates a token only when
   today's valid token is absent. It does **not** rotate a valid token on every
   restart; forced regeneration remains an audited waiter/manager action.
4. **Background safety net.** Dramatiq runs the same idempotent job shortly
   after local midnight and at worker start. The QR retrieval endpoint also
   ensures today's QR as a fallback, so a missed scheduler run cannot block a
   diner.
5. **Observable logs.** Log database connected, Redis connected, migration
   revision, daily QR count ensured, worker connected, and application ready.
   Do not log raw QR tokens, session cookies, or customer contact details.
6. **Connection pool later.** Add Postgres settings for `pool_size`,
   `max_overflow`, `pool_timeout`, `pool_recycle`, and pool metrics after a
   baseline load measurement. Pooling improves concurrent database connections;
   it does not fix a slow browser bundle, a missing API call, or a bad route.

## Target staff routes

### Shared shell

`StaffChrome` is the persistent role-aware sidebar. It displays only routes
the current staff account may use, the selected location, connection state,
pending safe offline work, restaurant directory, and sign out.

### Waiter

| Route | Purpose | Primary lists/actions |
| --- | --- | --- |
| `/ops/orders` | Service floor | Orders; accept, wait time, transfer, amend, cancel, serve |
| `/ops/orders/new` | Manual walk-in order | Table selector + visual food/drink card menu + cart |
| `/ops/tables` | Table activity | Tables, active visits, status |
| `/ops/reservations` | Reservations | Reservation list, confirmation and seating |
| `/ops/verify-reservation` | Arrival check-in | Scan/paste reservation QR and check in |

### Chef and bartender

| Route | Purpose | Primary lists/actions |
| --- | --- | --- |
| `/prep` | My preparation queue | Food or drink queue; claim and mark ready |
| `/prep/history` | Completed preparation | Role-safe completed line history |
| `/menu/availability` | Availability | Their permitted food/drink items; sold out/available |

### Manager

Managers inherit waiter pages and receive:

| Route | Purpose |
| --- | --- |
| `/manage/tables` | Tables, capacity, enable/disable, QR display/regeneration |
| `/manage/menu` | Categories, food/drink cards, modifiers, publishing and availability |
| `/manage/reservations` | Reservation queue, check-in, seating, cancellation and policy visibility |
| `/manage/orders` | Service exceptions, reassignment, audit trail and conflict resolution |
| `/manage/payments` | Payment attempts, cash records and permitted refund workflow |
| `/manage/feedback` | Ratings and complaints, manager-only resolution |
| `/manage/team` | Invite and assign waiters, chefs and bartenders |
| `/manage/reports` | Operations reports |

### Tenant owner

Owners receive all tenant-management routes (not prep operation):

| Route | Purpose |
| --- | --- |
| `/owner/locations` | List/create/edit/retire locations and select active workspace |
| `/owner/team` | Managers, roles and multi-location assignments |
| `/owner/menu` | Tenant/location menu oversight and publish state |
| `/owner/settings` | Charges, retention, branding and tenant-level policy |
| `/owner/reports` | Cross-location reports |

### Platform administrator

| Route | Purpose |
| --- | --- |
| `/platform/tenants` | Tenant list, bootstrap and lifecycle |
| `/platform/tenants/[tenantId]` | One tenant's platform-safe administration |
| `/platform/requests` | Retention-extension and platform requests |

## Diner routes: separate menu from table QR capability

The table QR is a capability that identifies a table; it is not the menu page
itself. The target flow is:

1. `/dine/[dailyQrCode]` validates the daily table capability.
2. It redirects or loads `/r/[tenantSlug]/[locationSlug]/menu?table=<capability>`.
3. The standalone public menu route renders visual food/drink cards, categories,
   filters, search, item detail overlay and cart.
4. `View menu` from the public restaurant/location page opens the same menu route
   without a table capability; browsing is allowed, creating a dine-in order is
   not. The diner must scan a valid table QR or explicitly select takeaway.
5. The cart carries only the opaque capability internally; it never displays
   database IDs to a diner.

This preserves the same card-based visual menu whether it is reached through a
QR, restaurant discovery, a reservation page, or a staff manual-order page.

## Atomic build order

1. Create the reusable list-response/query schema and cursor helpers; add
   authorization regression tests.
2. Add inventory endpoints for each collection that lacks a scoped list
   endpoint, beginning with tables, menu items/categories/modifiers, staff,
   reservations, orders, payments, feedback, locations, and tenants.
3. Add filter models and indexes for menu filters: item type, category,
   availability, preparation destination, temperature, alcohol status, dietary
   tags and text search. Add migrations before exposing filters.
4. Extract existing `/admin` sections into individual first-class route
   components without changing business logic; preserve role guards.
5. Update the sidebar for each role and add active-route and denied-route tests.
6. Extract the visual public menu into its own route, then make QR and public
   restaurant pages enter that route with different capabilities.
7. Add a dedicated Tables & QR route with an actual QR image, copy menu link,
   download/export QR image, daily expiry and forced regeneration audit data.
8. Implement idempotent daily QR ensure job and structured startup readiness
   logs; add restart and no-duplicate-token tests.
9. Add explicit Postgres pool settings and metrics only after measuring startup,
   API latency and database concurrency.
10. Build role-specific dashboards after workspaces and list contracts are
    stable; dashboards should link to the corresponding list pages, not replace
    them.

## Acceptance checks

- Every sidebar link is role-appropriate and goes to an independent page.
- Every selectable object comes from an authorized server list and appears by
  human name/label/card, not a raw ID field.
- Every large domain collection supports cursor pagination and documented
  filters.
- Every mutation has a matching view/list that lets authorized staff see its
  result.
- Daily QR issuance is available after startup without changing a valid same-day
  QR token.
- PostgreSQL and Redis connection status is observable in readiness logs and
  `/health`.
- Cross-tenant and cross-location list attempts return non-enumerating 404/403
  according to the existing authorization policy.
