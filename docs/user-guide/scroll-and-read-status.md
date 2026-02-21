# Scroll Position & Read Status Sync

## Overview

Syncs scroll position and read status across devices using **message-based anchoring** + **read status tracking**.

## Core Design

### Message-Based Anchoring
- Store `message_id` of **last visible message** in viewport
- On chat open, scroll with **70px offset** from that message (shows previous message context)
- Update anchor on scroll (debounced 500ms)

### Read Status
- Mark as **read** when user scrolls to bottom (sees last message)
- Manual "mark as read" option in chat context menu
- `unread_count` syncs across devices

### Caching Strategy (Draft-like)
- **IndexedDB**: Update immediately (local state) via [`db.ts`](../../frontend/packages/ui/src/services/db.ts)
- **Redis**: Update immediately (fast cross-device sync) via [`cache_service.py`](../../backend/core/api/app/services/cache_service.py)
- **Directus**: Update only when cache expires (reduces DB writes) via [`chat_methods.py`](../../backend/core/api/app/services/directus/chat_methods.py)
- **Exception**: Read status updates Directus immediately (important for badges)

## Data Schema

### IndexedDB & TypeScript Interface
Define in [`types/chat.ts`](../../frontend/packages/ui/src/types/chat.ts):
- `last_visible_message_id: string | null` - Anchor message UUID
- `scroll_offset_px?: number` - Fine-tune offset in pixels
- `unread_count: number` - 0 = read, >0 = unread
- `last_scroll_updated?: number` - Timestamp of last update

### Directus (chats collection)
Add to chats table schema:
- `last_visible_message_id VARCHAR(36) NULL`
- `scroll_offset_px INT DEFAULT 0`
- `unread_count INT DEFAULT 0`
- `last_scroll_updated TIMESTAMP`

**Note:** No encryption needed (UUIDs are non-sensitive)

### Redis Cache
Managed by [`cache_service.py`](../../backend/core/api/app/services/cache_service.py):
- Key pattern: `chat:{chat_id}:user:{user_id}`
- TTL: Same as draft cache (6 hours)

## Implementation

### Frontend

**[`ChatHistory.svelte`](../../frontend/packages/ui/src/components/ChatHistory.svelte)** - Track scroll position
- Add `on:scroll` listener (debounced 500ms)
- Find last visible message in viewport using `data-message-id` attributes
- Dispatch `scrollPositionChanged` event with message_id + offset
- Dispatch `scrolledToBottom` event when at bottom
- Export `restoreScrollPosition(message_id, offset)` function that scrolls to anchor with 70px offset
- Fallback to `scrollToBottom()` if anchor message not found

**[`ActiveChat.svelte`](../../frontend/packages/ui/src/components/ActiveChat.svelte)** - Save & restore
- Listen for `scrollPositionChanged` events from ChatHistory
- Debounce save (1s) → call [`chatDB.updateChatScrollPosition()`](../../frontend/packages/ui/src/services/db.ts)
- Send to server via [`chatSyncService.sendScrollPositionUpdate()`](../../frontend/packages/ui/src/services/chatSyncService.ts)
- On `scrolledToBottom` → mark as read (set `unread_count = 0`)
- On chat load → check if `last_visible_message_id` exists, then restore scroll position
- Handle errors gracefully with console logging

**[`Chat.svelte`](../../frontend/packages/ui/src/components/chats/Chat.svelte)** - Display unread count
- Display `chat.unread_count` in badge (already implemented)

**[`ChatContextMenu.svelte`](../../frontend/packages/ui/src/components/chats/ChatContextMenu.svelte)** - Manual mark as read
- Add "Mark as Read" menu option that sets `unread_count = 0`

**[`db.ts`](../../frontend/packages/ui/src/services/db.ts)** - IndexedDB operations
- Add `updateChatScrollPosition(chatId, messageId, offsetPx)` method
- Update schema version if needed for new fields

**[`chatSyncService.ts`](../../frontend/packages/ui/src/services/chatSyncService.ts)** - WebSocket sync
- Add `sendScrollPositionUpdate(chatId, messageId, offsetPx)` method
- Add `sendReadStatusUpdate(chatId, unreadCount)` method

### Backend

**[`websockets.py`](../../backend/core/api/app/routes/websockets.py)** - WebSocket event handlers

**scroll_position_update handler:**
- Extract `user_id` from session
- Validate payload contains `chat_id` and `message_id`
- Update Redis cache immediately via [`cache_service.py`](../../backend/core/api/app/services/cache_service.py)
- Update Directus when cache expires (like drafts) via [`chat_methods.py`](../../backend/core/api/app/services/directus/chat_methods.py)
- Set `last_scroll_updated` to current UTC timestamp
- Broadcast to other devices (exclude sender)

**chat_read_status_update handler:**
- Extract `user_id` from session
- Validate payload contains `chat_id` and `unread_count`
- Update Redis + Directus immediately (read status important for badges)
- Broadcast to other devices

**[`cache_service.py`](../../backend/core/api/app/services/cache_service.py)** - Redis operations
- Implement scroll position caching logic
- Handle TTL and expiry checks (draft-like pattern)

**[`chat_methods.py`](../../backend/core/api/app/services/directus/chat_methods.py)** - Directus operations
- Add methods to update scroll position fields
- Add methods to update read status fields

## Sync Flow

### Scroll Position Update
1. User scrolls in [`ChatHistory.svelte`](../../frontend/packages/ui/src/components/ChatHistory.svelte) → debounced event (500ms)
2. [`ActiveChat.svelte`](../../frontend/packages/ui/src/components/ActiveChat.svelte) receives event → debounced save (1s)
3. Update [`db.ts`](../../frontend/packages/ui/src/services/db.ts) IndexedDB
4. Send via [`chatSyncService.ts`](../../frontend/packages/ui/src/services/chatSyncService.ts) WebSocket
5. [`websockets.py`](../../backend/core/api/app/routes/websockets.py) updates Redis immediately
6. Directus updated only when cache expires

### Read Status Update
1. User scrolls to bottom in [`ChatHistory.svelte`](../../frontend/packages/ui/src/components/ChatHistory.svelte) → `scrolledToBottom` event
2. [`ActiveChat.svelte`](../../frontend/packages/ui/src/components/ActiveChat.svelte) marks as read
3. Update IndexedDB → send to server
4. Server updates Redis + Directus immediately (important for badges)
5. Broadcast to other devices → badges update everywhere

## Edge Cases

| Scenario | Solution |
|----------|----------|
| Anchor message deleted | Fallback to `scrollToBottom()` in [`ChatHistory.svelte`](../../frontend/packages/ui/src/components/ChatHistory.svelte) |
| No saved position | Default to bottom (newest messages) in [`ActiveChat.svelte`](../../frontend/packages/ui/src/components/ActiveChat.svelte) |
| Multiple devices scrolling | Last-write-wins via `last_scroll_updated` timestamp in [`websockets.py`](../../backend/core/api/app/routes/websockets.py) |
| New messages while reading | Don't auto-scroll if user scrolled up, handled in [`ActiveChat.svelte`](../../frontend/packages/ui/src/components/ActiveChat.svelte) |
| Very long messages | `scroll_offset_px` provides fine-tuned positioning |
| Empty chat | No scroll position saved, natural scrollToBottom behavior |


## Why Message-Based?

**Rejected alternatives:**
- ❌ **Percentage-based** `(scrollTop / scrollHeight) × 100` - Breaks with dynamic content/new messages
- ❌ **Pixel-based** `scrollTop` value - Not device-independent, breaks with any changes

**Chosen: Message-based anchoring**
- ✅ Device-independent (all screen sizes)
- ✅ Content-independent (handles dynamic heights)
- ✅ Proven pattern (Slack, Discord, Telegram)
- ✅ Graceful degradation (fallback if anchor deleted)

## Key Files

**Frontend:**
- [`ChatHistory.svelte`](../../frontend/packages/ui/src/components/ChatHistory.svelte) - Scroll tracking & restoration
- [`ActiveChat.svelte`](../../frontend/packages/ui/src/components/ActiveChat.svelte) - Save & restore orchestration
- [`Chat.svelte`](../../frontend/packages/ui/src/components/chats/Chat.svelte) - Unread badge display
- [`ChatContextMenu.svelte`](../../frontend/packages/ui/src/components/chats/ChatContextMenu.svelte) - Manual mark as read
- [`chatSyncService.ts`](../../frontend/packages/ui/src/services/chatSyncService.ts) - WebSocket communication
- [`db.ts`](../../frontend/packages/ui/src/services/db.ts) - IndexedDB operations
- [`types/chat.ts`](../../frontend/packages/ui/src/types/chat.ts) - TypeScript interface

**Backend:**
- [`websockets.py`](../../backend/core/api/app/routes/websockets.py) - WebSocket event handlers
- [`cache_service.py`](../../backend/core/api/app/services/cache_service.py) - Redis caching
- [`chat_methods.py`](../../backend/core/api/app/services/directus/chat_methods.py) - Directus persistence
