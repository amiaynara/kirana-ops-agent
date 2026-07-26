# Supermarket Ops Agent — Phase Roadmap

High-level phase/task breakdown. Each phase gets its own detailed bite-sized TDD implementation plan (`docs/superpowers/plans/YYYY-MM-DD-phaseN-*.md`) written just before that phase starts. This doc is the roadmap, not the executable plan.

Local-first priority: Phases 0–2 get you a fully working, testable agent on your machine with **no Telegram dependency** (via `CLIChannel`). Telegram, artifacts, and deploy come after core logic is proven.

## Phase 0 — Repo scaffolding & config
- `pyproject.toml`, package layout (`app/`, `tests/`), pinned deps
- `pydantic-settings` config, `ENV` var, `.env.example` + gitignored `.env.local`
- SQLAlchemy engine/session setup, WAL mode pragma, `create_all` bootstrap
- `scripts/seed_dev_data.py` — real SKUs (Aashirvaad Atta 5kg, Tata Salt 1kg, Amul Butter 100g, Fortune Oil 1L, Maggi 70g, Parle-G, Surf Excel, loose sugar/rice/dal)

## Phase 1 — Data model & service layer (TDD, no agent involved)
- SQLAlchemy models: `products, customers, khata_ledger, draft_bills, bills, bill_items, stock_movements, owner_preferences, processed_updates`
- `InventoryService`: `receive_stock`, `create_product`, `get_stock`, `list_low_stock`, oversell-guard primitive
- `BillingService`: `start_bill`, `add_item`, `update_item`, `drop_item`, `get_draft`, `finalize_bill` (idempotent, txn-wrapped, GST calc + CGST/SGST split + rounding), `cancel_bill`
- `KhataService`: `credit_customer`, `settle_khata`, `get_balance`
- Unit tests covering every hard part: oversell guard, GST math, idempotent finalize (double-call same update_id), concurrent finalize + stock-in (threading test against real SQLite file)

## Phase 2 — Tools, Skills, agent core, CLI channel
- Tool wrappers (Claude Agent SDK tool schema) over each Service method — thin, structured refusals
- `SKILL.md` per domain: inventory, billing, khata, preferences (invoicing/analytics skills land in Phase 4)
- `AgentSession`: session-start preference injection, control loop wiring
- `CLIChannel`: local REPL — talk to the agent without Telegram
- `PreferencesService` + `get_preference`/`set_preference` tools

## Phase 3 — Telegram channel adapter
- `TelegramChannel` (python-telegram-bot, long polling) wrapping the same `AgentSession`
- `update_id` passthrough into `finalize_bill`'s idempotency check
- Manual scenario pass over real Telegram (§3 table from the brief)

## Phase 4 — Artifacts: PDF invoice + PPTX analysis deck
- `InvoiceService` (reportlab): GST-correct tax-breakup PDF from `bills`/`bill_items`
- `AnalyticsService` (matplotlib + python-pptx): `get_daily_summary`, `render_analysis_deck`
- `invoicing` + `analytics` Skills, their tools wired into agent

## Phase 5 — Deployment: local run docs, stage, prod
- Dockerfile, `fly.toml`, Fly volumes/secrets for `kirana-ops-agent-stage` and `kirana-ops-agent`
- README local-setup section (this phase matters most right now — everything above should already run local via `CLIChannel` without this phase existing)

## Phase 6 — Hardening & submission polish
- Guardrail refusal tests (below-cost sale, settle nonexistent khata, delete-stock refusal)
- End-to-end Telegram scenario pass, fix gaps
- README (~1 page: harness choice, control loop, skill/tool design, hard-parts solutions)
- 4–5 min recording per brief §6
