# Apple/Web Streaming Parity

Status: Linux static audit  
Created: 2026-06-01  
Scope: AI task events, typing state, chunks, thinking, post-processing, queued messages

## Goal

Apple streaming must match web-visible AI response behavior: task initiation, typing indicator, incremental content chunks, thinking sections, final message readiness, post-processing metadata, suggestions, and queued-message handling.

## Web Source

- `frontend/packages/ui/src/services/websocketService.ts`
- `frontend/packages/ui/src/services/chatSyncServiceHandlersAI.ts`
- `frontend/packages/ui/src/services/chatSyncService.ts`
- `frontend/packages/ui/src/components/ChatMessage.svelte`
- `frontend/packages/ui/src/components/ThinkingSection.svelte`
- Web specs that assert `message-assistant`, `typing-indicator`, and streaming completion across skill flows

## Apple Source

- `apple/OpenMates/Sources/Core/Networking/WebSocketManager.swift`
- `apple/OpenMates/Sources/Core/Networking/StreamingClient.swift`
- `apple/OpenMates/Sources/Features/Chat/ViewModels/ChatViewModel.swift`
- `apple/OpenMates/Sources/Features/Chat/Views/ChatView.swift`
- `apple/OpenMates/Sources/Features/Chat/Views/ThinkingSectionView.swift`
- `apple/OpenMates/Sources/Features/Chat/Views/ProcessingDetailsView.swift`

## Confirmed Apple Behavior From Source

- `WebSocketManager` routes `ai_task_initiated` to `StreamingClient.StreamEvent.taskInitiated`.
- `ai_typing_started` is routed with chat metadata, including title, icons, category, model/provider/region, user message ID, and encrypted chat key.
- `ai_message_update` is routed as chunk events with sequence, full content so far, final flag, user message ID, category, model name, and rejection reason.
- `thinking_chunk` and `thinking_complete` have dedicated stream events.
- `ai_message_ready` has a dedicated stream event.
- `preprocessing_step` and `post_processing_completed` route to stream events.
- `StreamingClient` buffers up to 80 events per chat when no active stream exists, which is useful for race conditions where events arrive before a view subscribes.
- WebSocket routes `message_queued` through `.wsMessageReceived` but not into `StreamingClient` directly.

## Web Parity Risks

- Web has explicit queued `ai_typing_started` handling for a missing chat shell (OPE-360). Apple buffering is per chat ID and likely helps, but parity depends on `ChatViewModel` subscribing at the correct time and creating the shell from `new_chat_message` or metadata.
- Web handles background chat completion notifications and unread increments in AI handlers. Apple streaming source alone does not prove equivalent background notification behavior.
- Web `ai_message_update` comments show extensive debug handling around streaming. Apple route is simpler; verify final chunk ordering, duplicate chunks, and missed final events.
- `message_queued` should surface in the composer/input area on web, not as a generic notification. Apple needs equivalent UI behavior if supported.
- `post_processing_completed` carries follow-up suggestions, new chat suggestions, summary, tags, and updated title. Apple must confirm these are applied to UI and persisted.

## Testability IDs Needed

- `typing-indicator`
- `message-assistant`
- `thinking-section`
- `processing-details`
- `follow-up-suggestions`
- `new-chat-suggestions`
- `message-queued-banner` or native equivalent

## Mac Verification Checklist

- Send a prompt and verify typing indicator appears before first chunk.
- Verify chunks update the same assistant bubble rather than duplicating messages.
- Verify thinking chunks appear and collapse/complete like web.
- Verify final response persists and no streaming indicator remains stuck.
- Trigger post-processing and verify follow-up suggestions, summary/title updates, and new-chat suggestions.
- Trigger an active-task queued message and verify it appears in the composer/input surface, not as an unrelated notification.
- Start streaming on web and open Apple mid-stream to verify buffered event handling.

## First Implementation Tasks

- Audit `ChatViewModel` event handling against every `StreamingClient.StreamEvent` case.
- Add stable identifiers for typing, thinking, processing, and suggestions UI.
- Add a streaming race test plan for chat shell creation before/after `ai_typing_started`.
