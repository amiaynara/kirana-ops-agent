---
name: invoicing
description: Use whenever the owner asks for a bill/invoice as a document -- "send me that as a PDF", "print the invoice", "invoice for bill 12". Only applies to a bill that has already been finalized.
---

# Invoicing

Use `render_invoice_pdf` to produce a proper GST invoice document. It needs the `bill_id` --
you already have this from when the bill was finalized (e.g. "Bill #12 finalized"), so use that
number directly. If the owner asks for an invoice and you genuinely don't know which bill they
mean (no bill was finalized yet in this conversation, or they're asking about an old one), ask
which bill number rather than guessing -- never invent a bill id.

The generated PDF includes the shop's name, GSTIN, and address from standing preferences (if set)
-- if the owner hasn't set `shop_name`/`gstin`/`shop_address` yet, the invoice still generates with
sensible defaults, but it's worth mentioning once that setting those preferences would make future
invoices more complete.

Once you call this tool, the document is handled automatically by the channel -- you don't need to
do anything else with it. Just confirm briefly that it's been generated.
