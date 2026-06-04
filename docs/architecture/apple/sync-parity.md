# Apple/Web Sync Parity

Status: Linux static audit  
Created: 2026-06-01  
Scope: startup sync, cold boot recovery, offline extension, sync testability

## Goal

Apple sync must preserve the same user-visible chat state as the web app after login, reconnect, refresh/cold boot, and cross-device updates. Native Apple may additionally persist the last 100 chats for offline availability, but that must not change server-authoritative sync semantics.

## Web Source

- `frontend/apps/web_app/tests/startup-sync-contract.spec.ts`
- `frontend/apps/web_app/tests/chat-sync-empty-indexeddb-recovery.spec.ts`
- `frontend/packages/ui/src/services/websocketService.ts`
- `frontend/packages/ui/src/services/chatSyncServiceHandlersPhasedSync.ts`
- `frontend/packages/ui/src/services/chatSyncServiceHandlersCoreSync.ts`
- `frontend/packages/ui/src/types/chat.ts`

## Apple Source

- `apple/OpenMates/Sources/Core/Networking/WebSocketManager.swift`
- `apple/OpenMates/Sources/Core/Networking/SyncManager.swift`
- `apple/OpenMates/Sources/Core/Persistence/ChatStore.swift`
- `apple/OpenMates/Sources/Core/Persistence/OfflineStore.swift`
- `apple/OpenMates/Sources/Core/Persistence/OfflineSyncBridge.swift`
- `apple/OpenMates/Sources/Core/Models/ChatModels.swift`

## Web Contract From Specs

- Startup sync sends `phased_sync_request`.
- Phase 1b full-content sync is capped to 10 parent chats.
- Phase 2 is metadata-only and must not include `embeds`, `embed_keys`, `code_run_outputs`, `messages`, or `compression_checkpoints`.
- Startup login must not receive `background_message_sync` for chats 11-100.
- Opening a metadata-only chat sends `request_chat_content_batch` to hydrate older content on demand.
- Empty local IndexedDB plus cold server cache must keep sync pending instead of dispatching a synthetic completion and hiding the syncing indicator.
- Partial local IndexedDB schemas must be healed before authenticated sync starts.

## Confirmed Apple Behavior From Source

- `WebSocketManager` sends `phased_sync_request` with `phase: all`, `client_chat_versions`, `client_chat_ids`, `client_suggestions_count`, and `client_embed_ids`.
- `WebSocketManager` routes these sync event names to `.wsSyncEvent`: `initial_sync_response`, `initial_sync_error`, `phase_1_last_chat_ready`, `phase_1b_chat_content_ready`, `phase_2_last_20_chats_ready`, `phase_3_last_100_chats_ready`, `background_message_sync`, `cache_primed`, `cache_status_response`, `load_more_chats_response`, `sync_metadata_chats_response`, `phased_sync_complete`, `sync_status_response`, `offline_sync_complete`, and `chat_content_batch_response`.
- `SyncManager` models phase 1, phase 1 content, phase 2, phase 3, metadata sync, and completion.
- `ChatStore.makeSyncClientState` includes chat versions, local chat IDs, suggestions count, and embed IDs.
- `OfflineSyncBridge.loadFromDisk` loads persisted chats and eagerly loads messages/embeds for the first 5 chats before network sync.
- `OfflineSyncBridge` has an Apple-native offline prefetch path via `/v1/sync/offline-prefetch`, starting at cursor 10 in chunks of 3, gated by network cost, low power mode, thermal state, and a persisted-message cap.
- `OfflineStore` persists chats, messages, embeds, embed keys, and pending offline actions.

## Likely Gaps To Verify Or Fix

- Apple `SyncManager.startSync` sends `phased_sync_request` with `data: ["phase": "all"]`, while `WebSocketManager.requestPhasedSync` sends the richer `payload` shape. Confirm only one path is used in production and remove or align the simpler path if still reachable.
- `SyncManager.handlePhase2` treats phase 2 chats as regular `Chat` upserts. That is acceptable for metadata-only records, but Apple must avoid assuming messages/embeds exist until content hydration.
- `SyncManager` sets sync complete after a 30-second timeout even if still syncing. This is the exact failure pattern the web regression spec guards against. Apple needs a cold-cache/empty-local equivalent: do not hide syncing or finalize empty state when the server reports chats but phase payloads are blocked/delayed.
- Apple source routes `chat_content_batch_response`, but this static pass did not find the code path that sends `request_chat_content_batch` when opening a metadata-only chat. Verify and implement if missing.
- Apple has no direct equivalent to IndexedDB schema healing. SwiftData schema migration behavior needs a Mac/device verification checklist and possibly explicit recovery for missing/corrupt stores.
- Apple has no current `.accessibilityIdentifier("syncing-indicator")`; UI tests cannot prove sync pending/completion parity yet.

## Intentional Native Difference

- Apple may persist more data locally for native offline use, including the last 100 chats and optional content prefetch. This is allowed only if it remains additive: server sync still controls current chat metadata, message versions, unread state, keys, and deletes.

## Testability IDs Needed

- `syncing-indicator`
- `chat-history`
- `chat-item-wrapper` already exists
- `message-editor`
- `message-user`
- `message-assistant`
- `offline-banner`
- `connection-status`

## Mac Verification Checklist

- Login with a seeded account and confirm the Apple chat list matches web for recent chats.
- Confirm the sync indicator appears while sync is active and remains visible if server chat count is known but phase data does not arrive.
- Confirm phase 1b loads full content for at most 10 parent chats.
- Confirm metadata-only chats do not show stale/empty messages as final state.
- Open a metadata-only chat and confirm a content hydration request is sent and messages appear.
- Clear local Apple SwiftData/offline store, relaunch, and confirm server chats recover.
- Disconnect network, send or queue supported actions, reconnect, and confirm replay or explicit failure.
- Verify Apple-native offline prefetch does not overwrite newer server versions or resurrect deleted/hidden chats.

## First Implementation Tasks

- Add `syncing-indicator` and related stable identifiers to Apple UI.
- Audit and align all `phased_sync_request` send paths to the rich client-state payload.
- Add/verify metadata-only chat hydration on chat open.
- Replace timeout-based completion with a pending state when server chat count indicates data still exists.
- Add a SwiftData corruption/migration recovery strategy or documented manual reset behavior.
