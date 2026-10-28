---
status: active
last_verified: 2026-03-24
key_files:
- frontend/packages/ui/src/components/enter_message/MessageInput.svelte
- frontend/packages/ui/src/components/enter_message/editorConfig.ts
- frontend/packages/ui/src/components/enter_message/extensions/Embed.ts
- frontend/packages/ui/src/components/enter_message/extensions/WikiInlineNode.ts
- frontend/packages/ui/src/components/enter_message/handlers/sendHandlers.ts
- frontend/packages/ui/src/components/enter_message/embedHandlers.ts
- frontend/packages/ui/src/message_parsing/parse_message.ts
- frontend/packages/ui/src/message_parsing/serializers.ts
claims:
- id: arch-messaging-message-input-field-behavior
  type: unit
  claim: Message Input Field Architecture is grounded in current source-of-truth files that parse or resolve successfully.
  source:
  - frontend/packages/ui/src/components/enter_message/MessageInput.svelte
  - frontend/packages/ui/src/components/enter_message/editorConfig.ts
  - frontend/packages/ui/src/components/enter_message/extensions/Embed.ts
  - frontend/packages/ui/src/components/enter_message/handlers/sendHandlers.ts
  - frontend/packages/ui/src/components/enter_message/embedHandlers.ts
  test:
    file: scripts/tests/test_architecture_behavioral_claims.py
    command: python3 -m pytest scripts/tests/test_architecture_behavioral_claims.py
    assertion: arch-messaging-message-input-field-behavior
  verified: '2026-06-11'
- id: arch-messaging-message-input-field-source-1
  type: static
  file: scripts/tests/test_architecture_static_claims.py
  assertion: arch-messaging-message-input-field-source-1
  anchors:
  - type: file_exists
    path: frontend/packages/ui/src/components/enter_message/MessageInput.svelte
- id: arch-messaging-message-input-field-source-2
  type: static
  file: scripts/tests/test_architecture_static_claims.py
  assertion: arch-messaging-message-input-field-source-2
  anchors:
  - type: file_exists
    path: frontend/packages/ui/src/components/enter_message/editorConfig.ts
- id: arch-messaging-message-input-field-source-3
  type: static
  file: scripts/tests/test_architecture_static_claims.py
  assertion: arch-messaging-message-input-field-source-3
  anchors:
  - type: file_exists
    path: frontend/packages/ui/src/components/enter_message/embedHandlers.ts
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
- **WikiInlineNode** -- Read-only interactive Wikipedia references in sent messages. It preserves the selected article title and language and opens the proxied article fullscreen.
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
- `handleSend()` in [sendHandlers.ts](../../../frontend/packages/ui/src/components/enter_message/handlers/sendHandlers.ts) snapshots the clicked TipTap document, cancels its pending draft save, clears the ordinary composer and emits one provisional sending row before asynchronous preparation. Finished attachment references are normalized in that snapshot; later edits stay in the live editor.
- URL/embed preparation, PII handling, encryption and durable admission replace the same stable message ID with the prepared canonical payload. A disconnected send retains that ID for reconnect. A preparation failure restores the submitted draft only while the original chat/editor still owns an empty composer; it cannot overwrite a newer draft.
- Embed nodes are serialized to their fenced code block format (JSON references for server embeds, raw code for preview embeds).
- Wiki learning questions use a separate editor and the normal encrypted send path with `preserveDraft`; top-level boolean `preserve_draft: true` also retains the server draft. Rejected questions retain the article and composer for retry.

**Web microphone recordings:**
- An empty draft keeps the minimized recording layout. If text or embeds already exist when capture starts, the editor retains its expanded, scrollable layout and the compact recording bar sits over its bottom edge. Ordinary composer controls are hidden while recording owns this area. Existing images can open and close in fullscreen while capture continues; Escape belongs to the open viewer.
- Recording uses ephemeral realtime transcription and correction. Corrected text is inserted as literal TipTap text and hard breaks at the originating, transaction-mapped selection, preserving surrounding notes. Finish or Enter leaves the result editable for review. The recording overlay also reuses the minimized composer's `CompactSendButton`: choosing Send during recording or correction requests one normal composer submission after correction succeeds.
- The shared web composer creates no new recording embed and uploads no permanent recording file. Existing audio embeds, uploaded audio files and assistant speech output retain their separate paths. Native Apple recording is a separate implementation.
- Submission waits while correction is pending; a requested recording Send stays disabled to prevent duplicate requests. Cancel, an error, a new recording, editor destruction, chat/route changes, a sent draft or a queued edit invalidate the old insertion context and its Send request. Recording-owned audio resources close on completion/cancel; the normal Finish path restores focus after the overlay closes and only while the context still matches.

### Layout Behavior

- **Auto-expanding height** -- The input field grows with content up to a configurable max height.
- **Fullscreen toggle** -- When max height is reached, a fullscreen button appears in the top-right corner. Clicking it expands the editor to full viewport height.
- **Scroll minimization** -- When the user scrolls through chat history, the input field minimizes to show only the last few lines of the draft.
- **Send button and focus** -- A focused nonempty composer shows the translated Send label. A blurred nonempty composer minimizes and retains a round orange up-arrow Send button. Ordinary text focus uses no gray or translucent backdrop and leaves welcome content, established chat transcripts and existing workspace, task and workflow-editor content at full opacity. Background controls remain inert while focused; a parent pointer handler dismisses focus without mounting a full-area backdrop button. Recording, map and anonymous-attachment overlays retain their separate welcome suppression.
- **Workflow warm-up** -- Composer focus can send a debounced, authenticated metadata-only warm-up hint. Draft text is absent, and the hint invokes no AI inference. Server rate limits and a scoped lock bound the work; normal discovery handles cache misses or failure.

### Mentions

The `@` character triggers [MentionDropdown.svelte](../../frontend/packages/ui/src/components/enter_message/MentionDropdown.svelte). Mention search is handled by [mentionSearchService.ts](../../frontend/packages/ui/src/components/enter_message/services/mentionSearchService.ts), which searches mates, AI models, app skills, and explicitly activated Wikipedia titles. Generic `@` discovery does not send query text to Wikimedia. Selecting a Wiki result inserts an atom node serialized as `@wikipedia:<language>:<percent-encoded-title>`. Read mode converts that canonical directive into an interactive `WikiInlineNode`; write mode retains the directive so editing and reserialization remain lossless.

### Drafts

Draft persistence is managed by `draftService` (imported from `../../services/draftService`). Drafts are saved automatically on changes and restored when returning to a chat. The service handles encryption and IndexedDB storage.

Opening a saved Study goal flushes the composer before entering the Apps workspace. Leaving Chat invalidates the route's loaded-chat marker because ActiveChat is unmounted; its replacement loads the encrypted draft again. A fresh empty editor is not treated as a newer local edit merely because the saved draft state survived the unmount. Explicit unsaved or in-progress edit flags still protect local edits.

### PII Detection

The synchronous `piiDetectionService.ts` keeps supported patterns and configured private entries immediate. The `webPIIDetectionService.ts` adds local Redact inference for short composer and recording/transcript text. Official production builds enable it by default; the persistent Enhanced personal data protection switch returns to complete basic detection. Encrypted opt-outs hydrate before model/licensing initialization, and preference changes invalidate stale prepared sends. Linux document model scanning remains disabled. The inference Worker has no direct network access; a trusted broker verifies pinned public assets and permits only the approved licensing fields. The privacy policy explains the remaining licensing metadata and connection exposure. Inputs above 2,048 UTF-16 code units use basic detection. One lazy 2,500 ms enhancement budget is shared across each send's exclusions, recording fields and message body; slow downloads continue in the background. Basic fallback uses the existing one-time notification, without another status row. Final send uses immutable ownership/settings snapshots, retains exclusions, and stores originals only in encrypted owner mappings. Read-only messages display compact labels such as `[ADDRESS_1]` while retaining unique canonical tokens for copy, transport and restoration. See [the trial boundary and privacy assessment](../privacy/redact-browser-dev-trial.md).

## Edge Cases

- **Backspace on embed previews** -- Pressing backspace after an embed preview converts it back to editable markdown text. For groups, the last item is split off while the remaining items stay grouped (see [message-previews-grouping.md](./message-previews-grouping.md)).
- **Embed cleanup on deletion** -- When an embed node is removed from the editor, `cleanupRemovedEmbed()` in [Embed.ts](../../frontend/packages/ui/src/components/enter_message/extensions/Embed.ts) asynchronously deletes the corresponding entry from EmbedStore to prevent orphaned data.
- **Edit mode** -- `editMessageStore` allows editing previously sent messages. The original message content is loaded back into the editor as markdown.
- **Queued follow-up edit** -- Edit preserves the queued message ID and expected revision. Changed Send uses server compare-and-swap; unchanged Send leaves the queue untouched. Cancel edit appears above the composer and restores the independent unsent draft. Steer instead requests current-run consumption at a completed tool/agent boundary, subject to fresh gates and compatible context.
- Entering a queued edit synchronously blocks Send and temporarily makes the editor read-only. The draft service drains the ordinary draft's active save and pending resave before queued text replaces it, with chat, editor, account and Team fences. This prevents a fast Send from creating a separate message and prevents a delayed draft save from persisting queued text as the independent draft.
- **Notification reply** -- `pendingNotificationReplyStore` pre-fills the input when replying from a notification.

## Related Docs

- [Message Parsing](./message-parsing.md) -- The unified parser pipeline used in both write and read modes
- [Message Previews Grouping](./message-previews-grouping.md) -- How consecutive embeds are grouped in the input
- [Embeds Architecture](./embeds.md) -- Server-side embed storage and reference format
- [Message Processing](./message-processing.md) -- Backend processing after the message is sent

## Prepared sends and contextual suggestions

Composer focus or microphone activation prepares one invisible chat identity and encryption key for the current account and Team. Eligible first personal text turns journal one `chat_turn_admit` frame and send it before related discovery completes; correlated routing and private-detail frames follow. The encrypted journal remains until message confirmation and both context acknowledgements, and retries reuse the original IDs and timestamp. Existing saved-chat history, attachment, Team and incognito paths retain their gates.

Successful main inference can provide a separate next-message suggestion. Its ghost stays outside the editor document; Tab or the localized touch control inserts editable text without sending. Typing, Escape, recording, attachments, queued edits and scope changes keep user ownership. Clients encrypt the suggestion before durable storage and cross-device sync; postprocessor chips remain separate.
