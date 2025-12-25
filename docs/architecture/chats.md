# Chats Architecture

## Overview

Chats are managed with a zero-knowledge encryption architecture where all encryption happens client-side. The system implements a phased sync approach for optimal user experience, prioritizing the most recent chat for immediate access while loading the full chat history in the background.

For detailed sync mechanics, see `docs/architecture/sync.md` and `docs/architecture/scroll-position-sync.md`.

## Chat Display & Grouping

### Client-Side Organization

Chat display and grouping is handled entirely client-side in `frontend/packages/ui/src/components/chats/Chats.svelte`:

- **Sorting**: Chats are sorted by `last_edited_overall_timestamp` (most recent first) using `frontend/packages/ui/src/components/chats/utils/chatSortUtils.ts`
- **Grouping**: Chats are automatically grouped by time period (Today, Yesterday, Last 7 Days, etc.) using `frontend/packages/ui/src/components/chats/utils/chatGroupUtils.ts`
- **Phased Display**: Initially displays 20 chats, expanding to show all after full sync completes
- **Real-Time Updates**: Automatically updates when chats are modified via WebSocket events

### Encryption Model

Each chat has its own encryption key:

- **Chat Key**: Generated client-side per chat, stored encrypted in `chats.encrypted_chat_key`
- **Encrypted Fields**: `encrypted_title`, `encrypted_chat_summary`, `encrypted_chat_tags`, `encrypted_follow_up_request_suggestions`, `encrypted_active_focus_id`, `encrypted_icon`, `encrypted_category`
- **Zero-Knowledge**: Server never has access to decryption keys

See `backend/core/api/app/services/directus/chat_methods.py` for field definitions.

## Chat Context Menu

The chat context menu is accessible via right-click or press & hold on a chat item.

### Implemented Features

- **Download**: ✅ Export chat as YAML with all messages and metadata
  - Downloads as file with format: `YYYY-MM-DD_HH-MM-SS_[title].yaml`
  - Includes decrypted chat title, messages, and draft content
  - Implementation: `frontend/packages/ui/src/services/chatExportService.ts`

- **Copy**: ✅ Copy chat content to clipboard
  - Copies YAML format with embedded link
  - When pasted inside OpenMates, only the link is used
  - When pasted outside OpenMates, the full YAML is available
  - Implementation: `frontend/packages/ui/src/services/chatExportService.ts`

- **Delete**: ✅ Remove chat from IndexedDB and server
  - Deletes from local IndexedDB immediately
  - Sends delete request to server via WebSocket
  - Server broadcasts deletion to all connected devices for instant sync
  - Server marks chat as deleted (tombstone) in cache
  - Celery task persists deletion to Directus and removes all associated drafts
  - Files deleted, usage entries preserved for billing
  - Compliance event logged for audit trail
  - Implementation:
    - Frontend: `frontend/packages/ui/src/components/chats/Chat.svelte`
    - Backend: `backend/core/api/app/routes/handlers/websocket_handlers/delete_chat_handler.py`

- **Pin/Unpin**: ✅ Pin chats to keep them at the top of the chat list
  - Pinned chats are always shown at the top of the chats list
  - Pinned chats are never excluded from the last used 100 chats
  - Maximum 100 chats can be pinned
  - Updates are synced across all connected devices via WebSocket
  - Implementation: `frontend/packages/ui/src/components/chats/Chat.svelte`

### Planned Features (Not Yet Implemented)

- **Mark as unread**: Set unread status manually
- **Mark as completed**: Mark chat as read/done
- **Remind me**: Add reminder for follow-up

### Multi-Device Sync

All context menu actions that modify data (Delete) are immediately synced to other connected devices via WebSocket:

1. **Device A** performs action (e.g., deletes chat)
2. **Server** receives request and broadcasts event to all user's devices
3. **Device B, C, etc.** receive WebSocket event and update their local state
4. **All devices** show consistent state in real-time

Implementation reference: `frontend/packages/ui/src/components/chats/ChatContextMenu.svelte`

## Read Status

A chat is marked as "Read" only when:

1. User has scrolled to the bottom of the latest response
2. Scroll position tracking confirms full content visibility

See `docs/architecture/scroll-position-and-read-status.md` for scroll position tracking implementation.

## Drafts

### Storage & Synchronization

- **Server Storage**: Drafts stored in Directus `drafts` collection, linked by `chat_id` and `hashed_user_id`
- **Multi-Device Sync**: Draft updates sent to server and distributed to other logged-in devices via WebSocket
- **Cache Layer**: Server caches drafts in Redis for devices coming online after network interruption
- **Encryption**: All drafts encrypted client-side using chat-specific keys; server cannot read content
- **Cache Expiry**: Cached drafts auto-expire after 2 hours, then persisted to Directus
- **Deletion Sync**: Empty draft field triggers deletion sync across all devices

Implementation: `frontend/packages/ui/src/services/drafts/`

## Folders

> Feature not yet implemented

Planned features:

- Nested folder support
- Folders sorted by date like regular chats
- Auto-selected Lucide icons with color coding by request type
- Better visual identification and organization

## Icons

Chats have auto-selected Lucide icons and categories determined during pre-processing of the **first message only**. The icon and category match the request type for quick visual identification and organization. These are stored as `encrypted_icon` and `encrypted_category` fields in the chat model.

**One-Time Generation**: Icon, category, and title are generated only when a chat is created (first message). Follow-up messages do not regenerate these fields to maintain consistency and reduce processing overhead.

## Related Documentation

- `docs/architecture/sync.md` - Phased sync architecture and data flow
- `docs/architecture/scroll-position-sync.md` - Scroll position and read status tracking
- `docs/architecture/message_processing.md` - Message handling and processing
- `docs/architecture/account_backup.md` - Account data backup and export (for GDPR compliance and backups)
