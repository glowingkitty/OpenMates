# Edit / Reprocess Message Feature

## Summary

Add an "Edit" option to the message context menu for **user messages only**. Clicking it populates the message input with the original content, dims all messages from that point onward (opacity 0.5, non-interactive), and shows a slim "Editing message" banner above the input with a cancel button. When the user sends, all messages from the edit point are deleted and the new message is sent, triggering a fresh AI response.

## Architecture

**State management:** A new lightweight store `editMessageStore.ts` holds the edit state. This is the right pattern because three sibling/cousin components need to coordinate: `ChatMessage` (sets it), `ChatHistory` (reads it for dimming), `MessageInput` (reads it to populate editor + show banner).

**No backend changes needed.** The existing flow — client sends message, backend requests chat history from client — means deleting messages from IndexedDB before sending is sufficient. The backend will only receive history up to the edit point + the new message.

## Implementation Steps

### Step 1: Create `editMessageStore.ts`

**New file:** `frontend/packages/ui/src/stores/editMessageStore.ts`

```typescript
interface EditMessageState {
  chatId: string;
  messageId: string;        // The user message being edited
  messageContent: string;   // Original markdown content
  createdAt: number;        // Timestamp — used to identify "from this point onward"
}
```

Exports:
- `editMessageStore` — writable store (`EditMessageState | null`)
- `startEdit(chatId, messageId, content, createdAt)` — sets the store
- `cancelEdit()` — sets to null

### Step 2: Add "Edit" to `MessageContextMenu.svelte`

- Add `onEdit?: () => void` callback prop
- Add menu item with `icon_edit` icon between Copy and Fork
- Only render when `onEdit` is provided (parent controls visibility by only passing it for user messages)
- i18n key: `chats.context_menu.edit`

### Step 3: Wire up `ChatMessage.svelte`

- Import `startEdit` from the new store
- Add `handleEdit()`:
  - Reads `original_message.content` (markdown string)
  - Calls `startEdit(currentChatId, messageId, content, created_at)`
  - Closes menu
- Pass `onEdit={role === 'user' && messageId ? handleEdit : undefined}` to `<MessageContextMenu>`
- Disable edit when AI is streaming (`aiTypingStore`) to prevent conflicts

### Step 4: Dim messages in `ChatHistory.svelte`

- Import `editMessageStore`
- In the `{#each}` loop's wrapper `<div>` (line ~1583), apply conditional styling:
  - If `editMessageStore` is set AND `msg.original_message?.created_at >= editState.createdAt` AND same `chatId`:
    - `opacity: 0.5`
    - `pointer-events: none`
  - This overlays naturally on the existing inline `style=` on the wrapper div

### Step 5: Populate editor + show banner in `MessageInput.svelte`

**Populate editor:**
- Add `$effect` watching `editMessageStore`
- When edit state activates for current chat: set markdown content in the TipTap editor via `editor.chain().setContent(...).run()`, then `editor.commands.focus('end')`
- Follow the existing draft-loading / notification-reply-prefill pattern

**Banner above input:**
- When `$editMessageStore` is set, render a slim banner above the editor: `"Editing message"` text + `X` cancel button
- Cancel button calls `cancelEdit()` and clears the editor
- Escape key while editing also cancels

### Step 6: Handle send in edit mode (`sendHandlers.ts`)

Inside `handleSend()`, before dispatching `sendMessage`:

1. Read `editMessageStore` via `get(editMessageStore)`
2. If active and matches current `chatId`:
   - Fetch all messages for the chat from IndexedDB
   - Sort by `created_at`, find the index of the edited message by `messageId`
   - Delete all messages from that index onward (inclusive) from IndexedDB + notify server
   - Call `cancelEdit()` to clear the store
   - Include `isEditSend: true` + `editCreatedAt` in the dispatched event detail

### Step 7: Handle `currentMessages` truncation in `ActiveChat.svelte`

In `handleSendMessage()`:
- Check `event.detail.isEditSend` and `event.detail.editCreatedAt`
- If true, filter `currentMessages` to remove messages at/after the edit point
- Then append the new message (existing code handles this)
- Cancel edit on chat navigation (when `currentChat` changes)

### Step 8: Add i18n keys

**File:** `frontend/packages/ui/src/i18n/sources/chats.yml`

Add keys:
- `context_menu.edit` — "Edit"
- `edit_banner.editing` — "Editing message"
- `edit_banner.cancel` — "Cancel"

Then run `cd frontend/packages/ui && npm run build:translations`.

### Step 9: Export from barrel

Add `editMessageStore` exports to the appropriate barrel file (stores index or `@repo/ui` re-exports).

## Edge Cases

| Case | Handling |
|------|----------|
| AI is currently streaming | Disable edit button (check `aiTypingStore`) |
| User clears editor without sending | Cancel edit mode, restore all messages to normal |
| User navigates to different chat | Cancel edit mode automatically |
| Incognito chat | Edit works — no encryption complexity, just IndexedDB ops |
| First message in chat | Edit allowed (unlike delete, editing doesn't leave empty chat) |
| Message has embeds | Markdown includes embed refs; normal send flow re-processes them |
| Same-second timestamps | Use message ID + index in sorted array, not just timestamp |

## Files Changed

| File | Change |
|------|--------|
| `stores/editMessageStore.ts` | **New** — edit state store |
| `chats/MessageContextMenu.svelte` | Add Edit button + `onEdit` prop |
| `ChatMessage.svelte` | Add `handleEdit()`, pass `onEdit` to context menu |
| `ChatHistory.svelte` | Dim messages when edit is active |
| `enter_message/MessageInput.svelte` | Populate editor, show banner, handle cancel/escape |
| `enter_message/handlers/sendHandlers.ts` | Delete messages from edit point, pass `isEditSend` flag |
| `ActiveChat.svelte` | Truncate `currentMessages` on edit-send, cancel on navigation |
| `i18n/sources/chats.yml` | Add edit-related translation keys |
| `stores/index.ts` (or barrel) | Export new store |

## What This Does NOT Do (Intentional)

- **No backend changes** — client-side message deletion + normal send is sufficient
- **No "Reprocess" button label** — dimmed messages + banner already indicate edit mode
- **No assistant message editing** — only user messages get Edit
- **No settings panel** — unlike fork, this is a lightweight inline operation
