# Sportsbook Affiliate Bot

A production-ready, **Telegram-first affiliate/referral** bot that routes users to a
single approved external sportsbook offer, tracks referrals / clicks / conversions,
optionally sells compliant digital access via crypto, auto-delivers after a verified
conversion or confirmed payment, answers common questions, and escalates rare cases
to one admin.

> ⚠️ **Compliance:** This bot **never** accepts bets, holds betting balances, or acts
> as a bookmaker. It only routes users to one external offer and attributes conversions.
> A compliance gate (legal age, jurisdiction self-attestation, responsible-gambling
> notice, terms acceptance, marketing opt-in/opt-out) runs **before** any offer is shown.

---

## Stack (pinned, verified June 2026)

| Layer | Choice |
| --- | --- |
| Language | Python 3.12 |
| Bot framework | aiogram `>=3.29,<4` (modular Router + Dispatcher + middleware) |
| ORM / DB | SQLAlchemy 2.x async + aiosqlite (SQLite for MVP) |
| Migrations | Alembic |
| Webhooks | FastAPI + uvicorn (only if an external provider needs HTTPS callbacks) |
| Config | pydantic-settings |
| Logging | structlog (unified with stdlib → JSON to stdout) |
| Payments | xRocket Pay (optional; only if compatible with the chosen offer) |
| Tests | pytest + pytest-asyncio |
| Container | Docker + docker-compose |
| CI/CD | GitHub Actions |

---

## Project layout

```
app/            # entrypoint, config, logging (single source of truth each)
  main.py       # build Dispatcher, start polling, graceful shutdown
  config.py     # pydantic-settings Settings
  logging_conf.py
routers/        # aiogram routers (handlers) — added in later steps
services/       # domain services & external clients
db/             # engine, session, models, repositories, migrations
middlewares/    # i18n, correlation, throttling
states/         # aiogram FSM state groups
utils/          # shared helpers
texts/          # localization: en.json, ru.json
tests/          # pytest suite
Dockerfile, docker-compose.yml, .github/workflows/ci.yml
```

---

## Quickstart

```bash
cp .env.example .env            # fill BOT_TOKEN, ADMIN_CHAT_ID, LANDING_URL
pip install -e .[dev]           # install app + dev tooling

python -m app.main              # start long polling
python -m app.main --check      # boot smoke test (configures + logs, no polling)
```

---

## Configuration

All settings come from environment variables (or `.env`). See `.env.example`.

| Var | Required | Default | Notes |
| --- | --- | --- | --- |
| `BOT_TOKEN` | ✅ | — | from @BotFather |
| `ADMIN_CHAT_ID` | ✅ | — | numeric admin chat/user id |
| `LANDING_URL` | ✅ | — | external offer landing URL |
| `DATABASE_URL` | – | `sqlite+aiosqlite:///./bot.db` | Postgres URL swaps the driver |
| `ENVIRONMENT` | – | `dev` | `dev` \| `prod` |
| `LOG_LEVEL` | – | `INFO` | `DEBUG`..`ERROR` |
| `DEFAULT_LANG` | – | `en` | `en` \| `ru` |
| `PAYMENTS_ENABLED` | – | `false` | enables crypto path |
| `XROCKET_API_KEY` | – | — | required if payments enabled |
| `XROCKET_BASE_URL` | – | `https://pay.xrocket.tg/` | |
| `XROCKET_MODE` | – | `testnet` | `testnet` \| `live` |
| `WEBHOOK_ENABLED` | – | `false` | only if a provider needs HTTPS callbacks |
| `WEBHOOK_SECRET` | – | — | required if webhook enabled |
| `WEBHOOK_BASE_URL` | – | — | required if webhook enabled |

**Fail-fast:** required vars are enforced by the type system. In `prod`, extra
cross-field checks (`PAYMENTS_ENABLED` ⇒ `XROCKET_API_KEY`, `WEBHOOK_ENABLED` ⇒
secret + base url) raise at startup. Secrets are **never** committed — `.env` is gitignored.

---

## Conventions (followed throughout)

- **Files:** `snake_case.py`
- **Classes:** `PascalCase`
- **Routers:** variable named `router`
- **Services:** class suffix `Service`
- **Repositories:** class suffix `Repository`
- **Models:** singular `PascalCase`, mapped to plural `snake_case` tables
- **Text keys:** dot-namespaced — e.g. `start.welcome`
- **Callback data:** colon-namespaced — e.g. `offer:view:<id>`
- **Env vars:** `UPPER_SNAKE_CASE`

---

## Database & Postgres switch point

SQLite is the MVP store via async SQLAlchemy. To switch to PostgreSQL:

1. `pip install asyncpg`
2. Set `DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/dbname`
3. Re-run Alembic migrations against the new database.

No application code changes — SQLAlchemy 2 async + Alembic are already in place.

---

## Lint / Type-check / Test

```bash
ruff check .
mypy app
pytest -q
```

GitHub Actions (`.github/workflows/ci.yml`) runs ruff → mypy → pytest → boot smoke on every push/PR.

---

## Deployment (single VPS)

```bash
docker compose up -d --build     # builds + runs the bot container
```

The container runs long polling by default (no exposed ports). Webhook mode, when
needed, exposes port 8080 for the FastAPI process. A full deploy runbook is added in a later step.

---

## Status

MVP build chain in progress. See commit history for the step-by-step progress.
