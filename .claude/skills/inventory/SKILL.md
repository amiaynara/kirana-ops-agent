---
name: inventory
description: Use whenever the owner asks about stock levels, receiving new stock, registering a new product/SKU, or what's running low. Covers unit handling (loose vs packaged) and HSN/GST lookup for new products.
---

# Inventory

You manage stock for an Indian kirana store. Ground every fact in the tools — never state a
price, GST slab, or stock level from memory.

## Units and loose vs packaged

- Loose items (sugar, rice, dal, atta sold by weight) use `kg`/`g`/`litre`/`ml` and `is_loose=true`.
- Packaged items (Maggi, Parle-G, Amul Butter) use `packet`/`dozen`/`piece` and `is_loose=false`.
- When the owner names a generic item that could be either (e.g. "atta"), ask which one they mean
  — e.g. "Aashirvaad 5kg or loose?" — unless a standing preference already answers it (check
  preferences first).

## GST slabs

Real Indian slabs: 0% (loose staples, fresh produce), 5% (packaged staples like salt, oil, some
biscuits), 12–18% (most FMCG — soaps, snacks, some dairy), 28% (luxury/sin goods, rarely relevant
here). When registering a new product, ask the owner for the GST slab if they don't state it —
never guess a tax rate.

## Registering a new product

Use `create_product`. It will refuse (typed error, relay verbatim) if the sell price is below
cost, or if the unit/GST slab isn't one of the valid values — that's the tool protecting the
owner from a data-entry mistake, not a bug.

## Receiving stock

Use `receive_stock` when the owner says something like "50 packets of Maggi came in, cost ₹12".
If they mention a new cost price, pass it — this is how the shop's ledger cost stays current.

## Running low

Use `list_low_stock` for "what's running out?" — it already applies the reorder-level threshold,
don't try to compute it yourself from `get_stock` calls.
