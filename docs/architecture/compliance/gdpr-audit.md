# GDPR Compliance Audit — OpenMates

**Date:** 2026-04-08
**Session:** 269d
**Scope:** Full code-level GDPR audit + privacy policy / ToU accuracy check
**Method:** Parallel research agents covering PII storage, third-party providers, user-rights endpoints, retention/cookies/telemetry, plus orchestrator cross-checking against `shared/docs/privacy_policy.yml` and `frontend/packages/ui/src/i18n/sources/legal/{privacy,terms,imprint}.yml`.
**Output type:** Report only — no code or policy changes were made.

> **Confidence note.** Findings come from static code reading, not runtime testing. A few claims (e.g. "Anthropic direct API path is reachable") were verified by reading the source files; production routing depends on runtime config (`secrets_manager`/`config_manager` choices) and would need a config audit to confirm which paths are actually live.

---

## 1. Executive Summary

OpenMates has an **unusually strong privacy foundation** for an AI product: client-side encryption with in-memory-only server processing and HashiCorp Vault Transit key management, hashed user identifiers throughout the database, a 3-tier privacy filter on OpenTelemetry, structured compliance logging with legally justified retention windows, hardened cookies and CSP, and a working account-deletion cascade across Postgres, Redis, Vault and most user-content tables.

**However, the privacy policy is materially out of date with the codebase.** Roughly **20+ third-party providers** are reachable from production code paths but are not disclosed in `shared/docs/privacy_policy.yml` or `i18n/sources/legal/privacy.yml`. Several GDPR rights (Art. 18 restriction, Art. 21 objection, granular consent withdrawal, email rectification) are not implemented at all. The deletion cascade leaves PDFs in S3, leaves user_id in compliance logs, and does not propagate erasure to Stripe/Mailjet/LLM-provider logs. There is no cookie consent banner.

**Overall posture:** ~80% GDPR-aligned in *implementation*; ~60% aligned in *documented disclosure*. The biggest legal exposure is the **transparency gap** (Art. 13/14): users are not told about a large fraction of subprocessors that actually receive their data.

| Severity | Count | Examples |
|---|---|---|
| 🔴 Critical | 9 | Undisclosed LLM subprocessors, undisclosed payment processor (Revolut), S3 PDFs not deleted, no Art. 17 cascade to third parties, no cookie consent banner |
| 🟠 High | 11 | No Art. 21, no Art. 18, no email rectification, no granular consent withdrawal, ~18 undisclosed event/travel/health/shopping providers, Discord disclosed in i18n but not in `privacy_policy.yml`, possible Brevo/Mailjet inconsistency |
| 🟡 Medium | 8 | Inconsistent IP hashing in compliance logs, Caddy access logs <2y, chat-content export client-only, consent versioning by timestamp only, ~~`temp-images` bucket public~~ (✅ C6 resolved 2026-04-08), `safety_audit_log.user_id` in plaintext |
| 🟢 Low | 4 | sessionStorage WebSocket token fallback, `last_opened` not in export, demo-chat metadata cleartext, profile-image legacy URL field |

`legal/documents/privacy-policy.ts` reports `lastUpdated: 2026-03-06`. Code has clearly diverged since then.

---

## 2. Methodology

Four research streams ran in parallel via subagents, each producing a structured report:

1. **PII storage inventory** — every Directus collection, Redis cache, IndexedDB store, S3 bucket, and Vault key with PII content.
2. **Third-party providers** — every outbound integration with what data is sent and whether it appears in either policy file.
3. **GDPR rights endpoints (Art. 15–21)** — endpoint trace, deletion cascade depth, consent management, audit trail.
4. **Retention / cookies / consent / telemetry** — TTLs, cron deletions, cookie security, OTel privacy filtering, log redaction, TLS posture.

The orchestrator then read `shared/docs/privacy_policy.yml`, `frontend/packages/ui/src/legal/buildLegalContent.ts`, the demo-chat metadata, the privacy/terms/imprint i18n YAML, and spot-verified a few critical claims directly (Anthropic direct API path, Together base URL, Brevo+Mailjet coexistence).

---

## 3. PII storage map (what we hold)

### 3.1 Postgres (Directus) — encrypted fields

Directus is the system of record. Most user PII is encrypted at rest with a per-user master key wrapped by Vault Transit (zero-knowledge for chat content). Concrete tables found:

- `directus_users` — `encrypted_email_address`, `encrypted_email_with_master_key`, `encrypted_username`, `hashed_email`, `hashed_username`, `user_email_salt`, profile image fields, `encrypted_settings`, `connected_devices` (JSON), `last_online_timestamp`, `encrypted_credit_balance`, `encrypted_payment_method_id`, `stripe_customer_id`/`stripe_subscription_id` (cleartext), `encrypted_tfa_secret`, `tfa_backup_codes_hashes` (Argon2), `encrypted_tfa_app_name`, `vault_key_id`, `vault_key_version`, `lookup_hashes` (JSON of SHA-256), consent timestamps, `auto_delete_chats_after_days`, push notification subscription objects, `default_ai_model_simple`/`_complex`, `is_admin`. (`backend/core/directus/schemas/users.yml`)
- `chats` — `hashed_user_id`, `encrypted_title`, `encrypted_chat_summary`, `encrypted_chat_tags`, `encrypted_chat_key`, `shared_with_user_hashes`, `shared_encrypted_*` (Vault-encrypted shared metadata for OG tags), per-chat keys for client-side encryption.
- `messages` — `encrypted_content`, `encrypted_thinking_content`, `encrypted_pii_mappings`, role, `encrypted_model_name`.
- `embeds` / `embed_keys` — `encrypted_content`, `encrypted_text_preview`, `s3_file_keys`, AES-wrapped per-embed key.
- `api_keys` / `api_key_devices` — `encrypted_key_prefix`, `key_hash` (SHA-256), `encrypted_anonymized_ip` (first 2 octets), `encrypted_country_code`/`encrypted_region`/`encrypted_city`, `encrypted_machine_identifier`.
- `user_passkeys` — `credential_id`, `public_key_jwk`/`public_key_cose`, `aaguid`, `sign_count`, `encrypted_device_name`.
- `usage` — `user_id_hash`, `device_hash`, `encrypted_model_used`, encrypted credit-cost / token-count fields, `encrypted_server_provider`, `encrypted_server_region`.
- `invoices` / `credit_notes` — `encrypted_amount`, `encrypted_s3_object_key`, `encrypted_aes_key`, `encrypted_currency`, `provider` (`stripe`/`polar`/`revolut`).
- `reminders` — `encrypted_user_id` (Vault-encrypted raw user_id for WebSocket delivery), `encrypted_prompt`, `encrypted_chat_history`, repeat/random configs.
- `user_app_settings_and_memories` — `encrypted_app_key`, `encrypted_item_json`.
- `user_daily_inspirations` — encrypted phrases, AI responses, video metadata.
- `safety_audit_log` — **`user_id` cleartext**, `prompt_hash`, sightengine/VLM JSON, `safeguard_reasoning` truncated CoT.
- `upload_files` — `original_filename`, `content_hash`, `aes_key` (base64 cleartext) + `vault_wrapped_aes_key`, `ai_detection`, ClamAV scan result.
- `demo_chats` — title/summary/category/icon are **cleartext** (intentional, public).
- `encryption_keys` — `encrypted_key`, `key_iv`, `salt`, `login_method`.

### 3.2 Cache / ephemeral (`backend/core/api/app/services/cache_config.py`)

Redis/Dragonfly holds short-lived **decrypted** copies of profile, device, chat list, draft, and message context. Key prefixes: `user_profile:`, `session:`, `user_device:*`, `user_chats:`, `chat_list_item_data:`, `chat_messages:`, `user:{user_id}:chat:{chat_id}:draft`. TTLs range from 5 minutes to 72 hours. Encryption-service wrapper decrypts on read using the user's Vault key — so the cache is plaintext-equivalent for the duration of the TTL.

### 3.3 Object storage (`backend/core/api/app/services/s3/config.py`)

| Bucket | Encryption | Lifecycle |
|---|---|---|
| `openmates-profile-images-private` | AES-256-GCM (user key) | None |
| `openmates-chatfiles` | AES-256-GCM (per-file) | None |
| `openmates-invoices` | AES-256-GCM (user vault key) | **10 years** (AO §147 / HGB §257) |
| `openmates-userdata-backups` | User master key | 60 days |
| `openmates-compliance-logs-backups` | **Plaintext** | 2 y audit / 10 y financial |
| `openmates-usage-archives` | Server key | 3 years |
| `openmates-temp-images` | Plaintext, **private** (15min presigned URL to SerpAPI) — C6 resolved 2026-04-08 | 1 day (safety net) |
| `openmates-issue-logs` | Encrypted YAML + plaintext PNG | 1 year |

### 3.4 Browser-side (`frontend/packages/ui/src/services/db.ts` v22)

IndexedDB `chats_db` holds encrypted copies of chats, messages, embeds, suggestions, app settings/memories, daily inspirations, plus offline sync queues. All client-side encrypted with the user's master key. Cleared on logout.

`sessionStorage` holds an `incognito_chats` set (cleared on tab close) and a per-session UUID for the stability-log forwarding feature, plus a Safari/iOS WebSocket token fallback (`getWebSocketToken()` in `frontend/packages/ui/src/utils/cookies.ts:60`) — see **Finding L1** for the XSS exposure note.

### 3.5 Vault / KMS

HashiCorp Vault Transit provides per-user master keys, a `shared-content-metadata` key (for shared chat OG tags / community discovery), a static `email_encryption_key`, and the unsealing master. Account deletion calls `encryption_service.delete_user_key()` (`user_cache_tasks.py:1063-1073`), which invalidates all wrapped data for that user.

### 3.6 Telemetry (`backend/shared/python_utils/tracing/`)

OTel traces are routed through a 3-tier `TracePrivacyFilter` (`tracing/privacy_filter.py`):
- always-strip: `http.request.header.cookie`, `http.request.header.authorization`
- pseudonymized `user_id` → `SHA256(user_id + daily_salt)[:12]` (rotates daily)
- Tier 1 (regular users): only safe ops; redacts `db.statement`, `cache.key`, `skill.params`
- Tier 2 (error spans): + stacktrace, task IDs
- Tier 3 (admin / `debug_logging_opted_in`): full visibility

This is **best-in-class** for an AI product.

---

## 4. Third-party providers — disclosure gap matrix

The privacy policy (`shared/docs/privacy_policy.yml` + the human-facing translations rendered by `buildPrivacyPolicyContent()` in `frontend/packages/ui/src/legal/buildLegalContent.ts`) discloses **17 providers**: Vercel, Hetzner, IP-API, Brevo, Sightengine, Stripe, Polar, Mistral, AWS (Bedrock), OpenRouter, Cerebras, Brave, Webshare, Google, Firecrawl, Groq, Flightradar24, plus Discord (only in the i18n version, not in `privacy_policy.yml` itself).

The codebase calls **at least 35** distinct third-party services. The gap:

### 4.1 Critical undisclosed subprocessors (handle prompts / payment / health data)

| Provider | Code reference | What is sent | Disclosed? | Severity |
|---|---|---|---|---|
| **Anthropic (direct API)** | `backend/apps/ai/llm_providers/anthropic_direct_api.py` (uses `anthropic` SDK) | Full prompts, message history | ❌ (policy says "Anthropic via AWS Bedrock" only) | 🔴 Critical |
| **OpenAI (direct or Azure)** | `openai_client.py:53` — `server_choice` can be `"openai"`, `"openrouter"`, or `"azure"`; selects via `secrets_manager` | Full prompts, message history | ❌ | 🔴 Critical |
| **Together AI** | `together_client.py:31` — hardcoded `https://api.together.xyz/v1/chat/completions` | Full prompts, message history | ❌ | 🔴 Critical |
| **Google MaaS** (separate from Gemini) | `google_maas_client.py` | Prompts | ❌ | 🔴 Critical |
| **Revolut Business** | `services/payment/revolut_service.py` + `invoices.provider = "revolut"` | Email, payment method, billing info | ❌ (policy lists Stripe + Polar only; Revolut **is** in the `invoices.provider` enum) | 🔴 Critical |
| **FAL (Flux)** | `backend/shared/providers/fal/flux.py` | Image-generation prompts, possibly source images | ❌ | 🔴 Critical (hosted in US, prompts may contain PII) |
| **Recraft** | `backend/shared/providers/recraft/recraft.py` | Image-generation prompts | ❌ | 🔴 Critical |
| **SerpAPI** | `backend/shared/providers/serpapi.py`, `backend/apps/travel/providers/serpapi_provider.py`, `serpapi_hotels_provider.py` | Search/flight/hotel queries; image bytes uploaded to `temp-images` bucket for Google Lens reverse search | ❌ | 🔴 Critical |
| **Mailjet** | `backend/core/api/app/services/email/mailjet_provider.py` (coexists with `brevo_provider.py`) | Email addresses, content | ❌ (policy lists Brevo only) | 🟠 High — confirm whether Mailjet is dead code or live; if live, disclose; if dead, delete the provider |

### 4.2 Undisclosed event / travel / health / shopping aggregators

All of the following exist as live provider modules but are absent from both policy files:

- **Events:** `backend/apps/events/providers/{meetup,luma,google_events,bachtrack,resident_advisor,classictic,berlin_philharmonic,siegessaeule}.py`
- **Travel:** `backend/apps/travel/providers/{travelpayouts_provider,serpapi_provider,serpapi_hotels_provider,transitous_provider}.py`
- **Health:** `backend/apps/health/skills/search_appointments_skill.py` — Doctolib, Jameda/DocPlanner via Webshare proxy. **Note:** health-adjacent queries are special-category data (Art. 9) — even though queries are routed through Webshare without identifiers, the *purpose* (finding a doctor for a specific specialty) leaks health-relevant information. This deserves explicit disclosure and a DPIA.
- **Shopping:** `backend/apps/shopping/providers/{rewe_provider,amazon_provider}.py`
- **Shared:** `backend/shared/providers/youtube/youtube_metadata.py`, `backend/shared/providers/protonmail/protonmail_bridge.py` (Proton Mail bridge — verify whether this actually transmits user data outbound)

### 4.3 Frontend / observability gaps

- `@opentelemetry/*` packages in `frontend/packages/ui/package.json` plus `frontend/packages/ui/src/services/tracing/setup.ts` export client traces to `/v1/telemetry/traces`. The backend then forwards to **OpenObserve** (per `tracing/config.py`). OpenObserve is a subprocessor and must be disclosed if it is an external/managed service. If it is self-hosted on Hetzner, disclose that fact in the privacy section so users know traces don't leave the EU.
- `@fontsource-variable/lexend-deca` is loaded from npm and self-served (so no Google Fonts CDN call) — **verify** there is no `<link href="fonts.googleapis.com">` in the rendered HTML; if confirmed, this is a non-issue.

### 4.4 Discord — disclosed in one place but not the other

`buildLegalContent.ts:355-365` renders a "Discord Integration" section from the i18n source, but `shared/docs/privacy_policy.yml` has **no Discord block**. These two files are supposed to be the same source of truth per `.claude/rules/privacy.md`. Reconcile.

---

## 5. GDPR rights — endpoint coverage (Art. 15–21)

| Article | Status | Evidence | Gaps |
|---|---|---|---|
| **Art. 15 — Access** | ✅ Implemented | `GET /v1/settings/export-account-manifest` (`settings.py:3636`), `GET /v1/settings/export-account-data` (`settings.py:3756`), `GET /v1/settings/usage/export` (`settings.py:1920`). Compliance log entry written via `compliance.log_data_access()`. | Chat content not server-rendered (client must sync from IndexedDB first); email returned encrypted with master key. |
| **Art. 16 — Rectification** | ⚠️ Partial | Endpoints exist for username, language, darkmode, timezone, auto-topup. | **No email change endpoint.** `hashed_email` + `encrypted_email_address` cannot be updated by the user. This is a hard Art. 16 gap. |
| **Art. 17 — Erasure** | ✅ Strong / ⚠️ Incomplete cascade | `POST /v1/settings/delete-account` (`settings.py:3439`) → `tasks/user_cache_tasks.py:870` runs a 5-phase cascade: auth data, payments+refunds, content, Redis cache, final user record + compliance log. Reauth required (passkey / TOTP / email OTP). | See **Section 6** — multiple downstream stores are not cleaned up. |
| **Art. 18 — Restriction** | ❌ Not implemented | No endpoint, no `processing_restricted` flag. | Required by law; needs an explicit pause-of-processing path. |
| **Art. 20 — Portability** | ✅ Implemented (JSON) | Same export endpoints. | No standardized schema; chat-content portion incomplete. |
| **Art. 21 — Objection** | ❌ Not implemented | No endpoint to object to marketing / profiling / research. Settings has consent *recording* (`POST /user/consent/privacy-apps`, `/user/consent/mates`) — these are Art. 7 grants, not Art. 21 objections. | Required by law if any processing relies on legitimate interest (which `legal_basis.legitimate_interests` in the policy explicitly does). |
| **Art. 7(3) — Withdraw consent** | ⚠️ Implicit only | Withdrawal currently only possible by deleting the account. | Must be "as easy to withdraw as to give." Add granular per-purpose withdraw endpoints. |

---

## 6. Erasure cascade — what gets missed

`backend/core/api/app/tasks/user_cache_tasks.py` is comprehensive across Postgres + Redis + Vault, but several downstream stores are explicitly known to be incomplete:

| Store | Status | Evidence | Severity |
|---|---|---|---|
| **S3 invoice PDFs** | ❌ Not deleted | `user_cache_tasks.py:~1507` carries a `TODO: Delete invoice PDFs from S3 using encrypted_s3_object_key` | 🔴 Critical |
| **S3 credit-note PDFs** | ❌ Not deleted | `user_cache_tasks.py:~1638` `TODO` | 🔴 Critical |
| **S3 chat files** | ❓ Verify | Cascade calls `persistence_tasks.py` which deletes per-chat `upload_files` rows + storage counters; confirm S3 objects are actually removed when chats are bulk-deleted on account closure. | 🟠 High |
| **Compliance logs (`audit-compliance.log`, `financial-compliance.log`)** | ❌ Plaintext `user_id` retained 2–10y | `compliance.py:75-79` explicitly bypasses the `SensitiveDataFilter` for compliance logs to keep `user_id`. After Art. 17 erasure, this is a residual identifier. Financial logs *legitimately* must keep transaction-level audit (HGB §257), but the user_id should be replaced with the per-user `account_id` (the 7-char invoice id) and a non-reversible hash, not the live user_id. | 🔴 Critical |
| **OpenTelemetry / OpenObserve traces** | ❌ No deletion path | OTel pseudonymizes user_ids with a **daily-rotating** salt, so older traces become unjoinable to a known user_id within ~24 hours. That mitigates the issue but doesn't fully discharge Art. 17. Document the retention window. | 🟡 Medium |
| **Caddy access logs** | ❌ No deletion path; 30-day rotation in Caddyfile | `Caddyfile` lines 18-24. IPs in access logs aren't redacted. | 🟡 Medium |
| **Stripe customer / subscription** | ❌ Not cancelled or deleted | No call to `customers.delete` or `subscriptions.cancel` in the deletion task. Auto-refund logic (last 14 days) exists, but the subscription itself keeps running. | 🔴 Critical |
| **Polar customer** | ❌ Not deleted | Refund-only. | 🟠 High |
| **Mailjet / Brevo contact** | ❌ No deletion call | A `mailjet_contact_cleanup_task` is referenced but not called from the deletion cascade. | 🟠 High |
| **LLM provider conversation history** | ❌ Out of band | No code path notifies Anthropic / OpenAI / Google / Together that a user has exercised erasure. Most providers retain logs 30–90 days for trust & safety. Document this in the privacy policy as an inherent residual risk; consider building a manual purge runbook. | 🟠 High (transparency duty) |
| **Push notification subscriptions (FCM/Web Push)** | ❌ Not cleared | `directus_users.push_notification_subscription` is deleted with the user row, but no DELETE call is made to FCM or the Web Push endpoint. | 🟡 Medium |
| **Vector/search index** | ✅ N/A | No external vector DB found (no Pinecone/Weaviate/Qdrant calls). Embeds live in Postgres + S3 only. | — |
| **Backups (`openmates-userdata-backups`)** | ⚠️ Lifecycle-only | 60-day TTL means deleted users' exports drop off naturally. Document this as the policy. | 🟢 Low |

---

## 7. Retention & cookies

### 7.1 Retention — strong

- `tasks/auto_delete_tasks.py` ships with three Celery beat jobs:
  - **Auto-delete chats** — daily 02:30 UTC, honors `directus_users.auto_delete_chats_after_days`, hard-delete, capped at 100/user/run.
  - **Auto-delete issue reports** — daily 03:00 UTC, **14-day** retention, deletes encrypted YAML + screenshot from S3 + Directus row.
  - **Auto-expire stale devices** — daily 04:00 UTC, **90-day** TTL, cites Art. 5(1)(c) data minimization in the docstring.
- Compliance logs:
  - Audit — 2 years (`openmates-compliance-logs-backups/audit-compliance/`) — BSI §34 BDSG.
  - Financial — 10 years (same bucket, `financial-compliance/`) — AO §147 / HGB §257.
- Usage rows → S3 archive after 3 months → 3-year retention (`s3/config.py`).
- Redis TTLs are consistent and visible in `cache_config.py`.

### 7.2 Cookies — secure, but **no consent banner**

`backend/core/api/app/routes/auth_routes/auth_session.py:76-121`:

```
auth_refresh_token: HttpOnly=True, Secure=True, SameSite=Strict, Domain=parent-of-Origin, max_age={24h | 30d}
```

CSP, HSTS (1y `includeSubDomains; preload`), `X-Frame-Options: DENY`, `Permissions-Policy` (camera/microphone/geolocation/interest-cohort all `()`), `Referrer-Policy: strict-origin-when-cross-origin`, all set in both `Caddyfile` and `frontend/apps/web_app/src/hooks.server.ts`. Excellent.

**Gap:** No cookie consent banner exists in the frontend codebase. This is **acceptable today only if every cookie is strictly necessary** (e.g. `auth_refresh_token`). Verify there is no analytics cookie, no Stripe.js cookie that survives without an actual checkout, no Polar cookie, no embed-iframe third-party cookies. If any non-essential cookie ships, GDPR + ePrivacy require an opt-in banner.

### 7.3 sessionStorage WebSocket fallback (Safari iOS)

`frontend/packages/ui/src/utils/cookies.ts:40-67` — Safari iOS strips HttpOnly cookies on WebSocket upgrades, so the JWT is mirrored to `sessionStorage`. This is reachable via XSS, but the mitigation (master key + every payload encrypted client-side, plus reauth for sensitive ops) is reasonable. Document this in the security section of the privacy policy.

---

## 8. Logging & PII leakage

- `backend/core/api/app/utils/log_filters.py` runs a global `SensitiveDataFilter` over Celery + root + module loggers (`celery_config.py:195-207`). Patterns: email → `***@***.***`, IP → `[REDACTED_IP]`, UUID → `[REDACTED_ID]`, password/token/Bearer → `[REDACTED]`.
- `compliance.py:62-65, 75-79` — compliance loggers **bypass** the user_id redaction (intentional, for audit trail). Other PII (email/IP/password) is still redacted. Inconsistency: `log_auth_event()` and `log_data_access()` keep IP plaintext, while `log_consent()` and `log_refund_request()` hash it. Standardize.
- `safety_audit_log.user_id` is plaintext in Directus, not hashed. The schema comment justifies this for compliance review. Consider switching to `hashed_user_id` consistent with every other table; reviewers can map to user via the existing `account_id` lookup.

---

## 9. Privacy policy & ToU accuracy — line-by-line cross-check

### 9.1 `shared/docs/privacy_policy.yml` (canonical)

| Claim in policy | Reality | Verdict |
|---|---|---|
| `providers.brevo` is the email provider | Both `brevo_provider.py` AND `mailjet_provider.py` exist | ❓ Reconcile — flag for owner |
| `providers.aws` covers "Anthropic (AWS Bedrock)" only | `anthropic_direct_api.py` exists with the official `anthropic` SDK; `bedrock_client.py` exists separately. Routing depends on runtime config. | ❌ Inaccurate if the direct path is enabled |
| `providers.openrouter` + `cerebras` covers OpenAI-style models | `openai_client.py:53` allows `server_choice ∈ {openai, openrouter, azure}`; `together_client.py` calls `api.together.xyz` directly; `google_maas_client.py` is a separate Google path; `together_client.py` is not OpenRouter | ❌ Multiple direct paths undisclosed |
| `providers.google` covers "maps + LLM" | Also covers `google_events.py`, `youtube_metadata.py`, `google/vision_safety.py`, `google_maps/static_maps.py`, and Google Lens (via SerpAPI) | ⚠️ Underspecified — disclose all Google surfaces |
| `providers.stripe` + `providers.polar` are the payment processors | `invoices.provider` enum is `stripe / polar / revolut`; `revolut_service.py` exists | ❌ Revolut missing |
| `providers.sightengine` covers image moderation | Correct, plus Google Vision safety and OpenAI vision-safety fallback exist as additional layers | ⚠️ Disclose Google Vision + OpenAI vision fallback |
| `providers.webshare` covers "videos transcript / appointments / events" | Correct usage, but the *upstream* services routed through Webshare (Doctolib, Jameda, YouTube, Meetup) are not named anywhere | ⚠️ Disclose the upstream targets, not just the proxy |
| `providers.flightradar24` covers flight tracks | Also `travelpayouts_provider.py`, `serpapi_provider.py`, `serpapi_hotels_provider.py`, `transitous_provider.py` exist for travel app | ❌ Multiple travel providers undisclosed |
| `data_processing.ephemeral_stability_logs` — 48h ephemeral, 14d on error, sanitized, opt-out via Settings | Matches `.claude/rules/debugging.md` description; sanitization filter found in `log_filters.py` and the per-session UUID logic in the frontend | ✅ Accurate |
| `security_measures.device_fingerprinting` — 90d retention, hash-only, IPs not stored on the device record | Matches `auto_delete_tasks.py` (90d) and `api_key_devices.encrypted_anonymized_ip` (first 2 octets). Failed-login IP retention claim — verify `auth_routes` actually enforces 30d. | ⚠️ Verify failed-login IP retention SLA |
| `data_categories.account / usage / content / payments` | Matches schemas. The i18n version also includes `newsletter` (visible in `buildLegalContent.ts:299`) but the canonical YAML has no `newsletter` category. | ❌ Sync mismatch |
| `data_retention.payments_and_invoices: 10y` | Matches S3 lifecycle | ✅ |
| `data_retention.usage_and_logs: 12 months / failed-login IPs 30 days` | Caddy logs rotate at 30d, app logs go through redaction. **Verify** there is a 12-month retention enforcement somewhere. | ⚠️ Verify |
| `legal_rights.gdpr.rights` lists access/rectification/erasure/restriction/portability/objection/withdraw_consent | Restriction (Art. 18), objection (Art. 21), and granular withdraw are **not implemented in code** | ❌ Policy promises rights the code does not deliver |
| `contact.dpo: "No designated DPO at this time"` | Verify whether OpenMates is large enough to require a DPO under Art. 37; if not, this is fine. | ⚠️ Verify legal threshold |

### 9.2 `frontend/packages/ui/src/i18n/sources/legal/privacy.yml` (rendered to users)

The user-facing version is built by `buildPrivacyPolicyContent()` and includes 16 named provider sections (3.1–3.16). It also includes a Section 9 "Discord Integration" block that does not exist in the canonical YAML. According to `.claude/rules/privacy.md`, both files must be kept in sync.

The user-facing privacy text was last updated **2026-03-06** (`legal/documents/privacy-policy.ts:48`). The code has changed substantially since (new app providers, image safety pipeline, Polar/Revolut). Bump the date when it gets updated.

### 9.3 `frontend/packages/ui/src/i18n/sources/legal/terms.yml` (ToU)

Sections rendered by `buildTermsOfUseContent()`:

1. Agreement
2. About OpenMates
3. Intellectual property
4. Use license + restrictions (military, gambling, misinformation, scams, illegal)
5. AI accuracy + data sharing
6. Credits + payments + refunds
7. Disclaimer
8. Limitations (5 items)
9. Service availability
10. Encryption keys & account recovery
11. Governing law
12. Contact

Findings:
- ✅ The "encryption keys & account recovery" section maps cleanly to the actual zero-knowledge architecture (no recovery without the recovery code).
- ⚠️ "Refunds" — the code (`tasks/user_cache_tasks.py`) auto-refunds invoices from the **last 14 days** of credit purchases on account deletion, except gift cards. The ToU should match this exact policy. Verify the wording in `terms.refund` matches the 14-day window and the gift-card exception.
- ❌ The ToU lists Stripe + Polar (in section 6 contextually) but does not mention Revolut.
- ❌ "Limitations.list.data_loss" exists, but the ToU does not warn that **erasure does not propagate to upstream LLM providers** — users should know that prompts they send to an LLM may be retained by that provider for trust-and-safety windows (typically 30 days at OpenAI, 30 days at Anthropic).
- ⚠️ "Governing law" — confirm the imprint's country aligns with the chosen forum (German courts likely, given the BSI/AO/HGB references).
- 🟢 The terms reference "OpenMates™" as a trademark; ensure registration if claiming the symbol.

### 9.4 `imprint.yml`

Imprint is i18n keys + a TMG (German Telemedia Act §5) heading + 4 SVG images for postal contact info (in `frontend/apps/web_app/static/images/legal/{1..4}.svg`). Operator data is in the SVGs, not in a YAML field. Verify the SVGs are current (controller name, address, registry court, VAT ID, managing director).

---

## 10. Other findings

| ID | Finding | Severity |
|---|---|---|
| L1 | sessionStorage WebSocket token (Safari iOS fallback) — XSS-readable. Mitigated by client-side encryption of content + short-lived JWT, but document. | 🟢 Low |
| L2 | `demo_chats` table holds cleartext title/summary/icon. Intentional (public demo content) and outside GDPR scope (admin-curated, not user PII). | 🟢 Low |
| M1 | `aes_key` in `upload_files` is stored as plaintext base64 *and* as `vault_wrapped_aes_key`. Confirm whether the plaintext field is ever read in production; if not, drop it. | 🟡 Medium |
| M2 | ~~`openmates-temp-images` bucket is public-read with 1d TTL~~ ✅ **RESOLVED 2026-04-08 (OPE-372)** — bucket switched to private; SerpAPI Google Lens now receives a 15-minute presigned URL; skill deletes immediately after the call; 1-day lifecycle retained as safety net. Startup ACL reconciliation in `s3/service.py` flips existing buckets on next deploy. | 🔴 Critical |
| M3 | `safety_audit_log.user_id` plaintext (already noted). | 🟡 Medium |
| M4 | `connected_devices` JSON in `directus_users` carries device hashes; deletion path verified, but ensure `device_hash` rotation when a device is unlinked. | 🟡 Medium |
| M5 | Reminder records (`reminders` table) Vault-encrypt the **raw user_id** so the worker can deliver via WebSocket. On erasure, confirm the Vault key delete invalidates these. | 🟡 Medium |
| H1 | `default_ai_model_simple/_complex` are stored cleartext — not strictly PII, but reveal user preference; low risk. | 🟢 Low |

---

## 11. Findings catalog (sorted by severity)

### 🔴 Critical (must fix before next public release)

| # | Finding | Where | Action |
|---|---|---|---|
| C1 | Multiple **LLM subprocessors undisclosed** (Anthropic direct, OpenAI direct/Azure, Together, Google MaaS, FAL, Recraft) | `backend/apps/ai/llm_providers/`, `backend/shared/providers/{fal,recraft}/` | Add to `shared/docs/privacy_policy.yml` + `i18n/sources/legal/privacy.yml`; document data shared and jurisdiction for each; add SCC reference for US providers. |
| C2 | **Revolut** payment processor undisclosed | `services/payment/revolut_service.py`, `invoices.provider` enum | Add Revolut block to both policy files. |
| C3 | **S3 invoice & credit note PDFs not deleted on account erasure** | `user_cache_tasks.py:~1507`, `~1638` | Implement S3 delete using `encrypted_s3_object_key` (decrypt with Vault, then `s3.delete_object`). |
| C4 | **Compliance logs retain plaintext `user_id` after erasure** | `compliance.py:75-79` | Replace `user_id` with `account_id` + non-reversible hash for new entries; for past entries within the financial window, document the legitimate-interest basis (HGB §257) in the privacy policy. |
| C5 | **No Stripe subscription cancellation on erasure** | `user_cache_tasks.py` deletion task | Call `stripe.Subscription.delete()` + `stripe.Customer.delete()` (or anonymize per Stripe's GDPR docs). |
| ~~C6~~ | ✅ **RESOLVED 2026-04-08 (OPE-372)** — `openmates-temp-images` now private, SerpAPI receives a 15-min presigned URL, startup reconciliation in `s3/service.py` applies the new ACL to existing buckets. | `s3/config.py`, `s3/service.py`, `internal_api.py`, `search_skill.py` | Done. |
| C7 | **No cookie consent banner** | frontend (none found) | Either prove every cookie is strictly necessary and document this in the privacy policy, or add a banner. ePrivacy applies regardless of GDPR. |
| C8 | **Discord disclosed in i18n privacy.yml but missing from `shared/docs/privacy_policy.yml`** | both files | Per `.claude/rules/privacy.md` they must be kept in sync. Add Discord to the canonical YAML. |
| C9 | **Policy promises Art. 18 + Art. 21 rights that the code cannot deliver** | `legal_rights.gdpr.rights` vs absent endpoints | Either implement the endpoints or remove the promise (and document the alternative path: deletion). |

### 🟠 High

| # | Finding | Action |
|---|---|---|
| H1 | ~18 event/travel/health/shopping providers undisclosed (Meetup, Luma, Google Calendar, Bachtrack, ResidentAdvisor, ClassicTIC, Berlin Phil, Siegessäule, SerpAPI, Travelpayouts, Doctolib/Jameda, Rewe, Amazon, Transitous, ProtonMail bridge, YouTube metadata) | Add categorized provider sections; for health-adjacent (Doctolib/Jameda) add Art. 9 disclosure. |
| H2 | No email rectification endpoint | Add `/v1/settings/email-change` with email-OTP verification → updates `hashed_email`, both encrypted email fields, and Brevo/Mailjet contact. |
| H3 | No granular consent withdrawal | Add `/v1/settings/withdraw-consent/{type}`. |
| H4 | No Art. 21 objection endpoint | Add `/v1/settings/object-to-processing/{category}` and respect the flag in the relevant processors. |
| H5 | No Art. 18 restriction endpoint | Add `processing_restricted` flag + endpoints; pause AI processing, credit charges, analytics ingestion when set. |
| H6 | Mailjet provider exists alongside Brevo with no policy disclosure | Confirm whether Mailjet is live or dead code. If dead, delete the file. If live, add to policy. |
| H7 | Stripe / Polar / Mailjet contact deletion missing from erasure cascade | Add explicit cleanup calls. |
| H8 | LLM provider conversation history not erased | Document residual retention in the privacy policy under "limitations of erasure". |
| H9 | Push notification subscriptions not unregistered on erasure | Call FCM / Web Push DELETE. |
| H10 | `aes_key` plaintext field in `upload_files` | Confirm dead and remove. |
| H11 | Failed-login IP retention claim (30d) — verify enforcement | Spot-check `auth_routes` and any IP cleanup task. |

### 🟡 Medium

| # | Finding | Action |
|---|---|---|
| M1 | Inconsistent IP hashing across compliance log methods | Standardize on `hash_ip_address()` for everything except cases where the cleartext IP is required for an active fraud investigation. |
| M2 | Caddy access logs only retained 30d (less than the 2-year audit window the policy claims) | Either extend retention via S3 archive job, or rewrite the policy claim to be honest about the 30d window. |
| M3 | `safety_audit_log.user_id` plaintext | Switch to hashed_user_id. |
| M4 | OTel pseudonymization rotates daily — older traces are unjoinable; document the effective retention window | Add an OTel paragraph to the privacy policy. |
| M5 | Chat content export requires client-side sync (not server-rendered) | Document this clearly in the policy + add UI affordance. |
| M6 | Consent versioning is timestamp-only (no document hash) | Hash the rendered policy and store the hash alongside the timestamp on `consent_*` fields. |
| M7 | `data_categories.newsletter` exists in i18n privacy but not in canonical YAML | Reconcile. |
| M8 | `lastUpdated: 2026-03-06` is stale by ~5 weeks; code has materially diverged | Bump after the next update pass. |

### 🟢 Low

| # | Finding | Action |
|---|---|---|
| L1 | sessionStorage Safari WS fallback is XSS-readable | Document. |
| L2 | `demo_chats` cleartext (intentional) | No action. |
| L3 | `default_ai_model_simple/_complex` cleartext | No action. |
| L4 | `last_opened`, `signup_completed`, etc. not in user export | Add to export for completeness. |

---

## 12. Privacy policy & ToU — fix list (concrete edits)

The user requested **report-only**, so this is a checklist for a follow-up session, not a diff.

### 12.1 `shared/docs/privacy_policy.yml`

1. Add `providers.discord` (mirror the i18n version).
2. Add `providers.revolut`.
3. Replace `providers.aws` description with the truth about the Anthropic routing surface (Bedrock + direct API + how to tell which is in use).
4. Add `providers.openai` (or rename existing OpenRouter block to make clear that direct OpenAI is also a possible path).
5. Add `providers.together`.
6. Add `providers.google_maas` (separate from existing `google` block).
7. Add `providers.fal` and `providers.recraft` (image generation).
8. Add `providers.serpapi` and explain the `temp-images` upload flow for Google Lens (bucket is now private, SerpAPI receives a 15-min presigned URL — C6 fixed 2026-04-08).
9. Add a `providers.events_aggregators` block listing Meetup, Luma, Google Calendar, Bachtrack, ResidentAdvisor, ClassicTIC, Berlin Phil, Siegessäule.
10. Add `providers.travel_aggregators` (Travelpayouts, SerpAPI flights/hotels, Transitous).
11. Add `providers.health_directories` with explicit Art. 9 disclosure (Doctolib, Jameda).
12. Add `providers.shopping` (Rewe, Amazon).
13. Add `providers.youtube` and `providers.protonmail_bridge`.
14. Add `providers.openobserve` (or document self-host on Hetzner).
15. Add `data_categories.newsletter`, `data_categories.special_category_health` (for Doctolib queries).
16. Update `data_retention.usage_and_logs` to reflect the actual Caddy log retention.
17. Update `legal_rights.gdpr.rights` so that promised rights match implemented endpoints. **Either** implement Art. 18/21/granular-withdraw, **or** remove them from the list (legally riskier — prefer to implement).
18. Add a "limitations of erasure" subsection: residual retention windows at LLM providers, financial-compliance log retention, OTel pseudonymized window.
19. Add a "cookies" section explicitly listing every cookie the site sets and classifying each as strictly-necessary; if any non-essential cookie ships, add a banner.
20. Bump `lastUpdated`.

### 12.2 `frontend/packages/ui/src/i18n/sources/legal/privacy.yml`

Mirror the canonical YAML changes via the i18n source. Run `cd frontend/packages/ui && npm run build:translations` per `.claude/rules/i18n.md`.

### 12.3 `frontend/packages/ui/src/legal/buildLegalContent.ts`

Add new `lines.push(...)` blocks for each new provider section. Section numbering currently goes up to ~3.16; renumber consistently.

### 12.4 `frontend/packages/ui/src/config/links.ts` and `legal/documents/privacy-policy.ts`

Add the new provider link constants and bump `lastUpdated`.

### 12.5 `terms.yml`

1. Update section 6 (Credits/Payments) to mention all three payment processors (Stripe, Polar, Revolut) and the **14-day, gift-card-excluded** auto-refund policy that the code actually enforces.
2. Add a clause to section 5 (AI accuracy / data sharing) acknowledging that prompts sent to LLM providers may be retained by them for trust-and-safety windows independent of OpenMates' own retention.
3. Add a clause to section 10 (encryption keys / account recovery) noting that erasure invalidates the Vault key, which is what makes encrypted content unrecoverable — this is the technical mechanism, not a legal commitment, and strengthens the compliance story.
4. Bump the `lastUpdated` field in `terms.yml`.

### 12.6 `imprint.yml`

Verify the SVGs in `frontend/apps/web_app/static/images/legal/{1..4}.svg` are current with the registered legal entity, address, managing director, registry court, and VAT ID.

---

## 13. Recommended remediation order (no work performed in this session)

1. **Disclosure first** (lowest risk, biggest legal-risk reduction): the privacy policy fix list in §12.1–12.6. This unblocks the next release and matches the rule that "transparency is the cheapest form of compliance."
2. **Erasure cascade hardening:** S3 PDF deletion (C3), Stripe customer/subscription deletion (C5), `temp-images` bucket lockdown (C6), Mailjet contact cleanup, push token unregister, compliance-log user_id replacement (C4).
3. **GDPR rights endpoints:** Art. 18 restriction, Art. 21 objection, granular consent withdrawal, email rectification (H2–H5).
4. **Cookie banner / cookie inventory** (C7) — even if every cookie is strictly necessary, document the inventory in the privacy policy.
5. **OTel + log retention SLA reconciliation** (M1, M2, M4).
6. **Mailjet vs Brevo cleanup** (H6) — pick one, delete the other.
7. **Cleanup leftovers:** plaintext `aes_key` (H10), `safety_audit_log.user_id` hashing (M3), `data_categories.newsletter` reconciliation (M7).

---

## 14. Files referenced (high-signal paths)

```
backend/core/directus/schemas/                    # All Directus collection definitions
backend/core/api/app/services/compliance.py       # Audit + financial compliance logging
backend/core/api/app/services/cache_config.py     # Redis TTLs
backend/core/api/app/services/s3/config.py        # Bucket lifecycle policies
backend/core/api/app/services/encryption.py       # Vault Transit wrapper
backend/core/api/app/tasks/auto_delete_tasks.py   # Retention cron jobs
backend/core/api/app/tasks/user_cache_tasks.py    # 5-phase account-deletion cascade
backend/core/api/app/tasks/persistence_tasks.py   # Chat/message/embed hard delete
backend/core/api/app/routes/settings.py           # Export + delete-account endpoints
backend/core/api/app/routes/auth_routes/auth_session.py  # Cookie security
backend/core/api/app/utils/log_filters.py         # Global SensitiveDataFilter
backend/shared/python_utils/tracing/privacy_filter.py    # OTel 3-tier filter
backend/apps/ai/llm_providers/                    # All LLM client modules
backend/shared/providers/                         # Shared external API wrappers
backend/apps/{events,travel,health,shopping}/providers/  # Vertical aggregators
backend/core/api/app/services/payment/{stripe,polar,revolut}_service.py
backend/core/api/app/services/email/{brevo,mailjet}_provider.py
deployment/dev_server/Caddyfile                   # TLS, HSTS, CSP, access logs
frontend/packages/ui/src/services/db.ts           # IndexedDB schema
frontend/packages/ui/src/utils/cookies.ts         # WS token sessionStorage fallback
frontend/packages/ui/src/services/tracing/setup.ts # Frontend OTel client
frontend/apps/web_app/src/hooks.server.ts         # SvelteKit security headers
shared/docs/privacy_policy.yml                    # Canonical privacy disclosures
frontend/packages/ui/src/i18n/sources/legal/{privacy,terms,imprint}.yml
frontend/packages/ui/src/legal/buildLegalContent.ts
frontend/packages/ui/src/legal/documents/privacy-policy.ts
```

---

## 15. Open questions for the maintainer

1. Is **Mailjet** a live email provider or dead code? (Both `brevo_provider.py` and `mailjet_provider.py` exist.)
2. Which OpenAI/Anthropic routing surface is **actually configured in production** — Bedrock, OpenRouter, direct API, or all three?
3. Is **OpenObserve** self-hosted on Hetzner (no disclosure needed beyond "Hetzner") or a managed service (must disclose)?
4. Is the OpenMates legal entity above the Art. 37 threshold for needing a designated DPO?
5. Are the imprint SVGs current?
6. Is the German court / governing-law clause in `terms.governing_law` the entity's actual forum?
7. Is there an existing Art. 30 "records of processing activities" document anywhere outside the codebase? (If yes, this audit can be cross-referenced; if no, it should be created using the data flows mapped above.)

---

*End of report.*
