---
status: active
last_verified: 2026-03-24
key_files:
  - frontend/packages/ui/src/components/settings/developers/SettingsApiKeys.svelte
  - frontend/packages/ui/src/components/settings/developers/SettingsDevices.svelte
  - frontend/packages/ui/src/components/settings/developers/SettingsWebhooks.svelte
  - backend/core/api/app/routes/settings.py
  - backend/core/api/app/routers/webhooks.py
  - backend/core/api/app/utils/api_key_auth.py
  - backend/core/api/app/utils/webhook_auth.py
  - backend/core/api/app/services/directus/api_key_device_methods.py
---

# Developer Settings

> API key management, device authorization, and incoming webhooks for programmatic access — all zero-knowledge with client-side key generation and encrypted device data.

## Why This Exists

- Users need secure programmatic access from scripts, CI/CD, and CLI tools
- Device confirmation ensures even a compromised API key cannot be used from an unauthorized device
- Incoming webhooks let external services trigger chats without exposing API keys
- Zero-knowledge: server stores only SHA-256 hashes of keys, never plaintext

## How It Works

### API Keys

Settings > Developers > API Keys ([SettingsApiKeys.svelte](../../frontend/packages/ui/src/components/settings/developers/SettingsApiKeys.svelte))

- **Client-side generation:** Format `sk-api-` + 32 random alphanumeric chars (CSPRNG)
- **Zero-knowledge storage:** Only `SHA256(api_key)` stored server-side. Key shown once, never retrievable
- **Key wrapping:** Each API key can decrypt a wrapped copy of the user's master key, enabling access to encrypted data
- **Max 5 keys per user** — enforced in [settings.py](../../backend/core/api/app/routes/settings.py)
- Auth: `Authorization: Bearer sk-api-...` header → validated by [api_key_auth.py](../../backend/core/api/app/utils/api_key_auth.py)
- Cache-first lookup (5-min TTL) with Directus fallback

**Endpoints:** `GET/POST /v1/settings/api-keys`, `DELETE /v1/settings/api-keys/{id}`

### Device Authorization

Settings > Developers > Devices ([SettingsDevices.svelte](../../frontend/packages/ui/src/components/settings/developers/SettingsDevices.svelte))

When a new device attempts API access:
1. [api_key_auth.py](../../backend/core/api/app/utils/api_key_auth.py) generates device hash: `SHA256(IP:user_id)` (REST) or `SHA256(machine_id:user_id)` (CLI/npm/pip)
2. New device → request **blocked** (`DeviceNotApprovedError`, HTTP 403)
3. Background task notifies user via WebSocket + security email (always sent, independent of notification preferences)
4. User approves in Devices settings
5. Subsequent requests from that device pass automatically

**GDPR-compliant storage:** Only anonymized IP (first two octets + `xxx`), country, region, city — all encrypted with user's vault key. Full IPs never stored.

**Endpoints:** `GET /v1/settings/api-key-devices`, `POST .../approve`, `POST .../revoke`

### Incoming Webhooks

Settings > Developers > Webhooks ([SettingsWebhooks.svelte](../../frontend/packages/ui/src/components/settings/developers/SettingsWebhooks.svelte))

- **Key format:** `wh-` + 64 random alphanumeric chars
- **Max 10 webhooks per user**
- **Permissions:** `["trigger_chat"]` (extensible)
- **Optional confirmation:** `require_confirmation` flag makes webhook chats wait for user approval in web UI

**Incoming webhook flow** (`POST /v1/webhooks/incoming` in [webhooks.py](../../backend/core/api/app/routers/webhooks.py)):
1. Validate webhook key (format, hash lookup, expiry, active, permissions, rate limit)
2. Encrypt message with user's vault key
3. Store in pending cache (24h TTL)
4. If user online: broadcast via WebSocket. If offline: queue email notification
5. If `require_confirmation`: mark as pending until user confirms in web UI

**Security layers in [webhook_auth.py](../../backend/core/api/app/utils/webhook_auth.py):**
- Per-key sliding window rate limit: 30 req/3600s
- Idempotency via `X-Request-Id` header (5-min dedup window, 409 on duplicate)
- Direction check (only "incoming" accepted)
- Permission check against webhook's permission list

**CRUD endpoints:** `GET/POST /v1/webhooks`, `PATCH/DELETE /v1/webhooks/{id}`

### Access Methods

| Method | Device ID | Auth | Used by |
|--------|----------|------|---------|
| REST API | `SHA256(IP:user_id)` | API key in Bearer header | Scripts, CI/CD |
| pip/npm | `SHA256(machine_id:user_id)` | API key in config | Python/Node packages |
| CLI | `SHA256(machine_id:user_id)` | API key or magic link | `openmates` CLI |
| Webhook | N/A (key-based only) | Webhook key in Bearer header | External services |

## Edge Cases

- **Cache down:** API key auth falls back to Directus. Webhook rate limiting fails open (availability over security)
- **Expired key:** HTTP 401 with clear error message
- **Device not approved:** HTTP 403 with deep-link to `developers/devices` in notification
- **Webhook replay:** Idempotency key prevents duplicate chat creation (409 Conflict)
- **User offline during webhook:** Email notification queued, message stored in pending cache (24h TTL)

## Related Docs

- [CLI Package](../apps/cli-package.md) — CLI architecture using API keys
- [REST API](../apps/rest-api.md) — API endpoints accessible via API keys
- [Device Sessions](../data/device-sessions.md) — device management
- [Security](../core/security.md) — zero-knowledge architecture
