# Apple/Web Message Processing Parity

Status: Linux static audit  
Created: 2026-06-01  
Scope: user message persistence, assistant message persistence, message versions, deletion cleanup

## Goal

Apple must preserve the same message lifecycle as web: a user message is locally visible and persisted immediately, assistant responses stream and then persist, `messages_v` tracks server-authoritative versions, and refresh/cold boot restores all messages.

## Web Source

- `frontend/apps/web_app/tests/message-sync.spec.ts`
- `frontend/packages/ui/src/services/chatSyncServiceHandlersAI.ts`
- `frontend/packages/ui/src/services/chatSyncServiceHandlersCoreSync.ts`
- `frontend/packages/ui/src/services/chatSyncMerge.ts`
- `frontend/packages/ui/src/types/chat.ts`

## Apple Source

- `apple/OpenMates/Sources/Core/Models/ChatModels.swift`
- `apple/OpenMates/Sources/Core/Persistence/ChatStore.swift`
- `apple/OpenMates/Sources/Core/Persistence/OfflineStore.swift`
- `apple/OpenMates/Sources/Core/Persistence/OfflineSyncBridge.swift`
- `apple/OpenMates/Sources/Core/Networking/WebSocketManager.swift`
- `apple/OpenMates/Sources/Features/Chat/ViewModels/ChatViewModel.swift`
- `apple/OpenMates/Sources/Features/Chat/Views/ChatView.swift`

## Web Contract From Specs

- After sending first prompt and receiving response, IndexedDB has at least 2 messages: 1 user and 1 assistant.
- After sending the second user prompt, the second user message is persisted before the assistant response arrives.
- Final state has at least 4 messages: 2 user and at least 2 assistant messages.
- `messages_v` is greater than or equal to message count and never zero once messages exist.
- Reloading the page and returning to the chat restores all messages.
- Deleting the chat removes the active chat item.

## Confirmed Apple Behavior From Source

- `Message` decodes both camelCase and snake_case fields for IDs, encrypted content, timestamps, app ID, streaming state, embed refs, and model name.
- `ChatStore.appendMessage` upserts by message ID, updates in-memory state, and persists through `OfflineSyncBridge`.
- `ChatStore.setMessages` sorts by `createdAt` and persists.
- `ChatStore.updateMessage` updates content while preserving encrypted content, app ID, embed refs, and model name.
- `OfflineStore.persistMessagesBatch` upserts persisted messages by ID for a chat.
- `ChatStore.makeSyncClientState` includes `messages_v` for server diffing.
- Offline send queues a `send_message` pending action and immediately appends a local user message.

## Likely Gaps To Verify Or Fix

- `Message` lacks several web-side fields visible in `types/chat.ts`, including status-like fields used by tests (`status`), highlight metadata, and richer attachment/embed metadata. Confirm whether Apple intentionally computes these elsewhere or needs model expansion.
- `PersistedMessage.toMessage` always returns `isStreaming: false`, so app relaunch cannot represent an interrupted/in-progress stream. Confirm desired behavior for background or interrupted AI responses.
- Apple `Chat` currently lacks `unread_count`, parent/sub-chat fields, hidden/private fields beyond persistence-only `isPrivate`, and some metadata present in web sync types. These may affect message list parity and cross-device state.
- `messages_v` is stored on `Chat`, but static audit did not prove it is updated after every local/remote message event. Verify with Mac tests.
- Deletion cleanup in `ChatStore.removeChat` removes in-memory messages and calls `OfflineSyncBridge.onChatDeleted`, but parity for message-level delete/highlight events needs a separate audit.

## Testability IDs Needed

- `new-chat-button`
- `message-editor`
- `message-user`
- `message-assistant`
- `chat-context-delete`
- `chat-item-wrapper` already exists

## Mac Verification Checklist

- Send two sequential user messages in the same chat and confirm both appear before/after assistant responses.
- Relaunch the app and confirm all messages remain present.
- Compare Apple chat message count and roles against web for the same chat.
- Verify `messages_v` is sent in the next phased sync request after message changes.
- Delete the test chat and confirm it disappears locally and does not reappear after sync.

## First Implementation Tasks

- Add missing message test identifiers in Apple chat UI.
- Audit Apple message model fields against `frontend/packages/ui/src/types/chat.ts` and backend payloads.
- Add an Apple UI/integration test plan mirroring `message-sync.spec.ts`.
