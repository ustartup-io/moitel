# Deployment Runbook

This guide covers deploying the Sportsbook Affiliate Bot to a single VPS using Docker.

---

## 1. Prerequisites

- A VPS (1 vCPU, 1GB RAM minimum) running Ubuntu 22.04+ or Debian 12+
- SSH access with a non-root user that has `sudo`
- A Telegram bot token from [@BotFather](https://t.me/BotFather)
- (Optional) An xRocket Pay API key for crypto payments
- (Optional) A domain name + HTTPS if using webhooks

---

## 2. VPS Setup

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install Docker
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
# Log out and back in for the docker group to take effect.

# Create app directory
sudo mkdir -p /opt/affiliate-bot
sudo chown $USER:$USER /opt/affiliate-bot
cd /opt/affiliate-bot
```

---

## 3. Get the Code

```bash
cd /opt/affiliate-bot
git clone https://github.com/YOUR_USERNAME/YOUR_REPO.git .
```

---

## 4. Configure Environment

```bash
cp .env.example .env
nano .env
```

**Set these required values:**

| Variable | Value |
|---|---|
| `BOT_TOKEN` | Your token from @BotFather |
| `ADMIN_CHAT_ID` | Your Telegram user ID (send `/start` to @userinfobot to get it) |
| `LANDING_URL` | Your affiliate offer landing page URL |
| `BOT_USERNAME` | Your bot username (without @) |

**Optional values:**

| Variable | When to set |
|---|---|
| `PAYMENTS_ENABLED=true` | When selling paid access via crypto |
| `XROCKET_API_KEY` | Required if `PAYMENTS_ENABLED=true` |
| `XROCKET_MODE=testnet` | Start with testnet, switch to `live` for production |
| `WEBHOOK_ENABLED=true` | Only if an external provider requires HTTPS callbacks |
| `WEBHOOK_SECRET` | A random 32+ char string; required if webhook enabled |
| `WEBHOOK_BASE_URL` | Your HTTPS URL (e.g. `https://bot.example.com`); required if webhook enabled |
| `DATABASE_URL` | Defaults to `sqlite+aiosqlite:///./data/bot.db` (persists in Docker volume) |

---

## 5. BotFather Setup

1. Open [@BotFather](https://t.me/BotFather) on Telegram.
2. Send `/setdescription` — set a short description.
3. Send `/setabouttext` — set the about text.
4. (Optional) Send `/setdomain` if using webapps.
5. Your bot is now ready.

---

## 6. xRocket Pay Setup (Optional)

1. Register at [pay.xrocket.tg](https://pay.xrocket.tg/).
2. Generate an API key.
3. Set `XROCKET_API_KEY` in `.env`.
4. **Start with `XROCKET_MODE=testnet`** — test the payment flow with small amounts.
5. Once verified, switch to `XROCKET_MODE=live`.

> **Important:** The xRocket client has TODO markers for uncertain API fields.
> Verify against the live API before going live with payments.

---

## 7. Build and Run

```bash
cd /opt/affiliate-bot

# Build and start
docker compose up -d --build

# Check logs
docker compose logs -f bot

# The bot will:
#   1. Run `alembic upgrade head` (create/migrate database)
#   2. Start long polling
```

---

## 8. First Admin Setup

1. Send `/start` to your bot in Telegram.
2. Complete the compliance gate (age, jurisdiction, responsible gambling, terms).
3. Since your chat ID matches `ADMIN_CHAT_ID`, you can now use admin commands:
   - `/stats` — dashboard
   - `/offers` — list offers
   - `/offer_add <code> <title_key> <url>` — add an offer
   - `/health` — system health
   - `/broadcast <segment> <message>` — send a broadcast

---

## 9. Smoke Tests

After deployment, verify:

```bash
# Bot responds to /start
# Language picker appears for new users
# Compliance gate works end-to-end
# /help shows the help text
# /stats shows dashboard (admin only)
# Referral link is generated in "My Referral"
# FAQ matching works in Support

# Check health via admin command:
# /health in Telegram -> should show "Database: ✅ OK"
```

---

## 10. Backups

The SQLite database is stored in the Docker named volume `bot-data`.

```bash
# Manual backup
docker compose exec bot cp /app/data/bot.db /app/data/bot.db.bak

# Or copy from the volume:
docker run --rm -v affiliate-bot_bot-data:/data -v $(pwd):/backup \
  alpine cp /data/bot.db /backup/bot-$(date +%Y%m%d).db

# Automated cron backup (add to crontab -e):
# 0 3 * * * cd /opt/affiliate-bot && docker run --rm -v affiliate-bot_bot-data:/data -v $(pwd):/backup alpine cp /data/bot.db /backup/bot-$(date +\%Y\%m\%d).db
```

---

## 11. Updates

```bash
cd /opt/affiliate-bot
git pull origin main
docker compose up -d --build
```

The entrypoint runs `alembic upgrade head` on each start, so migrations apply automatically.

---

## 12. Webhook Mode (Optional)

Only needed if an external provider (e.g. xRocket) requires HTTPS callbacks.

1. Point a domain to your VPS IP.
2. Set up a reverse proxy (Caddy or Traefik) for HTTPS.
3. Set `WEBHOOK_ENABLED=true`, `WEBHOOK_BASE_URL`, `WEBHOOK_SECRET` in `.env`.
4. Uncomment the `webhook` service in `docker-compose.yml`.
5. Restart: `docker compose up -d --build`.

**Caddy example** (automatic HTTPS):

```
bot.example.com {
    reverse_proxy localhost:8080
}
```

---

## 13. Monitoring

- **Logs:** `docker compose logs -f bot`
- **Health:** Send `/health` to the bot (admin only)
- **Background jobs:** The `/health` command shows running jobs and error counts
- **Alerts:** Admin chat receives alerts on delivery failures and escalations

---

## 14. Postgres Switch (When Needed)

Switch from SQLite to PostgreSQL when concurrent writes cause contention:

```bash
# 1. Install asyncpg (add to pyproject.toml)
pip install asyncpg

# 2. Set in .env:
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/dbname

# 3. Run migrations against the new DB:
docker compose run --rm bot alembic upgrade head
```

No code changes needed — SQLAlchemy 2 async + Alembic handle the switch.

---

## Quick Reference: Admin Commands

| Command | Description |
|---|---|
| `/stats` | Dashboard stats (users, clicks, conversions, payments) |
| `/offers` | List all offers |
| `/offer_add <code> <title_key> <url> [paid] [amount] [currency]` | Add an offer |
| `/offer_toggle <id>` | Enable/disable an offer |
| `/confirm_payment <id>` | Manually confirm a payment |
| `/confirm_conversion <id> [approve\|reject]` | Approve/reject a conversion |
| `/health` | System health check |
| `/broadcast <segment> <message>` | Send a broadcast (all or marketing) |
| `/export [conversions\|payments]` | Export CSV |
| `/reply <request_id> <message>` | Reply to a support escalation |
