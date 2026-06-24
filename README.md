# Sportsbook Affiliate Bot

A production-ready **Telegram-first affiliate/referral** bot built for solo founders. It routes users to **one** approved external sportsbook offer, tracks referrals/clicks/conversions, optionally sells compliant digital access via crypto (xRocket Pay), auto-delivers after verified conversion or payment, answers common questions via a rules-based FAQ, and escalates rare cases to one admin — all in a single process on a single VPS.

**Stack:** Python 3.12 · aiogram 3.29 (Bot API 9.4) · SQLAlchemy 2 async + SQLite (WAL) · Alembic · pydantic-settings · structlog (JSON) · optional FastAPI webhooks · xRocket Pay (TON/USDT) · Docker + docker-compose · GitHub Actions CI/CD. **109 tests, 41 source files, mypy strict.**

**How it works:** Users complete a compliance gate (age + jurisdiction + responsible-gambling + terms + opt-in) before seeing any offer. Referral codes are deterministic (base62 of telegram ID). Clicks and conversions are tracked with last-touch attribution (30-day window) and anti-fraud (duplicate filtering, velocity, self-referral block, fingerprint flagging). Webhooks handle affiliate postbacks and payment callbacks with idempotent dedup. Auto-delivery fires on approved conversions or confirmed payments — each delivery is dedup-protected. Support uses keyword-based FAQ matching with escalation after 2 unmatched attempts. Admin commands cover stats, offers, manual confirms, broadcasts, health, and CSV export.

**Deployment:** `docker compose up -d --build` on a single VPS. The container runs `alembic upgrade head` then starts long polling. See [DEPLOY.md](DEPLOY.md) for the full runbook.

**MVP simplifications:** SQLite (single-file, WAL mode, switch to Postgres documented), single bot process + optional webhook process, last-touch attribution, rules-based support (no AI/NLP), one offer at a time, one admin.

**Exclusions:** No casino. No bets/wagers/deposits accepted. No Mini App. No Telegram Ads (disallowed for gambling). No odds/prediction scraping. No userbots. The bot only routes + tracks + delivers.

> ⚠️ **Compliance:** This bot never accepts bets, holds balances, or acts as a bookmaker. A compliance gate runs before any offer is shown. All timestamps are persisted.

---

## Quickstart

```bash
cp .env.example .env            # fill BOT_TOKEN, ADMIN_CHAT_ID, LANDING_URL, BOT_USERNAME
pip install -e .[dev]           # install app + dev tooling

python -m app.main              # start long polling
python -m app.main --check      # boot smoke test (no polling)
```

Seed the one real offer (edit values in `scripts/seed_offer.py` first):
```bash
python -m scripts.seed_offer
```

---

## Stack (pinned, verified June 2026)

| Layer | Choice |
| --- | --- |
| Language | Python 3.12 |
| Bot framework | aiogram `>=3.29,<4` (modular Router + Dispatcher + middleware) |
| ORM / DB | SQLAlchemy 2.x async + aiosqlite (SQLite for MVP, WAL mode) |
| Migrations | Alembic |
| Webhooks | FastAPI + uvicorn (only if an external provider needs HTTPS callbacks) |
| Config | pydantic-settings |
| Logging | structlog (unified with stdlib → JSON to stdout) |
| Payments | xRocket Pay (optional; TON/USDT; only if `PAYMENTS_ENABLED=true`) |
| Tests | pytest + pytest-asyncio (109 tests) |
| Container | Docker + docker-compose (non-root user, migrate-then-start) |
| CI/CD | GitHub Actions (lint→type→test→migrate→smoke→docker-build→deploy) |

---

## Project layout

```
app/            # entrypoint (main.py), config, logging, webhook_app
routers/        # aiogram routers: admin, start, referral, support, common
services/       # referral, conversion, anti_fraud, payment, delivery, support,
                # admin, broadcast, stats, jobs, xrocket_client
db/             # base, models (12 tables), repositories, session, migrations
middlewares/    # 8-layer stack (error, context, db, user, lang, throttle, admin, compliance)
states/         # FSM state groups (support)
utils/          # i18n, faq, security, compliance
texts/          # localization: en.json, ru.json (75 keys each)
faq/            # FAQ knowledge base: en.yaml, ru.yaml (13 entries each)
scripts/        # seed_offer.py
tests/          # 109 tests across 16 files
```

---

## Configuration

All settings from environment variables (or `.env`). See `.env.example`.

| Var | Required | Default | Notes |
| --- | --- | --- | --- |
| `BOT_TOKEN` | ✅ | — | from @BotFather |
| `ADMIN_CHAT_ID` | ✅ | — | numeric admin chat/user id |
| `LANDING_URL` | ✅ | — | external offer landing URL |
| `BOT_USERNAME` | – | `""` | bot username (without @) for referral deep links |
| `DATABASE_URL` | – | `sqlite+aiosqlite:///./bot.db` | Postgres: `postgresql+asyncpg://...` |
| `ENVIRONMENT` | – | `dev` | `dev` \| `prod` |
| `LOG_LEVEL` | – | `INFO` | `DEBUG`..`ERROR` |
| `DEFAULT_LANG` | – | `en` | `en` \| `ru` |
| `PAYMENTS_ENABLED` | – | `false` | enables crypto payment path |
| `XROCKET_API_KEY` | – | — | required if payments enabled in prod |
| `XROCKET_BASE_URL` | – | `https://pay.xrocket.tg/` | |
| `XROCKET_MODE` | – | `testnet` | `testnet` \| `live` |
| `WEBHOOK_ENABLED` | – | `false` | only if a provider needs HTTPS callbacks |
| `WEBHOOK_SECRET` | – | — | required if webhook enabled in prod |
| `WEBHOOK_BASE_URL` | – | — | required if webhook enabled in prod |

**Fail-fast:** required vars enforced by the type system. In `prod`, extra cross-field checks raise at startup. Secrets never committed.

---

## Internationalization (i18n)

All user-facing strings via `t(key, lang)` loaded from `texts/{en,ru}.json` (75 keys each). Fallback: requested lang → English → key string. FAQ answers resolve through the same system. Parity enforced by tests.

Supported: **English (en)** and **Russian (ru)** only.

---

## Middleware Pipeline

| # | Middleware | Purpose |
|---|---|---|
| 1 | ErrorMiddleware | Catch unhandled, log + alert admin + show error text |
| 2 | ContextMiddleware | Inject settings/logger, bind correlation fields |
| 3 | DbSessionMiddleware | Async session per update, commit/rollback |
| 4 | UserUpsertMiddleware | Upsert user by telegram_id |
| 5 | LanguageMiddleware | Resolve lang, expose `t()` |
| 6 | ThrottleMiddleware | Per-user token-bucket (burst=10) |
| 7 | AdminMiddleware | Flag `is_admin` when chat_id == ADMIN_CHAT_ID |
| 8 | ComplianceMiddleware | Flag `is_compliant` for offer gating |

---

## Compliance Gate

Before any offer is shown: legal-age (18+) → jurisdiction self-attestation → responsible-gambling acknowledgement → terms acceptance (links to LANDING_URL) → marketing opt-in/out. All timestamps persisted. Soft-stop (not crash) if declined.

---

## Referral & Attribution

- **Referral codes**: deterministic base62(telegram_id) + checksum. Deep links: `https://t.me/<bot_username>?start=<code>`.
- **Attribution**: last-touch within 30-day window. Self-referral blocked.
- **Dedup**: `partner_conversion_id` UNIQUE. Duplicate postback = no-op 200.
- **Anti-fraud**: duplicate clicks (5-min window), velocity (10/min), self-referral block, fingerprint flagging (3+ accounts on same IP hash). Flag, don't auto-ban.

---

## Payments & Delivery

- **xRocket Pay**: invoice creation + polling + webhook callback. Status machine: created → pending → paid/expired/failed. TON/USDT only. Gated by `PAYMENTS_ENABLED`.
- **Auto-delivery**: triggers on approved conversion or paid payment. 5 types (external_link, access_link, file_ref, access_code, text). Dedup via `dedupe_key` UNIQUE. Never logs payload contents.
- **Background jobs**: payment polling, delivery retry (cap=5), webhook reconciliation, expired cleanup, broadcast worker, health heartbeat.

---

## Support

Rules-based FAQ (no AI/NLP): 13 entries × 5 categories (general, payments, referrals, delivery, compliance). Keyword matching in EN+RU. Escalation after 2 unmatched attempts or explicit request. Admin receives structured card, can reply via `/reply` and close via callback.

---

## Admin Commands

| Command | Description |
|---|---|
| `/stats` | Dashboard: users, clicks, conversions, payments, deliveries |
| `/offers` | List all offers |
| `/offer_add <code> <title_key> <url> [paid] [amount] [currency]` | Add an offer |
| `/offer_toggle <id>` | Enable/disable an offer |
| `/confirm_payment <id>` | Manual payment confirm (audited) |
| `/confirm_conversion <id> [approve\|reject]` | Manual conversion confirm (audited) |
| `/health` | DB ping, job status, error counts |
| `/broadcast <segment> <message>` | Send broadcast (all/marketing; rate-limited, opt-out respected) |
| `/export [conversions\|payments]` | CSV export |
| `/reply <request_id> <message>` | Reply to support escalation |

---

## Webhooks (FastAPI, optional)

```
POST /webhooks/affiliate/{provider}   — affiliate postbacks
POST /webhooks/payments/{provider}     — payment callbacks
GET  /health                           — health check
```

Secret verified via `X-Webhook-Secret` or `secret_token`. Idempotent via `dedupe_hash`. Start separately:
```bash
uvicorn app.webhook_app:create_app --factory --host 0.0.0.0 --port 8080
```

---

## Lint / Type-check / Test

```bash
ruff check .          # clean
mypy app              # clean (41 files, strict)
pytest -q             # 109 passed
```

---

## Deployment

```bash
docker compose up -d --build    # single VPS, migrate-then-start
```

See **[DEPLOY.md](DEPLOY.md)** for the full runbook and **[LAUNCH_CHECKLIST.md](LAUNCH_CHECKLIST.md)** for the go-live checklist. See **[RISK_REGISTER.md](RISK_REGISTER.md)** for top launch risks.

---

## Assumptions

1. **One offer at a time.** The catalog shows the first active offer. Multiple offers are supported by the schema but the MVP UI surfaces one.
2. **Last-touch attribution.** The most recent click within 30 days gets credit. First-touch or multi-touch is a future enhancement.
3. **xRocket Pay API fields** are marked TODO where uncertain. The client is isolated behind typed models + MockXRocketClient. Verify against the live API before production payments.
4. **SQLite for MVP.** WAL mode + busy_timeout reduce contention. Switch to Postgres when concurrent writes or broadcast volume cause `SQLITE_BUSY`.
5. **Rules-based support only.** No AI/NLP. FAQ matching is keyword/substring. Escalation after 2 unmatched attempts.
6. **Organic/partner/direct traffic only.** Telegram Ads are disallowed for gambling and are not an acquisition assumption.
7. **Single admin.** One `ADMIN_CHAT_ID` handles all escalations, broadcasts, and manual operations.

---

## Post-Launch Priorities

Ranked by revenue/retention impact:

1. **Better partner analytics** — conversion rate by source, EPC (earnings per click), cohort retention. The StatsService infrastructure exists; needs richer dashboards.
2. **PostgreSQL migration** — when concurrent writers or broadcast volume causes SQLite contention. Fully documented; swap `DATABASE_URL` + `asyncpg`.
3. **Improved FAQ/support deflection** — more FAQ entries, better keyword coverage, reduce admin escalation load.
4. **Landing A/B testing** — test different offer presentations/landing pages for higher conversion rates.
5. **Broadcast segmentation** — segment by jurisdiction, activity, conversion status for targeted re-engagement.

---

## Status

**v0.1.0 — Launch ready.** 109 tests green, mypy strict clean, ruff clean, Docker builds, CI/CD with deploy, full runbook + checklist + risk register.
