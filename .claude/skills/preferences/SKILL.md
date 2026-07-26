---
name: preferences
description: Use whenever the owner states a standing rule for how they want things handled going forward (e.g. a default payment mode, a default brand/size for an ambiguous item, the shop's name or GSTIN for invoices) — and check remembered preferences before asking a question they've already answered.
---

# Preferences

These are facts that should apply silently and persist across conversations (including after
`/new`) — not something to re-confirm every time.

- When the owner says something like "always assume UPI unless I say cash" or "default atta is
  Aashirvaad 5kg", call `set_preference` with a clear key (`default_payment_mode`,
  `default_atta_sku`, `shop_name`, `shop_gstin`, `shop_address`) and the stated value. Acknowledge
  briefly — don't make a big deal of it.
- Before asking a clarifying question about payment mode, product ambiguity, or invoice details,
  check `get_preference` first (or rely on the standing-preferences block already given to you at
  the start of this conversation) — don't re-ask something a preference already answers.
- Preferences apply silently. Don't announce "using your default payment mode of UPI" every single
  time — just use it, the way a regular shop assistant would.
