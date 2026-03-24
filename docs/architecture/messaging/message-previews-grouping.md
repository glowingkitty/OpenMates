---
status: active
last_verified: 2026-03-24
key_files:
  - frontend/packages/ui/src/message_parsing/embedGrouping.ts
  - frontend/packages/ui/src/message_parsing/groupHandlers.ts
  - frontend/packages/ui/src/message_parsing/types.ts
  - frontend/packages/ui/src/components/enter_message/extensions/embed_renderers/GroupRenderer.ts
  - frontend/packages/ui/src/components/enter_message/extensions/Embed.ts
---

# Message Previews Grouping Architecture

> Consecutive embed nodes of the same type are automatically merged into horizontal scroll groups, reducing vertical space in messages.

## Why This Exists

LLM responses and user messages frequently contain multiple consecutive embeds of the same type (e.g., several search results, multiple code files, a sequence of URLs). Without grouping, each embed would take full width and stack vertically, creating excessive scrolling. Grouping collapses them into a single horizontally scrollable row with a count header.

## How It Works

### Grouping Pipeline

The function `groupConsecutiveEmbedsInDocument()` in [embedGrouping.ts](../../frontend/packages/ui/src/message_parsing/embedGrouping.ts) runs three passes:

1. **Intra-paragraph grouping** -- `groupConsecutiveEmbedsInParagraph()` groups consecutive `embed` nodes within a single paragraph. Whitespace-only text nodes between embeds do not break a group.

2. **Cross-paragraph grouping** -- `groupConsecutiveEmbedParagraphs()` groups consecutive paragraphs that each contain a single embed. Empty/whitespace-only paragraphs between embed paragraphs (from blank lines in markdown) are treated as ignorable and do not break grouping. These spacer paragraphs are discarded when embeds are grouped.

3. **Scattered app-skill-use merging** -- `groupScatteredAppSkillEmbeds()` handles the common case where the LLM interleaves text between tool calls. All `app-skill-use` and `app-skill-use-group` nodes across the entire document are collected and merged into a single group at the first occurrence position. Text structure between them is preserved.

**Post-processing:** `removeEmptyParagraphsAfterEmbeds()` strips empty paragraphs that immediately follow an embed-only paragraph, preventing visual gaps in read mode.

### Group Handler System

[groupHandlers.ts](../../frontend/packages/ui/src/message_parsing/groupHandlers.ts) defines the `EmbedGroupHandler` interface and per-type handler classes. A singleton `GroupHandlerRegistry` manages all handlers with O(1) Map lookups.

**Registered handlers (6 types):**

| Handler | Embed Type | Group Type | Grouping Rule |
|---------|-----------|------------|---------------|
| `WebWebsiteGroupHandler` | `web-website` | `web-website-group` | Same type only |
| `VideosVideoGroupHandler` | `videos-video` | `videos-video-group` | Same type only |
| `CodeCodeGroupHandler` | `code-code` | `code-code-group` | Same type regardless of language |
| `DocsDocGroupHandler` | `docs-doc` | `docs-doc-group` | Same type only |
| `SheetsSheetGroupHandler` | `sheets-sheet` | `sheets-sheet-group` | Same type only |
| `AppSkillUseGroupHandler` | `app-skill-use` | `app-skill-use-group` | All consecutive app-skill-use embeds regardless of `app_id`/`skill_id` |

Each handler implements four methods:
- `canGroup(nodeA, nodeB)` -- Determines if two embeds can be grouped together
- `createGroup(embedNodes)` -- Creates group attributes from individual embeds
- `handleGroupBackspace(groupAttrs)` -- Returns backspace action (`delete-group`, `split-group`, or `convert-to-text`)
- `groupToMarkdown(groupAttrs)` -- Serializes group back to canonical markdown

### Deterministic Group IDs

`generateDeterministicGroupId()` derives the group ID from the first item's `contentRef` (preferred) or `id`. This is critical for streaming stability -- when a group grows from N to N+1 items during streaming, the stable ID lets TipTap match and update the existing NodeView instead of destroying and recreating it.

### Group Creation

When `createGroup()` is called:
1. A deterministic group ID is generated from the first item (before sorting)
2. Items are sorted by status: `processing` first, then `finished` (app-skill-use adds `error` after finished)
3. Only essential, serializable attributes are extracted into `groupedItems` (varies by type)
4. The group node has type `{embedType}-group`, status `finished`, and null `contentRef`

### Backspace Behavior

Defined per handler via `handleGroupBackspace()`:

- **>2 items** -- Last item is removed and converted to editable text; remaining items stay grouped
- **2 items** -- Group is dissolved: first item becomes individual embed, last becomes editable text
- **1 item** -- Converts to editable text (URL, code fence, or table markdown depending on type)
- **0 items** -- Group node is deleted entirely

The backspace keyboard integration is in [Embed.ts](../../frontend/packages/ui/src/components/enter_message/extensions/Embed.ts).

### Rendering

[GroupRenderer.ts](../../frontend/packages/ui/src/components/enter_message/extensions/embed_renderers/GroupRenderer.ts) handles visual display. It resolves embed data from the EmbedStore, decodes TOON content, and mounts the appropriate Svelte preview component for each item. The renderer supports 40+ distinct embed preview components (web search, code, docs, sheets, images, travel, mail, health, shopping, events, maps, PDFs, etc.).

Group display structure:
- Container div with type-specific CSS class
- Group header showing count (e.g., "3 websites")
- Horizontal scroll container with individual preview cards

## Edge Cases

- **Single embeds** -- When only one embed of a type exists (no consecutive neighbors), it is not wrapped in a group node. It renders as an individual embed.
- **Mixed app-skill types** -- The `AppSkillUseGroupHandler` groups all consecutive `app-skill-use` embeds regardless of `app_id`/`skill_id`. Each item retains its own metadata so the correct Svelte preview component renders within the shared group.
- **Error embeds in groups** -- Failed skill executions stay in the group with an error state indicator. Previously they were filtered out, which caused instability during streaming (group type transitions triggered NodeView recreation).
- **Empty paragraphs between embeds** -- Blank lines in markdown between consecutive embeds do not prevent grouping. The spacer paragraphs are discarded during group creation and also cleaned up in post-processing.
- **Assistant embed promotion** -- In read mode for assistant messages, non-app-skill non-code groups are expanded into consecutive `embedPreviewLarge` nodes for slideshow rendering. Code groups are exempt and keep the horizontal scroll layout. This promotion happens in `promoteAssistantEmbedsToLarge()` in [parse_message.ts](../../frontend/packages/ui/src/message_parsing/parse_message.ts).

## Data Structures

### Group Node Attributes

A group embed node in the TipTap document looks like:

```
type: "embed"
attrs:
  id: "group_embed:<server-uuid>"  (deterministic)
  type: "web-website-group"        ({embedType}-group)
  status: "finished"
  contentRef: null
  groupedItems: [...]              (array of individual EmbedNodeAttributes)
  groupCount: 3                    (number of items)
```

See [types.ts](../../frontend/packages/ui/src/message_parsing/types.ts) for the full `EmbedNodeAttributes` interface.

## Related Docs

- [Message Parsing](./message-parsing.md) -- The unified parser that invokes grouping as step 6
- [Embeds Architecture](./embeds.md) -- Server-side embed storage and embed types
- [Message Input Field](./message-input-field.md) -- Editor integration and backspace behavior
