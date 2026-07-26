---
name: khata
description: Use whenever the owner mentions putting an amount on someone's credit, a customer paying off what they owe, or asks for a customer's balance. This is the store's credit ledger (khata) — a first-class kirana concept, distinct from a regular cash/UPI/card sale.
---

# Khata (credit ledger)

Khata is running credit a regular customer buys against and pays down later — not the same as a
bill's payment mode.

- **`credit_customer`** — "put ₹500 on Ramesh's credit". If this is the customer's first-ever
  khata entry, the tool creates them automatically — you don't need a separate "add customer"
  step.
- **`settle_khata`** — "Ramesh paid ₹300". This REQUIRES the customer to already exist — if the
  tool refuses because the customer is unknown, tell the owner plainly (e.g. "I don't have a
  khata for anyone named X yet") rather than silently creating one. Settling a khata that doesn't
  exist is exactly the mistake this guard prevents.
- **`get_khata_balance`** — "what's Ramesh's balance?" — reports the net credit outstanding
  (credit given minus payments received). Same not-found behavior as settling.

Customer names are matched case-insensitively but must otherwise match exactly — if the owner's
phrasing is ambiguous about which customer they mean, ask rather than guessing.
