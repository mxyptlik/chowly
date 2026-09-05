# Reservation evolution plan

## Delivery order

1. **Policy and persistence** — location-level customer edit/cancel cutoffs; safe defaults; migration.
2. **Customer reservation workspace API** — opaque-token read, edit, cancel, QR-pass issue/reissue; every mutation audited.
3. **Staff verification API** — authenticated, location-scoped QR validation and explicit check-in action.
4. **Customer journey** — receipt-style success page, then separate reservation workspace with edit/cancel/link/QR actions.
5. **Staff journey** — reservation settings and QR scan/verify/check-in interface.
6. **Verification and demo** — API tests, frontend typecheck/build, seed Mango & Ash role accounts.

## Rules agreed

- Customer may edit party size, date, and time while policy allows; edits reset a requested/confirmed reservation to `REQUESTED`.
- Customer may cancel while policy allows; cancellation is retained with actor/time/audit data.
- Policies are location-level: edit enabled/cutoff minutes; cancellation enabled/cutoff minutes.
- A reservation QR is a separate opaque bearer pass, never customer PII. Only assigned staff can verify it.
- Scan shows a verification result; staff must explicitly check in the guest. QR passes can expire and be reissued.
- Success acknowledgement and reservation workspace are separate pages.
