# Papa's Grill public ordering reference

Source inspected in a browser on 2026-09-01: <https://papasgrill.daash.restaurant/>. This is a product/interaction reference for Chowly, not source material to copy verbatim. Do not reuse its logo, photography, text, or brand assets without permission.

## What the live site offers

- Restaurant: **Papasgrill — Always Worth It! ❤️**
- Default outlet shown: **lekki phase 1**; the live site said it was closed and opens at 09:00 AM.
- Fulfilment: **Pickup** and **Delivery**. Pickup is the default tab.
- Accepted payment marks shown: Mastercard, Visa, Verve, and Paystack.
- Contact: +234 913 641 8582; papasgrillng@gmail.com.
- Published hours: Monday–Sunday, 09:00 AM–08:00 PM.

### Published locations

| Location | Published address |
|---|---|
| Lekki Phase 1 | Prince Bode Adebowale Cres, Lekki Phase I, Lekki 106104, Lagos |
| Chevron | 24 Oba Akinloye Dr, Lekki Penninsula II, Lekki 105101, Lagos |
| Ikeja GRA | 8A Oba Akinjobi Way, Ikeja GRA, Lagos 100271 |
| Wuse 2 | Bathurst St, Wuse, Abuja 904101, FCT |
| Yaba | 14 University Rd, Onike, Lagos 101245 |
| Ikorodu | Alogba St, Ikorodu 104101 |
| Egbeda | Shasha Rd, Lagos 102213 |
| Gwarimpa | Gostu Plaza, 1st Avenue, Gwarinpa Estate, Gwarinpa 900108, FCT |
| Alausa Ikeja | Otunba Jobi Fele Way, Agidingbi, Ikeja 101233 |

## Visible menu at Lekki Phase 1

Prices are the displayed starting prices in Nigerian naira. Availability and prices may change; this is a snapshot, not an import-ready commercial catalogue.

### Grill House

| Item | Description | Price from |
|---|---|---:|
| Chicken Lap | Chicken lap | ₦4,000 |
| Chicken Wings | Chicken wings | ₦3,000 |
| Turkey | Turkey | ₦5,500 |

### Chicken Small Chops

| Item | Contents / description | Price from |
|---|---|---:|
| Chicken Classic Small Chops Platter | 7 samosas, 7 spring rolls, 20 puff puff, 20 mosa, 7 chicken pieces | ₦9,000 |
| Chicken Elite Small Chops Platter | 15 samosas, 15 spring rolls, 50 puff puff, 50 mosa, 15 chicken pieces, 10 gizzard pieces | ₦20,000 |
| Chicken Mini Small Chops Platter | 5 samosas, 5 spring rolls, 15 puff puff, 15 mosa, 5 chicken pieces | ₦7,000 |
| Chicken Premium Small Chops Platter | 10 samosas, 10 spring rolls, 30 puff puff, 30 mosa, 10 chicken pieces, 10 gizzard pieces | ₦15,000 |
| Chicken Solo Pack Small Chops | 1 samosa, 1 spring roll, 7 puff puff, 7 mosa, 1 chicken piece | ₦2,000 |
| Chicken Standard Small Chops Platter | 10 samosas, 10 spring rolls, 30 puff puff, 30 mosa, 10 chicken pieces | ₦12,000 |
| Chicken Starter Pack Small Chops | 1 samosa, 1 spring roll, 7 puff puff, 7 mosa, 1 peppered gizzard piece | ₦3,500 |

### Turkey Small Chops

| Item | Contents / description | Price from |
|---|---|---:|
| Turkey Classic Small Chops Platter | 7 samosas, 7 spring rolls, 20 puff puff, 20 mosa, 2 turkey wings | ₦9,500 |
| Turkey Elite Small Chops Platter | 15 samosas, 15 spring rolls, 50 puff puff, 50 mosa, 4 turkey wings, 10 peppered gizzard pieces | ₦22,000 |
| Turkey Mini Small Chops Platter | 5 samosas, 5 spring rolls, 15 puff puff, 15 mosa, 1 turkey wing | ₦7,500 |
| Turkey Premium Small Chops Platter | 10 samosas, 10 spring rolls, 30 puff puff, 30 mosa, 3 turkey wings, 10 peppered gizzard pieces | ₦16,000 |
| Turkey Standard Small Chops Platter | 10 samosas, 10 spring rolls, 30 puff puff, 30 mosa, 3 turkey wings | ₦14,000 |
| Turkey Starter Pack Small Chops | 1 samosa, 1 spring roll, 7 puff puff, 7 mosa, 1 turkey wing | ₦5,500 |

### Grill Platters

| Item | Contents / description | Price from |
|---|---|---:|
| Kings Grill Platter | 6 turkey pieces, 6 chicken laps, 25 chicken wings | ₦68,000 |
| Mini Grill | 1 turkey piece, 1 chicken piece | ₦9,000 |
| Prestige Grill Platter | 6 turkey pieces | ₦31,500 |
| Royal Grill Platter | 6 turkey pieces, 6 chicken laps | ₦55,000 |
| Special Grill | 3 turkey pieces | ₦16,000 |

### Sides and gift items

| Item | Price from |
|---|---:|
| French Fries | ₦2,000 |
| Fried Plantain | ₦1,500 |
| Sweet Potato | ₦1,500 |
| Xtra BBQ Sauce | ₦300 |
| Xtra Pepper Sauce | ₦300 |
| Yam Chips | ₦1,500 |
| Papa's Grill gift card / note | ₦500 |

## Interaction patterns worth borrowing (not copying)

1. A visible restaurant and selected-location context heads the menu.
2. Pickup and delivery are chosen before browsing; Chowly will use **dine-in/table QR** and **takeaway** instead.
3. Categories are jump links/chips, then products appear as image-led cards with a short description and price.
4. A cart counter stays in the header, separate from browsing.
5. Branch selection is a dialog showing open/closed state, address, and an action to order.
6. Footer carries hours, delivery types, locations, contact, and payment methods.

## Chowly-specific interpretation

For Chowly, a diner must first see the restaurant/location identity. A **table QR** then grants the specific table ordering capability. Product choices belong in a product-detail dialog; the cart and guest/contact/order confirmation belong in an explicit checkout overlay. This preserves separate per-person table orders and avoids exposing another diner's order.
