---
status: active
last_verified: 2026-03-24
key_files:
  - frontend/packages/ui/src/components/enter_message/MessageInput.svelte
  - frontend/packages/ui/src/components/enter_message/editorConfig.ts
  - frontend/packages/ui/src/components/enter_message/extensions/Embed.ts
  - frontend/packages/ui/src/components/enter_message/handlers/sendHandlers.ts
  - frontend/packages/ui/src/components/enter_message/embedHandlers.ts
  - frontend/packages/ui/src/message_parsing/parse_message.ts
  - frontend/packages/ui/src/message_parsing/serializers.ts
---

# Message Input Field Architecture

> The TipTap-based message editor that provides real-time markdown parsing, inline embed previews, mentions, file attachments, and serialization to canonical markdown for sending.

## Why This Exists

The message input field is the primary interaction point for users composing messages. It must handle rich content types (code blocks, URLs, tables, documents) inline while keeping the underlying storage format as plain markdown. The editor uses TipTap (ProseMirror wrapper) with custom extensions for embed nodes, mentions, and markdown highlighting.

## How It Works

### Editor Setup

[MessageInput.svelte](../../frontend/packages/ui/src/components/enter_message/MessageInput.svelte) initializes a TipTap `Editor` instance with extensions configured in [editorConfig.ts](../../frontend/packages/ui/src/components/enter_message/editorConfig.ts). The unified parser (`parse_message` from [parse_message.ts](../../frontend/packages/ui/src/message_parsing/parse_message.ts)) is imported directly and called in write mode to convert markdown into TipTap JSON with inline embed previews.

Key extensions:
- **Embed** ([Embed.ts](../../frontend/packages/ui/src/components/enter_message/extensions/Embed.ts)) -- Unified atom node for all embed types. Renders via type-specific renderers. Handles backspace behavior (group splitting, convert-to-text) through `GroupHandlerRegistry`.
- **EmbedInlineNode** / **EmbedPreviewLargeNode** -- Read-mode embed link badges and large preview cards.
- **MateNode** / **AIModelMentionNode** / **BestModelMentionNode** / **GenericMentionNode** -- @mention atom nodes for team mates, AI models, and generic mentions.
- **MarkdownExtensions** -- Syntax highlighting for headings, bold, italic, lists, etc. in edit mode.
- **SourceQuoteNode** -- Styled clickable quote cards for `> [text](embed:ref)` patterns.
- **Placeholder** -- Placeholder text when the editor is empty.

### Content Flow

**Typing/pasting to embed detection:**
1. User types or pastes content into the TipTap editor.
2. `parse_message(markdown, 'write')` is called, which runs the full pipeline including `handleStreamingSemantics()` for unclosed blocks.
3. Detected embeds (code blocks, URLs, tables) appear as inline previews while being typed. Unclosed blocks show as highlighted "processing" state.
4. Once a block is closed (closing `` ``` ``, space after URL, empty line after table), the embed renders as a finished preview.

**Paste handling:**
- Code from VS Code is detected via clipboard HTML and creates code embeds with language detection ([codeEmbedService.ts](../../frontend/packages/ui/src/components/enter_message/services/codeEmbedService.ts)).
- URLs are processed by [urlMetadataService.ts](../../frontend/packages/ui/src/components/enter_message/services/urlMetadataService.ts), which creates proper embeds with `embed_id` for LLM context.
- File attachments (images, PDFs, EPUBs, audio) are handled by [fileHandlers.ts](../../frontend/packages/ui/src/components/enter_message/fileHandlers.ts) and [embedHandlers.ts](../../frontend/packages/ui/src/components/enter_message/embedHandlers.ts).

**Sending:**
- `handleSend()` in [sendHandlers.ts](../../frontend/packages/ui/src/components/enter_message/handlers/sendHandlers.ts) serializes the TipTap document back to canonical markdown via `tipTapToCanonicalMarkdown()` from [serializers.ts](../../frontend/packages/ui/src/message_parsing/serializers.ts).
- Embed nodes are serialized to their fenced code block format (JSON references for server embeds, raw code for preview embeds).
- Draft state is flushed and cleared after successful send.

### Layout Behavior

- **Auto-expanding height** -- The input field grows with content up to a configurable max height.
- **Fullscreen toggle** -- When max height is reached, a fullscreen button appears in the top-right corner. Clicking it expands the editor to full viewport height.
- **Scroll minimization** -- When the user scrolls through chat history, the input field minimizes to show only the last few lines of the draft.
- **Send button** -- Appears in the bottom-right corner when the input is non-empty, displacing camera/recording buttons to the left.

### Mentions

The `@` character triggers [MentionDropdown.svelte](../../frontend/packages/ui/src/components/enter_message/MentionDropdown.svelte). Mention search is handled by [mentionSearchService.ts](../../frontend/packages/ui/src/components/enter_message/services/mentionSearchService.ts), which searches mates, AI models, and app skills. Selected mentions insert atom nodes that serialize to `@mention` syntax.

### Drafts

Draft persistence is managed by `draftService` (imported from `../../services/draftService`). Drafts are saved automatically on changes and restored when returning to a chat. The service handles encryption and IndexedDB storage.

### PII Detection

[piiDetectionService.ts](../../frontend/packages/ui/src/components/enter_message/services/piiDetectionService.ts) scans message content for personally identifiable information before sending. When PII is detected, [PIIWarningBanner.svelte](../../frontend/packages/ui/src/components/enter_message/PIIWarningBanner.svelte) shows a warning banner.

## Edge Cases

- **Backspace on embed previews** -- Pressing backspace after an embed preview converts it back to editable markdown text. For groups, the last item is split off while the remaining items stay grouped (see [message-previews-grouping.md](./message-previews-grouping.md)).
- **Embed cleanup on deletion** -- When an embed node is removed from the editor, `cleanupRemovedEmbed()` in [Embed.ts](../../frontend/packages/ui/src/components/enter_message/extensions/Embed.ts) asynchronously deletes the corresponding entry from EmbedStore to prevent orphaned data.
- **Edit mode** -- `editMessageStore` allows editing previously sent messages. The original message content is loaded back into the editor as markdown.
- **Notification reply** -- `pendingNotificationReplyStore` pre-fills the input when replying from a notification.

## Related Docs

- [Message Parsing](./message-parsing.md) -- The unified parser pipeline used in both write and read modes
- [Message Previews Grouping](./message-previews-grouping.md) -- How consecutive embeds are grouped in the input
- [Embeds Architecture](./embeds.md) -- Server-side embed storage and reference format
- [Message Processing](./message-processing.md) -- Backend processing after the message is sent
