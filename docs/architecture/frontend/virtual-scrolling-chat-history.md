# Virtual Scrolling for Chat Message List

> **Status**: Planned (not yet implemented)
> **Author**: Research session, 2026-04-03
> **Linear**: See linked task

## Problem

OpenMates renders ALL chat messages in a single `{#each}` loop with no virtualization.
Each message creates a TipTap editor (ProseMirror) that stays alive forever once scrolled
into view. For long conversations (100+ messages), this means:

- 100+ TipTap editor instances alive simultaneously
- 50-150 DOM nodes per message = 5,000-15,000+ unnecessary DOM nodes
- Significant memory pressure and GC overhead
- Slower scroll performance on mobile devices

### Current Architecture

| Aspect | Implementation | File |
|--------|---------------|------|
| Message list | `{#each displayMessages}` — full array, no windowing | `ChatHistory.svelte:1580` |
| Editor lifecycle | Lazy init via IntersectionObserver (500px buffer), **never destroyed** | `ReadOnlyMessage.svelte:939` |
| Data loading | `getAll()` from IndexedDB — entire conversation at once | `messageOperations.ts:316` |
| Height reads | Post-render DOM reads (`scrollHeight`, `offsetHeight`) | `ChatHistory.svelte` |
| Spacer system | Dynamic spacer shrinks as AI response grows during streaming | `ChatHistory.svelte:687-1086` |

### Existing Partial Mitigation

`ReadOnlyMessage.svelte` defers TipTap editor creation until a message is within 500px of
the viewport. But once created, editors are never destroyed — they accumulate for the
lifetime of the chat view. The observer disconnects after first intersection (one-shot).

## Pretext Evaluation

[Pretext](https://github.com/chenglou/pretext) by Cheng Lou (Midjourney) is a 15KB library
that predicts text line-wrapping and height using pure arithmetic, avoiding DOM reflow.
~483x faster than DOM measurement.

**Verdict: Not applicable.** Pretext solves pre-render height prediction for plain text.
Our messages contain rich content (TipTap editors, embeds, code blocks, images) that Pretext
cannot measure. We don't need pre-render height prediction in the current architecture, and
even with virtualization, height estimation for off-screen messages requires content-aware
heuristics, not text-only measurement.

## Why NOT TanStack Virtual

`@tanstack/svelte-virtual` was evaluated and rejected:

1. **Absolute positioning conflicts** — TanStack positions items with `transform: translateY()`.
   Our layout uses document flow with sibling elements (spacer div, permission dialog,
   follow-up suggestions, debug panel) that depend on natural flow.
2. **Streaming spacer incompatible** — The spacer is a flow-based sibling whose height
   shrinks as the last message grows. TanStack's total-height container model has no concept
   of a dynamic spacer after the last virtual item.
3. **Dynamic height adversarial** — During streaming, the last message grows every 80ms.
   TanStack expects items to stabilize quickly after mount.

## Proposed Solution: Custom 3-Phase Implementation

### Phase 1: Editor Lifecycle Management (ship independently)

**Impact: HIGH | Risk: LOW | Effort: ~2 days**

Make the IntersectionObserver in `ReadOnlyMessage.svelte` bidirectional:

- **Create** editor when message enters 1500px of viewport
- **Destroy** editor when message exits 1500px of viewport
- Before destruction: cache `editor.getJSON()` and `offsetHeight`
- On re-entry: recreate from cached JSON (skip expensive markdown re-parsing)
- Show `min-height` placeholder while editor is absent
- **Exempt streaming messages** from destruction

This alone addresses the primary performance bottleneck (editor accumulation).

### Phase 2: Height Cache Infrastructure (prep)

**Impact: NONE (prep) | Risk: LOW | Effort: ~1 day**

New utility: `frontend/packages/ui/src/utils/messageHeightCache.ts`

- `Map<messageId, measuredHeight>` updated via `ResizeObserver`
- `estimateHeight(message)` heuristic for unmounted messages:
  - User messages: `max(60, min(contentLength * 0.4, 300))`
  - Assistant messages: `max(80, min(contentLength * 0.5, 600))`
  - Code blocks: +200px each, embeds: +150px each

### Phase 3: Windowed Rendering

**Impact: HIGH | Risk: MEDIUM-HIGH | Effort: ~5 days**

Replace `{#each displayMessages}` with a **padding-based** windowed renderer:

```svelte
<div style="padding-top: {topPadding}px; padding-bottom: {bottomPadding}px;">
  {#each windowedMessages as msg (msg.id)}
    <ChatMessage ... />
  {/each}
  <!-- spacer, follow-up suggestions remain as natural siblings -->
</div>
```

- `windowedMessages` = visible messages + 5 overscan above/below
- `topPadding` / `bottomPadding` = sum of cached/estimated heights for off-screen messages
- Preserves document flow — all existing scroll management continues to work
- `scrollToBottom()`, spacer system, search scroll all remain functional

**Scroll management adaptations:**
- `restoreScrollPosition(id)`: compute offset from height cache → scroll → refine with DOM
- Search scroll: Phase 1 to estimated offset, Phase 2 retry `<mark>` query (existing 30-retry loop)

## Risks

| Risk | Mitigation |
|------|-----------|
| Height estimation → scroll jumps | Visible messages measured immediately; two-phase scroll with refinement |
| `animate:flip` removal | Replace with CSS `@keyframes` on newly-added messages only |
| Cross-message text selection | Acceptable trade-off — already fragile with TipTap |
| Search in unmounted messages | Existing retry loop handles delayed mount |

## Key Files

| File | Phase | Change |
|------|-------|--------|
| `frontend/packages/ui/src/components/ReadOnlyMessage.svelte` | 1 | Bidirectional IO, editor destroy/recreate |
| `frontend/packages/ui/src/utils/messageHeightCache.ts` | 2 | New file — height cache |
| `frontend/packages/ui/src/components/ChatHistory.svelte` | 2, 3 | ResizeObserver, windowed rendering |
| `frontend/packages/ui/src/components/ActiveChat.svelte` | 3 | Verify scroll API callers |
| `frontend/packages/ui/src/services/db/messageOperations.ts` | Future | Cursor-based pagination for 500+ message chats |

## Verification Plan

1. **Phase 1**: Open 50+ message chat, scroll through. Monitor DevTools — editors should appear/disappear. Memory should plateau.
2. **Phase 3**: Open 100+ message chat. DOM should have ~15-20 message wrappers. Verify: scroll to bottom/top, search scroll, chat switch restore, streaming with spacer, scroll away during streaming.
3. **E2E**: `chat-scroll-streaming.spec.ts` must pass unchanged.
