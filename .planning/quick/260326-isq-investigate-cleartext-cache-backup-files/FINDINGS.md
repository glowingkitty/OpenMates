# Cleartext Cache Backup & Redis Leakage Audit

**Date:** 2026-03-26
**Scope:** All cache backup files written to `/shared/cache/`, all Redis cache keys containing user data, and Docker volume exposure of the `/shared` directory.
**Context:** OpenMates is an E2E-encrypted messaging application. Any cleartext user data persisted to the host filesystem is a privacy violation.

## Executive Summary

Three disk backup files are written to `/shared/cache/` during graceful shutdown:

| # | File | Encrypted? | Privacy Risk | Status |
|---|------|-----------|--------------|--------|
| 1 | `inspiration_cache_backup.json` | **NO** | HIGH | Cleartext on disk |
| 2 | `pending_orders_backup.json` | **NO** | HIGH | Cleartext on disk |
| 3 | `web_analytics_backup.json` | **NO** | MEDIUM | Cleartext on disk |

**Key finding:** Despite the plan context mentioning the inspiration cache was "recently fixed with Vault transit encryption," the actual implementation in `cache_inspiration_mixin.py` writes **cleartext JSON** to disk. The `dump_inspiration_cache_to_disk()` method calls `json.dump(backup_data, fh)` directly with no Vault encryption step. The mixin header says "Topic suggestions are stored encrypted (per-user, not cross-user)" for the *Redis* entries, but the *disk backup* is plaintext.

Additionally, 25+ containers mount `../../shared:/shared` as a read-write bind mount, meaning any compromised container can read all backup files.

## Findings

---

### 1. Disk Backup Files

#### 1.1 Inspiration Cache Backup

- **Path:** `/shared/cache/inspiration_cache_backup.json`
- **Source:** `backend/core/api/app/services/cache_inspiration_mixin.py`
- **Constant:** `INSPIRATION_CACHE_BACKUP_PATH`
- **Trigger:** `dump_inspiration_cache_to_disk()` called during graceful shutdown (SIGTERM) in `main.py` line ~1339
- **Restored by:** `restore_inspiration_cache_from_disk()` called during startup in `main.py` line ~734
- **Encrypted on disk:** **NO** -- `json.dump(backup_data, fh)` writes cleartext JSON
- **Privacy risk:** **HIGH**

**Data fields stored:**
- `daily_inspiration_topics:{user_id}` -- Per-user topic suggestion batches. Each batch contains 3 short phrases extracted from user's chat post-processing (e.g., "cooking recipes", "quantum physics", "travel to Japan"). These reflect the user's interests and conversation topics.
- `daily_inspiration_last_paid_request:{user_id}` -- Timestamp + language code per user. Reveals which users are paying customers and their preferred language.
- User IDs are stored as full UUIDs (not hashed) in the Redis key names, which are preserved in the backup file.

**What an attacker gains from this file:**
- Which users are active (paid requests in last 48h)
- What topics each user discusses (interest profiling)
- User language preferences
- Full user UUIDs

#### 1.2 Pending Orders Backup

- **Path:** `/shared/cache/pending_orders_backup.json`
- **Source:** `backend/core/api/app/services/cache_order_mixin.py`
- **Constant:** `ORDER_BACKUP_PATH`
- **Trigger:** `dump_pending_orders_to_disk()` called during graceful shutdown in `main.py` line ~1322
- **Restored by:** `restore_orders_from_disk()` called during startup in `main.py` line ~707
- **Encrypted on disk:** **NO** -- `json.dump(backup_data, f, indent=2)` writes cleartext JSON
- **Privacy risk:** **HIGH**

**Data fields stored:**
- `order_id` -- Payment order UUID
- `user_id` -- Full user UUID
- `credits_amount` -- How many credits purchased
- `status` -- Order state (created, pending, etc.)
- `support_email` -- **Cleartext email address** for support contributions
- `email_encryption_key` -- Encryption key used for email (sensitive cryptographic material!)
- `amount`, `currency` -- Payment amounts
- `provider` -- Payment provider (stripe/polar/revolut)
- `is_gift_card`, `is_auto_topup`, `is_recurring` -- Purchase metadata
- `subscription_id` -- Subscription identifier
- `timestamp` -- When order was created
- `_cache_key` -- Redis key (includes order ID)

**What an attacker gains from this file:**
- User identity tied to payment amounts
- Email addresses (support orders)
- Email encryption keys (cryptographic material)
- Payment provider information
- Subscription status and amounts

#### 1.3 Web Analytics Backup

- **Path:** `/shared/cache/web_analytics_backup.json`
- **Source:** `backend/core/api/app/services/web_analytics_service.py`
- **Constant:** `WEB_ANALYTICS_BACKUP_PATH`
- **Trigger:** `dump_to_disk()` called during graceful shutdown in `main.py` line ~1312
- **Restored by:** `restore_from_disk()` called during startup in `main.py` line ~745
- **Encrypted on disk:** **NO** -- `json.dump(backup_data, f)` writes cleartext JSON
- **Privacy risk:** **MEDIUM**

**Data fields stored (aggregate counters, not per-user):**
- `page_loads` -- Total page view counts per day
- `countries:{CC}` -- Per-country visitor counts (e.g., `countries:DE: 50`)
- `devices:{type}` -- Device class distribution (mobile/tablet/desktop)
- `browsers:{name}` -- Browser distribution (e.g., `browsers:Chrome 120: 42`)
- `os:{name}` -- OS distribution
- `referrers:{domain}` -- Referrer domain distribution
- `screen_classes:{size}` -- Screen size distribution
- `duration:{bucket}` -- Session duration bucket distribution
- `unique_visits_approx` -- HyperLogLog cardinality estimate

**Privacy assessment:** This data is genuinely aggregate -- no user IDs, no IPs, no email addresses. The web analytics service explicitly discards IPs after GeoIP lookup and discards UA strings after parsing. However, for a very small user base, aggregate country/browser/OS combinations could be re-identifying (e.g., if only 1 user visits from Iceland with Firefox on Linux).

---

### 2. Redis/Dragonfly Cache Keys Audit

The Dragonfly instance stores all cache data in memory, persisted to a Docker named volume `openmates-cache-data` at `/data`. Dragonfly uses snapshotting by default, meaning all cache contents may be written to disk in cleartext in the Docker volume.

#### 2.1 Cache Keys Containing User Content

| Key Pattern | Mixin | Contains User Content? | Encrypted in Redis? | Risk |
|---|---|---|---|---|
| `daily_inspiration_topics:{user_id}` | InspirationCacheMixin | YES -- topic phrases from chats | NO | HIGH |
| `daily_inspiration_pending:{user_id}` | InspirationCacheMixin | YES -- generated inspiration text | YES (Vault key) | LOW |
| `daily_inspiration_last_paid_request:{user_id}` | InspirationCacheMixin | NO -- timestamp + lang only | N/A | LOW |
| `daily_inspiration_views:{user_id}` | InspirationCacheMixin | NO -- UUIDs only | N/A | LOW |
| `user:{hash}:daily_inspirations_sync` | InspirationCacheMixin | YES -- inspiration content for sync | Unclear | MEDIUM |
| `order:{order_id}` | OrderCacheMixin | YES -- email, payment data | NO | HIGH |
| `reminder:{reminder_id}` | ReminderCacheMixin | YES -- reminder text/metadata | Encrypted per header comment | LOW |
| `reminder_pending_delivery:{user_id}` | ReminderCacheMixin | YES -- fired reminder payloads | NO (plaintext content noted in docstring) | HIGH |
| `debug:admin_requests` | DebugCacheMixin | YES -- full AI request/response data | YES (Vault transit) | LOW |
| `chat_list:{user_id}:{chat_id}` | ChatCacheMixin | YES -- chat metadata (titles, etc.) | NO | HIGH |
| `chat_versions:{user_id}:{chat_id}` | ChatCacheMixin | NO -- version numbers only | N/A | LOW |
| `user_draft:{user_id}:{chat_id}` | ChatCacheMixin | YES -- draft message content | NO | HIGH |
| `user:{user_id}` | UserCacheMixin | YES -- user profile data | NO | MEDIUM |
| `session:{token_hash}` | UserCacheMixin | YES -- session/user ID mapping | NO | MEDIUM |
| `user:{hash}:new_chat_suggestions` | ChatCacheMixin | YES -- suggestion text | NO | MEDIUM |
| `public:demo_chat:*` | DemoChatCacheMixin | YES -- public demo content | N/A (public data) | LOW |
| `short_url:{token}` | ShortUrlCacheMixin | YES -- encrypted URL blob | YES (pre-encrypted) | LOW |
| `pending_embed_encryption:{user_id}` | ReminderCacheMixin | NO -- embed IDs only | N/A | LOW |
| `web:analytics:daily:{date}` | WebAnalyticsService | NO -- aggregate counters | N/A | LOW |
| `discovered_apps_metadata_v1` | CacheService | NO -- app config | N/A | LOW |
| `ai:base_instructions_v1` | CacheService | NO -- system prompts | N/A | LOW |
| `ai:mates_configs_v1` | CacheService | NO -- AI persona configs | N/A | LOW |

#### 2.2 High-Risk Redis Keys Summary

These keys contain cleartext user content in Redis and would be exposed if Dragonfly's data volume is compromised:

1. **`daily_inspiration_topics:{user_id}`** -- User interest phrases from post-processing
2. **`order:{order_id}`** -- Email addresses, email encryption keys, payment data
3. **`reminder_pending_delivery:{user_id}`** -- Plaintext fired reminder payloads including reminder text
4. **`chat_list:{user_id}:{chat_id}`** -- Chat titles and metadata
5. **`user_draft:{user_id}:{chat_id}`** -- Unsent message draft content
6. **`user:{user_id}`** -- User profile data (may include email, timezone, etc.)

---

### 3. Docker Volume Exposure

#### 3.1 The `/shared` Bind Mount

The host directory `../../shared` (relative to `backend/core/`) is bind-mounted as `/shared` into **25+ containers**:

- `api`, `task-worker`, `task-scheduler`
- All app microservices: `app-ai`, `app-web`, `app-videos`, `app-audio`, `app-news`, `app-events`, `app-maps`, `app-travel`, `app-health`, `app-shopping`, `app-code`, `app-docs`, `app-mail`, `app-images`, `app-reminder`, `app-jobs`, `app-pdf`, `app-math`
- Workers: `app-ai-worker`, `app-images-worker`, `app-pdf-worker`

**All mounts are read-write** (no `:ro` flag). This means:
- Any compromised container can read `/shared/cache/*.json` backup files
- Any compromised container can write to `/shared/cache/`, potentially injecting malicious data that the API will restore on next startup
- The attack surface is the union of all 25+ container images and their dependencies

#### 3.2 The Dragonfly `cache-data` Volume

- **Volume:** `openmates-cache-data` (Docker named volume)
- **Mount:** `/data` inside the `cache` container
- **Contains:** Dragonfly snapshot files (RDB-compatible format)
- **Encryption at rest:** **NONE** -- Dragonfly does not support encryption at rest
- **Access:** Only the `cache` container mounts this volume, but it is accessible to anyone with Docker socket access (including the `core-admin-sidecar` container which mounts `/var/run/docker.sock`)

#### 3.3 Other Volumes of Note

| Volume | Container | Risk |
|---|---|---|
| `openmates-postgres-data` | `cms-database` | Contains all Directus data (encrypted columns exist, but much data is cleartext) |
| `openmates-vault-data` | `vault` | Vault's encrypted storage (properly secured) |
| `openmates-vault-setup-data` | `vault-setup`, `api` | Contains unseal keys and tokens (critical security material) |

---

### 4. Additional Disk Write Locations

Beyond `/shared/cache/`, these paths also write data to disk:

| Path | Source | Risk |
|---|---|---|
| `/vault-data/keys/unseal_key` | `vault_setup/initialization.py` | CRITICAL -- Vault unseal key |
| `/vault-data/tokens/root_token` | `vault_setup/initialization.py` | CRITICAL -- Vault root token |
| `/vault-data/tokens/api_token` | `vault_setup/initialization.py` | CRITICAL -- API Vault token |
| `./api/logs/` | API container logging | MEDIUM -- logs may contain user data snippets |
| `/shared/geoip/GeoLite2-Country.mmdb` | GeoIP database (read-only) | NONE |

---

## Architectural Recommendations

### Priority 1: CRITICAL -- Encrypt Disk Backup Files

All three backup files must be encrypted before writing to disk. The pattern to follow already exists conceptually in the codebase (DebugCacheMixin uses Vault transit encryption for its Redis storage).

**Recommended approach:** Use Vault Transit encryption (already available via `SecretsManager`/`EncryptionService`).

For each backup file:
1. Before `json.dump()`, serialize data to JSON string
2. Encrypt the JSON string using Vault Transit `encrypt` endpoint
3. Write the encrypted ciphertext to disk
4. On restore, read ciphertext from disk, decrypt via Vault Transit, then parse JSON

**Implementation order:**
1. **`pending_orders_backup.json`** -- Contains email addresses, encryption keys, and payment data. Highest sensitivity.
2. **`inspiration_cache_backup.json`** -- Contains user interest profiling data and user IDs.
3. **`web_analytics_backup.json`** -- Aggregate data only, lowest sensitivity, but should still be encrypted for consistency.

**Effort estimate:** ~1-2 hours per file. The dump/restore methods are well-structured and isolated. Adding Vault Transit encrypt/decrypt calls is straightforward.

### Priority 2: HIGH -- Encrypt Sensitive Redis Cache Keys

The following Redis keys should store encrypted values (using Vault Transit, matching the pattern used by `DebugCacheMixin` and `daily_inspiration_pending`):

1. **`order:{order_id}`** -- Contains email addresses and email encryption keys
2. **`reminder_pending_delivery:{user_id}`** -- Contains plaintext reminder content
3. **`user_draft:{user_id}:{chat_id}`** -- Contains unsent message text
4. **`daily_inspiration_topics:{user_id}`** -- Contains user interest phrases

The `chat_list` and `user` cache keys are harder to encrypt because they are read frequently for UI rendering and would add latency. Consider:
- Encrypting only the sensitive fields within the cached JSON (e.g., `chat_title`, `email`) rather than the entire value
- Using a symmetric key cached in memory (derived from Vault at startup) rather than making a Vault Transit call per read

### Priority 3: MEDIUM -- Restrict `/shared` Volume Access

1. **Mount as read-only** for all containers that don't need write access:
   ```yaml
   volumes:
     - ../../shared:/shared:ro
   ```
   Only `api` needs write access to `/shared/cache/`. All app microservices only read from `/shared/config/`.

2. **Use separate mount paths** for config vs. cache:
   ```yaml
   # App microservices: only need config
   - ../../shared/config:/shared/config:ro

   # API container: needs config (read) + cache (write)
   - ../../shared/config:/shared/config:ro
   - ../../shared/cache:/shared/cache
   ```

### Priority 4: LOW -- Dragonfly Encryption at Rest

Dragonfly does not support native encryption at rest. Options:
- **LUKS/dm-crypt on the host volume:** Encrypt the Docker volume's backing filesystem
- **Accept the risk:** If the server's disk is already encrypted (full-disk encryption), this is redundant
- **Periodic cache clearing:** The `CLEAR_CACHE_ON_UPDATE` flag is already set to `true` by default, which clears the Dragonfly volume on updates

### Priority 5: LOW -- Vault Token File Security

The Vault setup writes unseal keys and tokens to `/vault-data/`. These are protected by the `openmates-vault-setup-data` named volume, but:
- The `api` container has access to this volume (`vault-setup-data:/vault-data`)
- Consider deleting these files after initial setup or using Vault's auto-unseal feature

---

## Reference: DebugCacheMixin Encryption Pattern

The `cache_debug_mixin.py` demonstrates the correct pattern for encrypting cache data:

```python
# Encrypt before storing
encrypted_data = await encryption_service.encrypt_debug_request_data(entries_json)
await client.set(DEBUG_REQUESTS_KEY, encrypted_data, ex=TTL)

# Decrypt on retrieval
decrypted_json = await encryption_service.decrypt_debug_request_data(encrypted_data)
entries = json.loads(decrypted_json)
```

This same pattern should be applied to disk backup files by calling Vault Transit encrypt/decrypt around the `json.dump()`/`json.load()` calls in each backup method.
