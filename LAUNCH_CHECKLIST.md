# Launch Checklist

From empty repo to live bot accepting users. Tick each item as you complete it.

> Items marked **[AUTO]** are verified automatically by CI/tests. Items marked **[MANUAL]** require human action on the VPS or external services.

---

## Phase 1: Repo & Environment

- [x] **[AUTO]** Repo is downloadable and pushable to a fresh GitHub repository
- [x] **[AUTO]** `pip install -e .[dev]` succeeds with pinned deps
- [x] **[AUTO]** `ruff check .` clean
- [x] **[AUTO]** `mypy app` clean (41 files)
- [x] **[AUTO]** `pytest` — 109 tests pass
- [x] **[AUTO]** `python -m app.main --check` boots and exits cleanly
- [x] **[AUTO]** `alembic upgrade head` creates all 12 tables
- [x] **[AUTO]** `alembic downgrade -1` then `upgrade head` is idempotent
- [ ] **[MANUAL]** Clone repo to VPS: `git clone <repo-url> /opt/affiliate-bot`
- [ ] **[MANUAL]** Copy `.env.example` to `.env` and fill in all values

## Phase 2: External Services

- [ ] **[MANUAL]** Register bot via [@BotFather](https://t.me/BotFather) → get `BOT_TOKEN`
- [ ] **[MANUAL]** Set bot description and about text in BotFather
- [ ] **[MANUAL]** Set `BOT_USERNAME` (without @) for referral deep links
- [ ] **[MANUAL]** Get your `ADMIN_CHAT_ID` (send `/start` to @userinfobot)
- [ ] **[MANUAL]** Set `LANDING_URL` to the approved partner offer landing page
- [ ] **[MANUAL]** Verify landing page has terms/compliance/responsible-gambling copy
- [ ] **[MANUAL]** (Optional) Register at [pay.xrocket.tg](https://pay.xrocket.tg/) → get `XROCKET_API_KEY`
- [ ] **[MANUAL]** Set `XROCKET_MODE=testnet` for initial testing

## Phase 3: Database & Migration

- [x] **[AUTO]** Migration `alembic upgrade head` runs in Docker CMD automatically
- [ ] **[MANUAL]** Verify database file created: `ls -la data/bot.db`
- [ ] **[MANUAL]** Seed the one real offer: edit `scripts/seed_offer.py` values, then:
  ```bash
  docker compose exec bot python -m scripts.seed_offer
  ```

## Phase 4: Deployment

- [x] **[AUTO]** Dockerfile builds (non-root user, migrations in CMD)
- [x] **[AUTO]** docker-compose.yml: single `bot` service + named volume
- [ ] **[MANUAL]** `docker compose up -d --build` on VPS
- [ ] **[MANUAL]** Check logs: `docker compose logs -f bot` — should show structured JSON startup
- [ ] **[MANUAL]** Verify boot shows: `bot.starting`, `i18n.loaded`, `faq.loaded`, `dispatcher.ready`

## Phase 5: Smoke Tests (Telegram)

- [ ] **[MANUAL]** Send `/start` → language picker appears
- [ ] **[MANUAL]** Pick English → compliance gate starts
- [ ] **[MANUAL]** Complete compliance (age → jurisdiction → RG → terms → marketing)
- [ ] **[MANUAL]** Main menu appears
- [ ] **[MANUAL]** Pick Russian → repeat onboarding → verify RU text
- [ ] **[MANUAL]** Open Catalog → see the seeded offer
- [ ] **[MANUAL]** Tap offer → get the affiliate link
- [ ] **[MANUAL]** Open My Referral → see referral link + stats (0/0/0)
- [ ] **[MANUAL]** Open Support → pick category → type question → get FAQ answer
- [ ] **[MANUAL]** `/help` → shows landing URL

## Phase 6: Conversion & Delivery Tests

- [ ] **[MANUAL]** Affiliate path: send a test postback to `/webhooks/affiliate/default` with the offer code → verify conversion created + delivery sent
- [ ] **[MANUAL]** Send same postback again → verify no-op (duplicate)
- [ ] **[MANUAL]** (If payments enabled) Paid path: open paid offer → get invoice → pay on testnet → verify delivery
- [ ] **[MANUAL]** (If payments enabled) Verify expired invoice → no delivery

## Phase 7: Support Escalation Test

- [ ] **[MANUAL]** Type two unmatched questions → verify escalation to admin
- [ ] **[MANUAL]** Admin receives escalation card with user info
- [ ] **[MANUAL]** Admin replies via `/reply <request_id> <message>` → user receives it
- [ ] **[MANUAL]** Admin closes request → user gets "closed" notice

## Phase 8: Admin Commands

- [ ] **[MANUAL]** `/stats` → dashboard with counts
- [ ] **[MANUAL]** `/health` → DB OK, jobs running, no errors
- [ ] **[MANUAL]** `/offers` → list shows seeded offer
- [ ] **[MANUAL]** `/broadcast all 🧪 Test broadcast` → message sent to you

## Phase 9: Go-Live Switch

- [ ] **[MANUAL]** Switch `XROCKET_MODE=live` (if payments approved)
- [ ] **[MANUAL]** Set `ENVIRONMENT=prod`
- [ ] **[MANUAL]** Restart: `docker compose up -d --build`
- [ ] **[MANUAL]** Final `/health` check
- [ ] **[MANUAL]** Backup verification: `docker compose exec bot ls -la data/bot.db`
- [ ] **[MANUAL]** Set up cron backup (see DEPLOY.md §10)
- [ ] **[MANUAL]** **GO-LIVE DECISION**: bot is live and accepting users ✅

---

## Post-Launch Monitoring

- Watch logs for `unhandled.error` or `job.error` events
- Check `/health` daily for first week
- Monitor admin chat for escalations
- Review `/stats` weekly for conversion trends
- Verify backups run via cron
