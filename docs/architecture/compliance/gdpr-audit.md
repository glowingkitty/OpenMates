# GDPR Compliance Audit — OpenMates

**Original audit:** 2026-04-08 (session 269d)
**Last updated:** 2026-04-09 — cleaned to reflect current state after the 2026-04-08/09 remediation wave
**Scope:** Full code-level GDPR audit + privacy policy / ToU accuracy check
**Method:** Parallel research agents covering PII storage, third-party providers, user-rights endpoints, retention/cookies/telemetry, cross-checked against `shared/docs/privacy_policy.yml` and `frontend/packages/ui/src/i18n/sources/legal/{privacy,terms,imprint}.yml`.

> **Confidence note.** Findings come from static code reading, not runtime testing. Production routing between e.g. Anthropic direct API and AWS Bedrock depends on runtime config (`secrets_manager` / `config_manager`) and needs a config audit to confirm which paths are actually live.

---

## 1. Executive Summary

OpenMates has an **unusually strong privacy foundation** for an AI product: client-side encryption with in-memory-only server processing and HashiCorp Vault Transit key management, hashed user identifiers throughout the database, a 3-tier privacy filter on OpenTelemetry, structured compliance logging with legally justified retention windows, hardened cookies and CSP, and an account-deletion cascade across Postgres, Redis, Vault, S3 (including invoice/credit-note PDFs), and Stripe.

The 2026-04-08/09 remediation wave closed the largest category of findings — the transparency gap. The privacy policy is now restructured around provider-trigger groups (A–J), discloses every LLM, image, search, travel, events, health, shopping and community subprocessor that the code actually calls, and adds an explicit "Limitations of erasure" section. Dead code (Revolut, Mailjet, Azure OpenAI scaffold) was removed rather than disclosed. Cookie and browser-storage inventories now exist in `docs/architecture/compliance/{cookies,browser-storage}.yml`. A twice-weekly legal-compliance scanner feeds `top-10-recommendations.md`.

**Overall posture:** ~90% GDPR-aligned in *implementation*; ~90% aligned in *documented disclosure*. Remaining exposure is concentrated in (a) four GDPR rights endpoints that the policy still promises but the code does not yet implement (Art. 16 email rectification, Art. 18 restriction, Art. 21 objection, Art. 7(3) granular withdraw), (b) compliance-log plaintext `user_id` after erasure, (c) Polar customer and push-subscription cleanup missing from the erasure cascade, and (d) the open ePrivacy decision on whether a cookie banner is required given the now-documented inventory.

| Severity | Open | Closed in 04-08/09 wave |
|---|---|---|
| 🔴 Critical | 3 (C4 compliance-log user_id, C7 cookie banner decision, C9 rights promised vs delivered) | C1 LLM subprocessor disclosure, C2 Revolut (deleted as dead code), C3 S3 PDF deletion, C5 Stripe customer delete, C6 temp-images bucket, C8 Discord sync |
| 🟠 High | 7 (H2–H5 rights endpoints, H7 Polar/push cleanup, H9 push unregister, H11 failed-login IP SLA) | H1 ~18 aggregators undisclosed, H6 Mailjet (deleted as dead code), H8 LLM residual retention disclosed |
| 🟡 Medium | 7 (M1–M6 compliance-log IP hashing, Caddy SLA, safety_audit_log, OTel retention doc, chat export UX, consent versioning) | M7 `newsletter` category, M8 stale `lastUpdated` |
| 🟢 Low | 4 (L1 Safari WS token, L2 demo cleartext, L3 default model cleartext, L4 export fields) | — |

---

## 2. Methodology

Four research streams ran in parallel via subagents: (1) PII storage inventory across Directus, Redis, IndexedDB, S3, Vault; (2) third-party provider matrix; (3) GDPR rights endpoints Art. 15–21; (4) retention, cookies, consent, telemetry. The orchestrator then cross-checked findings against the canonical privacy policy, the i18n legal sources, and the demo-chat metadata, and spot-verified critical claims (Anthropic direct API path, Together base URL, Brevo presence) by reading source files.

---

## 3. PII storage map

### 3.1 Postgres (Directus) — encrypted fields

Directus is the system of record. Most user PII is encrypted at rest with a per-user master key wrapped by Vault Transit. Concrete tables:

- `directus_users` — `encrypted_email_address`, `encrypted_email_with_master_key`, `encrypted_username`, `hashed_email`, `hashed_username`, `user_email_salt`, profile image fields, `encrypted_settings`, `connected_devices` (JSON), `last_online_timestamp`, `encrypted_credit_balance`, `encrypted_payment_method_id`, `stripe_customer_id`/`stripe_subscription_id` (cleartext), `encrypted_tfa_secret`, `tfa_backup_codes_hashes` (Argon2), `encrypted_tfa_app_name`, `vault_key_id`, `vault_key_version`, `lookup_hashes`, consent timestamps, `auto_delete_chats_after_days`, push notification subscription objects, `default_ai_model_simple`/`_complex`, `is_admin`.
- `chats` — `hashed_user_id`, `encrypted_title`, `encrypted_chat_summary`, `encrypted_chat_tags`, `encrypted_chat_key`, `shared_with_user_hashes`, `shared_encrypted_*`.
- `messages` — `encrypted_content`, `encrypted_thinking_content`, `encrypted_pii_mappings`, role, `encrypted_model_name`.
- `embeds` / `embed_keys` — `encrypted_content`, `encrypted_text_preview`, `s3_file_keys`, AES-wrapped per-embed key.
- `api_keys` / `api_key_devices` — `encrypted_key_prefix`, `key_hash`, `encrypted_anonymized_ip` (first 2 octets), `encrypted_country_code`/`_region`/`_city`, `encrypted_machine_identifier`.
- `user_passkeys` — `credential_id`, `public_key_jwk`/`public_key_cose`, `aaguid`, `sign_count`, `encrypted_device_name`.
- `usage` — `user_id_hash`, `device_hash`, encrypted model / credit-cost / token fields, encrypted server region.
- `invoices` / `credit_notes` — `encrypted_amount`, `encrypted_s3_object_key`, `encrypted_aes_key`, `encrypted_currency`, `provider` enum `stripe`/`polar` (plus legacy `revolut` values for historical rows only — the Revolut integration was removed in `OPE-373`).
- `reminders` — `encrypted_user_id`, `encrypted_prompt`, `encrypted_chat_history`, repeat/random configs.
- `user_app_settings_and_memories` — `encrypted_app_key`, `encrypted_item_json`.
- `user_daily_inspirations` — encrypted phrases, AI responses, video metadata.
- `safety_audit_log` — **`user_id` cleartext** (see M3).
- `upload_files` — `original_filename`, `content_hash`, `aes_key` (base64 cleartext) + `vault_wrapped_aes_key` (see H10).
- `demo_chats` — title/summary/category/icon cleartext (intentional, public).
- `encryption_keys` — `encrypted_key`, `key_iv`, `salt`, `login_method`.

### 3.2 Cache / ephemeral

Redis/Dragonfly holds short-lived decrypted copies of profile, device, chat list, draft, and message context. Key prefixes: `user_profile:`, `session:`, `user_device:*`, `user_chats:`, `chat_list_item_data:`, `chat_messages:`, `user:{user_id}:chat:{chat_id}:draft`. TTLs 5 min – 72 h. The encryption-service wrapper decrypts on read using the user's Vault key — the cache is plaintext-equivalent for the TTL.

### 3.3 Object storage (`backend/core/api/app/services/s3/config.py`)

| Bucket | Encryption | Lifecycle |
|---|---|---|
| `openmates-profile-images-private` | AES-256-GCM (user key) | None |
| `openmates-chatfiles` | AES-256-GCM (per-file) | None |
| `openmates-invoices` | AES-256-GCM (user vault key) | **10 years** (AO §147 / HGB §257) |
| `openmates-userdata-backups` | User master key | 60 days |
| `openmates-compliance-logs-backups` | Plaintext | 2 y audit / 10 y financial |
| `openmates-usage-archives` | Server key | 3 years |
| `openmates-temp-images` | Plaintext, **private** (15 min presigned URL to SerpAPI) | 1 day (safety net) |
| `openmates-issue-logs` | Encrypted YAML + plaintext PNG | 1 year |

### 3.4 Browser-side

IndexedDB `chats_db` (`services/db.ts` v22) holds encrypted copies of chats, messages, embeds, suggestions, app settings/memories, daily inspirations, plus offline sync queues. All client-side encrypted with the user's master key. Cleared on logout. `sessionStorage` holds an `incognito_chats` set (cleared on tab close), a per-session stability-log UUID, and a Safari/iOS WebSocket token fallback (`utils/cookies.ts` — see L1).

### 3.5 Vault / KMS

HashiCorp Vault Transit provides per-user master keys, a `shared-content-metadata` key for shared-chat OG tags, a static `email_encryption_key`, and the unsealing master. Account deletion calls `encryption_service.delete_user_key()` at the end of Phase 3 of the cascade (moved from Phase 1 in `OPE-370` so refund and S3 key decryption can still happen in Phase 2).

### 3.6 Telemetry

OTel traces pass through a 3-tier `TracePrivacyFilter`:
- always-strip cookie/authorization headers
- pseudonymize `user_id` → `SHA256(user_id + daily_salt)[:12]` (rotates daily)
- Tier 1 (regular users): safe ops only; redacts `db.statement`, `cache.key`, `skill.params`
- Tier 2 (error spans): + stacktrace, task IDs
- Tier 3 (admin / `debug_logging_opted_in`): full visibility

Client traces export to `/v1/telemetry/traces`; backend forwards to OpenObserve (self-hosted on Hetzner per `tracing/config.py`).

### 3.7 Cookie & browser-storage inventory

`docs/architecture/compliance/cookies.yml` and `browser-storage.yml` enumerate every cookie, `localStorage`, and `sessionStorage` key the site sets, with lengths only (values stripped). These inventories are populated by an E2E fixture and are the basis for the open C7 consent-banner decision.

---

## 4. Third-party providers

The privacy policy is restructured into provider-trigger groups (commit `7b1c22e97`):

| Group | Trigger | Providers |
|---|---|---|
| A | Always active | Vercel, Hetzner, IP-API, Brevo, OpenObserve (self-hosted) |
| B | Payments | Stripe, Polar |
| C | AI models | Anthropic (direct + Bedrock), OpenAI (direct + OpenRouter), Vertex MaaS (DeepSeek), Together AI, Groq, Cerebras, Mistral |
| D | Image generation | FAL (Flux), Recraft |
| E | Web / search | Brave, Firecrawl, SerpAPI, Google (Maps, Vision safety, Lens via SerpAPI) |
| F | Travel | Flightradar24, Travelpayouts, SerpAPI flights/hotels, Transitous |
| G | Events | Meetup, Luma, Bachtrack, Resident Advisor, ClassicTIC, Berlin Philharmonic, Siegessäule |
| H | Health | Doctolib, Jameda (via Webshare proxy) — Art. 9 disclosure |
| I | Shopping | REWE, Amazon |
| J | Community | Discord, YouTube metadata |

**Dead code removed** (`OPE-373`): Revolut, Mailjet, Azure OpenAI scaffold, Google Calendar events provider. These were never disclosed precisely because the code path was never live; the source files have been deleted.

**Open verification items:**
- `@fontsource-variable/lexend-deca` is bundled and self-served — confirm no `fonts.googleapis.com` link exists in the rendered HTML.
- Sightengine is the primary image moderation path; Google Vision safety and OpenAI vision fallback exist as additional layers — confirm the privacy policy mentions all three.
- ProtonMail bridge (`backend/shared/providers/protonmail/protonmail_bridge.py`) — confirm whether it actually transmits outbound user data; if so, disclose.

---

## 5. GDPR rights — endpoint coverage (Art. 15–21)

| Article | Status | Evidence | Gaps |
|---|---|---|---|
| **Art. 15 — Access** | ✅ Implemented | `GET /v1/settings/export-account-manifest`, `/export-account-data`, `/usage/export` in `settings.py`. Logged via `compliance.log_data_access()`. | Chat content not server-rendered (client must sync from IndexedDB first); email returned encrypted with master key. |
| **Art. 16 — Rectification** | ⚠️ Partial | Endpoints for username, language, darkmode, timezone, auto-topup. | **No email change endpoint.** `hashed_email` + `encrypted_email_address` cannot be updated by the user. Hard Art. 16 gap (**H2**). |
| **Art. 17 — Erasure** | ✅ Strong | `POST /v1/settings/delete-account` → `user_cache_tasks.py` runs a 5-phase cascade: auth, payments+refunds, content+S3 PDFs, Redis cache, final user row + compliance log. Reauth required. Includes Stripe subscription cancel + customer delete (`OPE-371`) and S3 invoice / credit-note PDF delete (`OPE-370`). | Polar customer delete missing (**H7**); push-subscription unregister missing (**H9**); LLM provider logs out of band (documented as limitation). |
| **Art. 18 — Restriction** | ❌ Not implemented | No endpoint, no `processing_restricted` flag. | **H5** — required by law; needs explicit pause-of-processing path. |
| **Art. 20 — Portability** | ✅ Implemented (JSON) | Same export endpoints. | No standardized schema; chat-content portion incomplete (**M5**). |
| **Art. 21 — Objection** | ❌ Not implemented | Consent *recording* exists (`/user/consent/privacy-apps`, `/user/consent/mates`) — those are Art. 7 grants, not Art. 21 objections. | **H4** — required because `legal_basis.legitimate_interests` appears in the policy. |
| **Art. 7(3) — Withdraw consent** | ⚠️ Implicit only | Withdrawal currently only possible via account deletion. | **H3** — must be "as easy to withdraw as to give." |

---

## 6. Erasure cascade — open items

The cascade in `backend/core/api/app/tasks/user_cache_tasks.py` now covers Postgres, Redis, Vault, S3 invoices + credit notes, and Stripe. Remaining gaps:

| Store | Status | Severity |
|---|---|---|
| **S3 chat files** | ❓ Verify — cascade calls `persistence_tasks.py` which deletes per-chat `upload_files` rows + storage counters; confirm S3 objects are actually removed when chats are bulk-deleted on account closure. | 🟠 High |
| **Compliance logs (`audit-compliance.log`, `financial-compliance.log`)** | ❌ Plaintext `user_id` retained 2–10 y (`compliance.py:75-79` bypasses `SensitiveDataFilter`). Replace with `account_id` + irreversible hash for new entries; document legitimate-interest basis for past entries within the financial window. | 🔴 Critical (**C4**) |
| **OpenTelemetry / OpenObserve traces** | ❌ No deletion path. The daily-rotating pseudonymization salt makes traces older than ~24 h unjoinable, but document the effective retention window. | 🟡 Medium (**M4**) |
| **Caddy access logs** | ❌ 30-day rotation, IPs not redacted. Extend retention or correct the policy's 2-year claim. | 🟡 Medium (**M2**) |
| **Polar customer** | ❌ Refund-only; no customer delete. | 🟠 High (**H7**) |
| **LLM provider conversation history** | ❌ Out of band — no erasure notification to Anthropic / OpenAI / Google / Together. **Documented** in the privacy policy's "Limitations of erasure" section; consider a manual purge runbook. | — (documented) |
| **Push notification subscriptions (FCM / Web Push)** | ❌ The `directus_users.push_notification_subscription` row is deleted, but no DELETE call is made to FCM or the Web Push endpoint. | 🟡 Medium (**H9**) |
| **Vector / search index** | ✅ N/A — no external vector DB. | — |
| **Backups (`openmates-userdata-backups`)** | ⚠️ Lifecycle-only — 60-day TTL means deleted users' exports drop off naturally; document. | 🟢 Low |

---

## 7. Retention & cookies

### 7.1 Retention

- `tasks/auto_delete_tasks.py` ships three Celery beat jobs:
  - **Auto-delete chats** — daily 02:30 UTC, honors `auto_delete_chats_after_days`, hard delete, capped 100/user/run.
  - **Auto-delete issue reports** — daily 03:00 UTC, 14-day retention, deletes encrypted YAML + screenshot from S3 + Directus row.
  - **Auto-expire stale devices** — daily 04:00 UTC, 90-day TTL, cites Art. 5(1)(c).
- Compliance logs: audit 2 y (BSI §34 BDSG) / financial 10 y (AO §147 / HGB §257).
- Usage rows → S3 archive after 3 months → 3-year retention.
- Redis TTLs are consistent and documented in `cache_config.py`.

### 7.2 Cookies

`auth_refresh_token`: `HttpOnly=True`, `Secure=True`, `SameSite=Strict`, `Domain=parent-of-Origin`, `max_age={24h | 30d}`. CSP, HSTS (1 y `includeSubDomains; preload`), `X-Frame-Options: DENY`, `Permissions-Policy` (camera/microphone/geolocation/interest-cohort all `()`), `Referrer-Policy: strict-origin-when-cross-origin`, set in both `Caddyfile` and `frontend/apps/web_app/src/hooks.server.ts`.

**C7 — cookie consent decision still open.** `cookies.yml` now lists every cookie the site sets. Before deciding whether a banner is required, confirm that *every* listed cookie is strictly necessary (auth, CSRF) — in particular that no analytics cookie, no Stripe.js persistent cookie (outside an active checkout), no Polar cookie, and no embed-iframe third-party cookie ships. If any non-essential cookie is present, GDPR + ePrivacy require opt-in.

### 7.3 Safari iOS WebSocket token fallback (L1)

`utils/cookies.ts` mirrors the JWT to `sessionStorage` because Safari iOS strips HttpOnly cookies on WebSocket upgrades. XSS-readable, mitigated by client-side content encryption + short-lived JWT + reauth for sensitive ops. Document in the security section.

---

## 8. Logging & PII leakage

- `utils/log_filters.py` runs a global `SensitiveDataFilter` over Celery + root + module loggers: email → `***@***.***`, IP → `[REDACTED_IP]`, UUID → `[REDACTED_ID]`, password/token/Bearer → `[REDACTED]`.
- `compliance.py` — compliance loggers **intentionally** bypass `user_id` redaction for audit trail. Inconsistency: `log_auth_event()` and `log_data_access()` keep IP plaintext, while `log_consent()` and `log_refund_request()` hash it. Standardize on `hash_ip_address()` (**M1**).
- `safety_audit_log.user_id` is plaintext (**M3**) — switch to `hashed_user_id` consistent with every other table; reviewers can map via `account_id` lookup.

---

## 9. Verification items in the current privacy policy

| Claim | Verification needed |
|---|---|
| `security_measures.device_fingerprinting` — 30-day failed-login IP retention | Spot-check `auth_routes` enforces this (**H11**). |
| `data_retention.usage_and_logs: 12 months / failed-login IPs 30 days` | Confirm a 12-month enforcement exists somewhere; Caddy logs rotate at 30 d. |
| `contact.dpo: "No designated DPO at this time"` | Verify the entity is below the Art. 37 threshold. |
| Terms section 6 refund wording | Confirm it matches the code: 14-day auto-refund on account deletion, gift cards excluded. |
| Terms section 10 encryption clause | Confirm it says erasure invalidates the Vault key (the technical mechanism that makes content unrecoverable). |
| Imprint SVGs (`static/images/legal/{1..4}.svg`) | Confirm controller name, address, registry court, VAT ID, managing director are current. |
| Governing law clause | Confirm forum matches the imprint country. |

---

## 10. Findings catalog (current / open only)

### 🔴 Critical

| # | Finding | Action |
|---|---|---|
| C4 | Compliance logs retain plaintext `user_id` after erasure (`compliance.py:75-79`) | Replace `user_id` with `account_id` + irreversible hash for new entries; document the legitimate-interest basis for past entries within the financial window. |
| C7 | Cookie consent banner decision pending review of `cookies.yml` inventory | Confirm every cookie is strictly necessary and document in the policy, or ship a banner. ePrivacy applies regardless of GDPR. |
| C9 | Policy promises Art. 18 + Art. 21 + granular-withdraw rights that the code does not implement | Either implement the endpoints (preferred) or remove the promises. |

### 🟠 High

| # | Finding | Action |
|---|---|---|
| H2 | No email rectification endpoint | Add `/v1/settings/email-change` with email-OTP verification → updates `hashed_email`, both encrypted email fields, and the Brevo contact. |
| H3 | No granular consent withdrawal | Add `/v1/settings/withdraw-consent/{type}`. |
| H4 | No Art. 21 objection endpoint | Add `/v1/settings/object-to-processing/{category}` and honor the flag in the relevant processors. |
| H5 | No Art. 18 restriction endpoint | Add `processing_restricted` flag + endpoints; pause AI processing, credit charges, analytics ingestion when set. |
| H7 | Polar customer delete missing from erasure cascade | Add explicit `polar_service.delete_customer()` call in `user_cache_tasks.py` Phase 2. |
| H9 | Push notification subscriptions not unregistered on erasure | Call FCM / Web Push DELETE before clearing the Directus row. |
| H10 | `aes_key` plaintext field in `upload_files` alongside `vault_wrapped_aes_key` | Confirm the plaintext field is never read in production; drop it. |
| H11 | 30-day failed-login IP retention claim — verify enforcement in `auth_routes`. | |

### 🟡 Medium

| # | Finding | Action |
|---|---|---|
| M1 | Inconsistent IP hashing across compliance log methods | Standardize on `hash_ip_address()`. |
| M2 | Caddy access logs retained 30 d (less than the 2-year claim in the policy) | Either extend retention via an S3 archive job, or correct the policy wording. |
| M3 | `safety_audit_log.user_id` plaintext | Switch to `hashed_user_id`. |
| M4 | OTel daily-rotating pseudonymization retention window not documented in the policy | Add a paragraph. |
| M5 | Chat content export requires client-side sync (not server-rendered) | Document clearly + add a UI affordance. |
| M6 | Consent versioning is timestamp-only (no document hash) | Hash the rendered policy and store alongside the timestamp on `consent_*` fields. |
| M-S3 | S3 chat files — verify that bulk-delete on account closure actually removes S3 objects, not just `upload_files` rows. | |

### 🟢 Low

| # | Finding | Action |
|---|---|---|
| L1 | sessionStorage Safari WS fallback (XSS-readable) | Document in security section. |
| L2 | `demo_chats` cleartext (intentional) | No action. |
| L3 | `default_ai_model_simple/_complex` cleartext | No action. |
| L4 | `last_opened`, `signup_completed`, etc. not in user export | Add for completeness. |

---

## 11. Recommended remediation order

1. **GDPR rights endpoints** (C9, H2–H5) — single biggest gap between policy promises and code; highest legal risk.
2. **Compliance-log user_id replacement** (C4) — schema + logger refactor; needs a migration plan for past entries inside the financial window.
3. **Cookie banner decision** (C7) — review `cookies.yml`, confirm strictly-necessary classification, add the section to the policy, and ship a banner if anything else is present.
4. **Erasure cascade hardening** — Polar customer delete (H7), push-subscription unregister (H9), S3 chat-file verification.
5. **Compliance-log IP standardization** (M1) and Caddy SLA reconciliation (M2).
6. **Schema cleanups** — `safety_audit_log.user_id` (M3), `upload_files.aes_key` plaintext (H10), OTel retention doc (M4), consent-versioning hash (M6), export field completeness (L4).

---

## 12. Open questions for the maintainer

1. Which OpenAI / Anthropic routing surface is actually configured in production — Bedrock, OpenRouter, direct API, or multiple?
2. Is every cookie in `cookies.yml` strictly necessary, or is a consent banner required?
3. Is the OpenMates legal entity above the Art. 37 threshold for a designated DPO?
4. Are the imprint SVGs current (entity, address, managing director, registry court, VAT ID)?
5. Does the German court / governing-law clause in `terms.governing_law` match the entity's actual forum?
6. Does an Art. 30 "records of processing activities" document exist outside the codebase? If not, the data flows mapped in §3–§4 are the starting point.
7. Does the ProtonMail bridge transmit outbound user data, or is it receive-only?

---

## 13. Files referenced

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
backend/core/api/app/services/payment/{stripe,polar}_service.py
backend/core/api/app/services/email/brevo_provider.py
deployment/dev_server/Caddyfile                   # TLS, HSTS, CSP, access logs
frontend/packages/ui/src/services/db.ts           # IndexedDB schema
frontend/packages/ui/src/utils/cookies.ts         # WS token sessionStorage fallback
frontend/packages/ui/src/services/tracing/setup.ts # Frontend OTel client
frontend/apps/web_app/src/hooks.server.ts         # SvelteKit security headers
shared/docs/privacy_policy.yml                    # Canonical privacy disclosures
frontend/packages/ui/src/i18n/sources/legal/{privacy,terms,imprint}.yml
frontend/packages/ui/src/legal/buildLegalContent.ts
frontend/packages/ui/src/legal/documents/privacy-policy.ts
docs/architecture/compliance/{cookies,browser-storage}.yml  # Compliance inventories
docs/architecture/compliance/top-10-recommendations.md       # Twice-weekly scanner output
```

---

*End of report.*
