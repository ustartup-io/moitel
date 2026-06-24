# Risk Register

Top launch risks, prioritized by likelihood × impact. Each includes a one-line mitigation.

---

## R1: Partner Callback Unreliability

| | |
|---|---|
| **Likelihood** | **High** |
| **Impact** | High — conversions may not be attributed; revenue tracking breaks |
| **Description** | The affiliate partner's postback/callback may be delayed, dropped, or sent multiple times. This is the most fragile integration point. |
| **Mitigation** | Dual confirmation paths: (1) webhook endpoint with idempotent dedupe_hash, (2) polling job fallback. Postbacks are retry-safe (duplicate = no-op 200). Admin can manually confirm via `/confirm_conversion`. |

---

## R2: Payment Confirmation Delays

| | |
|---|---|
| **Likelihood** | **Medium** |
| **Impact** | High — users who paid don't receive access; support escalations spike |
| **Description** | xRocket Pay may not call our webhook promptly, or blockchain confirmation may lag. Users see "stuck" payments. |
| **Mitigation** | 3-path confirmation: (1) webhook callback (primary), (2) payment_polling job every 60s (fallback), (3) admin manual confirm via `/confirm_payment <id>` (emergency). Expired payment cleanup marks stale invoices. FAQ guides users to wait/check. |

---

## R3: SQLite Write Contention

| | |
|---|---|
| **Likelihood** | **Medium** (at scale) |
| **Impact** | Medium — `database is locked` errors under concurrent writes (broadcasts + webhooks + polling) |
| **Description** | SQLite uses file-level locking. WAL mode + busy_timeout=5000ms reduces contention, but high broadcast volume or concurrent webhook + bot writes can still cause `SQLITE_BUSY`. |
| **Mitigation** | WAL mode enabled; busy_timeout=5s; broadcast rate-limited to 25 msg/s. Postgres switch documented in DEPLOY.md (swap DATABASE_URL + asyncpg). Switch when concurrent writers or broadcast volume causes contention. |

---

## R4: Telegram Rate Limits

| | |
|---|---|
| **Likelihood** | **Medium** (during broadcasts) |
| **Impact** | Medium — 429 errors during broadcasts; some users don't receive messages |
| **Description** | Telegram enforces ~30 msg/sec globally and ~1 msg/sec per chat. Aggressive broadcasts can hit 429. |
| **Mitigation** | Broadcast worker uses 25 msg/s batches with 1s spacing. On 429, stops the batch and resumes next cycle (respects retry-after). Per-recipient status tracking. Opt-out respected for marketing sends. |

---

## R5: Compliance / Offer-Availability Errors

| | |
|---|---|
| **Likelihood** | **Low** |
| **Impact** | **High** — regulatory exposure if offers shown to ineligible users |
| **Description** | Bot could accidentally show offers to minors, restricted jurisdictions, or users who declined terms. |
| **Mitigation** | Compliance gate (age + jurisdiction + RG + terms + marketing) runs before ANY offer access. Gate enforced in catalog handler (`is_compliant` check). All timestamps persisted. Jurisdiction allowlist on Offer model (unused in MVP but available). |

---

## Additional Risks (monitored)

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| R6 | Delivery duplication | Low | Medium | `dedupe_key` UNIQUE constraint prevents double delivery; idempotency tested in integration tests |
| R7 | Admin overload (too many escalations) | Medium | Medium | FAQ resolves common questions autonomously; escalation after 2 unmatched attempts; admin can close requests |
| R8 | xRocket API field mismatch | Medium | Medium | Client isolated behind typed models; uncertain fields marked TODO; MockXRocketClient for testing; verify against live API before production |
| R9 | Data loss (SQLite corruption) | Low | High | WAL mode + regular backups (DEPLOY.md cron); Docker named volume persists across rebuilds |
| R10 | xRocket private key leak | Low | Critical | Secrets only in `.env` (gitignored); `SecretStr` in pydantic; never logged |
