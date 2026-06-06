# Tasks: Unified Notifications And Private Push Payloads

Spec: `docs/specs/unified-notifications/spec.md`
Plan: `docs/specs/unified-notifications/plan.md`

- [ ] T-1: Add backend notification event service with safe schema.
  Covers: S-1, S-4, S-5, AC-1
  Areas: `backend/core/api/app/services/notification_event_service.py`, `backend/tests/test_unified_notifications.py`
  Verify: `python3 -m pytest backend/tests/test_unified_notifications.py`
  Independently deployable: yes, service can be unused until routes/dispatch are wired.

- [ ] T-2: Expose authenticated notification list and SSE stream.
  Covers: S-4, S-5, AC-2, AC-3
  Areas: `backend/core/api/app/routes/notifications.py`, `backend/core/api/main.py`, `backend/tests/test_notifications_api.py`
  Verify: `python3 -m pytest backend/tests/test_notifications_api.py`
  Independently deployable: yes, safe API only.

- [ ] T-3: Wire assistant-message offline path to notification events and safe APNs payloads.
  Covers: S-1, S-2, S-6, AC-1, AC-4, AC-8
  Areas: `backend/core/api/app/routes/websockets.py`, `backend/core/api/app/tasks/push_notification_task.py`, `backend/core/api/app/services/push_notification_service.py`, `backend/tests/test_unified_notifications.py`
  Verify: `python3 -m pytest backend/tests/test_unified_notifications.py`
  Independently deployable: yes, preserves existing email fallback behavior.

- [ ] T-4: Add APNs encryption public key registration and encrypted custom payload construction.
  Covers: S-2, S-3, AC-5, AC-6, AC-8
  Areas: `backend/core/api/app/routes/push.py`, `backend/core/api/app/services/push_notification_service.py`, `backend/tests/test_unified_notifications.py`
  Verify: `python3 -m pytest backend/tests/test_unified_notifications.py`
  Independently deployable: yes, devices without keys fall back to generic safe payload.

- [ ] T-5: Add Apple notification encryption key registration and service-extension decryption.
  Covers: S-2, S-3, AC-6, AC-7
  Areas: `apple/OpenMates/Sources/Core/Networking/PushNotificationManager.swift`, Apple Notification Service Extension target/source, `apple/OpenMates/Sources/Core/I18n/AppStrings.swift`
  Verify: Apple build if Xcode tooling is available; otherwise static grep plus source review on Linux.
  Independently deployable: conditional; deploy after Xcode project verification where possible.

- [ ] T-6: Add OpenMates CLI notification list and stream commands.
  Covers: S-7, AC-10
  Areas: `frontend/packages/openmates-cli/src/http.ts`, `frontend/packages/openmates-cli/src/client.ts`, `frontend/packages/openmates-cli/src/cli.ts`, `frontend/packages/openmates-cli/tests/cli.test.ts`
  Verify: CLI help/static tests through the repo test dispatcher when applicable.
  Independently deployable: yes, safe read-only API access.

- [ ] T-7: Rebuild translations and verify full spec.
  Covers: S-2, S-3, AC-7, AC-9
  Areas: `frontend/packages/ui/src/i18n/sources/notifications.yml`, generated locale JSON if source changes
  Verify: `cd frontend/packages/ui && npm run build:translations`; `verify-spec docs/specs/unified-notifications/spec.md`
  Independently deployable: yes, if paired with the related code slice.
