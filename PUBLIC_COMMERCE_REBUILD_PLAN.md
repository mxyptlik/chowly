# Public restaurant journeys, routing, and onboarding rebuild plan

Status: **planning in progress.** Directory publication is now decided; remaining decision gates must be answered before their dependent implementation paths begin.

## Product outcome

Chowly becomes both:

1. a light public discovery surface where a diner can find a participating restaurant and its locations; and
2. a branded restaurant ordering/reservation surface that each tenant can share directly.

It is **not** a full marketplace in this phase: no rankings, reviews, map search, delivery dispatch, platform-wide checkout, or restaurant comparison.

Customers never create Chowly accounts. Staff sign in with their work account. A daily table QR remains the only authority to add an order to a physical table.

## Target routes and authority boundaries

| Route | User | Purpose | Server authority |
|---|---|---|---|
| `/` | Everyone | Chowly landing, “Find a restaurant”, “List your restaurant”, “Staff sign in” | Public, no customer identity |
| `/restaurants` | Diner | Lightweight restaurant discovery | Public, active/public tenants only |
| `/r/[tenantSlug]` | Diner | Branded restaurant page; choose a location | Public, no table authority |
| `/r/[tenantSlug]/[locationSlug]` | Diner | Location page: menu preview, hours, location, reserve, takeaway | Public, no table authority |
| `/r/[tenantSlug]/[locationSlug]/reserve` | Diner | Reservation form and confirmation | Public opaque reservation capability after creation |
| `/dine/[dailyTableCode]` | Diner at a table | Table menu and dine-in/takeaway ordering | Valid, daily table code only |
| `/join` | New restaurant owner | Bare-minimum self-service tenant/location registration | Creates a pending tenant and owner invitation/account |
| `/onboarding` | New tenant owner | Complete initial setup: hours, tables, menu, invite staff | Authenticated tenant owner only |
| `/login` | Existing staff | Work email/password sign-in | Backend resolves tenant, roles, and assigned locations |
| `/ops`, `/prep`, `/admin`, future `/owner` | Staff | Role workspace | Backend role and tenant/location checks on every API call |

The route must never contain a trusted `role`, tenant ID, staff ID, or unrestricted table ID. Slugs are public identifiers, not authority. The backend remains the source of truth for session, role, tenant, location assignment, and table-QR validity.

## Dependency-ordered development paths

### P1 — Public identity and discovery foundation

**Why first:** reservations, branded pages, QR menu context, and self-service onboarding all need stable public restaurant/location identities.

1. Add a unique, immutable public slug to `Tenant` and `Location` in `backend/app/models.py`.
2. Create an Alembic migration in `backend/alembic/versions/` that backfills collision-safe slugs for existing rows and creates unique indexes.
3. Add safe public DTOs in `backend/app/location_schemas.py`: only name, slug, cover image, description, address, operating state/hours, currency, and menu preview metadata. Never expose customer/staff contacts, internal IDs, or payment data.
4. Add public read routes in a new `backend/app/routers/public_restaurants.py`, then register them in `backend/app/main.py`:
   - list public restaurants;
   - get one public restaurant and active locations;
   - get one public location and its public menu preview.
5. Add tests proving unpublished/inactive locations, foreign tenant data, private fields, and guessed IDs are not exposed.
6. Add public assets in the data model: initially `cover_image_url` on tenant/location and `image_url` on menu items. Validate HTTPS URLs and allow an intentional image placeholder. Object-storage uploads are a later path, not hidden inside this one.

### P2 — Public restaurant and reservation experience

**Depends on P1.**

1. Replace `frontend/app/page.tsx` with a public Chowly entry page containing the three clear actions: find a restaurant, list your restaurant, staff sign in.
2. Add `frontend/app/restaurants/page.tsx`: searchable, lightweight public directory; no claim of full marketplace behaviour.
3. Add `frontend/app/r/[tenantSlug]/page.tsx`: branded restaurant landing page, locations, cover image, description and reserve/order actions.
4. Add `frontend/app/r/[tenantSlug]/[locationSlug]/page.tsx`: location details, opening state, category-led menu preview, location/map link, reservation action, and takeaway action.
5. Replace the raw `Restaurant Location ID` field in `frontend/components/diner/reservation-form.tsx` with a route-derived public location. Retain required name/phone and optional note; no diner login.
6. Add a reservation confirmation route using only the opaque reservation capability. It must show restaurant, location, requested date/time, party size, status, and a safe “keep this link” message.
7. Add browser tests for browse → choose location → reserve → confirmation and for private-token access failure.

### P3 — QR table ordering and visual menu rebuild

**Depends on P1; can run alongside P2 after public schemas are settled.**

1. Preserve `frontend/app/dine/[code]/page.tsx` as the table-only entry. Remove the stale hard-coded “Try table experience” route from the root page.
2. Extend the QR response shown in `frontend/app/admin/page.tsx` with a real scannable SVG/Canvas QR image using an audited client QR package; retain the URL as accessible text/copy fallback.
3. Add a print-ready `TableQrCard` component in `frontend/components/staff/` containing restaurant/location/table name, daily expiry, QR graphic and fallback URL.
4. Refactor `frontend/components/diner/diner-menu.tsx` into atomic components:
   - `RestaurantMenuHeader` (restaurant, location, table, order mode);
   - `CategoryRail` (sticky category navigation);
   - `MenuItemCard` (image, title, price, availability);
   - `ProductDetailDialog` (image, description, modifiers, dietary/allergen space later, special instruction, quantity);
   - `CartDrawer` (persistent item count and editable cart);
   - `GuestCheckoutDialog` (name/phone required, email optional, service mode, total, submit);
   - `OrderConfirmation` (secure tracking link).
5. Use an accessible dialog with a backdrop/blur, focus trap, Escape close and responsive bottom-sheet behaviour on mobile. The background menu must not remain interactive while checkout is open.
6. Move modifier selection and special instruction out of every menu card and into `ProductDetailDialog`; only an explicit “Add to cart” changes the cart.
7. Keep the user’s existing rule: every checkout creates a **new separate order** for that table. Changing to takeaway is allowed before submission only; it does not mutate someone else’s table order.
8. Add correct visual states for unavailable items, location closed, invalid/expired QR, pending submission, successful order, and re-opened secure order tracking.
9. Add tests for QR graphic encoding the returned daily URL, modifier validation, accessible dialog behaviour, cart totals, duplicate submit/idempotency, and table-code expiry.

### P4 — Minimal self-service restaurant onboarding

**Depends on P1.**

1. Add onboarding lifecycle fields to `Tenant` (`PENDING_SETUP`, `ACTIVE`, `SUSPENDED`) and migration. A public restaurant is not listed until active.
2. Add `backend/app/routers/onboarding.py` and schemas for a minimal registration request: restaurant name, first location name, address, owner name, owner email, password/invitation choice, and acceptance of terms. Avoid collecting menus, payment details, or staff data in this first form.
3. Generate tenant/location slugs, initial operating hours, and a tenant-owner account atomically. Use server-side rate limiting and tenant-name/slug collision handling.
4. Build `frontend/app/join/page.tsx` with a short staged form and a clear “your restaurant is not public until setup is complete” result.
5. Build `frontend/app/onboarding/page.tsx` as a progress checklist: restaurant profile → hours → at least one table → menu → invite team → publish public page.
6. Expose existing invitation capability through a prominent “Invite employee” action. Owner can invite managers, waiters, chefs and bartenders; managers can invite only waiters, chefs and bartenders for locations they are assigned to.
7. Add onboarding tests: one tenant/location/owner creation, no cross-tenant mutation, duplicate submission idempotency, non-enumerating public errors, and invite authority matrix.

### P5 — Menu authoring and availability responsibilities

**Depends on P4 for the new onboarding flow; the existing endpoints can be hardened before then.**

1. Turn the hidden Administration menu forms into a guided menu editor: categories → item → image → price → prep destination → modifiers → availability.
2. Add role capabilities at the backend, not only hidden buttons:
   - owner/manager: categories, items, prices, images, modifiers, availability;
   - chef: food items and food availability only;
   - bartender: drink items and drink availability only.
3. Audit every menu create/update/sold-out action with actor, location, before/after value, and timestamp.
4. Add role-specific frontend entry actions in `/ops`, `/prep`, and onboarding so “Invite employee” and “Menu & availability” are discoverable rather than buried in tabs.
5. Test chef/bartender cannot modify another prep destination, price, category, staff, payments, or another tenant/location.

### P6 — Staff navigation and admin usability

**Can start after P4 routes are known.**

1. Replace the generic administration tab overload with clear cards/links: Service, Menu & availability, Reservations, Team, Tables & QR, Payments, Reports, Restaurant settings.
2. Add a dedicated tenant owner workspace (`/owner`) for tenant-wide locations, team, onboarding progress, and reports; keep location service work in `/ops` and management in `/admin`.
3. Add a Settings entry only after the separate settings grilling session resolves its scope; do not put unknown policy choices into the build.
4. Ensure each workspace has an obvious sign-out action (already implemented) and a visible active-location switcher for multi-location staff.

### P7 — Routing, performance, and release proof

**Runs throughout, completed after P1–P6.**

1. Document the client/server contract in `README.md`: browser calls `/api/v1`, FastAPI authorizes and returns DTOs, PostgreSQL persists, Dramatiq/Redis handles background work, WebSocket pushes status. Never make frontend routes the authorization boundary.
2. Add typed API contracts for every new public/onboarding route; reject unsafe unknown shapes before rendering.
3. Keep public listing/restaurant pages server-rendered or cached where safe; keep cart/dialog/state client-side only. This targets perceived route/render speed without prematurely changing the whole stack.
4. Add responsive and accessibility tests for public diner mobile, QR/table tablet and staff desktop.
5. Run the existing release-validation checklist in `TASKS_TO_DO.md` after functional paths are implemented; do not mark it complete based on static code review.

## Decision gates — answer before P3/P4 behaviour is finalized

1. **Restaurant discovery visibility — DECIDED:** A newly registered restaurant remains private until its owner completes setup and explicitly publishes it. Publishing makes its branded link live and opts it into the Chowly directory.
2. **Menu images:** Can an owner paste image URLs only in the first release, or must Chowly host uploaded images from day one? Recommendation: validated image URL plus a refined fallback first; add managed uploads in a follow-up.
3. **Chef/bartender price authority:** May they set prices while populating items, or can only owner/manager approve prices? Recommendation: chefs/bartenders can draft food/drink items and availability; owner/manager approves prices/publishing.
4. **Self-service activation:** Does a newly registered restaurant publish immediately, or stay private until the owner completes setup? Recommendation: private/pending until the checklist has location details, opening hours, and at least one public-ready menu item.
5. **Delivery:** Is Chowly only taking a delivery request/order for the restaurant to fulfil itself, or should it integrate dispatch/delivery pricing? Recommendation: no dispatch integration in this phase; show only service modes the restaurant enables.

## Explicit non-goals for this rebuild

- Customer account creation, sign-in, loyalty or order-history dashboard.
- A global marketplace with ratings, ranking, maps search, or central payment settlement.
- Delivery-driver assignment, live driver tracking, or delivery-fee calculation.
- Copying Papa’s Grill’s content, images, branding, or source code.
