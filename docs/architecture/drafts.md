# Drafts System Architecture

> **Status**: ✅ Implemented  
> **Last Updated**: 2025-10-01

This document describes the draft saving and synchronization system that allows users to maintain unsent message drafts across multiple devices with zero-knowledge encryption.

## User Flow: Creating and Syncing Drafts

### 1. User Starts Typing
When a user types in the [MessageInput component](../../frontend/packages/ui/src/components/enter_message/MessageInput.svelte), the Tiptap editor triggers update events that call the [draft service](../../frontend/packages/ui/src/services/draftService.ts).

### 2. Local Draft Save
The [draftSave service](../../frontend/packages/ui/src/services/drafts/draftSave.ts) implements a 1.2-second debounced save:
- Content is encrypted using the user's master key
- Draft is saved to IndexedDB via [chatDB](../../frontend/packages/ui/src/services/db.ts)
- UI state is updated in [draftState](../../frontend/packages/ui/src/services/drafts/draftState.ts)

### 3. Server Synchronization
If online, the encrypted draft is sent to the server via WebSocket:
- [chatSyncService](../../frontend/packages/ui/src/services/chatSyncService.ts) sends the encrypted content
- Backend [draft_update_handler](../../backend/core/api/app/routes/handlers/websocket_handlers/draft_update_handler.py) processes the update
- Server increments version and updates cache

### 4. Cross-Device Sync
When another device receives the draft update:
- [draftWebsocket handler](../../frontend/packages/ui/src/services/drafts/draftWebsocket.ts) processes the WebSocket message
- Draft content is decrypted and loaded into the editor
- [ActiveChat component](../../frontend/packages/ui/src/components/ActiveChat.svelte) displays the updated draft

### 5. Chat List Updates
Draft previews are shown in chat lists:
- [Chat component](../../frontend/packages/ui/src/components/chats/Chat.svelte) displays draft status
- [Chats component](../../frontend/packages/ui/src/components/chats/Chats.svelte) refreshes the list
- Cache invalidation ensures fresh draft data

## Architecture Components

### Frontend Services
- **[draftCore.ts](../../frontend/packages/ui/src/services/drafts/draftCore.ts)** - Editor lifecycle management
- **[draftSave.ts](../../frontend/packages/ui/src/services/drafts/draftSave.ts)** - Debounced saving and encryption
- **[draftWebsocket.ts](../../frontend/packages/ui/src/services/drafts/draftWebsocket.ts)** - Real-time sync handling
- **[draftState.ts](../../frontend/packages/ui/src/services/drafts/draftState.ts)** - Svelte store for UI state

### Backend Services
- **[draft_update_handler.py](../../backend/core/api/app/routes/handlers/websocket_handlers/draft_update_handler.py)** - WebSocket draft processing
- **[persistence_tasks.py](../../backend/core/api/app/tasks/persistence_tasks.py)** - Async draft persistence
- **[drafts.yml](../../backend/core/directus/schemas/drafts.yml)** - Database schema

## Key Features

### Zero-Knowledge Encryption
All draft content is encrypted client-side before transmission. The server never sees unencrypted drafts, maintaining user privacy.

### Real-Time Synchronization
Drafts sync across devices in real-time via WebSocket connections, with automatic conflict resolution.

### Offline Support
Draft changes are queued when offline and synchronized when connection is restored.

### Version Management
Each draft edit increments the version number, enabling conflict detection and resolution.

## Configuration

### Environment Variables
- `DRAFT_PERSISTENCE_TTL_SECONDS`: Cache TTL for drafts
- `MAX_DRAFT_CHARS`: Maximum draft content length

### Frontend Settings
- Debounce delay: 1200ms
- Cache TTL: 15 minutes
- Max content length: Configurable per deployment

---

## Read Next

**Related Architecture:**
- [Message Input Field](./message_input_field.md) - MessageInput component architecture
- [Chat Sync Architecture](./chat_sync.md) - Overall sync system design

**Implementation Guides:**
- [WebSocket Service](../developer-guides/websocket.md) - WebSocket implementation
- [Encryption System](../technical-specs/encryption.md) - Client-side encryption details

**Related Features:**
- [Real-time Updates](./notifications.md) - Real-time notification system
- [Offline Support](./offline.md) - Offline functionality overview
