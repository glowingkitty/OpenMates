# Unified Notifications And Private Push Payloads

## Goal
OpenMates should have one notification event model that can drive in-app UI,
email, APNs, future Web Push, developer webhooks, and a public SSE stream. Chat
assistant notifications must never expose chat titles or assistant response
content to Apple Push Notification service (APNs), browser push providers, or
developer notification streams unless the content is explicitly encrypted for a
user device.

## Scope
In:
- A backend notification event contract for user notification events.
- Authenticated `GET /v1/notifications` for recent safe notification events.
- Authenticated `GET /v1/notifications/stream` for SSE delivery.
- OpenMates CLI access to list and stream safe notification events.
- A dispatch path for assistant-message notifications that uses the unified
  event contract.
- APNs alert payloads that show only localized/generic safe text by default.
- APNs custom encrypted payload metadata for device-local preview decryption.
- Apple client support for encrypted notification payload registration and
  decryption, including safe fallback when decryption fails.
- Tests proving plaintext assistant responses and chat titles are not sent to
  APNs alert fields or public notification streams.

Out:
- Restoring browser Web Push service worker support.
- Android FCM or UnifiedPush implementation.
- Outgoing developer webhooks with plaintext chat content.
- Server-side storage of decrypted assistant notification previews.
- A Directus schema migration for a persistent notification table in the first
  slice, unless implementation discovery proves persistence is required for
  `GET /v1/notifications`.

## Scenarios

### S-1: Offline assistant response creates safe notification event
Given Alice has a chat named "Private medical plan"
And an assistant completes a response containing private content
And Alice has no active websocket connections
When OpenMates creates the notification event
Then the event type is `chat.assistant_message_received`
And safe text uses localization keys, not chat title or response text
And APNs alert title/body do not contain "Private medical plan" or response text
And the event keeps routing metadata such as `chat_id` for opening the chat.

### S-2: Apple receives generic localized fallback
Given Alice has registered an APNs device
When OpenMates sends an assistant-message APNs notification
Then `aps.alert` contains only generic app/title text and localized fallback body
And `aps.alert` contains no assistant response preview
And `aps.alert` contains no chat title
And tapping or replying still routes to the target chat using safe metadata.

### S-3: Apple can decrypt an optional encrypted preview locally
Given Alice's Apple app has registered a notification encryption public key
And the backend can encrypt a preview to that device key
When APNs delivers a notification with `mutable-content: 1`
Then Apple servers only receive ciphertext for the preview
And the Notification Service Extension decrypts locally
And the displayed notification may show decrypted preview lines on device
And if decryption fails, the notification displays the generic fallback.

### S-4: Developer SSE receives safe events only
Given Alice connects to `/v1/notifications/stream`
When a new assistant-message notification event is created
Then the SSE stream emits a safe event with ID, type, timestamp, safe text keys,
and routing metadata
And the SSE event does not include assistant response content or chat title
And the stream sends heartbeats while idle.

### S-5: Recent notification list is safe and authorized
Given Alice requests `GET /v1/notifications`
When notification events exist for Alice
Then Alice receives only her own notification events
And the payload contains safe fields only by default
And Bob cannot fetch Alice's events.

### S-7: CLI can list and stream notifications
Given Alice has paired the OpenMates CLI
When she runs `openmates settings notifications list --json`
Then the CLI returns recent safe notification events from `/v1/notifications`
And when she runs `openmates settings notifications stream --count 1 --json`
Then the CLI reads one safe SSE notification event and exits.

### S-6: Existing email notification behavior remains compatible
Given Alice has email notifications enabled for AI responses
When an assistant response completes while Alice is offline
Then existing email fallback behavior still works
And the first implementation does not broaden email content beyond the current
email preference and encryption model.

## Acceptance Criteria
- [ ] AC-1: A unified notification event schema exists in backend code and is
  used by the assistant-message offline notification path.
- [ ] AC-2: `GET /v1/notifications` returns authenticated, user-scoped, safe
  recent notification events.
- [ ] AC-3: `GET /v1/notifications/stream` emits SSE events and heartbeats for
  authenticated clients.
- [ ] AC-4: APNs chat-message alert title/body never include chat titles or
  assistant response content.
- [ ] AC-5: APNs chat-message payload includes `mutable-content: 1` when an
  encrypted device payload is present.
- [ ] AC-6: Apple device registration can register notification encryption
  material without storing private keys on the server.
- [ ] AC-7: Apple notification decryption falls back to localized "New message
  received" when encrypted preview data is absent or invalid.
- [ ] AC-8: Automated tests cover safe APNs payload construction and safe SSE
  event serialization.
- [ ] AC-9: Translation sources include the generic notification body and
  generated locale JSON is rebuilt.
- [ ] AC-10: OpenMates CLI exposes safe notification list and SSE stream commands.

## Contracts

API:
- `GET /v1/notifications?limit=50&after=<cursor>` returns recent safe events for
  the authenticated user.
- `GET /v1/notifications/stream` returns `text/event-stream` for authenticated
  clients. Events use `event: notification`, `id: <event_id>`, and JSON `data`.
- `POST /v1/notifications/register-device` continues to register APNs tokens and
  may accept `notification_public_key` plus `encryption_version` for encrypted
  notification payloads.

Data:
- First slice may store short-lived events in Redis for SSE/recent-list support.
- Durable storage can be added later if product requires notification history
  across restarts.
- APNs registration stores public encryption material only. Private keys remain
  in the Apple app Keychain/app group.

UI states:
- Web and Apple show generic safe text for assistant-message notifications when
  no local decrypted preview is available.
- Apple Notification Service Extension may replace the generic text with a
  decrypted preview only on device.
- SSE consumers receive safe fallback text keys and routing metadata only.

Privacy/security:
- No assistant response plaintext or chat title plaintext in APNs alert fields.
- No assistant response plaintext or chat title plaintext in SSE payloads.
- Encrypted APNs preview ciphertext is allowed as custom payload metadata.
- Notification encryption is device-targeted; private keys must not leave the
  user's Apple device.
- Public developer streams are authenticated and user-scoped.

## Test Matrix
| Scenario | Test Type | File | Status |
| --- | --- | --- | --- |
| S-1, S-2 | Pytest/unit | `backend/tests/test_unified_notifications.py` | planned |
| S-3 | Swift/unit or static build | `apple/OpenMates/...` | planned |
| S-4, S-5 | Pytest/API | `backend/tests/test_notifications_api.py` | planned |
| S-6 | Existing tests | `backend/tests/test_webhook_incoming.py` and email task tests | planned |
| S-7 | CLI test | `frontend/packages/openmates-cli/tests/cli.test.ts` | planned |

## Implementation Notes
Existing patterns to reuse:
- `backend/core/api/app/routes/push.py` for APNs registration.
- `backend/core/api/app/services/push_notification_service.py` for APNs send.
- `backend/core/api/app/routes/websockets.py` for offline assistant detection.
- `frontend/packages/ui/src/i18n/sources/notifications.yml` for generic text.
- `apple/OpenMates/Sources/Core/Networking/PushNotificationManager.swift` for
  native notification registration and routing.
- `docs/architecture/android/notifications.md` for provider-agnostic direction.

Likely files touched:
- `backend/core/api/app/routes/notifications.py` — notification list/SSE routes.
- `backend/core/api/app/services/notification_event_service.py` — event model and dispatch.
- `backend/core/api/app/services/push_notification_service.py` — safe/encrypted APNs payloads.
- `backend/core/api/main.py` — include notification routes.
- `backend/core/api/app/routes/push.py` — APNs token + public key registration.
- `apple/OpenMates/Sources/Core/Networking/PushNotificationManager.swift` — key registration.
- `apple/OpenMates/.../NotificationServiceExtension` — decrypt APNs payload.
- `frontend/packages/ui/src/i18n/sources/notifications.yml` — generic text.
- `frontend/packages/openmates-cli/src/client.ts` and `cli.ts` — list/SSE commands.
- `backend/tests/test_unified_notifications.py` — backend privacy assertions.

Risks:
- Notification Service Extension setup may require Xcode project changes that
  are hard to fully verify on Linux.
- Persisting notification history may require Directus schema work; avoid this
  in the first slice unless required.
- Encrypted previews protect against Apple seeing content, but not against the
  OpenMates backend seeing previews if the backend generates them from plaintext.

## Open Questions
- Should encrypted preview generation be enabled by default for Apple devices,
  or gated behind a user preference?
- How long should recent notifications remain available from
  `GET /v1/notifications` before durable storage exists?
