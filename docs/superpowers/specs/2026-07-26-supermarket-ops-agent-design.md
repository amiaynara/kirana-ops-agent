# Supermarket Ops Agent — Design Spec

BigMantra take-home. Conversational agent that runs an Indian kirana store end-to-end via Telegram — no web app, no forms, no keyword router. The model reasons over tools; business rules live in the data layer.

## 1. Goals / non-goals

**Goals**
- Owner operates the whole shop (stock, billing, khata, close-of-day, invoices, analysis decks) from a Telegram chat, in plain English.
- Every fact (price, GST slab, stock level) is grounded in the DB via tools — the model never invents one.
- Business-critical rules (oversell guard, GST correctness, idempotent finalize, khata integrity) are enforced at the tool/service layer, never only "hoped for" via prompt.
- Standing preferences persist across `/new` chats — memory lives in the DB, not the conversation.
- Real generated artifacts: GST-correct PDF invoice, PPTX analysis deck with real charts.

**Non-goals (this iteration)**
- Multi-store / multi-tenant support.
- Real payment gateway integration (cash/UPI/card are recorded, not processed).
- Voice notes, barcode scanning, multi-language — stretch, not required.
- Horizontal scaling — single Fly.io instance, single SQLite file is the target scale.

## 2. Architecture

One Claude Agent SDK session per Telegram `chat_id`. Domain **Skills** (`SKILL.md`) teach the agent store-specific reasoning; thin **tools** call a **service layer** that owns every DB transaction and business rule.

```
Telegram (owner) <-> python-telegram-bot <-> Claude Agent SDK session
                                                 |
                                            [Skills: inventory, billing,
                                             khata, invoicing, analytics,
                                             preferences]
                                                 |
                                            [Tools: thin wrappers,
                                             no business logic]
                                                 |
                                            [Service layer: owns every
                                             transaction + rule]
                                                 |
                                            SQLite (WAL) via SQLAlchemy
                                                 |
                                    +------------+------------+
                              InvoiceService              AnalyticsService
                              (reportlab)                 (matplotlib + python-pptx)
```

Full diagram + bill-lifecycle sequence diagram: see architecture artifact shared during brainstorming (requirement map, control-flow diagram, hard-parts table). This spec is the source of truth; the artifact is illustrative.

Deployment: Fly.io, single machine, persistent volume for the SQLite file, long-polling bot process (no public webhook needed, simpler than managing a public HTTPS endpoint for a take-home).

## 3. Data model

SQLite + SQLAlchemy. `stock_movements` and `khata_ledger` are append-only audit trails — cached totals (`qty_on_hand`, khata balance) are always derived/updated inside the same transaction as the movement, never mutated independently.

```
products(id, name, category, unit, is_loose, hsn_code, gst_slab,
         cost_price, sell_price, mrp, qty_on_hand, reorder_level,
         created_at, updated_at)

customers(id, name, phone, created_at)

khata_ledger(id, customer_id, amount, direction[credit|payment],
             note, bill_id nullable, created_at)   -- append-only

draft_bills(chat_id PK, payload_json, payment_mode, created_at, updated_at)
            -- one open draft per chat; overwritten on edit, deleted on finalize/cancel

bills(id, chat_id, status[finalized|void], payment_mode, payment_ref,
      subtotal, cgst_total, sgst_total, grand_total,
      idempotency_key unique, created_at)

bill_items(id, bill_id, product_id, qty, unit_price, gst_slab,
           cgst_amt, sgst_amt, line_total)

stock_movements(id, product_id, delta, reason[purchase|sale|adjustment],
                ref_bill_id nullable, created_at)   -- append-only

owner_preferences(key PK, value, updated_at)
                  -- default_payment_mode, default_atta_sku, shop_name,
                  -- gstin, shop_address

processed_updates(telegram_update_id PK, processed_at)  -- idempotency dedup
```

`unit` ∈ {kg, g, litre, ml, packet, dozen, piece}. `gst_slab` ∈ {0, 5, 12, 18, 28}. Intra-state assumed throughout → CGST = SGST = slab/2 per line; bill totals round to nearest paisa at the bill level (not per-line) to avoid rounding drift across items.

## 4. Skills & tools

| Skill | Domain knowledge it carries | Tools |
|---|---|---|
| `inventory` | unit conversion, loose-vs-packaged distinction, HSN/GST lookup, when to ask "which SKU?" | `get_stock`, `list_low_stock`, `receive_stock`, `create_product` |
| `billing` | GST slab math, CGST/SGST split, draft-vs-final semantics, oversell is a tool-layer refusal not a prompt suggestion | `start_bill`, `add_bill_item`, `update_bill_item`, `drop_bill_item`, `get_bill_draft`, `finalize_bill`, `cancel_bill` |
| `khata` | credit is a ledger (append-only), not a mutable balance field; settling a nonexistent customer is refused | `credit_customer`, `settle_khata`, `get_khata_balance` |
| `invoicing` | when the owner wants a document vs. a text answer | `render_invoice_pdf` |
| `analytics` | daily close vs. weekly deck distinction; what "top items" / "running out" means | `get_daily_summary`, `render_analysis_deck` |
| `preferences` | standing prefs override defaults silently; don't re-ask once a preference is set | `get_preference`, `set_preference` |

Tool contract: each tool validates input shape and calls exactly one Service method, returning a structured result — including a typed refusal reason (`insufficient_stock`, `below_cost`, `customer_not_found`, `bill_already_finalized`, etc.) the agent must relay to the owner, never silently work around.

## 5. Concurrency & idempotency

- **Idempotent finalize**: `finalize_bill` runs inside `BEGIN IMMEDIATE`; first checks `processed_updates(telegram_update_id)` — if seen, returns the prior `bill_id` as a no-op instead of re-billing.
- **Oversell guard**: inside the same transaction, `qty_on_hand >= requested` is checked per line before any write; insufficient stock aborts the whole finalize with no partial writes.
- **Concurrent writers** (two bills, or a bill + a stock receipt, in flight): SQLite WAL mode + `BEGIN IMMEDIATE` serializes writers while keeping reads unblocked — sufficient for single-instance, single-file scale.
- **Multi-turn bills**: `draft_bills` keyed by `chat_id` persists the in-progress bill outside the model's context — a process restart mid-build does not lose the draft, and stock is untouched until `finalize_bill` commits.

## 6. Memory (cross-session)

`owner_preferences` is read once at session start and injected into the system prompt as current fact, not conversation history. `set_preference` writes through immediately. Starting `/new` clears the Telegram-side conversation; the next session-start read re-populates the same facts from the DB — preferences appear "remembered" because they never left durable storage.

## 7. Artifacts

- **Invoice PDF** (`InvoiceService`, reportlab): renders from `bills`/`bill_items` directly — HSN codes, per-line CGST/SGST, tax breakup table, rounding shown. Never a screenshot of chat text.
- **Analysis deck** (`AnalyticsService`, matplotlib + python-pptx): sales trend, top items, stock health, GST collected — matplotlib charts embedded as images on real slides, not text boxes.

## 8. Tech stack decisions

| Requirement | Technology | Why |
|---|---|---|
| Agent control loop | Claude Agent SDK (Python) | native tool-use loop matches observe→reason→act→feed-back requirement; Skills primitive matches the brief's "author skill files" grading criterion directly |
| Chat interface | python-telegram-bot | mature `update_id` handling, required for idempotent finalize under at-least-once redelivery |
| Durable store | SQLite (WAL) + SQLAlchemy | zero-ops, file-based, survives restart; sufficient concurrency story for this scale without standing up Postgres infra to justify |
| PDF invoice | reportlab | full control over GST tax-breakup layout |
| Analysis deck | python-pptx + matplotlib | real chart images in real slides |
| Deployment | Fly.io | persistent volume for the SQLite file + always-on long-polling process; Render's free tier idles and would drop the bot mid-review |

## 9. Testing approach

- Service layer is unit-testable independent of the agent (no LLM calls needed) — oversell guard, GST math, idempotent finalize, khata ledger integrity all get direct tests against the service classes.
- Tool layer gets thin contract tests (input validation, refusal shapes).
- End-to-end: manual Telegram scenarios per the brief's §3 table, recorded for the submission video.

## 10. Open risks / assumptions

- Assumes intra-state GST only (CGST+SGST), per brief — no IGST path.
- Single owner per store, single store per bot instance — no multi-tenant auth.
- Fly.io free tier limits (shared CPU, small volume) assumed sufficient for review-period load.
