# A4 design: chat list and chat window of the Apple app from the client core

Read-only analysis of 2026-11-11. Swift paths are under `apple/OpenMates/Sources/`.

## Data flow today

**Session.** `Features/Auth/ViewModels/AuthManager.swift`: `checkSession()` restores and validates; logins end in `handleSuccessfulLogin`, `completePasskeyLogin` or `completePairLogin`. Swift holds the master key (Keychain), cookies (URLSession store), ws token and session id. `.authenticated` triggers `MainAppView.bootstrapAuthenticatedSession()`.

**Chat list.**
- Disk: `AppSessionCoordinator.prepareAuthenticatedRuntime` → `OfflineSyncBridge.loadFromDisk` → `OfflineStore.loadStartupChats` (SwiftData) → `ChatStore.chats`.
- Network: `MainAppView.connectWebSocket()` → `WebSocketManager` posts `.wsSyncEvent` → `handleSyncEvent` → `processSyncEvent`; phases 1 to 3 call `upsertSyncedChats`, `decryptAndUpsertChatMetadata`, `loadChatKeys`, `ChatStore.upsertChats` (persists through `OfflineSyncBridge`). REST fallback: `loadInitialData`, `loadMoreChatMetadata`.
- View: `ChatStore.chats` → `ChatSidebarDisplayPolicy` → `Shared/Components/ChatSidebarContent.swift` → `ChatListRow.swift`. Other readers: `ChatSearchView`, `DraftSyncCoordinator`, `WebSocketManager.makeSyncClientState`, `SettingsSharedView`.

**Chat window.** `ChatView` → `ChatViewModel.loadChat`; cached path `loadSyncedChat` → `OfflineStore.loadLatestMessageWindow` → `decryptMessagesForDisplay`; cold path REST plus `fetchRemoteWindow` → `ChatMessageWindowClient.fetch`. Live: `phase_1b_chat_content_ready` and `background_message_sync` → `ChatStore.applySyncedContent` → `ChatViewModel.applySynced`. `Core/Networking/SyncManager.swift` is dead code.

## Field gaps in the core records

**Chat row** (`ChatListRowRecord` has id, titles, summary, category, status, created/updated, messagesV, unreadCount, pinned, archived, hasDraft, footer). Missing for the Swift views: icon; parent id and sub-chat settings; team id and shared-by-others; last message / last edited timestamps (the core delivers display order, Swift must stop sorting); last visible message id; private and hidden flags; app id, focus id, budget; draft preview text and versions; total count and has-more for the list.

**Message** (`MessageViewRecord` has id, role, status, content, sender, thinking, embeds, sendState). Missing: createdAt/updatedAt; model name, category, app id; PII mappings; thinking token count and signature; server and user message ids; queue fields; newer-messages flag and anchor windows. The core already holds most of these in `SavedChatMessageMetadata` (`client/saved_chat_read.rs`); `view_model/convert.rs` drops them. The web app consumes them (`frontend/packages/ui/src/services/rustCore/savedReadProtocol.ts`).

## Seams copied from the web app

- A mapper from core rows to the existing UI type so views stay unchanged; it refuses shapes it cannot represent.
- A typed refusal ("the core does not own this chat shape") is the only fallback; every other failure is surfaced.
- Cache first, background reconcile second; the core decides list order.

## Login

Owner decision (2026-11-11): the Apple app is not built or shipped at present, so there is no runtime switch, no twin phase and no import of Swift-held sessions. Each lane replaces the Swift code directly and deletes it in the same deploy.

The core performs login and owns the session (cookies, ws token, master key). `AuthManager` becomes a thin state holder over `ViewModelCore` (`loginPassword`, pair login, `start`, `logout`). Login variants not yet exposed: backup code and recovery key already exist in the core as sans-IO code used by the web shell (`web_auth.rs`, `web_auth_recovery.rs`) and are reused, not rewritten; passkey is the only variant missing in the core (the system ceremony stays in Swift, the core runs the rest).

## Lanes

No switch. Tests inject an in-memory credential store (no Keychain entitlement on the unsigned CI simulator).

0. **Core and binding prerequisites (Rust).** Extend the row and message records with the fields above; add a debug-only fixture seeding function for Swift tests; pair-login cancel fix.
1. **Core session lifecycle, no UI change.** New `Core/CoreBridge/CoreSession.swift` (owns `ViewModelCore`, credential store, relay, published state), created at app start in `App/OpenMatesApp.swift`; hooks in `AuthManager` (login, checkSession, logout). Timing lines next to the Swift phases. Tests: `CoreSessionTests`.
2. **Chat list from the core.** Sidebar source becomes `CoreSession.rows` through `CoreBridge/CoreChatRowMapper.swift`; personal chats first. Delete in the same deploy: the phase cases of `processSyncEvent`, `upsertSyncedChats`, metadata decrypt helpers, `loadChatKeys`, `loadInitialData`, `loadMoreChatMetadata`, `ChatStore.upsertChats`, `SyncManager.swift`, `OfflineStore.persistChats`/`loadStartupChats`. Measure: process start to first non-empty sidebar, both paths in one run.
3. **Chat window from the core.** `ChatViewModel.loadChat` calls `openChat`; new `ChatViewModel+CoreWindow.swift` applies window events by request id and builds the render form off the main actor once per changed message; whole-window replace only on Cached, FirstPage, Canonical, CacheSettled. Delete in the same deploy: `ChatMessageWindowClient.swift`, `loadSyncedChat`, `decryptMessagesForDisplay`, `fetchRemoteWindow`, the phase_1b and background sync cases, message storage in `ChatStore` and `OfflineStore`.
4. **Live updates and transport ownership.** The Swift socket stays only for capabilities not yet in the core; chat and message routing is dropped. Needs core events for deletion, typing metadata and new-chat suggestions, or one Swift socket kept until A5/A6.
5. **Cache retirement.** Delete `OfflineStore` chat/message/embed stores and `OfflineSyncBridge` once drafts, queued sends and checkpoints are served by the core (A5 and the drafts lane). Server content is re-synced, never migrated. Open owner decision before this lane: the Specification (`client-core.cache.safe-store-retirement`, `storage.client.shared-policy-existing-adapters`) and plan AC-5 require that unsynced local state (drafts, queued sends, checkpoints) of existing installs is carried over; TestFlight installs exist. Either keep that one-time migration or record a dated exception in the Specification.

## Rules from the parent plan and Specification that each lane must meet

- Old Swift code is deleted in the same deploy (AC-1); the suite of the shell is green on the deployed commit (AC-2: apple-unit, apple-core, the capability's apple-ui selectors, rust-check, sdk-conformance for core changes); status recorded with the commit in the parent plan's capability inventory (AC-3).
- The mapped `ChatStore` of lanes 2 and 3 and the Swift socket of lane 4 are frozen remainders with a named end: `ChatStore` goes when share, search, notifications and Spotlight read from the core (A3b, A6); the Swift socket goes with A5 and A6. Neither may gain logic.
- Send and streaming are wired in Swift only after sync and cache are core-only on Apple (`client-core.apple.strangler-order`); the binding being ready earlier is fine.
- Targets from `sync.overview.ready-fast`: cached chat open p95 under 300 ms, uncached under 1 s.
- Tests carry `// contract-test: ... surface=gui.apple assertions=<ids>`; production Swift files carry `// Specification:` and `// Assertions:` lines. Assertions to reference: `client-core.viewmodel.capability-contract`, `client-core.viewmodel.stream-updates`, `client-core.cache.rust-owned-encrypted`, `client-core.cache.safe-store-retirement`, `sync.client.shared-rust-policy`, `sync.surface.semantic-parity`, `storage.client.shared-policy-existing-adapters`.
- Swift edits under `Core/**` without a Rust change carry a `shell-only: <reason>` line in the deploy message.
- Real-account checks on a signed build that CI cannot give: one login, one cold start with timing, one send.
- Extensions (notification service, share, widget) do not link the core yet; linking them and their memory budget is a separate step before A5 finishes.

## Risks

- `MainAppView.swift` (about 12,700 lines) and `ChatViewModel.swift` (about 7,600): all new code goes in new files, and each lane makes these files smaller.
- About 20 Swift files still decrypt with chat keys (share, search, notifications, Spotlight); lanes 2 and 3 keep a mapped `ChatStore` filled until they move.
- The core emits a full window per stream update: never apply it per update on long chats.
- The Keychain path is proven only on a signed build.
- Until every Swift consumer has moved, the app may not build feature-complete between lanes; each lane must still compile and keep the Apple unit suite at or below the known failure set (TASK-8027).
