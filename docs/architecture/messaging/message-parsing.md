---
status: active
last_verified: 2026-03-24
key_files:
  - frontend/packages/ui/src/message_parsing/parse_message.ts
  - frontend/packages/ui/src/message_parsing/embedParsing.ts
  - frontend/packages/ui/src/message_parsing/serializers.ts
  - frontend/packages/ui/src/message_parsing/types.ts
  - frontend/packages/ui/src/message_parsing/documentEnhancement.ts
  - frontend/packages/ui/src/message_parsing/streamingSemantics.ts
  - frontend/packages/ui/src/components/enter_message/utils/tiptapContentProcessor.ts
---

# Message Parsing Architecture

> All messages are stored as markdown and parsed client-side into TipTap JSON for rendering, with a unified `parse_message()` function handling both editing and display modes.

## Why This Exists

Messages flow between users, the LLM, and storage as markdown text. The client must convert this markdown into rich TipTap document nodes for rendering -- detecting code blocks, URLs, embed references, tables, and inline formatting. A single parser ensures consistent behavior across drafts, sent messages, and streamed AI responses.

## How It Works

### Unified Parser: `parse_message()`

The entry point is `parse_message()` in [parse_message.ts](../../frontend/packages/ui/src/message_parsing/parse_message.ts). It accepts raw markdown, a mode (`write` or `read`), and options including `unifiedParsingEnabled` and `role`.

**Pipeline (when unified parsing is enabled):**

1. **Markdown to TipTap** -- `markdownToTipTap()` via [serializers.ts](../../frontend/packages/ui/src/message_parsing/serializers.ts) converts markdown to a basic TipTap document using markdown-it.
2. **Migration check** -- `needsMigration()` / `migrateEmbedNodes()` handles old embed node formats.
3. **Embed parsing** -- `parseEmbedNodes()` in [embedParsing.ts](../../frontend/packages/ui/src/message_parsing/embedParsing.ts) uses a `CodeBlockStateMachine` to detect:
   - **JSON embed references** -- ```` ```json ```` blocks with `{type, embed_id}` become `app-skill-use` nodes (or other types via `normalizeEmbedType`).
   - **`json_embed` blocks** -- Legacy URL-based website embeds.
   - **`document_html` blocks** -- Rich documents for the Docs app.
   - **Regular code blocks** -- Any fenced code becomes `code-code` or `docs-doc` embeds.
   - **Standalone URLs** (read mode only) -- Detected outside code blocks; YouTube URLs become `videos-video`, others become `web-website`.
   - **Tables** -- Now converted to sheet embeds by the backend (`stream_consumer.py`), which replaces raw markdown tables with JSON embed references.
4. **Streaming semantics** -- `handleStreamingSemantics()` in [streamingSemantics.ts](../../frontend/packages/ui/src/message_parsing/streamingSemantics.ts) detects unclosed code blocks in write mode and creates partial embed nodes with `status: "processing"` for visual feedback.
5. **Document enhancement** -- `enhanceDocumentWithEmbeds()` in [documentEnhancement.ts](../../frontend/packages/ui/src/message_parsing/documentEnhancement.ts) replaces raw text/code-fence nodes with unified `embed` atom nodes, deduplicating by embed_id.
6. **Embed grouping** -- `groupConsecutiveEmbedsInDocument()` groups consecutive same-type embeds into group nodes (see [message-previews-grouping.md](./message-previews-grouping.md)).
7. **Assistant embed promotion** (read mode, assistant role only) -- `promoteAssistantEmbedsToLarge()` converts non-app-skill embeds to `embedPreviewLarge` block nodes. Code groups are exempt and keep their horizontal scroll layout.
8. **Embed link conversion** (read mode only) -- `convertEmbedLinks()` rewrites `[text](embed:ref)` link marks into `embedInline` atom nodes. Uses a two-pass approach: Pass 1 collects `app_id` from sibling embed nodes; Pass 2 converts links using that as fallback. `[!](embed:ref)` and `[](embed:ref)` become `embedPreviewLarge` block nodes.
9. **Block embed hoisting** -- `_hoistBlockEmbedPreviews()` lifts `embedPreviewLarge` nodes out of paragraph wrappers to document level, then assigns `carouselIndex`/`carouselTotal` to consecutive runs for slideshow navigation.
10. **Source quote conversion** (read mode only) -- `convertSourceQuotes()` detects blockquotes containing a single `embedInline` child (pattern: `> [quoted text](embed:ref)`) and converts them to `sourceQuote` atom nodes.

**Fast path (unified parsing disabled):** Falls back to `markdownToTipTap()` only, still applying embed link and source quote conversion in read mode.

### Serialization: TipTap to Markdown

`tipTapToCanonicalMarkdown()` in [serializers.ts](../../frontend/packages/ui/src/message_parsing/serializers.ts) walks the TipTap document and serializes each node back to canonical markdown. Embed nodes are serialized via their group handler's `groupToMarkdown()` method, producing fenced code blocks with JSON content.

### Legacy Processor

[tiptapContentProcessor.ts](../../frontend/packages/ui/src/components/enter_message/utils/tiptapContentProcessor.ts) provides `preprocessTiptapJsonForEmbeds()`, which is still imported by `ChatHistory.svelte` as a fallback path. It uses regex-based detection for URLs and code blocks within TipTap text nodes, but the unified parser is the primary path.

## Edge Cases

- **Duplicate embed references** -- `enhanceDocumentWithEmbeds` tracks rendered embed_ids and marks duplicates for removal, preventing double-rendering during streaming.
- **Stable node IDs** -- All embed IDs are deterministic (derived from content hash or server embed_id) so TipTap can match and update nodes during streaming without destroying/recreating NodeViews.
- **URLs inside markdown links** -- `parseEmbedNodes()` builds protected ranges for URLs within `[text](url)` syntax and skips them during standalone URL detection.
- **Mixed embed: link forms** -- `[!](embed:ref)` renders as large preview card; `[](embed:ref)` (empty text) also renders as large preview; `[text](embed:ref)` renders as inline badge. Line-range fragments (`#L10-L20`) are parsed for code focus highlighting.
- **Scattered app-skill-use embeds** -- When the LLM interleaves text between tool calls, `groupScatteredAppSkillEmbeds()` merges all app-skill-use embeds across the document into a single group at the first occurrence position.

## Data Structures

### EmbedNodeAttributes

Defined in [types.ts](../../frontend/packages/ui/src/message_parsing/types.ts). Key fields:

- `id` -- UUID per Q&A, deterministically derived
- `type` -- `EmbedType` union: `code-code`, `web-website`, `videos-video`, `docs-doc`, `sheets-sheet`, `app-skill-use`, `image`, `pdf`, `maps`, `recording`, plus group variants (`*-group`) and `focus-mode-activation`
- `status` -- `processing | finished | error | cancelled`
- `contentRef` -- `embed:<server_uuid>` for server embeds, `stream:<id>` during generation, `preview:<type>:<id>` for write-mode previews
- `groupedItems` / `groupCount` -- For group nodes
- `app_id`, `skill_id`, `query`, `provider` -- App skill metadata extracted from JSON references

### ParseMessageOptions

- `unifiedParsingEnabled` -- Feature flag for the full pipeline
- `role` -- `user | assistant | system`, controls embed promotion behavior

## Related Docs

- [Embeds Architecture](./embeds.md) -- Server-side embed storage and the embed reference format
- [Message Previews Grouping](./message-previews-grouping.md) -- How consecutive embeds are grouped
- [Message Input Field](./message-input-field.md) -- Write-mode behavior and editor integration
- [Message Processing](./message-processing.md) -- Backend message processing pipeline
