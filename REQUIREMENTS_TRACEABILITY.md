# Chowly V1 requirements traceability

**Audit date:** 2026-08-31  
**Authority:** [`CONTEXT.md`](./CONTEXT.md) is the agreed product-language and behaviour authority. [`TASKS_TO_DO.md`](./TASKS_TO_DO.md) is the implementation ledger. This document records evidence, not intent. A `Partial` or `Open` row must not be represented as shipped.

## Evidence scale

| State | Meaning |
|---|---|
| Verified | Named implementation and focused automated tests are recorded in `brain.md`. It still needs final clean-environment release proof where stated below. |
| Partial | Some implementation or static-contract coverage exists, but a required route, browser journey, integration proof, or release check is absent. |
| Open | No adequate implementation/test evidence has been recorded. |

## Product and domain traceability

| Requirement from CONTEXT | Primary implementation evidence | Test evidence recorded | State / release caveat |
|---|---|---|---|
| Restaurant Tenant / Restaurant Location isolation | `backend/app/models.py`, auth dependencies and scoped routers | `test_schema_constraints.py`, `test_auth_tenancy.py` | Verified at focused-test level; final multi-service hostile authorization run remains P13. |
| One global Customer by required name and normalized phone, no diner account; optional email | customer/customer-tenant record model and public-order route | P01/P05 focused evidence in `brain.md` | Verified at focused-test level; browser journey still unproven. |
| Tenant-scoped Customer visibility and retention | customer-tenant records; feedback/retention routers/services | `test_auth_tenancy.py`, `test_feedback_retention.py` | Verified at focused-test level; final retention worker run is open. |
| Invitation-only staff, multiple roles and explicit location assignments | auth router, models, dependencies | `test_auth_tenancy.py`, `test_platform_admin.py` | Verified at focused-test level; staff-management browser workflow remains unproven. |
| Daily table QR, early staff regeneration, QR-first dine-in | table QR model and table/public-menu routers | `test_menu_table_qr.py` | Verified at focused-test level; race/E2E/physical tablet validation are open P13. |
| Separate simultaneous orders at a table and table-visit activity | order/table models and staff-order operations | `test_order_lifecycle.py` | Verified at focused-test level; complete cross-service journey is open. |
| QR order may switch to takeaway only before acceptance; manual staff orders remain fallback | public/staff order routers and lifecycle service | `test_order_lifecycle.py` | Verified at focused-test level. Browser and regression proof are open. |
| Structured modifiers, price deltas, special instructions, all-in VAT/service prices, per-location availability | menu models/router and order pricing snapshots | `test_menu_table_qr.py`, `test_order_lifecycle.py` | Verified at focused-test level; sold-out race proof is open. |
| Waiter accepts and owns; manager may assign/reassign; waiter/manager audit actions | staff-order router/service and audit events | `test_order_lifecycle.py`, `test_auth_tenancy.py` | Verified at focused-test level; role E2E is open. |
| Food routes to kitchen and drink to bar; preparer claim locks line; all active lines ready before service | prep router and lifecycle operations | `test_order_lifecycle.py` | Verified at focused-test level; live queue/realtime proof is open. |
| Diner pre-acceptance cancellation; accepted amendment/cancellation requires staff and reason; new order for additions | public/staff order routers and audit events | `test_order_lifecycle.py` | Verified at focused-test level; browser correction flow is open. |
| Order transfers preserve an actor/timestamp trail and diner notice | staff-order transfer operations and public order view | `test_order_lifecycle.py` | Verified at focused-test level; browser/E2E notice proof is open. |
| Served-only, single full NGN mock online payment; staff-recorded cash; failed retries; manager full refunds | payment/refund/receipt model and payment router | `test_payments_receipts.py` | Verified at focused-test level. Provider settlement is explicitly out of V1; E2E/retry concurrency proof is open. |
| Digital receipt and optional email delivery | receipt records, payment route, Dramatiq task | `test_payments_receipts.py`, `test_realtime_jobs.py` | Partial: persistence/task contract is covered; no real mail provider or end-to-end delivery evidence. |
| Item and order ratings; optional low-score complaint prompt; manager-only complaint handling | feedback router/services | `test_feedback_retention.py` | Verified at focused-test level; browser/reporting E2E remains open. |
| Reservations: name/phone, location, table or party/time, staff confirmation; no deposits/waitlist/auto allocation | reservation model/router/service | `test_reservations.py` | Verified at focused-test level; browser journey is open. |
| Reports: daily orders/revenue/payment, wait time, top items, cancellation, complaints, ratings by location/date | reports router/service | `test_reports.py` | Verified at focused-test level; rendered report UI and production data proof are open. |
| Real-time scoped staff/diner updates with replay and no cross-scope leakage | realtime router/events and Redis contracts | `test_realtime_jobs.py`, `test_auth_tenancy.py` | Partial: unit contracts exist; live Redis multi-process/reconnect test is open. |
| Offline-tolerant, not fully offline: cache browsing and queue only safe actions; financial/destructive actions require confirmation | frontend offline/outbox/service-worker modules | `frontend/tests/foundation.test.mjs`, `frontend/tests/diner.test.mjs` | Partial: static Node contracts only; browser network-loss/replay proof is open. |
| Website first, optional PWA; three web UIs (diner, staff, prep/admin) | Next routes/components and PWA files | `frontend/tests/*.test.mjs` | Partial: static Node tests pass as recorded; lint, typecheck, production build, rendered accessibility, and browser E2E are not yet evidenced. |
| Seven independent pilot tenants, one location each | Required by `TASKS_TO_DO.md` P13 | None | **Open.** Current README refers to a single demo tenant; no verified seven-tenant deterministic seed evidence is recorded. |

## Release blockers and unsupported claims

The following work is still required before a completion statement is valid:

1. Restore a reproducible frontend dependency source and run `pnpm lint`, `pnpm typecheck`, `pnpm test`, and `pnpm build`. The recorded workspace lacks the required Next/TypeScript/ESLint executables.
2. Prove a clean PostgreSQL migration and restart path, then a live Redis/Dramatiq worker path. Existing focused evidence does not substitute for an end-to-end environment.
3. Add and execute browser E2E and rendered accessibility tests for diner, staff, prep, manager, owner, authentication, reservation, receipt, feedback, and reporting screens.
4. Seed and verify seven isolated pilot tenants. This is absent from release evidence.
5. Execute P13 hostile-authorization, concurrency/idempotency, offline-loss/replay, QR/sold-out correction, payment/refund/receipt, and websocket replay tests against the composed services.
6. Reconcile all remaining unchecked P11/P12/P13 ledger items and independently audit every checked item before final confirmation.

## Explicit V1 boundaries

- No native mobile apps.
- No real Paystack or other live payment-provider credentials, settlement, or chargeback workflow.
- No diner account registration, sign-in, or required OTP.
- No split bills, partial payments/refunds, or one payment across orders.
- No reservation deposit, waitlist, or automatic table optimisation.
- No guaranteed fully offline transaction processing.
- Retention beyond 120 days requires platform approval.

## Evidence inventory

Backend focused suites currently present: `test_schema_constraints.py`, `test_auth_tenancy.py`, `test_realtime_jobs.py`, `test_menu_table_qr.py`, `test_order_lifecycle.py`, `test_payments_receipts.py`, `test_reservations.py`, `test_feedback_retention.py`, `test_reports.py`, and `test_platform_admin.py`.

Frontend static-contract suites currently present: `frontend/tests/foundation.test.mjs`, `frontend/tests/diner.test.mjs`, and `frontend/tests/staff-admin.test.mjs`. No `frontend/e2e` test inventory was found during this audit.

Exact results and caveats from each owner are recorded in [`brain.md`](./brain.md). Final release evidence belongs to P13 and is intentionally still unchecked.
