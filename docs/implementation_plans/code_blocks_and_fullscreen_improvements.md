# Implementation Plan: Code Block Parsing & Fullscreen Improvements

## Overview
This plan covers:
1. **Code block auto-parsing into embeds** (server-side and client-side)
2. **Fullscreen improvements** for video transcript and web read skills
3. **Reference implementation** from web search skill for encrypted content processing

---

## 1. Code Block Auto-Parsing into Embeds

### 1.1 Server-Side: Stream Code Blocks as Embeds (Real-Time Detection)

**Current State:**
- Assistant responses contain code blocks in markdown format (```language\ncode\n```)
- Code blocks are NOT automatically converted to embeds on the server
- They appear as plain markdown code blocks in messages
- Need to detect code blocks **as they stream** and create embeds immediately

**Implementation Location:**
- `backend/apps/ai/tasks/stream_consumer.py` - Detect code blocks in streaming chunks
- `backend/core/api/app/services/embed_service.py` - Create/update code embeds
- `backend/apps/ai/utils/stream_utils.py` - Code block detection utilities

**Implementation Steps:**

1. **Add code block state tracking in stream consumer** (`stream_consumer.py`):
   - Track state: `in_code_block: bool`, `current_code_language: str`, `current_code_content: str`, `current_code_embed_id: str`
   - When processing string chunks, detect code block opening: `chunk.strip().startswith("```")`
   - Extract language from opening fence: ````language` or ````language:filename`

2. **Create processing embed immediately when code block opens**:
   - When ```` detected:
     - Generate `embed_id` (UUID)
     - Create processing embed placeholder via `EmbedService.create_processing_embed_placeholder()`
     - Embed type: `"code"` (not `"app_skill_use"`)
     - Status: `"processing"`
     - Yield embed reference as JSON code block: ````json\n{"type": "code", "embed_id": "..."}\n````
     - Store `embed_id` in state for updates

3. **Update embed content as code streams**:
   - As subsequent chunks arrive (while `in_code_block == True`):
     - Accumulate code content in `current_code_content`
     - Periodically update embed (every N characters or every paragraph)
     - **Create new method**: `EmbedService.update_code_embed_content()` to update cached embed
       - Similar to `update_embed_with_results()` but for code content
       - Updates TOON-encoded content in cache
       - Maintains status as "processing" until finalized
     - Send `send_embed_data` WebSocket event to client with updated content
     - Client receives updates and refreshes embed display

4. **Finalize embed when code block closes**:
   - When closing ```` detected:
     - Finalize code content (remove closing fence from content)
     - Update embed with final content, set status to `"finished"`
     - Send final `send_embed_data` event to client
     - Reset code block state
     - Continue with normal text streaming

5. **Handle edge cases**:
   - Code blocks without language (use empty string)
   - Code blocks that span multiple chunks (accumulate content)
   - Very long code blocks (update periodically, not on every character)
   - Multiple code blocks in same response (track each separately)
   - Code block interrupted by revocation (mark as finished with partial content)

**Reference Implementation:**
- See how skill placeholders are created in `main_processor.py` (lines 928-950)
- See how embed references are yielded as code blocks (line 859-860)
- Follow same pattern: create placeholder → yield reference → update content → finalize

**Reference:**
- See how `EmbedService.create_embeds_from_skill_results()` handles skill results
- Follow the same pattern: TOON encoding → vault encryption → cache → embed reference

---

### 1.2 Client-Side: Auto-Parse Code Blocks in Message Input (On Closing)

**Current State:**
- `tiptapContentProcessor.ts` already detects code blocks and creates embed nodes
- However, embeds are created without `contentRef` (no actual embed storage)
- **Key difference from server-side**: Client should convert to embed when code block CLOSES, not when it opens

**Implementation Location:**
- `frontend/packages/ui/src/components/enter_message/utils/tiptapContentProcessor.ts`
- `frontend/packages/ui/src/components/enter_message/MessageInput.svelte`
- `frontend/packages/ui/src/services/embedStore.ts`

**Implementation Steps:**

1. **Detect code block closing in TipTap editor**:
   - Monitor editor content changes
   - Detect when closing fence (```) is typed
   - Extract complete code block: language, content, filename (if present)

2. **Create embed when code block closes**:
   - When closing ```` detected:
     - Extract code content (everything between opening and closing fences)
     - Generate `embed_id` (UUID)
     - Create embed entry in EmbedStore with:
       - `type: 'code-code'`
       - `language: extracted_language` (or empty string)
       - `content: code_content` (TOON-encoded)
       - `status: 'finished'`
     - Update embed node in TipTap document with `contentRef: 'embed:{embed_id}'`
     - Replace code block markdown with embed node

3. **Handle code block editing**:
   - If code block content changes after embed creation:
     - Update embed content in EmbedStore
     - Maintain same `embed_id` (update vs create new)
   - If code block is deleted, remove embed from EmbedStore

4. **Integration with existing code block detection**:
   - Current `tiptapContentProcessor.ts` creates embed nodes on code block detection
   - Modify to only create placeholder nodes (without contentRef) while code block is open
   - Convert to full embed (with contentRef) only when closing fence is detected

**Reference:**
- See how `tiptapContentProcessor.ts` handles URL embeds
- Follow similar pattern: detect → create embed → update node

---

## 2. Fullscreen Improvements

### 2.1 Video Transcript: Show Full Transcript in Fullscreen

**Current State:**
- `VideoTranscriptSkillFullscreen.svelte` exists and displays transcript
- However, it may not be showing the full transcript properly
- Need to verify transcript is fully displayed

**Implementation Location:**
- `frontend/packages/ui/src/components/app_skills/VideoTranscriptSkillFullscreen.svelte`

**Implementation Steps:**

1. **Verify transcript data structure**:
   - Check `decodedContent.results[].transcript` contains full transcript
   - Verify transcript is not truncated in preview vs fullscreen

2. **Ensure full transcript display**:
   - Current implementation shows `result.transcript` in `.transcript-content`
   - Verify CSS allows full scroll (currently has `max-height: 600px`)
   - Ensure all results are displayed (not just first one)

3. **Add transcript formatting** (if needed):
   - Preserve line breaks
   - Add timestamp display if available
   - Format for readability

**Reference:**
- See `VideoTranscriptSkillFullscreen.svelte` lines 161-180
- Current implementation should work, but verify data flow

---

### 2.2 Web Read: Create Fullscreen Component for Full Markdown

**Current State:**
- Web read skill returns markdown content in `decodedContent.results[].markdown`
- No fullscreen component exists (`WebReadSkillFullscreen.svelte` not found)
- Fullscreen view falls back to generic JSON display

**Implementation Location:**
- Create: `frontend/packages/ui/src/components/app_skills/WebReadSkillFullscreen.svelte`
- Update: `frontend/packages/ui/src/components/ActiveChat.svelte` (add fullscreen handler)

**Implementation Steps:**

1. **Create `WebReadSkillFullscreen.svelte` component**:
   - Similar structure to `VideoTranscriptSkillFullscreen.svelte`
   - Use `AppSkillFullscreenBase` as base component
   - Display:
     - Website title, URL, favicon
     - Full markdown content (rendered as HTML)
     - Metadata (language, og_image, etc.)

2. **Render markdown content**:
   - Use markdown renderer (check existing markdown rendering in codebase)
   - Display in scrollable container
   - Preserve markdown formatting (code blocks, lists, etc.)

3. **Add fullscreen handler in `ActiveChat.svelte`**:
   - Add condition for `appId === 'web' && skillId === 'read'`
   - Load markdown from `decodedContent.results[].markdown`
   - Pass to `WebReadSkillFullscreen` component

**Reference:**
- See `VideoTranscriptSkillFullscreen.svelte` for structure
- See `WebSearchSkillFullscreen.svelte` for styling patterns
- Check how markdown is rendered elsewhere in the codebase

---

## 3. Web Search Skill Reference: Encrypted Content Processing

**Research Task:**
Understand how web search skill processes encrypted TOON content for reference.

**Key Findings:**

1. **TOON Format Usage** (`backend/apps/web/skills/search_skill.py`):
   - Text data is converted to TOON format before sanitization
   - TOON format reduces token usage by 30-60% vs JSON
   - Structure: `{"results": [{"title": "...", "description": "...", "extra_snippets": "..."}]}`
   - Extra snippets converted to pipe-delimited string for tabular format

2. **Sanitization Process**:
   - Content sanitized via `sanitize_external_content()` (LLM-based)
   - Sanitized TOON is decoded back to dict
   - Validates structure (all results must be dicts)
   - Merges sanitized content with non-text metadata

3. **Embed Creation**:
   - Parent embed: `app_skill_use` type with query, provider, metadata
   - Child embeds: `website` type, one per search result
   - Parent embed contains `embed_ids` array pointing to children
   - All content stored as TOON-encoded strings

4. **Fullscreen Display**:
   - Fullscreen loads parent embed
   - Extracts `embed_ids` from decoded content
   - Loads child website embeds from EmbedStore
   - Decodes TOON content for each child
   - Transforms to results array for display

**Key Patterns to Follow:**
- Use TOON format for content storage (space-efficient)
- Sanitize external content before embedding
- Create parent-child embed structure for composite results
- Decode TOON content in fullscreen view
- Handle both array and pipe-separated string formats for `embed_ids`

---

## Implementation Order

1. ✅ **Research web search skill** (reference implementation)
2. **Server-side code block streaming** (highest priority - affects all assistant responses)
   - Detect code block opening → create processing embed → yield reference
   - Update embed content as code streams paragraph by paragraph
   - Finalize embed when code block closes
3. **Client-side code block parsing** (improves user experience)
   - Detect code block closing → create embed → update node
4. **Video transcript fullscreen fix** (quick win)
5. **Web read fullscreen component** (new feature)

---

## Testing Checklist

- [ ] Server-side: Code blocks in assistant responses are converted to embeds
- [ ] Server-side: Embed references appear in message markdown
- [ ] Client-side: Code blocks typed in input are converted to embeds when closed
- [ ] Client-side: Code embed content is stored in EmbedStore
- [ ] Video transcript: Full transcript displays in fullscreen view
- [ ] Web read: Fullscreen component displays full markdown content
- [ ] Web read: Markdown is properly rendered (formatting preserved)
- [ ] All fullscreen views: Close button works, content scrolls properly

---

## Files to Modify/Create

### Backend:
- `backend/apps/ai/tasks/stream_consumer.py` - Add real-time code block detection and streaming
- `backend/core/api/app/services/embed_service.py` - Add code embed creation/update methods
- `backend/apps/ai/utils/stream_utils.py` - Add code block detection utilities (if needed)

### Frontend:
- `frontend/packages/ui/src/components/enter_message/utils/tiptapContentProcessor.ts` - Enhance code block handling
- `frontend/packages/ui/src/components/enter_message/MessageInput.svelte` - Add code block completion detection
- `frontend/packages/ui/src/components/app_skills/VideoTranscriptSkillFullscreen.svelte` - Verify full transcript display
- `frontend/packages/ui/src/components/app_skills/WebReadSkillFullscreen.svelte` - **CREATE NEW**
- `frontend/packages/ui/src/components/ActiveChat.svelte` - Add web read fullscreen handler

---

## Notes

- Code embeds should follow the same architecture as other embeds (TOON format, vault encryption, EmbedStore)
- Code blocks without language should still create embeds (empty language string)
- Very long code blocks may need special handling (chunking or truncation)
- Markdown rendering for web read should use existing markdown renderer if available
- All changes should maintain backward compatibility with existing embeds

