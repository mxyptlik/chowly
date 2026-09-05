# Chowly Tasks To Do

This is the canonical implementation ledger for Chowly V1. Every checkbox represents an independently verifiable change. An assigned agent may change `[ ]` to `[x]` only after the named acceptance evidence passes. A development path is complete only when every checkbox in that path is checked and its evidence is recorded in `brain.md`.

## Completion protocol

1. Work in dependency-rank order. A path may start only when every path in its `Depends on` field is complete.
2. Agents edit only the ownership paths listed in their assignment unless they coordinate a conflict in `brain.md` first.
3. Each task must ship code, tests, and any necessary documentation together.
4. No mock UI may claim an action succeeded until the API confirms it. Offline actions must remain visibly pending.
5. A path is not complete merely because code exists: its targeted tests, lint/type checks, and relevant integration checks must pass.
6. The master agent performs the final reconciliation and may reopen any incorrectly checked item.

## Dependency map

| Rank | Path | Depends on | Intended owner | Status |
|---|---|---|---|---|
| 0 | P00 Planning and audit ledger | None | master | In progress |
| 1 | P01 Relational model and migrations | P00 | `data_migrations` | Complete (18/18) |
| 1 | P03 Realtime and background infrastructure | P00 | `realtime_jobs` | Complete (8/8) |
| 1 | P10 Frontend foundation, accessibility, and PWA shell | P00 | `frontend_foundation` | Implementation complete (12/12; full toolchain proof pending) |
| 2 | P02 Authentication, authorization, and tenant isolation | P01 | `security_tenancy` | Complete (11/11) |
| 2 | P04 Menu, location, table, and QR administration | P01, P02 | `menu_table_qr` | Complete (11/11) |
| 2 | P07 Reservations | P01, P02 | `reservations` | Complete (7/7) |
| 2 | P08 Feedback, complaints, and retention | P01, P02 | `feedback_retention` | Complete (9/9) |
| 3 | P05 Order lifecycle and staff operations | P02, P03, P04 | `order_operations` | Complete (21/21) |
| 3 | P09 Reporting and operational analytics | P02, P05, P07, P08 | `reporting` | Complete (9/9) |
| 4 | P06 Payments, refunds, and receipts | P02, P03, P05 | `payments_receipts` | Complete (9/9) |
| 4 | P11 Diner web experience | P04, P05, P06, P07, P08, P10 | `diner_frontend` | Blocked |
| 4 | P12 Staff and tenant administration web experience | P02, P04-P10 | `staff_admin_frontend` | In progress — foundational staff UI and Node tests complete; remaining atomic UI workflows below stay open |
| 5 | P13 System integration, hardening, and release proof | P01-P12 | `release_verification` | Blocked |

## P00 - Planning and audit ledger

**Goal:** Preserve the complete agreed scope and make distributed progress auditable.

**Ownership:** `TASKS_TO_DO.md`, `brain.md`, root `README.md` documentation links only.

- [x] Create this dependency-ranked task ledger with atomic implementation and verification steps.
- [x] Create `brain.md` with the agreed domain decisions, known baseline, dependency rules, and agent journal.
- [x] Link `TASKS_TO_DO.md` and `brain.md` from `README.md` after implementation begins.
- [x] Record every agent assignment, completion report, test command, and reopening decision in `brain.md`.

**Evidence:** Both documents exist and describe the full V1 scope without silently weakening `CONTEXT.md`.

## P01 - Relational model and Alembic migrations

**Goal:** Make PostgreSQL the versioned source of truth for every agreed domain concept and enforce cross-tenant/location integrity at the database boundary.

**Depends on:** P00.

**Ownership:** `backend/app/models.py`, `backend/app/db.py`, `backend/alembic.ini`, `backend/alembic/**`, `backend/tests/test_schema_constraints.py`, relevant requirements only.

**Required imports:** SQLAlchemy 2 types and constraints (`ForeignKeyConstraint`, `UniqueConstraint`, `CheckConstraint`, `Index`, `Enum`, `JSON`, `Numeric`), Alembic `op`, PostgreSQL dialect UUID where appropriate.

- [x] Add tenant retention fields (`retention_days`, approval metadata) to `models.Tenant`; enforce the normal 1-120 day range in application logic and default 90.
- [x] Add location configuration to `models.Location`: currency, VAT rate, service-charge rate, timezone, active state, and operating-hours relation.
- [x] Add `OperatingHour` with tenant/location composite ownership, weekday, open/close time, and closed-day support.
- [x] Replace single-role/single-location staff assumptions with `StaffAccount`, `StaffRoleAssignment`, and `StaffLocationAssignment` (or equivalent normalized associations) supporting invitation state, multiple roles, and multiple locations.
- [x] Preserve global `Customer.phone` uniqueness while adding restaurant-scoped `CustomerTenantRecord`/visibility metadata so one tenant cannot infer another tenant's order history.
- [x] Add durable daily `TableQrToken` records with token hash, issue date, invalidation timestamp, generator staff, and composite table/location/tenant references.
- [x] Extend menu storage for tenant/location-specific price and availability, typed modifier groups/options, option price deltas, selection limits, and temporary sold-out state.
- [x] Extend orders with secure public access-token hash, source (`QR`/`MANUAL`), service mode (`DINE_IN`/`TAKEAWAY`), owner/assignee, accepted/served/cancelled timestamps, wait estimate, cancellation reason, and immutable pricing/tax snapshots.
- [x] Extend order lines with destination queue, claimed-by staff, claim/ready timestamps, status, special instructions, menu/modifier IDs, modifier name/price snapshots, and per-line tax/charge/total snapshots.
- [x] Add normalized `PaymentAttempt`, `Refund`, and `Receipt` records supporting failed/retried mock online attempts, staff-recorded cash, one successful full payment per order, one full refund, and receipt delivery status.
- [x] Add `Reservation` with location, optional table, party size, requested time, customer identity, status, confirmation staff, and audit timestamps.
- [x] Add `ItemRating`, `OrderRating`, `Complaint`, and complaint resolution fields with one-per-line/order constraints and manager visibility semantics.
- [x] Make `AuditEvent` append-only in service behavior and rich enough for acceptance, assignment, amendment, transfer, cancellation, payment, refund, QR regeneration, availability, and complaint-resolution before/after metadata.
- [x] Add composite foreign keys or equivalent constraints preventing cross-tenant and cross-location relationships across tables, menu records, orders, staff assignments, reservations, ratings, payments, and complaints.
- [x] Add indexes for active queue lookup, active table state, public order token, daily QR lookup, reservation time, complaint status, and report date filters.
- [x] Initialize Alembic, wire `backend/app/db.py` metadata into `alembic/env.py`, and create a reproducible initial migration for the complete schema.
- [x] Remove production reliance on `Base.metadata.create_all`; retain explicit test-only schema creation if useful.
- [x] Add migration/schema tests proving upgrade from an empty database and rejecting representative cross-tenant/location, duplicate rating, duplicate successful payment, and invalid status data.

**Evidence:** `alembic upgrade head` succeeds on an empty PostgreSQL database; schema constraint tests pass.

## P02 - Authentication, authorization, and tenant isolation

**Goal:** Staff are invited, authenticated people; every protected operation is authorized by role and explicit location assignment.

**Depends on:** P01.

**Ownership:** `backend/app/core/security.py`, `backend/app/auth.py`, `backend/app/dependencies.py`, `backend/app/routers/auth.py`, auth schemas in `backend/app/schemas.py`, `backend/tests/test_auth_tenancy.py`, settings/requirements needed by this path.

**Required imports:** FastAPI `Depends`, `HTTPException`, `Request`, `Response`; SQLAlchemy `Session`, `select`; password hashing library; signed token/session library; `models.StaffAccount`, role and location assignment models.

- [x] Add secure password hashing/verification and signed, expiring staff session or JWT utilities; never store raw passwords or raw invite/session tokens.
- [x] Add tenant-owner/manager invitation issuance and invite acceptance endpoints with expiry, one-time use, role set, and explicit location assignments.
- [x] Add staff login, logout, current-session, and session-refresh behavior suitable for same-site web clients.
- [x] Implement `CurrentStaff` authentication dependency returning account, tenant, roles, and allowed location IDs.
- [x] Implement reusable `require_roles(...)` and `require_location_access(...)` dependencies and a platform-admin boundary.
- [x] Replace arbitrary staff-ID trust in protected endpoints with the authenticated principal; IDs may identify a target but never authority.
- [x] Enforce tenant and location predicates in every protected query and return non-enumerating 404/403 responses for foreign resources.
- [x] Limit waiter actions to their assigned locations and ownership rules; allow manager overrides only in assigned locations; restrict chef/bartender queue access to assigned locations and station role.
- [x] Restrict customer contact visibility to authorized waiter/manager roles and keep it out of chef/bartender payloads.
- [x] Add bootstrap behavior for local demo data without creating a production backdoor; document seeded credentials as development-only.
- [x] Add tests for invite lifecycle, multi-role/multi-location accounts, expired/invalid sessions, role denial, ownership denial, and cross-tenant/location enumeration attempts.

**Evidence:** Auth/tenancy suite passes and no protected route accepts caller authority solely from request-supplied staff IDs.

## P03 - Realtime, event, and background-job infrastructure

**Goal:** Provide reliable live updates and asynchronous work without claiming false success during disconnection.

**Depends on:** P00 for scaffolding; integrate final model references after P01.

**Ownership:** `backend/app/realtime.py`, `backend/app/events.py`, `backend/app/routers/realtime.py`, `backend/app/tasks.py`, `backend/app/worker.py`, `backend/tests/test_realtime_jobs.py`, `docker-compose.yml` worker/Redis configuration.

**Required imports:** FastAPI `WebSocket`, `WebSocketDisconnect`; asyncio; Dramatiq actors/broker; Redis client; typed event dataclasses or Pydantic models.

- [x] Define versioned event envelopes for order, order-line, table, menu availability, reservation, complaint, payment, and receipt changes.
- [x] Implement authenticated staff WebSocket channels scoped to tenant/location/role and public order channels scoped by unguessable order access token.
- [x] Implement connection registry, subscribe/unsubscribe cleanup, heartbeat, and reconnect-safe event sequencing.
- [x] Publish domain events only after successful database commits; prevent rolled-back changes from appearing as live success.
- [x] Configure Redis-backed cross-process publish/subscribe so API instances and workers share events.
- [x] Configure Dramatiq worker startup in `docker-compose.yml` and make broker configuration environment-driven.
- [x] Implement idempotent background receipt delivery and retention-cleanup actors with retry/backoff and durable delivery/cleanup state.
- [x] Add tests for channel authorization/isolation, event schema, disconnect cleanup, publish-after-commit behavior, actor idempotency, and retries.

**Evidence:** Realtime/job tests pass with no event leakage across tenants, locations, or public order tokens.

## P04 - Location, menu, table, and QR administration

**Goal:** Managers can configure real restaurant locations while diners can safely enter the correct table menu through renewable daily QR codes.

**Depends on:** P01 and P02.

**Ownership:** `backend/app/routers/locations.py`, `backend/app/routers/menu.py`, `backend/app/routers/tables.py`, `backend/app/services/qr.py`, `backend/app/services/pricing.py`, matching schemas, `backend/tests/test_menu_table_qr.py`.

**Required imports:** FastAPI router/dependencies; SQLAlchemy query APIs; `secrets`, `hashlib`, timezone/date utilities; `Decimal`; relevant models and auth dependencies.

- [x] Add tenant-owner location CRUD and manager-readable configuration endpoints with explicit assigned-location enforcement.
- [x] Add operating-hours create/update/read endpoints and expose current open/closed state to the public menu response.
- [x] Add manager menu category/item CRUD, per-location pricing, availability, sold-out toggles, queue destination, and modifier group/option CRUD.
- [x] Validate modifier min/max and selected option IDs server-side and reject unavailable items/options.
- [x] Centralize Decimal pricing in `services.pricing`: item/modifier subtotal, VAT, service charge, rounding, and all-in display totals.
- [x] Add table CRUD and state calculation where a table remains active while any associated order has not met the terminal payment/refund/closure condition.
- [x] Generate one unpredictable QR token per table/local calendar day, persist only its hash, and map it to the table/location without exposing sequential IDs.
- [x] Add waiter/manager forced QR regeneration that invalidates the previous token immediately and emits an audit event.
- [x] Make public QR/menu lookup reject expired, invalidated, foreign, or guessed tokens and return the menu with all-in prices, modifiers, availability, hours, VAT, and service charge disclosure.
- [x] Add printable/digital QR response payload and keep print optional; daily digital presentation is the default.
- [x] Add tests for daily rotation by location timezone, forced invalidation, token guessing, sold-out rejection, modifier validation, price/tax rounding, operating hours, and active table state.

**Evidence:** Menu/table/QR tests pass, including security and date-boundary cases.

## P05 - Order lifecycle and staff operations

**Goal:** Implement the complete audited workflow from separate diner orders through queue preparation, service, and permitted real-world corrections.

**Depends on:** P02, P03, and P04.

**Ownership:** `backend/app/routers/public_orders.py`, `backend/app/routers/staff_orders.py`, `backend/app/routers/prep.py`, `backend/app/order_service.py`, `backend/app/order_schemas.py`, `backend/tests/test_order_lifecycle.py`.

**Required imports:** FastAPI dependencies; SQLAlchemy transaction/locking APIs; order/menu/staff/audit models; pricing and event services; enums and `Decimal`.

- [x] Require diner name and phone for every order, normalize global phone identity, accept optional email, and expose no signup/signin flow.
- [x] Create a new independent order per submission even when other active orders exist at the same table; never merge diners implicitly.
- [x] Create secure public order access tokens and require them for subsequent public status, cancellation, payment, receipt, rating, and complaint access.
- [x] Snapshot every line name, base price, modifier IDs/names/deltas, special instructions, charges, taxes, and total at submission.
- [x] Allow diner service-mode switch from dine-in to takeaway only before acceptance and record the change.
- [x] Allow diner cancellation only before acceptance; after acceptance reject self-change and instruct diner to request a waiter.
- [x] Implement waiter acceptance/ownership and manager acceptance; enforce waiter assigned-location and ownership policies.
- [x] Let managers reassign accepted orders and record prior/new waiter plus actor/reason/timestamps in the audit trail.
- [x] Implement manager/waiter order transfer to another table with reason, audit history, public customer notice, and table-state updates.
- [x] Implement pre-claim waiter/manager amendment of quantities/modifiers/instructions with required reason and full before/after pricing audit.
- [x] Lock a line against waiter amendment after chef/bartender claim while allowing a manager to cancel with explicit reason according to policy.
- [x] Implement waiter/manager cancellation after acceptance with mandatory reason and precise line/order state transitions.
- [x] Treat requested additions as a brand-new order rather than mutation of the accepted order.
- [x] Add waiter manual-order creation for QR failure using the same customer, pricing, availability, and audit rules.
- [x] Route food/drink lines to kitchen/bar, authorize role-specific claim, and support claimed/preparing/ready timestamps.
- [x] Keep diner aggregate status `PREPARING` until every active line is ready; then expose `READY_FOR_SERVICE`.
- [x] Require assigned waiter or manager to mark ready order served; record the actor/timestamp and emit live events.
- [x] Add recommended wait estimate plus buttons for 5/10/15/30/45 minutes and a validated manual value; waiter/manager owns the final choice.
- [x] Return explicit conflict/version responses for stale offline mutations so clients do not silently overwrite newer server state.
- [x] Build an append-only audit timeline endpoint for managers covering every critical action and relevant timestamps.
- [x] Add lifecycle tests for every state transition, denial, concurrent claim, separate same-table orders, transfer notice, amendments, cancellation, manual order, wait estimate, aggregate status, and audit event.

**Evidence:** Complete order lifecycle suite passes, including concurrency and authorization cases.

## P06 - Payments, full refunds, and digital receipts

**Goal:** Support safe mock NGN payment behavior that mirrors a future processor adapter without confusing online and staff-recorded cash.

**Depends on:** P02, P03, and P05.

**Ownership:** `backend/app/routers/payments.py`, `backend/app/services/payments.py`, `backend/app/services/receipts.py`, payment schemas, receipt templates, `backend/tests/test_payments_receipts.py`.

**Required imports:** abstract base/protocol typing; SQLAlchemy transactions; `Decimal`; cryptographic token helpers; payment/refund/receipt models; auth dependencies; Dramatiq receipt actor.

- [x] Define a payment-provider adapter interface and a deterministic mock adapter for card, bank transfer, and wallet success/failure/retry scenarios.
- [x] Permit public online payment only after service and only through the secure public order token; reject cash from public callers.
- [x] Add staff-only cash recording for waiter/manager in the order's assigned location with actor and audit event.
- [x] Record every payment attempt, including failure code/message, and allow retries without duplicating successful charges.
- [x] Enforce one full successful payment per order and verify amount/currency against immutable order totals server-side.
- [x] Add manager-only full refund with required reason, one-refund idempotency, audit event, and updated order/table terminal state.
- [x] Generate a soft-copy digital receipt containing restaurant/location identity, order lines/modifiers, VAT/service charge breakdown, payment method/reference, timestamps, and refund state.
- [x] Expose receipt through the secure order link and queue email delivery only when the diner supplied email; persist delivery status and retry safely.
- [x] Add tests for premature payment, public cash denial, amount tampering, mock failure/retry, duplicate callbacks/submissions, cash authorization, refund authorization/idempotency, receipt access, and email task state.

**Evidence:** Payment/receipt suite passes with no path to public cash or double payment/refund.

## P07 - Reservations

**Goal:** Deliver the agreed simple V1 reservation workflow without deposits, waitlists, or automatic table optimization.

**Depends on:** P01 and P02.

**Ownership:** `backend/app/routers/reservations.py`, `backend/app/reservation_service.py` (safe deviation because `backend/app/services.py` is an existing module), `backend/app/reservation_schemas.py`, `backend/tests/test_reservations.py`.

**Required imports:** FastAPI dependencies; SQLAlchemy; timezone-aware datetime; reservation/location/table/customer models; auth and event/audit services.

- [x] Add public reservation request with required name, phone, location, party size, requested date/time, and optional table/request note.
- [x] Validate location operating hours, active state, future time, party size, and table/location consistency without promising automatic availability.
- [x] Add manager/waiter assigned-location reservation queue with safe customer-contact visibility.
- [x] Add explicit confirm, reject, cancel, and seated status transitions with authorized actor, optional table assignment, reason/note, and timestamps.
- [x] Keep reservations separate from active table occupancy until seated; connect a seated reservation to table/order context without merging independent diner orders.
- [x] Emit scoped live events and audit all staff status/table changes.
- [x] Add tests for public validation, status machine, cross-location denial, overlapping requests being allowed for human review, and audit/events.

**Evidence:** Reservation suite passes and contains no deposit, waitlist, or auto-allocation behavior.

## P08 - Ratings, complaints, and retention

**Goal:** Collect post-service feedback privately and enforce tenant-configurable customer-data retention.

**Depends on:** P01 and P02.

**Ownership:** `backend/app/routers/feedback.py`, `backend/app/routers/retention.py`, `backend/app/services/feedback.py`, `backend/app/services/retention.py`, schemas, `backend/tests/test_feedback_retention.py`.

**Required imports:** SQLAlchemy; date/time utilities; rating/complaint/customer/order models; secure public order dependency; manager role dependency; background cleanup actor.

- [x] Allow item ratings only for food/drink lines on a served order, once per line, 1-5 score, optional comment.
- [x] Allow one overall order rating after service with 1-5 score and optional comment.
- [x] Return a non-blocking complaint prompt after a score of 1 or 2 without requiring complaint submission.
- [x] Allow a complaint only after service through the active receipt/order link, tied to the order and optionally a specific line.
- [x] Restrict complaint detail/list/resolution to assigned-location managers; expose no complaint content to waiters, chefs, or bartenders.
- [x] Add manager complaint acknowledgement/resolution with resolution note, actor, timestamp, and immutable audit events.
- [x] Add tenant-owner retention configuration defaulting to 90 days, allowing 1-120 days, and representing longer periods as pending platform approval rather than silently accepting them.
- [x] Implement idempotent retention cleanup/anonymization that removes tenant-visible customer contact/history after policy expiry without breaking statutory financial aggregates and without deleting another tenant's visibility record.
- [x] Add tests for timing, uniqueness, score validation, low-rating prompt, role visibility, resolution audit, 90/120-day policy, approval requirement, and cross-tenant cleanup isolation.

**Evidence:** Feedback/retention suite passes and complaint/customer data never leaks across unauthorized roles or tenants.

## P09 - Reports and operational analytics

**Goal:** Give authorized tenant staff accurate location/date-filtered V1 reports derived from source records.

**Depends on:** P02, P05, P07, and P08.

**Ownership:** `backend/app/routers/reports.py`, `backend/app/services/reporting.py`, report schemas, `backend/tests/test_reports.py`.

**Required imports:** SQLAlchemy aggregation/functions; `Decimal`; timezone/date range utilities; order/payment/refund/line/rating/complaint models; manager/owner dependencies.

- [x] Implement location-local date-range filters with tenant and assigned-location enforcement.
- [x] Report daily order counts and gross/net revenue with explicit treatment of failed payments, cash, and refunds.
- [x] Report payment totals by method/status and refund totals.
- [x] Report average acceptance, preparation, ready-to-serve, and total wait times from actual timestamps.
- [x] Report top menu items by quantity and paid revenue using immutable order-line snapshots.
- [x] Report cancellations by actor/reason/stage.
- [x] Report complaint counts/status/resolution time and rating averages/distributions for orders and items.
- [x] Return empty datasets and zero values consistently rather than errors or misleading nulls.
- [x] Add tests for timezone boundaries, refund math, excluded failed/unpaid orders, location isolation, and every required metric.

**Evidence:** Deterministic fixture-based report suite passes for multiple tenants, locations, days, and currencies (NGN in V1).

## P10 - Frontend foundation, authentication shell, accessibility, and PWA behavior

**Goal:** Establish a distinctive, responsive, accessible web-first foundation shared by the diner, staff, and administration experiences.

**Depends on:** P00; integrate auth/events against P02/P03 contracts before completion.

**Ownership:** `frontend/app/layout.tsx`, `frontend/app/globals.css`, `frontend/app/pwa-registration.tsx`, `frontend/components/**`, `frontend/lib/api.ts`, `frontend/lib/auth.tsx`, `frontend/lib/realtime.ts`, `frontend/lib/offline/**`, `frontend/public/manifest.json`, `frontend/public/sw.js`, icon assets, frontend tests/config.

**Required imports:** Next.js App Router APIs; React state/context/hooks; accessible component primitives where justified; IndexedDB helper; typed API contracts; service-worker APIs.

- [x] Define reusable design tokens, typography, spacing, focus, status, table, form, dialog, toast, and responsive navigation styles without generic placeholder visuals.
- [x] Add skip link, semantic landmarks, visible keyboard focus, reduced-motion support, sufficient contrast, touch target sizing, and screen-reader status regions.
- [x] Build labelled input/select/textarea/button components with `htmlFor`, accessible names, validation messages, autocomplete/input modes, and pending/disabled states.
- [x] Centralize typed API requests, credentials/session handling, error normalization, request IDs, and abort behavior in `lib/api.ts`.
- [x] Add authenticated staff provider and role/location-aware route guards; remove any UI behavior that chooses the first staff record as the acting user.
- [x] Add realtime client with authenticated/public-token subscriptions, exponential reconnect, event sequence tracking, and polling fallback.
- [x] Add IndexedDB cache for public menu and active order snapshots plus an outbox restricted to explicitly safe mutations.
- [x] Make queued actions visibly `Pending sync`; reconcile idempotently on reconnect and surface conflicts for human resolution without ever showing accepted/paid prematurely.
- [x] Replace cache-only service-worker behavior with versioned app-shell/static stale-while-revalidate and conservative API handling; do not cache private/contact/payment responses unsafely.
- [x] Add installable manifest metadata, start URL, display/theme fields, and real maskable/standard application icons.
- [x] Add responsive online/offline indicator and install affordance while keeping normal website use primary.
- [x] Add unit tests for API errors, auth guards, reconnect behavior, outbox retry/conflict, accessible form association, and service-worker cache policy.

**Evidence:** Frontend unit tests, typecheck, lint, production build, automated accessibility smoke test, and PWA manifest checks pass.

## P11 - Diner web experience

**Goal:** Deliver the friction-light QR ordering, status, payment, receipt, reservation, and feedback journey with no customer account.

**Depends on:** P04, P05, P06, P07, P08, and P10.

**Ownership:** `frontend/app/dine/[code]/**`, `frontend/app/order/[token]/**`, `frontend/app/reserve/**`, diner components under `frontend/components/diner/**`, `frontend/tests/diner*.{ts,tsx}`.

**Required imports:** shared API/realtime/offline clients; accessible form components; React/Next navigation; typed menu/order/payment/feedback models.

- [x] Render valid QR table/location identity, operating status, categories, all-in base and modifier pricing, availability, and sold-out state.
- [x] Support quantity, structured multi-select modifier groups, and optional free-text special instructions with server error mapping.
- [x] Require name and phone, accept optional email, use appropriate autocomplete/input modes, and explain why contact data is requested.
- [x] Create a separate order and retain only its secure public access token locally; never expose sequential order IDs as authority.
- [x] Support dine-in to takeaway switch and self-cancellation only while the server says the order is unaccepted.
- [x] Render live line and aggregate status, chosen wait estimate, transfer notice, cancellation reason, offline/pending state, and recovery guidance.
- [x] Enable mock card/bank-transfer/wallet payment only after service; render failed-attempt retry without duplicate-payment risk.
- [x] Render accessible soft-copy receipt and refunded state; support returning through the secure receipt/order link.
- [x] Support per-food/drink-line rating, overall order rating, optional comments, and optional low-score complaint prompt after service.
- [x] Support later complaint submission through the secure order/receipt link without exposing manager-only resolution data.
- [x] Build simple public reservation request and confirmation/status view.
- [x] Add responsive, keyboard, screen-reader, offline-loss, stale-token, sold-out race, and full diner journey tests.

**Evidence:** Diner automated journey passes from QR through served payment/receipt/feedback plus cancellation, takeaway, reservation, and network-loss variants.

## P12 - Staff operations and tenant administration web experience

**Goal:** Deliver role-correct web workspaces for waiter, kitchen/bar, manager, tenant owner, and platform administration.

**Depends on:** P02 and P04-P10.

**Ownership:** `frontend/app/login/**`, `frontend/app/ops/**`, `frontend/app/prep/**`, `frontend/app/admin/**`, staff/admin components, `frontend/tests/staff*.{ts,tsx}`.

**Required imports:** shared auth/API/realtime/offline clients; accessible data/form/dialog components; role/location routing; typed domain/report models.

- [x] Build invitation acceptance, staff login/logout, expired-session recovery, and current-role/location switcher for multi-role/multi-location users.
- [x] Build waiter order queue with live new-order notice, accept/own, wait selection/manual estimate, detail, and customer contact only where authorized.
- [x] Build waiter/manager actions for reassignment, table transfer, pre-claim amendment, reasoned cancellation, manual new order, serve, staff-recorded cash, and audit visibility according to role.
- [x] Build kitchen and bar queues that show only relevant line/food data, exclude customer contact, and support atomic claim/ready actions.
- [x] Build table dashboard with calculated active state and forced daily QR regeneration/display/print controls.
- [x] Build reservation queue and explicit confirm/reject/cancel/seat/table-assignment workflow.
- [x] Build manager menu/location/hours/tax/service-charge/availability/modifier/table administration.
- [x] Build manager payment attempt detail, cash record, manager-only full refund with mandatory reason, and receipt delivery state.
- [x] Build manager-only complaint inbox/detail/resolution and rating overview; do not render complaint content in waiter/prep bundles.
- [x] Build tenant-owner staff invitation, roles, location assignments, and retention-policy administration.
- [x] Build location/date-filtered reports for orders, revenue/payment/refund, wait time, top items, cancellations, complaints, and ratings.
- [x] Build minimal platform-admin tenant/location bootstrap and >120-day retention approval controls.
- [x] Apply explicit pending-sync/conflict states only to safe offline-tolerant staff actions; payments/refunds and destructive decisions require confirmed connectivity.
- [ ] Add role matrix, responsive, keyboard, accessible dialog/form/table, realtime reconnect, and end-to-end staff workflow tests.

**Evidence:** Each role's automated journey passes and forbidden UI/actions remain inaccessible even when routes are entered directly.

## P13 - System integration, hardening, and release proof

**Goal:** Prove the seven-tenant pilot build behaves as one secure, deployable system and reconcile every agreed requirement.

**Depends on:** P01-P12.

**Ownership:** cross-stack test/config/docs only unless a defect is reassigned to its owning path; `backend/tests/integration/**`, `frontend/e2e/**`, root compose/env/README, CI configuration, final `brain.md` audit.

**Required imports/tools:** pytest; PostgreSQL and Redis fixtures; browser E2E runner; accessibility runner; Next/FastAPI production commands; migration and worker health checks.

- [ ] Add one-command local startup with API, web, PostgreSQL, Redis, and Dramatiq worker health checks plus documented environment variables.
- [ ] Seed seven independent pilot tenants with one location each and enough staff roles, tables, menus, modifiers, and credentials for deterministic demos without shared tenant data.
- [x] Run migrations from empty PostgreSQL and prove restart safety without `create_all` drift.
- [ ] Add end-to-end happy paths for QR order, waiter acceptance, kitchen/bar preparation, service, each online payment mode, cash, receipt, ratings, complaints, and reservation.
- [ ] Add end-to-end correction paths for diner pre-acceptance cancel/takeaway, sold-out race, reassignment, table transfer, amendment lock, staff cancellation, failed payment retry, full refund, QR regeneration, and manual order.
- [ ] Add hostile authorization tests for every role, guessed QR/order tokens, cross-tenant IDs, cross-location IDs, hidden customer contact, and manager-only complaint/refund data.
- [ ] Add concurrency/idempotency tests for acceptance, prep claim, payment, refund, QR regeneration, WebSocket reconnect, outbox replay, and receipt jobs.
- [ ] Add accessibility checks for diner, waiter, prep, manager, owner, login, reservation, receipt, feedback, and report screens.
- [ ] Add offline-tolerance tests proving cached browsing/pending safe actions and proving no false accepted, served, paid, refunded, or resolved state.
- [ ] Run backend tests, frontend tests, lint, typecheck, production build, migration checks, worker checks, and browser E2E; record exact commands/results in `brain.md`.
- [ ] Reconcile every decision in `CONTEXT.md` against implementation/tests and reopen any unsupported checkbox.
- [ ] Update `README.md` with architecture, role matrix, local setup, migrations, worker, seeded access, test commands, offline guarantees, mock-payment boundary, and known non-V1 items.
- [ ] Confirm every checkbox in P00-P13 is checked by its owner and independently audited by the master agent.

**Evidence:** All commands pass on a clean environment and the final requirements traceability audit has no open or assumed item.

## Explicitly outside V1

- Native mobile applications.
- Real Paystack or other live payment-provider credentials/settlement.
- Customer account signup/signin or OTP requirement.
- Split bills, partial payments, partial refunds, or one payment covering multiple orders.
- Reservation deposits, waitlists, or automatic table optimization.
- Guaranteed full offline operation.
- Automatic retention beyond 120 days without platform approval.
