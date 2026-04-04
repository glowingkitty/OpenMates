# Semantic Chat Search via Encrypted Embeddings

> **Status:** Planned
> **Author:** Research session 86ac (2026-04-04)
> **Related:** `searchService.ts`, `postprocessor.py`, `chatSyncService.ts`

## Problem

Current chat search (`searchService.ts`) uses client-side `indexOf()` substring matching.
This means:

- "cheap flights" won't find a chat about "affordable airfare to Barcelona"
- "vacation" won't find a chat about hotels in Rome where the word "vacation" was never used
- "recipe" won't find "Rezept für Kartoffelsuppe" in a German chat
- "that math problem" won't find a chat full of LaTeX equations about quadratic formulas

Users with hundreds of chats can't find what they're looking for unless they remember the exact words used.

## Solution: Encrypted Embedding Vectors

Generate semantic embedding vectors during postprocessing, encrypt them with the chat key (same as content), store server-side, sync to client, and perform similarity search entirely in the browser.

### Why This Preserves Zero-Knowledge

- The server already sees plaintext during postprocessing (to generate summaries, tags, suggestions)
- Embedding vectors are encrypted with the per-chat key before storage — same as `encrypted_chat_summary`
- Similarity search happens client-side after decryption — the server never sees the query
- No privacy regression vs. current architecture

## Architecture

### Embedding Generation (Backend — Postprocessor)

```
User sends message
  → AI responds
    → Postprocessor runs (already has decrypted content)
      → Generate chat summary (existing)
      → Generate chat tags (existing)
      → NEW: Generate embedding from summary + tags
      → Encrypt embedding with chat key
      → Store encrypted embedding in Directus
```

**Model:** OpenAI `text-embedding-3-small` with `dimensions: 512` (truncated from 1536).
- 512 dimensions × 4 bytes = **2 KB per vector**
- Cost: ~$0.02 per 1M tokens (effectively free)
- Latency: ~50ms per API call (non-blocking, runs in postprocessor)

**Input text:** Concatenation of `chat_summary` + `chat_tags` (not raw messages).
This keeps embeddings small, stable (summary updates less often than messages),
and avoids per-message vector bloat.

**Re-embedding trigger:** Whenever the postprocessor updates the chat summary
(already happens after every assistant response).

### Storage (Directus)

New field on the `chats` collection:

```yaml
# In backend/core/directus/schemas/chats.yml
- field: encrypted_embedding_vector
  type: text          # Base64-encoded encrypted Float32Array
  schema:
    max_length: null   # ~3 KB base64 for 512-dim vector + NaCl overhead
  meta:
    hidden: true
```

No pgvector needed. The server is dumb storage — it never queries the vectors.

### Sync (WebSocket — Phased Sync)

Embedding vectors sync alongside existing chat metadata (summary, tags, title).
No new WebSocket message type needed — extend the existing `chat_metadata_update` payload:

```typescript
// In chatSyncServiceHandlersCoreSync.ts
interface ChatMetadataUpdate {
  chat_id: string;
  encrypted_title: string;
  encrypted_chat_summary: string;
  encrypted_chat_tags: string;
  encrypted_embedding_vector: string;  // NEW — base64 NaCl ciphertext
  // ...
}
```

### Client-Side Storage (IndexedDB)

Store encrypted vectors in `chatDB` alongside other chat metadata.
On warm-up, decrypt and build an in-memory vector index (same pattern as `messageIndex` in `searchService.ts`):

```typescript
// New: vectorIndex in searchService.ts
const vectorIndex = new Map<string, Float32Array>(); // chatId → decrypted vector

async function indexChatVector(chatId: string, encryptedVector: string, chatKey: Uint8Array): Promise<void> {
  const decrypted = nacl.secretbox.open(/* ... */);
  vectorIndex.set(chatId, new Float32Array(decrypted.buffer));
}
```

### Search (Client-Side)

```
User types query in search bar
  → Embed query text (see "Query Embedding" below)
  → Cosine similarity against all vectors in vectorIndex
  → Rank by similarity score
  → Return top-K chat IDs
  → Existing substring search finds exact message within those chats
```

**Cosine similarity in JS (512 dims, 1000 chats ≈ 0.5ms):**

```typescript
function cosineSimilarity(a: Float32Array, b: Float32Array): number {
  let dot = 0, normA = 0, normB = 0;
  for (let i = 0; i < a.length; i++) {
    dot += a[i] * b[i];
    normA += a[i] * a[i];
    normB += b[i] * b[i];
  }
  return dot / (Math.sqrt(normA) * Math.sqrt(normB));
}
```

No HNSW or ANN indexing needed at this scale. Brute-force is sub-millisecond.

### Query Embedding

Two options for embedding the user's search query:

| Approach | Pros | Cons |
|----------|------|------|
| **API call to OpenAI** | Same model as stored vectors (best accuracy), tiny payload | Requires network, ~100ms latency, query sent to OpenAI |
| **Client-side ONNX model** (`all-MiniLM-L6-v2`, 23MB) | Fully offline, no query leaves browser | Different model than stored vectors (dimension mismatch), 23MB download, ~50ms WASM inference |

**Recommendation:** Use the OpenAI API for query embedding. The search query is a short string (not sensitive chat content), and matching the same model ensures accurate similarity scores. Add a debounce (300ms) so the API is only called after the user stops typing.

If offline search is a future requirement, a hybrid approach can embed queries locally with a compatible model.

## Size Budget

| Chats | Vector size | Total (encrypted) | Sync time (first load) |
|-------|-------------|-------------------|----------------------|
| 100 | 2 KB | 200 KB | Instant |
| 1,000 | 2 KB | 2 MB | ~1s on 3G |
| 5,000 | 2 KB | 10 MB | ~3s on 3G |
| 10,000 | 2 KB | 20 MB | Lazy-load in batches |

Encryption overhead: 40 bytes per vector (NaCl nonce + MAC) — negligible.

## Search UX

Semantic search augments, not replaces, the current substring search:

1. **Semantic results** — ranked by cosine similarity, shown first with a "Related" label
2. **Exact matches** — current `indexOf()` results, shown with "Exact match" label
3. **Combined ranking** — if a chat appears in both, boost its rank

Threshold: Only show semantic results with similarity > 0.3 (tunable).

## Implementation Phases

### Phase 1: Infrastructure (backend)
- Add `encrypted_embedding_vector` field to Directus `chats` schema
- Add OpenAI embedding call to `postprocessor.py` (after summary generation)
- Encrypt vector with chat key, store via DirectusService
- Include vector in chat metadata WebSocket sync payload

### Phase 2: Client-Side Search (frontend)
- Extend `chatDB` schema to store encrypted vectors
- Add vector decryption + indexing to `searchService.ts` warm-up
- Add query embedding (OpenAI API call from client, debounced)
- Implement cosine similarity ranking
- Merge semantic + substring results in search UI

### Phase 3: Backfill
- Celery task to generate embeddings for existing chats that have summaries
- Process in batches (100 chats/batch) to avoid rate limits
- Skip chats without summaries (they have no searchable content anyway)

## Future Extensions (Out of Scope)

These are natural follow-ons once the vector infrastructure exists:

- **"Related chats" nudge** when starting a new chat (embed draft → find similar past chats)
- **Cross-chat RAG** for AI responses (retrieve relevant past conversations as context)
- **Smarter follow-up suggestions** informed by past conversation topics
- **Message-level embeddings** for precise in-chat search (higher storage cost)
- **Chat deduplication** detection

## Dependencies

- OpenAI `text-embedding-3-small` API access (already have `openai` SDK installed)
- No new infrastructure (no pgvector, no vector DB) — plain Directus text field + client-side search

## Risks

| Risk | Mitigation |
|------|------------|
| OpenAI embedding API downtime | Postprocessor already handles LLM failures gracefully — skip embedding, retry on next summary update |
| Embedding model deprecation | Store model version alongside vector; migration script re-embeds with new model |
| Query embedding latency (user perception) | 300ms debounce hides API latency; show substring results immediately, semantic results async |
| Semantic drift across model versions | Version field enables detection; backfill task handles re-embedding |
