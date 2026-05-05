---
status: active
last_verified: 2026-05-03
key_files:
  - backend/apps/ai/instructions/base_diff_editing_instruction.md
  - backend/apps/ai/tasks/stream_consumer.py
  - backend/core/api/app/services/embed_service.py
  - backend/core/api/app/services/embed_diff_service.py
  - backend/core/directus/schemas/embed_diffs.yml
  - frontend/packages/ui/src/services/embedDiffStore.ts
  - frontend/packages/ui/src/components/embeds/shared/EmbedVersionTimeline.svelte
---

# Embed Diff-Based Editing

> Instead of regenerating full content on every edit, the assistant outputs unified diffs
> that patch existing embeds in-place. Saves output tokens, reduces storage, and enables
> a version timeline where users can scrub through the edit history.

## Why This Exists

- **Token savings:** A 200-line code embed with a 5-line change outputs ~10 lines (diff) instead of 200 (full regen)
- **Storage savings:** Diffs are ~5-15% the size of full content; only the latest snapshot is stored full
- **Version timeline:** Users can see how their code/doc/sheet evolved over time, scrub between versions
- **Sharing:** Share link includes full history — recipients see the evolution
- **Audit trail:** Every change is tracked with timestamp and diff

## How It Works

### LLM Output Flow

```
User: "rename the function to parse_csv"
    ↓
main_processor detects diffable embeds in history → injects base_diff_editing_instruction
    ↓
LLM outputs:  ```diff:process_data.py-k8D
              @@ -5,3 +5,3 @@
              -def process_csv(
              +def parse_csv(
              ```
    ↓
stream_consumer detects ```diff:<embed_ref> fence
    ↓
Resolves embed_ref → embed_id via file_path_index
    ↓
Fetches current content from Redis cache
    ↓
Applies unified diff (3-tier: exact → fuzzy → visual fallback)
    ↓
On success: updates encrypted_content (new full snapshot) + appends embed_diffs row
    ↓
Client receives embed update via WebSocket (same as today)
```

### Version Storage Model

```
embed (row in embeds collection)
├── encrypted_content = ALWAYS latest full snapshot (vN)
├── version_number = N (current version)
└── content_hash = SHA256 of latest content

embed_diffs (separate collection, append-only)
├── row v=1: full_snapshot (original content before any edits)
├── row v=2: unified_diff (v1 → v2)
├── row v=3: unified_diff (v2 → v3)
└── row v=N: unified_diff (v(N-1) → vN)
```

**Reconstruction:**
- Latest: read `encrypted_content` directly (zero computation)
- Original (v1): read `embed_diffs[v=1].encrypted_snapshot`
- Any version K: apply patches v2..vK to v1 snapshot (forward-only)

### Diff Application — 3-Tier Fallback

| Tier | Strategy | Success rate |
|------|----------|-------------|
| 1 | Exact patch — context lines must match perfectly | ~90% |
| 2 | Fuzzy patch — allow ±3 line offset for context | ~8% |
| 3 | Visual diff card — show "Suggested Changes" card, embed stays unchanged | ~2% |

**Tier 3 detail:** The diff is rendered as a styled green/red card in the message
(not as a code embed). The original embed is untouched. User sees what the AI
intended and can ask to regenerate or apply manually.

### Instruction Injection

The `base_diff_editing_instruction` is injected into the system prompt **only when**
diffable embeds exist in the chat history. Detection logic in main_processor:

```python
_has_diffable_embeds = any(
    '"type": "code"' in msg or "type: code" in msg or
    '"type": "document"' in msg or "type: document" in msg or
    '"type": "sheet"' in msg or "type: sheet" in msg
    for msg in message_history_contents
)
```

The instruction tells the LLM:
1. When user asks to modify an existing embed, output ```` ```diff:<embed_ref> ```` fence
2. Use standard unified diff format (context lines, @@ hunks)
3. Fall back to full regeneration if change affects >60% of the content
4. Multiple diff blocks in one response are allowed
5. The embed_ref comes from the history (same refs used for inline linking)

### Fence Format

```
```diff:embed_ref
@@ -start,count +start,count @@
 context line
-removed line
+added line
 context line
```
```

- `embed_ref` matches the embed reference from chat history (e.g., `process_data.py-k8D`)
- Standard unified diff format (compatible with `difflib.unified_diff`)
- Multiple hunks supported
- Multiple diff blocks per response supported (different embed_refs)

## Data Structures

### `embed_diffs` Collection (Directus)

| Field | Type | Purpose |
|-------|------|---------|
| `id` | uuid | Primary key (auto) |
| `embed_id` | string | FK to embeds.embed_id |
| `version_number` | integer | Version this row represents |
| `encrypted_snapshot` | text | Full content for v=1 only (null for v>1) |
| `encrypted_patch` | text | Unified diff for v>1 (null for v=1) |
| `hashed_user_id` | string | Owner (for access control) |
| `created_at` | integer | Unix timestamp of this version |

Encryption: same key as parent embed (`embed_key` from `embed_keys` collection).

### IndexedDB Sync

`embed_diffs` rows sync to IndexedDB in a new `embedDiffs` object store:
- **Eager sync:** Only the latest diff (for undo support)
- **Lazy sync:** Full history fetched on-demand when user opens timeline view
- Key: `{embed_id}_{version_number}`
- Encrypted with the same embed_key as the parent

### WebSocket Events

| Event | Direction | Payload |
|-------|-----------|---------|
| `embed_diff_created` | Server → Client | `{embed_id, version_number, encrypted_patch, created_at}` |
| `request_embed_diffs` | Client → Server | `{embed_id}` |
| `embed_diffs_response` | Server → Client | `{embed_id, diffs: [...]}` |

## Frontend — Version Timeline

Accessible from fullscreen view of any versioned embed (code, doc, sheet):

- **Timeline scrubber:** horizontal bar showing version dots with timestamps
- **Diff view toggle:** switch between "current state" and "changes" (green/red diff)
- **Version restore:** click any version to view it; "Restore this version" button
- Restore creates a new version (v=N+1) whose content equals the restored snapshot

### UI Integration Points

| Component | Change |
|-----------|--------|
| `CodeEmbedFullscreen.svelte` | Add version timeline when `version_number > 1` |
| `DocsEmbedFullscreen.svelte` | Add version timeline when `version_number > 1` |
| `SheetEmbedFullscreen.svelte` | Add version timeline when `version_number > 1` |
| `EmbedVersionTimeline.svelte` | New shared component — timeline scrubber + diff view |

## Edge Cases

- **Cache miss during diff apply:** Fetch content from Directus (same pattern as embed cache miss)
- **Concurrent edits:** Last-write-wins (single user, no CRDT needed)
- **Diff on empty embed:** If embed has status=processing, queue the diff until finalized
- **Embed shared mid-history:** Recipient gets latest snapshot + full diff history via share key
- **Cold storage:** `embed_diffs` rows follow same cold-storage rules as parent embed

## Embed Types Supported

| Type | Diff unit | Status |
|------|-----------|--------|
| `code` | Line-level unified diff | Implemented |
| `document` | Line-level unified diff on HTML | Implemented |
| `sheet` | Line-level unified diff on markdown table | Implemented |
| `video` (Remotion TSX) | Line-level unified diff on TSX code | Planned (OPE-TBD) |

## Related Docs

- [Embeds Architecture](./embeds.md) — base embed lifecycle
- [Embed Cold Storage](../storage/embed-cold-storage.md) — cold tier includes diffs
- [Message Processing](./message-processing.md) — embed resolution in AI context
