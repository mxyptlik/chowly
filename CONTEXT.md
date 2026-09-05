# Chowly

Chowly is a restaurant digital dining platform for independent restaurant businesses. This context captures the domain language and decisions agreed while designing it.

## Language

**Restaurant Tenant**:
An independent restaurant business that owns one or more restaurant locations and is isolated from every other tenant on Chowly.
_Avoid_: restaurant, restaurant account, client restaurant

**Restaurant Location**:
A physical venue operated by exactly one Restaurant Tenant where dining service, staff, menus, tables, and orders are managed.
_Avoid_: restaurant, branch

**Diner**:
A person browsing a Restaurant Location's menu or placing an order through Chowly, whether or not their identity has been collected.
_Avoid_: user, guest customer

**Customer**:
A Diner represented by the required customer record for an order, created or identified from their name and phone number without requiring sign-in or account registration.
_Avoid_: authenticated user, account holder

**Order Contact Detail**:
An optional email address supplied for a Customer.
_Avoid_: customer account, required contact, phone number

**Staff Account**:
An invitation-created Chowly account for a restaurant worker, with one or more roles and explicit Restaurant Location assignments.
_Avoid_: public staff registration

**Platform Administrator**:
A Chowly internal operator who administers the multi-tenant platform.
_Avoid_: restaurant manager

**Tenant Owner**:
The Restaurant Tenant's administrator who can manage locations, managers, staff, tables, and menus.
_Avoid_: platform administrator

**Tenant-Scoped Customer Data**:
The subset of a global Customer's records created at a Restaurant Tenant's locations and visible only to that tenant.
_Avoid_: shared customer history

**Order Acceptance**:
The restaurant staff decision that confirms a submitted order can proceed to preparation.
_Avoid_: automatic confirmation

**Order Owner**:
The waiter responsible for an accepted order's guest-service coordination.
_Avoid_: order creator, preparer

**Preparation Queue**:
The location-specific work queue of accepted food or drink order lines awaiting a chef or bartender to claim and prepare.
_Avoid_: order queue, kitchen order

**Ready for Service**:
The order state reached when every active food and drink line has been completed by its preparer.
_Avoid_: partially ready

**Order Amendment**:
A waiter-initiated change or cancellation to an order after it has been accepted.
_Avoid_: customer edit, cart edit

**Served Order**:
An order marked by its waiter as delivered to the diner and eligible for Chowly payment.
_Avoid_: completed order, ready order

**Order Payment**:
The single full payment recorded for a Served Order in the initial Chowly release.
_Avoid_: split payment, partial payment

**Service Mode**:
Whether an order is fulfilled as dine-in at a table or as a takeaway order.
_Avoid_: order type

**Table Activity**:
The operational state of a table that remains active while it has unpaid orders and becomes available only after its service is closed.
_Avoid_: QR status, table session

**Table Visit**:
The time-bounded seating context for a table, started by an accepted order and closed by staff after all associated orders are paid or cancelled.
_Avoid_: permanent table state

**Menu Modifier**:
A structured customer-selectable variation or add-on for a menu item, such as size, spice level, extras, or exclusions.
_Avoid_: free-text customisation

**Special Instruction**:
Optional free-text preparation guidance supplied by a Customer for an ordered item.
_Avoid_: feedback, complaint

**Wait-Time Suggestion**:
A Chowly-provided preset waiting-time option that the Order Owner or a manager may select or override manually.
_Avoid_: automatic wait estimate

**Order Transfer**:
A waiter- or manager-initiated movement of an accepted order from one table to another, recorded with actor and timestamp.
_Avoid_: silent table change

**Order Cancellation**:
A waiter- or manager-initiated cancellation of an accepted order, recorded with a mandatory reason.
_Avoid_: deletion

**Mock Payment**:
A simulated payment used in the initial release rather than a live payment-provider transaction.
_Avoid_: live payment integration

**Manual Order**:
An order created by a waiter or manager for a walk-in diner when the QR ordering route cannot be used.
_Avoid_: primary order path

**Audit Event**:
An immutable timestamped record of a material staff action and its actor.
_Avoid_: editable log

**Retention Policy**:
The tenant-configurable period for retaining Customer details and order history, constrained by a platform-wide maximum.
_Avoid_: indefinite storage

**Final Menu Price**:
The customer-visible price for a menu item or selected modifier, inclusive of applicable VAT and service charge.
_Avoid_: checkout surcharge, hidden fee

**Customer Phone Identity**:
The normalized phone number that uniquely identifies a global Customer in the initial Chowly release.
_Avoid_: shared contact number

**Location Charge Policy**:
The configurable VAT and service-charge percentages used to calculate Final Menu Prices for one Restaurant Location.
_Avoid_: platform-wide fixed tax rate

**Locked Preparation Line**:
An order line claimed by a chef or bartender that a waiter can no longer amend directly.
_Avoid_: mutable prepared line

**Reservation**:
A staff-confirmed request for a party to use a Restaurant Location at a specified date and time.
_Avoid_: walk-in order, waitlist

**Offline-Tolerant Operation**:
The ability to keep safe local work available during a network interruption and synchronize it when connectivity returns, without falsely confirming online-only actions.
_Avoid_: fully offline transaction processing

**Item Rating**:
One Customer rating of one food or drink order line, permitted only for an item on that Customer's served order.
_Avoid_: menu rating

**Order Rating**:
One Customer rating of the overall dining order, permitted only for that Customer's served order.
_Avoid_: item rating

**Table QR Code**:
A daily, location-specific code that opens the menu for exactly one dining table and identifies that table for a dine-in order.
_Avoid_: permanent QR code, generic QR code

## Relationships

- A **Restaurant Tenant** owns one or more **Restaurant Locations**.
- A **Restaurant Location** owns its operational data, including menus, staff, tables, and orders.
- A **Tenant Owner** administers a Restaurant Tenant's locations, managers, staff, tables, and menus.
- A **Staff Account** may hold multiple roles and is assigned explicitly to one or more Restaurant Locations.
- A **Table QR Code** identifies exactly one table at a **Restaurant Location**.
- A **Table QR Code** is regenerated daily and may be regenerated early by a waiter.
- A **Customer** has a required name and phone number and may have an **Order Contact Detail**.
- A **Customer Phone Identity** uniquely identifies a global Customer.
- An order belongs to exactly one **Customer**.
- A table may have many separate orders from different Customers.
- A **Customer** may place orders at many Restaurant Tenants.
- A Restaurant Tenant may access only its **Tenant-Scoped Customer Data**.
- A submitted order requires **Order Acceptance** before its line items are routed for preparation.
- The waiter who accepts an order becomes its **Order Owner** by default.
- A manager may assign or reassign an **Order Owner**.
- Order food lines enter the kitchen **Preparation Queue** after acceptance.
- Order drink lines enter the bar **Preparation Queue** after acceptance.
- A diner sees an order as preparing until it reaches **Ready for Service**; only staff see individual-line progress.
- A diner may cancel their submitted order only before Order Acceptance.
- An accepted order may be changed or cancelled only through an **Order Amendment** by a waiter.
- A diner adds further items by creating a separate order for the table, not by changing an existing order.
- The Order Owner marks an order as a **Served Order** when it has been delivered to the diner.
- A diner may pay through Chowly only for a **Served Order** and must pay before leaving the Restaurant Location.
- A Served Order has at most one successful **Order Payment**, covering its full amount.
- An order is dine-in by default after a Table QR Code scan and may be switched to takeaway only before Order Acceptance.
- An accepted order starts a **Table Visit** and places its table in **Table Activity**.
- A table remains in **Table Activity** while it has unpaid orders; staff close the Table Visit only after all its orders are paid or cancelled.
- An ordered menu item may include **Menu Modifiers** and an optional **Special Instruction**.
- A **Menu Modifier** may add to the Final Menu Price; the selected modifier and its price are snapshotted on the order line.
- A Restaurant Location applies its **Location Charge Policy** to calculate Final Menu Prices.
- The Order Owner or a manager selects a **Wait-Time Suggestion** or sets the wait time manually.
- Staff may make an **Order Transfer** with a complete timestamped audit trail.
- An Order Owner or manager may make an **Order Cancellation** with a required reason.
- Initial Order Payments are **Mock Payments** in Nigerian naira (NGN); they simulate card, bank-transfer, and wallet payments, while cash is recorded by staff rather than selected by the diner.
- Menu prices are displayed as **Final Menu Prices**, including VAT and service charge, with no surprise checkout surcharge.
- A Customer may create one **Item Rating** for each served order line and one **Order Rating** for the served order overall.
- An Item Rating may be made for either a food or drink order line.
- A waiter or manager may create a **Manual Order**, although QR ordering remains the primary path.
- Acceptance, reassignment, wait-time changes, preparation claims, transfers, amendments, cancellations, refunds, and availability changes each create an **Audit Event**.
- A **Retention Policy** is configurable by each Restaurant Tenant, defaults to 90 days, has a 120-day platform maximum, and requires an approved request to exceed that maximum.
- Chefs and bartenders see only the table, ordered items, modifiers, and special instructions needed for preparation, never Customer contact details.
- A chef or bartender claim turns an order line into a **Locked Preparation Line**; a waiter may not amend it directly.
- A Reservation records the Customer name and phone number, location, table or party size, date/time, and staff-confirmed status.
- Table QR Codes are displayed digitally on a table tablet in the first release.
- Chowly supports **Offline-Tolerant Operation**: menus and safe work are cached or queued locally, while payments, QR regeneration, acceptance, and real-time status wait for online confirmation.

## Example dialogue

> **Dev:** "Can a staff member at one **Restaurant Tenant** see another tenant's orders?"
> **Domain expert:** "No — each **Restaurant Tenant** is isolated from all other tenants."

> **Dev:** "How does a **Diner** start an order?"
> **Domain expert:** "They scan the **Table QR Code**, which opens the menu for that table."

> **Dev:** "Does a **Customer** need to sign in before placing an order?"
> **Domain expert:** "No. Chowly creates or identifies the required customer record during the order flow using the customer's name and phone number; email is optional."

> **Dev:** "Can a Restaurant Tenant view a Customer's orders at other restaurants?"
> **Domain expert:** "No. The Customer is global, but each tenant sees only its Tenant-Scoped Customer Data."

> **Dev:** "When can food and drinks begin preparation?"
> **Domain expert:** "Only after restaurant staff complete Order Acceptance."

> **Dev:** "Who owns an accepted order?"
> **Domain expert:** "The waiter who accepted it, unless a manager assigns or reassigns another waiter."

> **Dev:** "Who chooses the chef or bartender for an accepted line?"
> **Domain expert:** "The relevant preparer claims the line from their location's Preparation Queue."

> **Dev:** "What does the diner see while only part of an order is complete?"
> **Domain expert:** "Preparing. The order becomes Ready for Service only when every active line is complete."

> **Dev:** "Can a diner add an item after submitting an order?"
> **Domain expert:** "No. They place a new order; after acceptance, a waiter handles any amendment to the existing order."

> **Dev:** "When can a diner pay?"
> **Domain expert:** "After their waiter marks the order served, and before they leave the Restaurant Location."

> **Dev:** "Can a Served Order be paid in instalments or split between diners?"
> **Domain expert:** "Not in the initial release: it has one full Order Payment."

> **Dev:** "Can a diner change an accepted order?"
> **Domain expert:** "Only a waiter can amend it; the diner makes further additions as a new order."

> **Dev:** "How long does a Table QR Code remain valid?"
> **Domain expert:** "It is refreshed daily for its table, and a waiter may regenerate it immediately when necessary."

> **Dev:** "Can anyone create a staff account?"
> **Domain expert:** "No. Staff Accounts are invitation-created and have explicit roles and Restaurant Location assignments."

> **Dev:** "Does Chowly add charges at checkout?"
> **Domain expert:** "No. The displayed price already includes applicable VAT and service charge."

> **Dev:** "Can a waiter change a line after a preparer has claimed it?"
> **Domain expert:** "No. It is a Locked Preparation Line and requires a preparer or manager to resolve."

> **Dev:** "When can staff close a Table Visit?"
> **Domain expert:** "Only after every associated order has been paid or cancelled."

> **Dev:** "What happens if the network drops during service?"
> **Domain expert:** "Chowly preserves safe local work and synchronizes it on reconnection, but never claims an online-only action has completed until confirmed."

> **Dev:** "How is a wait time selected?"
> **Domain expert:** "Chowly offers preset suggestions such as 5, 10, 15, 30, and 45 minutes, but the waiter or manager can set another value manually."

> **Dev:** "Can a Customer rate the food and the overall experience?"
> **Domain expert:** "Yes: once per served menu line and once for the served order overall."

## Flagged ambiguities

- "Restaurant" can mean either the business tenant or a physical venue; resolved: use **Restaurant Tenant** for the business and **Restaurant Location** for the venue.
- The source model's mandatory **Customer** was initially confused with authentication; resolved: every order requires a Customer record with a name and phone number, but no sign-in, password, or account registration is required; email is optional.
- The source model's Rating entity allows only one rating per order; resolved: Chowly needs both an overall Order Rating and per-order-line Item Ratings.
- The first release uses Mock Payments in NGN despite exposing card, transfer, wallet, and staff-recorded cash flows; live processor integration is not in scope yet.
- The Table QR Code is dynamic rather than permanent: it refreshes daily and staff may regenerate it early.
- Customer-detail and order-history retention defaults to 90 days and normally may not exceed 120 days without approval.
- Reservations are part of the first release, limited to staff confirmation and core party, table, and time details; deposits, waitlists, and automatic table optimisation are deferred.
