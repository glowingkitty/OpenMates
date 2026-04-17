# Message Highlights

Architecture doc for the text-highlighting (annotation) feature in chat messages.

## Overview

Users can select text in any chat message, right-click (or use the floating toolbar on touch devices), and apply a yellow highlight with an optional comment. Highlights are end-to-end encrypted, persisted to IndexedDB, and synced across devices via WebSocket.

## User Flow

1. **Select text** in a message body (user or assistant message).
2. **Right-click** → context menu shows "Highlight" and "Highlight & comment".
   - On touch devices (iOS/iPadOS), a floating `MessageSelectionToolbar` appears instead (long-press triggers `selectionchange`, not `contextmenu`).
3. **Highlight applied** — selected text is wrapped in yellow `<mark>` elements. A pill in `ChatHeader` shows the count ("2 highlights, 1 comment").
4. **Click a highlight** — a `HighlightCommentPopover` opens showing the author, comment text, and Edit/Delete buttons (author-only).
5. **Navigation** — `HighlightNavigationOverlay` lets users step through highlights in document order.

## Data Model

```typescript
interface HighlightAnchor {
  exact: string;    // The selected text verbatim
  prefix: string;   // Up to 20 chars of context before the selection
  suffix: string;   // Up to 20 chars of context after the selection
}

interface MessageHighlight {
  id: string;                  // UUID
  chat_id: string;
  message_id: string;
  kind: 'text' | 'embed';
  anchor: HighlightAnchor;     // Text-quote selector (W3C Web Annotation pattern)
  start: number;               // Character offset hint (used for sort order)
  end: number;
  comment?: string;            // Optional, max 500 chars
  author_user_id: string;
  author_display_name?: string;
  key_version: number;         // Encryption key version
  created_at: string;
  updated_at: string;
}
```

Anchors use the **W3C text-quote selector** pattern (`exact` + `prefix` + `suffix`) instead of raw character offsets. This is robust against re-renders, font changes, and embed content updates — the exact phrase is re-located in the live DOM at render time using context-scoring disambiguation.

## Architecture

### Capture (selection → anchor)

`captureHighlightAnchor()` in `messageHighlights.ts`:
1. Walks text nodes inside `messageBodyElement`, **skipping embed subtrees** (`.embed-full-width-wrapper`).
2. Maps the DOM Range boundaries to offsets in the filtered rendered text.
3. Extracts `exact` (trimmed selection), `prefix` (preceding context), and `suffix` (following context).

### Persistence & Sync

1. **Optimistic local persist** — anchor is written to IndexedDB (`message_highlights` store) and the Svelte store immediately.
2. **Encrypt & send** — `sendAddMessageHighlightImpl()` encrypts the payload with the chat key and sends an `add_message_highlight` WebSocket event.
3. **Receive** — `handleMessageHighlightAddedImpl()` decrypts the payload with the chat key, upserts to IndexedDB and the store.
4. **Cold boot** — `loadHighlightsForChat()` bulk-loads all highlights from IndexedDB when a chat is opened.

### Rendering (anchor → marks)

`MessageHighlightOverlay.svelte` runs a `recompute()` cycle whenever highlights, content, or focus state change:

1. **Remove** all existing `<mark>` elements from the message body.
2. **Resolve** each anchor via `findAnchorInRendered()` — walks filtered text, enumerates all occurrences of `exact`, scores each by prefix/suffix context match, picks the best, maps back to DOM Range coordinates.
3. **Wrap** via `wrapRange()` — splits text nodes at range boundaries and wraps each segment in a `<mark class="message-highlight-mark">` element.
   - Single-text-node selections are handled directly (TreeWalker can't descend into a Text node root).
   - Embed subtrees are excluded via a `NodeFilter` to prevent false highlighting of embed content.
4. **Attach event handlers** — click (opens popover), mouseenter/mouseleave (group hover across fragments).

### Popover Positioning

`HighlightCommentPopover.svelte` uses `position: fixed` with viewport-relative coordinates. The popover is **portaled to `document.body`** on mount to avoid the containing-block issue caused by `filter: drop-shadow()` on `.user-message-content` / `.mate-message-content`.

Position logic: try above the mark first; flip below if insufficient space; clamp to viewport edges.

## Visual States

All three states use the same yellow hue at different opacities, with no border-radius (so multi-fragment highlights look continuous):

| State | Background | Trigger |
|-------|-----------|---------|
| Default | `rgba(255, 213, 0, 0.4)` | Always |
| Focused (clicked) | `rgba(255, 213, 0, 0.65)` | Click on mark |
| Hovered | `#ffd500` (solid) | Mouseenter on any fragment |

Hover uses a **group highlight** pattern: `mouseenter`/`mouseleave` handlers toggle a `.hovered` class on all `<mark>` elements sharing the same `data-highlight-id`, so hovering one fragment of a multi-mark highlight lights up the entire highlight.

## Key Files

| File | Purpose |
|------|---------|
| `ui/src/utils/messageHighlights.ts` | Anchor capture, resolution, context scoring, sorting |
| `ui/src/components/MessageHighlightOverlay.svelte` | Mark wrapping, event handlers, CSS |
| `ui/src/components/HighlightCommentPopover.svelte` | Comment view/edit popover (portaled to body) |
| `ui/src/components/MessageSelectionToolbar.svelte` | Floating toolbar for touch devices |
| `ui/src/components/HighlightNavigationOverlay.svelte` | Step-through navigation UI |
| `ui/src/components/ChatMessage.svelte` | Wires highlights to message rendering |
| `ui/src/stores/messageHighlightsStore.ts` | Reactive store keyed by (chatId, messageId) |
| `ui/src/services/db/messageHighlights.ts` | IndexedDB CRUD |
| `ui/src/services/sendersMessageHighlights.ts` | Encrypt + WS send |
| `ui/src/services/handlersMessageHighlights.ts` | WS receive + decrypt |
| `ui/src/types/chat.ts` | `HighlightAnchor`, `MessageHighlight` types |

## Known Design Decisions

- **Text-quote anchors over offsets**: Character offsets break when the DOM re-renders (streaming, embed updates, font loads). Text-quote selectors are resilient — they find the phrase by content, not position.
- **Inline marks over overlay boxes**: Earlier versions used absolutely-positioned boxes. Inline `<mark>` elements reflow naturally with text on viewport changes, zoom, and font-size shifts.
- **Portal popover to body**: The message bubble's `filter: drop-shadow()` creates a CSS containing block that breaks `position: fixed`. Portaling avoids this without changing the shadow.
- **Embed exclusion at both capture and render**: Embed text is excluded from anchor capture (`collectFilteredText`) AND from mark wrapping (`wrapRange` NodeFilter). This prevents embeds from polluting anchors or getting falsely highlighted.
- **No border-radius on marks**: Multi-fragment highlights (spanning bold, italic, links) render as separate `<mark>` elements. Removing border-radius makes adjacent fragments look like one continuous highlight.

## E2E Tests

| Spec | Coverage |
|------|----------|
| `message-highlights.spec.ts` | Full lifecycle + correctness: exact text match, visibility, viewport resize (mobile/tablet), embed exclusion, popover positioning, touch toolbar, text integrity |
| `message-highlights-touch.spec.ts` | Touch-device regression: iPad emulation, geometric overlap validation |
