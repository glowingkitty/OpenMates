# Incoming Webhooks

External services (cron jobs, GitHub Actions, Zapier, monitoring tools) can
POST to `/v1/webhooks/incoming` with a `wh-…` bearer key and a single message
to spawn a new chat in the user's account. The message becomes a `role: "system"`
opening turn — exactly like a scheduled reminder firing — and the AI assistant
responds automatically and server-side, regardless of whether any device is
currently online.

This document describes the production design after the unification with the
reminder pipeline. The reminder code in `backend/apps/reminder/tasks.py` is the
canonical reference; the webhook flow is intentionally kept structurally
identical so a single mental model covers both.

## Components

| Layer    | File                                                                                | Role                                                                              |
| -------- | ----------------------------------------------------------------------------------- | --------------------------------------------------------------------------------- |
| Backend  | `backend/core/api/app/routers/webhooks.py`                                          | CRUD endpoints, `POST /incoming`, AI dispatch helper                              |
| Backend  | `backend/core/api/app/utils/webhook_auth.py`                                        | `verify_webhook_key` dependency: hash lookup, rate limit, idempotency, expiry     |
| Backend  | `backend/core/api/app/tasks/email_tasks/webhook_chat_notification_email_task.py`    | Offline notification email                                                        |
| Frontend | `frontend/packages/ui/src/services/chatSyncServiceHandlersWebhooks.ts`              | WebSocket handler for `webhook_chat`: encrypts with chat key, persists, refreshes |
| Frontend | `frontend/packages/ui/src/services/chatSyncService.ts`                              | Registers the `webhook_chat` handler alongside `reminder_fired`                   |
| Frontend | `frontend/packages/ui/src/components/settings/developers/SettingsWebhooks.svelte`   | Settings UI to create / list / delete webhook keys                                |
| Frontend | `frontend/packages/ui/src/components/settings/notifications/SettingsChatNotifications.svelte` | `webhookChats` email-notification toggle                                          |

## CRUD model

Webhook keys live in the Directus `webhook_keys` collection. They follow the
same zero-knowledge pattern as API keys (`SettingsApiKeys.svelte`):

- The plaintext `wh-…` key is generated client-side and shown to the user
  exactly once.
- Only the SHA-256 hash of the key is stored server-side.
- The webhook name and key prefix are encrypted with the user's master key
  before they leave the browser. The server cannot decrypt them — they exist
  only so the UI can render a friendly name in the settings list.
- Per-user limit: 10 keys (`MAX_WEBHOOKS_PER_USER`).
- Each key has an `is_active` flag, optional `expires_at`, a `permissions`
  array currently fixed to `["trigger_chat"]`, and a `require_confirmation`
  flag.

## Authentication (`POST /v1/webhooks/incoming`)

`webhook_auth.WebhookAuthService.authenticate_webhook_key` performs:

1. Format check (`wh-` prefix).
2. SHA-256 hash → cache-first lookup → Directus fallback.
3. Active flag + `expires_at` enforcement.
4. Direction check (only `incoming` keys may call `/incoming`).
5. Permission check (`trigger_chat` required).
6. Per-key sliding-window rate limit (30 requests / hour) via Redis.
7. Optional idempotency: when the caller passes `X-Request-Id` (or
   `Idempotency-Key`), duplicates within a window are rejected with HTTP 409.
8. Best-effort `last_used_at` update.

Failures map to HTTP 401 (bad/missing/expired key), 403 (deactivated, wrong
direction, missing permission), 409 (duplicate request id), or 429 (rate
limit, with `Retry-After` header).

## Incoming flow (`webhook_incoming`)

The endpoint mirrors the reminder firing path step-by-step. The aim is that
the *only* difference between "a reminder fires" and "a webhook arrives" is
which event opens the system message — everything downstream is shared.

```
external service ──POST──▶ /v1/webhooks/incoming
                              │
                              ├─ verify_webhook_key (auth + rate limit + dedupe)
                              │
                              ├─ pre-create chat row in Directus (minimal metadata)
                              │
                              ├─ vault-encrypt copy → 24h Redis pending cache
                              │     (offline safety net only)
                              │
                              ├─ if user online:
                              │     manager.broadcast_to_user("webhook_chat", {
                              │       chat_id, message_id,
                              │       content: <PLAINTEXT>,
                              │       status, source: "webhook",
                              │       webhook_id, fired_at
                              │     })
                              │
                              │  if user offline:
                              │     queue webhook_chat_notification_email_task
                              │
                              └─ if not require_confirmation:
                                    _dispatch_webhook_ai_request()
                                    └─ get_global_registry().dispatch_skill("ai", "ask", …)
```

### Why plaintext over the WebSocket?

Earlier iterations of this code vault-encrypted the message before broadcasting
and forced the client to call a `/v1/webhooks/decrypt-pending` endpoint to
recover the plaintext. That added a round-trip and introduced a vault-key /
chat-key mismatch race that produced "Content decryption failed" errors. It
also diverged from the reminder pattern, which already sends plaintext over the
same WebSocket without issue.

The WebSocket channel is already protected by:

- TLS to the edge.
- A session-bound JWT validated on every connection.
- Per-user routing — `manager.broadcast_to_user(..., user_id=…)` only writes to
  sockets owned by that user.

Vault encryption on top of all of that adds nothing the chat-key encryption
performed by the frontend handler doesn't already cover. The vault-encrypted
copy in the 24h pending cache exists *only* so the system can recover the
chat for a user that was completely offline at trigger time.

## Frontend handler (`chatSyncServiceHandlersWebhooks.ts`)

`handleWebhookChatImpl` receives the `webhook_chat` event and runs through:

1. Dedupe via `chatDB.getMessage(message_id)`.
2. `chatKeyManager.createKeyForNewChat(chat_id)` — single source of truth for
   chat-key generation.
3. Encrypt the title and content with the new chat key
   (`encryptWithChatKey`).
4. Persist the new chat row + the system message to IndexedDB.
5. Send `chat_system_message_added` over the WebSocket so the backend
   `system_message_handler` queues the persistence task that writes the
   chat-key-encrypted system message to Directus.
6. Dispatch a `chatUpdated` CustomEvent so the active-chat UI and sidebar
   refresh in place without a full IndexedDB reload.
7. Show an in-app toast notification.

The AI assistant response then arrives through the normal AI streaming
events — no special handling required.

## `require_confirmation` (approval gate)

Setting `require_confirmation=true` on a webhook key keeps the chat in a
`pending_confirmation` state and **skips the AI dispatch**. The system message
is still created and visible. The full approval UI (banner + approve / reject
buttons + corresponding backend transition endpoint) is intentionally a
follow-up; until then `require_confirmation` essentially means "create the
chat but don't talk to the LLM until the user manually replies in the chat".

## Offline path

When `manager.is_user_active(user_id)` is false at request time:

1. The vault-encrypted pending record sits in Redis under
   `webhook_pending_chat:{user_id}:{chat_id}` for 24 hours.
2. `webhook_chat_notification_email_task` is enqueued, gated on
   `email_notifications_enabled` and `email_notification_preferences.webhookChats`
   (default `true`).
3. The AI ask-skill still runs server-side and persists the assistant response
   to Directus the same way it persists every other AI response.

When the user reconnects, the normal phased sync surfaces the chat row and
both messages (system + assistant) from Directus. The user comes back to a
fully-resolved conversation.

## Tests

| Test                                                                              | Coverage                                                                          |
| --------------------------------------------------------------------------------- | --------------------------------------------------------------------------------- |
| `backend/tests/test_webhook_auth.py`                                              | Auth service unit tests (key format, lookup, expiry, rate limit, dedupe)          |
| `backend/tests/test_webhook_incoming.py`                                          | Incoming endpoint integration: pre-create, plaintext WS broadcast, AI dispatch, offline email branch, `require_confirmation`, encryption failure |
| `frontend/apps/web_app/tests/webhook-incoming-chat.spec.ts`                       | E2E: create key in UI, POST to /incoming, new chat appears, system + assistant messages render, cleanup |
