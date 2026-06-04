# Apple/Web Notifications Parity

Status: Linux static audit  
Created: 2026-06-01  
Scope: push notifications, in-app banners, unread counts, offline/webhook/system notifications

## Goal

Apple notifications should preserve the same user-visible semantics as web while using native APNs and badge APIs where appropriate. In-app notifications, unread counts, offline banners, webhook pending banners, and background chat completion should stay consistent across platforms.

## Web Source

- `frontend/packages/ui/src/stores/notificationStore.ts`
- `frontend/packages/ui/src/stores/unreadMessagesStore.ts`
- `frontend/packages/ui/src/services/chatSyncServiceHandlersAI.ts`
- `frontend/packages/ui/src/services/chatSyncServiceHandlersPhasedSync.ts`
- `frontend/packages/ui/src/components/Notification.svelte`
- `frontend/packages/ui/src/components/PushNotificationBanner.svelte`
- `frontend/packages/ui/src/components/OfflineBanner.svelte`
- `frontend/packages/ui/src/components/WebhookPendingBanner.svelte`
- Specs with `notification`, `notification-dismiss`, `typing-indicator`, `message-assistant`, and unread/chat assertions

## Apple Source

- `apple/OpenMates/Sources/Core/Networking/PushNotificationManager.swift`
- `apple/OpenMates/Sources/Core/Services/UnreadMessagesStore.swift`
- `apple/OpenMates/Sources/Shared/Components/NotificationBanners.swift`
- `apple/OpenMates/Sources/Core/Networking/WebSocketManager.swift`
- `apple/OpenMates/Sources/Core/Persistence/OfflineSyncBridge.swift`

## Confirmed Apple Behavior From Source

- `PushNotificationManager` requests alert, badge, and sound permissions.
- APNs device tokens are registered via `/v1/notifications/register-device` with platform `apns`.
- Native chat message notifications support reply and open-chat actions.
- Tapping or replying to a notification sets pending chat/reply state and clears the badge.
- `UnreadMessagesStore` tracks per-chat unread counts, total unread, and updates the iOS badge.
- `NotificationBanners.swift` contains SwiftUI equivalents for push notification, webhook pending, and offline banners.
- `OfflineSyncBridge` tracks network status via `NWPathMonitor` and marks `OfflineStore` offline/online.

## Likely Gaps To Verify Or Fix

- `Chat` model does not expose `unread_count`, while web phased sync explicitly populates `unreadMessagesStore` from server-authoritative unread counts. Apple `UnreadMessagesStore.setUnread` exists, but static audit did not prove sync events call it.
- `OfflineBanner` has hardcoded English text (`messages will sync when reconnected`) and hardcoded accessibility label. This violates Apple localization rules and should use `AppStrings`/i18n.
- `PushNotificationBanner` and `WebhookPendingBanner` use accessible labels but no stable `.accessibilityIdentifier(...)`, so parity tests cannot target them yet.
- Web distinguishes server restarting and generic offline states. Apple static audit only confirmed offline status, not server restarting banner parity.
- Web AI handlers show background chat completion notifications and unread increments. Apple needs a source-level audit tying streaming/background events to `UnreadMessagesStore.incrementUnread` and `PushNotificationBanner`/native notification display.
- `willPresent` currently returns banner/sound/badge even when app is foregrounded. Confirm this is intended and does not duplicate custom in-app banners.

## Testability IDs Needed

- `notification`
- `notification-dismiss`
- `push-notification-banner`
- `webhook-pending-banner`
- `offline-banner`
- `unread-badge`
- `chat-item-wrapper` already exists

## Mac Verification Checklist

- Receive an assistant response in a background chat and verify unread count increments.
- Open the chat and verify unread clears and badge updates.
- Trigger an APNs/local notification, tap it, and verify the app opens the target chat.
- Reply from a notification and verify the message sends into the target chat.
- Toggle network offline/online and verify offline banner appears/disappears and queued actions replay.
- Trigger webhook pending state and verify the native banner matches web semantics.
- Confirm no duplicate notifications appear when the app is foregrounded.

## First Implementation Tasks

- Add `unread_count` support to Apple chat sync model or wire server unread events into `UnreadMessagesStore`.
- Localize `OfflineBanner` strings.
- Add stable identifiers to notification/banner views.
- Audit foreground notification deduplication between native notifications and in-app banners.
