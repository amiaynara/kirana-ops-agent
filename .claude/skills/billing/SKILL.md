---
name: billing
description: Use whenever the owner is cutting a bill, mentions items to buy, wants to edit an in-progress bill (drop/add/change quantity), asks to see the current bill, or wants to finalize/cancel one. Covers GST tax breakup and the oversell guard.
---

# Billing

A bill is built over several messages before it's final. Follow this lifecycle:

1. **`start_bill`** — begin a new bill for this chat. If the owner just starts listing items
   without saying "start a bill" or "make a bill", call `start_bill` implicitly first, then add
   the items — don't ask them to explicitly say "start" first.
2. **`add_bill_item`** (repeat per item) — resolve the product by its exact name. If the owner's
   phrasing is ambiguous (e.g. "atta" with no size, and no standing preference answers it), ask
   which SKU before adding.
3. Mid-build edits — **`update_bill_item`** to change a quantity, **`drop_bill_item`** to remove a
   line. These work on the SAME draft; don't call `start_bill` again unless the owner clearly
   wants to discard everything and start over (use `cancel_bill` for that instead, then
   `start_bill`).
4. **`get_bill_draft`** — show the running total with its GST tax breakup whenever the owner asks
   "what's the total so far" or similar, or after adding items if it feels natural to confirm.
5. **`finalize_bill`** — ONLY when the owner has clearly confirmed they want to complete the sale
   (e.g. "that's it, UPI" / "finalize" / "done, cash"). This is the point stock actually
   decrements — never call it speculatively or "just to check" the total; use `get_bill_draft` for
   that instead.

## Payment mode

If the owner doesn't state a payment mode, check preferences for a default before asking — many
owners set "always assume UPI unless I say cash" as a standing preference. If there's genuinely no
default and none was stated, ask before finalizing.

## Oversell guard

If `add_bill_item` or `finalize_bill` refuses because there isn't enough stock, relay that refusal
plainly — e.g. "Only 6 in stock, you asked for 10." Never round down silently or substitute a
different quantity without the owner's say-so.

## GST tax breakup

Every draft and every finalized bill shows CGST and SGST separately, plus the subtotal and grand
total — this is what a printed GST invoice needs to show. Don't collapse them into one "tax" line
when relaying to the owner.
