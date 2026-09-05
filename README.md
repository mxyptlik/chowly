# Chowly

Chowly is a website-first, QR-table dining platform for independent, multi-location Restaurant Tenants. It has separate diner, restaurant-staff, and kitchen/bar web experiences. The product authority is [`CONTEXT.md`](./CONTEXT.md); current delivery status is deliberately tracked rather than assumed.

## Build status

- [`TASKS_TO_DO.md`](./TASKS_TO_DO.md) is the dependency-ranked implementation and verification ledger.
- [`brain.md`](./brain.md) records architecture decisions, agent ownership, test evidence, and final audit state.
- [`REQUIREMENTS_TRACEABILITY.md`](./REQUIREMENTS_TRACEABILITY.md) maps each agreed requirement to implementation/test evidence and lists release blockers.
- [`CONTEXT.md`](./CONTEXT.md) is the product and domain requirements authority.

Do not treat the prototype endpoints below as a completion claim. V1 is complete only when every ledger item has verified evidence.

## Stack

- Frontend: Next.js, TypeScript, responsive web UI, optional PWA installation
- API: FastAPI with SQLAlchemy and Alembic migrations
- Data: PostgreSQL, with Redis for realtime/event and background-job infrastructure
- Background jobs: Dramatiq worker
- Web: Next.js/TypeScript website with optional PWA installation
- Payments: NGN mock adapter in V1; the code must not call a live payment provider

## Roles and privacy

Platform Administrators administer the platform. Tenant Owners administer their Restaurant Tenant. Managers, waiters, chefs, and bartenders are invitation-created Staff Accounts with explicit Restaurant Location assignments; staff sessions are authenticated rather than supplied in request bodies.

Diners do not create Chowly accounts. An order requires a Customer name and phone number; email is optional and supports receipt delivery. Global customer identity is scoped through tenant-specific visibility records, so one Restaurant Tenant must not access another tenant's customer history. Chefs and bartenders receive preparation data only, never customer contact details.

## Run locally

1. Copy `backend/.env.example` to `backend/.env` for a non-Docker API run, setting PostgreSQL, Redis, and CORS values.
2. Run database migrations before starting the API: `cd backend; python -m alembic upgrade head`.
3. For the composed local services, run `docker compose up --build`. This defines PostgreSQL, Redis, API, Dramatiq worker, and web services.
4. Verify API readiness at `http://localhost:8000/health` and open `http://localhost:3000`.

The API runtime intentionally does not call `create_all`; Alembic owns schema creation. Development/test startup may bootstrap deterministic demo data, while production does not use placeholder credentials or deterministic seed data. A seven-tenant pilot seed is still a P13 requirement and has not yet been release-verified.

## Migrations, worker, and tests

- Migrations: `cd backend; python -m alembic upgrade head`
- Focused backend tests: `cd backend; python -m pytest tests -q`
- Frontend static-contract tests: `cd frontend; node --test tests/*.test.mjs`
- Intended frontend verification when dependencies are available: `cd frontend; pnpm lint; pnpm typecheck; pnpm test; pnpm build`
- Worker: Docker Compose runs `dramatiq app.tasks --processes 2 --threads 4` as the `worker` service.

The final cross-service/browser test evidence is not complete yet. See the traceability matrix before treating a command or screen as release-ready.

## Operational boundaries

- QR codes are daily and may be regenerated early by authorised staff.
- Menu prices are intended to be final prices inclusive of the location VAT/service-charge policy.
- Offline tolerance is deliberately narrow: cached browsing and explicitly safe queued actions may be replayed, while payment, refund, QR regeneration, acceptance, and other destructive actions remain online-confirmed.
- Card, bank-transfer, and wallet flows are mock online payments; cash is staff-recorded. There is no live payment provider, settlement, split payment, partial refund, or chargeback workflow in V1.
- Reservations support staff confirmation and core party/table/time details only—no deposits, waitlist, or automatic table allocation.

## Core endpoints

The API is composed from protected authentication, location/menu/table, public order, staff order/preparation, payment, reservation, feedback/retention, reporting, platform-administration, and realtime routers. Treat route contracts and access tokens as security-sensitive; use the generated OpenAPI definition from a running API rather than this README as an endpoint reference.
