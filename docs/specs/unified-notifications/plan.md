# Plan: Unified Notifications And Private Push Payloads

Spec: `docs/specs/unified-notifications/spec.md`

## Existing Patterns
- `backend/core/api/app/routes/push.py` — existing APNs token registration route.
- `backend/core/api/app/services/push_notification_service.py` — existing APNs send path and safe generic alert body.
- `backend/core/api/app/routes/websockets.py` — existing offline assistant response detection and push/email fallback trigger.
- `backend/core/api/app/tasks/push_notification_task.py` — async push dispatch task.
- `backend/core/api/app/services/cache.py` — Redis-backed short-lived state and pub/sub primitives.
- `frontend/packages/ui/src/i18n/sources/notifications.yml` — source for generic notification translation keys.
- `apple/OpenMates/Sources/Core/Networking/PushNotificationManager.swift` — Apple APNs registration and notification action routing.
- `docs/architecture/android/notifications.md` — provider-agnostic push direction and minimal encrypted payload principle.

## Architecture
Build a provider-agnostic notification event layer without introducing a Directus
migration in the first slice.

Backend boundaries:
- `NotificationEventService` owns safe event creation, Redis retention, and SSE publish.
- `push_notification_service` remains a channel adapter for APNs/Web Push delivery.
- `websockets.py` delegates assistant-message notification creation to the event service instead of constructing channel payloads directly where practical.
- `/v1/notifications` routes expose safe recent events and an authenticated SSE stream.

Apple boundaries:
- `PushNotificationManager` registers the APNs token and a notification encryption public key.
- A Notification Service Extension decrypts optional encrypted payload data locally and falls back to localized safe text.
- The backend never stores Apple notification private keys.

Privacy boundary:
- Safe fields can leave OpenMates through APNs/SSE.
- Assistant content and chat titles can leave only as ciphertext encrypted to a device public key.
- The first backend slice may encrypt a server-generated preview because the AI pipeline already handles response plaintext; this protects against Apple/push providers, not against the OpenMates server.

## Data Flow
1. Assistant finishes response for chat `<CHAT_ID>` while user `<USER_ID>` is offline.
2. `websockets.py` calls `NotificationEventService.create_chat_assistant_message_event(...)` with routing metadata and optional preview plaintext.
3. The service creates a safe event:
   - `type = "chat.assistant_message_received"`
   - `safe_title_key = "apps.openmates"`
   - `safe_body_key = "notifications.chat_message.new_message_received"`
   - `metadata = {"chat_id": "<CHAT_ID>", "has_encrypted_preview": true|false}`
4. The event is cached in Redis and published to a per-user notification channel.
5. `/v1/notifications/stream` subscribers receive only the safe event JSON.
6. APNs channel sends:
   - `aps.alert.title` as generic app name or localized key
   - `aps.alert.body` as generic localized safe body
   - `aps.mutable-content = 1` only if encrypted preview exists
   - custom ciphertext under `encrypted_notification`
7. Apple Notification Service Extension decrypts custom ciphertext on device and replaces visible text. If unavailable or invalid, it leaves the safe fallback.

## API Impact
Routes:
- `GET /v1/notifications?limit=50` returns safe recent events for `current_user`.
- `GET /v1/notifications/stream` returns authenticated `text/event-stream` with heartbeats.
- `POST /v1/notifications/register-device` accepts optional encryption material:
  - `notification_public_key: str | null`
  - `encryption_version: str | null`

No public API returns assistant response content or chat titles in notification payloads.

CLI:
- `openmates settings notifications list --limit 50 --json` calls `GET /v1/notifications`.
- `openmates settings notifications stream --count 1 --json` consumes SSE from `GET /v1/notifications/stream`.

## Data Impact
First slice uses Redis only:
- Recent event list key: `notifications:recent:{user_id}`
- SSE pub/sub channel: `notifications:stream:{user_id}`
- Event retention: short TTL, e.g. 7 days or bounded list length.

No Directus migration in first slice. Add durable storage later if notification history must survive Redis flush/restart.

## UI Impact
Web:
- No new UI required for first slice.
- Existing in-app notification store remains local UI state for now.

CLI:
- Existing notification settings command group gains safe list/stream commands.

Apple:
- Register notification public key with backend.
- Add Notification Service Extension target/source for local decryption.
- Local fallback remains `AppStrings.newMessageReceived`.

## Privacy And Security
- Authenticate both notification routes with `get_current_user`.
- SSE only subscribes to the authenticated user's Redis channel.
- Serialize notification events through an allowlisted safe schema.
- Do not log plaintext previews, chat titles, ciphertext, APNs tokens, or public keys beyond short prefixes.
- APNs alert fields must be built from safe keys/constants only.

## Affected Files
- `backend/core/api/app/services/notification_event_service.py` — event schema, Redis storage, pub/sub, safe serialization.
- `backend/core/api/app/routes/notifications.py` — list and SSE routes.
- `backend/core/api/main.py` — route include.
- `backend/core/api/app/routes/push.py` — APNs token registration with encryption public key.
- `backend/core/api/app/services/push_notification_service.py` — encrypted APNs custom payload and `mutable-content`.
- `backend/core/api/app/tasks/push_notification_task.py` — pass encrypted notification payload fields.
- `backend/core/api/app/routes/websockets.py` — use event service for assistant-message notification dispatch.
- `backend/tests/test_unified_notifications.py` — safe event and APNs privacy tests.
- `backend/tests/test_notifications_api.py` — list/SSE API tests.
- `apple/OpenMates/Sources/Core/Networking/PushNotificationManager.swift` — key generation/registration.
- `apple/OpenMates/.../NotificationServiceExtension` — payload decryption.
- `frontend/packages/ui/src/i18n/sources/notifications.yml` — generic fallback text if missing/changed.
- `frontend/packages/openmates-cli/src/http.ts` — SSE transport parser.
- `frontend/packages/openmates-cli/src/client.ts` — notifications list/stream methods.
- `frontend/packages/openmates-cli/src/cli.ts` — CLI commands.

## Migration And Rollout
- No migration for first slice.
- Backward-compatible APNs registration: devices without public keys still receive generic safe notifications.
- Feature flag optional: `NOTIFICATION_ENCRYPTED_APNS_PREVIEW_ENABLED=false` until Apple extension is verified.
- SSE route can ship before developer UI/documentation because it is authenticated and safe.

## Observability
- Log event creation with user/chat prefixes only.
- Log SSE connect/disconnect counts, not event payload details.
- Log APNs encrypted payload presence as boolean only.
- Add warnings for APNs devices missing encryption public key when encrypted preview is requested.

## Verification Strategy
- Backend unit/API tests:
  - `python3 -m pytest backend/tests/test_unified_notifications.py backend/tests/test_notifications_api.py`
- Backend compile/import smoke:
  - `python3 -m py_compile backend/core/api/app/services/notification_event_service.py backend/core/api/app/routes/notifications.py backend/core/api/app/services/push_notification_service.py`
- Translation rebuild if i18n sources change:
  - `cd frontend/packages/ui && npm run build:translations`
- CLI help/static tests through the repo test dispatcher when needed.
- Apple build if Xcode tooling is available; otherwise static source checks on Linux.

## First Slice
Implement backend safe notification events, authenticated recent-list/SSE routes,
CLI list/stream access, safe APNs payload construction with optional encrypted
custom payload fields, and tests proving no chat title or assistant response
plaintext appears in APNs alert or SSE payloads. Apple Notification Service
Extension can follow as a second slice because it requires Xcode project/target
validation.

## Open Questions
- Whether encrypted preview display should be enabled by default or guarded by a user preference after Apple extension verification.
- Whether Redis-only recent events are enough for developer integrations or if durable Directus-backed notification history is needed.
