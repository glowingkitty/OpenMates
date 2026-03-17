# Embed Cold Storage — Phase 3 Architecture Plan

**Status:** Planned — do not implement until embeds table exceeds ~500K rows or `pg_relation_size('embeds') > 5 GB.  
**Prerequisite:** Phases 1 and 2 must already be deployed (indexes, N+1 fix, paginated bulk fetches).  
**Decision log:** See discussion in task "embed scalability phase 1+2" (session 9747, 2026-03-17).

---

## Problem

At current growth rates (≈2,000 embeds/month in early 2026), the `embeds` table will reach
**~500K rows in ~2028** and **~1M rows in ~2030**. The critical constraint is not row count
but the `encrypted_content` column: at an average of 2,566 bytes per row, the content fields
alone account for **93% of the per-row storage** (2,566 / 2,756 total bytes).

| Scale     | Full-row heap size | Metadata-only heap size |
| --------- | ------------------ | ----------------------- |
| 500K rows | ~1.4 GB            | ~95 MB                  |
| 1M rows   | ~2.8 GB            | ~190 MB                 |
| 10M rows  | ~27.5 GB           | ~1.9 GB                 |
| 20M rows  | ~55 GB             | ~3.8 GB                 |

Offloading the three content fields (`encrypted_content`, `encrypted_text_preview`,
`encrypted_diff`) to S3 keeps Directus at **190 MB at 1M rows** vs 2.8 GB — a 93% reduction.
With proper indexes (Phase 1), this table remains fast even at 20M rows.

---

## Proposed Design

### Core Idea

Keep embed **metadata** in Directus forever.  
Move embed **encrypted content** to S3 when an embed has not been accessed in 90 days.

The three fields that move to S3 are all already-opaque AES-256-GCM blobs:

| Field                    | Notes                                                                    |
| ------------------------ | ------------------------------------------------------------------------ |
| `encrypted_content`      | Client-encrypted TOON; server is zero-knowledge for `client` mode embeds |
| `encrypted_text_preview` | Same encryption; lightweight text preview                                |
| `encrypted_diff`         | Only populated for versioned file embeds (currently 0 rows)              |

**Vault-mode embeds** (`encryption_mode = 'vault'`) are a special case — see below.

---

### Schema Changes (one migration)

Two new fields on the `embeds` collection:

```yaml
content_location:
  type: string
  default: "hot"
  note:
    "'hot' = content in Directus (default). 'cold' = content in S3 (cold_storage_key).
    Vault-mode embeds and shared embeds are never marked cold."

cold_storage_key:
  type: string
  nullable: true
  note: "S3 key when content_location='cold'.
    Format: chatfiles/{hashed_user_id}/cold/{embed_id}.enc
    The file is a server-side AES-256-GCM envelope containing a JSON blob:
    { c: encrypted_content, p: encrypted_text_preview, d: encrypted_diff }"
```

The three content fields become **nullable** (they are already nullable in PostgreSQL; Directus
schema just needs to document this explicitly).

Add a PostgreSQL index on `content_location` for the eviction query:

```sql
CREATE INDEX CONCURRENTLY IF NOT EXISTS embeds_content_location_idx
ON public.embeds (content_location) WHERE content_location = 'cold';
```

---

### Eviction Policy (which embeds go cold)

Run a daily Celery Beat task at **04:00 UTC** (after the existing auto-delete tasks).

**An embed is eligible for eviction if ALL of the following are true:**

1. `content_location = 'hot'` (not already cold)
2. `encryption_mode = 'client'` — server has no key, content is opaque; safe to move
3. `is_shared = false` — shared embeds must load fast for share-link recipients
4. `updated_at < now() - 90 days` — not recently active
5. The embed's `hashed_chat_id` does NOT belong to the user's **3 most recently accessed chats**
   (see "Hot Chat Window" section below)

**Embeds that are NEVER evicted:**

- `encryption_mode = 'vault'` — server must be able to decrypt via `GET /v1/embeds/{id}/content`
- `is_shared = true` — share links must load instantly
- Child embeds without `embed_ids` parent (group eviction rules below)

**Group eviction rule:** A composite embed (with `embed_ids`) and all its children are
evicted together or not at all. If any child is ineligible (vault, shared), the parent stays hot.

---

### Hot Chat Window

The 3 most recently accessed chats per user are always kept hot, regardless of `updated_at`.
This prevents the most jarring UX case: a user opening yesterday's chat and seeing skeleton
states while embeds load from S3.

Implementation: the eviction task reads the `chats` collection for each user, orders by
`last_message_timestamp DESC`, takes the first 3, and excludes their `hashed_chat_id` values
from the eviction candidate query.

Choosing **3** (not "last 100" as originally discussed):

- Users typically interact with 1–3 active chats at a time
- Keeping 3 full chats hot means ~36 embeds/user stay in Directus (avg 12 embeds/chat)
- At 100K users with 3 hot chats each = 3.6M hot embed rows — still manageable
- If a user opens a cold chat, the load is felt once; subsequent loads use the re-warmed cache

This number can be tuned upward without a schema change (it's a constant in the task).

---

### S3 Cold File Format

**Bucket:** `chatfiles` (existing bucket, `private` ACL, Hetzner Object Storage)  
**Key:** `{hashed_user_id}/cold/{embed_id}.enc`  
**Content:** AES-256-GCM encrypted JSON (server-side envelope key from Vault)

```json
{
  "c": "<encrypted_content as stored in Directus>",
  "p": "<encrypted_text_preview as stored in Directus, or null>",
  "d": "<encrypted_diff as stored in Directus, or null>"
}
```

The inner values (`c`, `p`, `d`) are already client-encrypted — the server cannot read them.
The outer envelope provides a second layer of encryption so the cold file at rest is not even
readable by someone with raw S3 access to the `chatfiles` bucket.

**Important:** The client decryption flow is unchanged. The client receives the same
`encrypted_content` / `encrypted_text_preview` fields it always received — it never knows
the data came from S3 vs Directus.

---

### Read Path Changes

Affected files:

1. **`phased_sync_handler.py`** — loads embeds for chat sync
2. **`request_embed_handler.py`** — handles individual embed requests

In both, after fetching embeds from Directus:

```python
# New step: re-hydrate cold embeds before sending to client
cold_embeds = [e for e in embeds if e.get('content_location') == 'cold']
if cold_embeds:
    await _hydrate_cold_embeds(cold_embeds, s3_service, encryption_service)
```

`_hydrate_cold_embeds` fetches and decrypts the S3 cold file for each cold embed,
then injects the content fields back into the embed dict. The client receives a response
with the same shape as today — `content_location` is never sent to the client.

**Latency budget:**

- Redis (72h TTL) hit: 0ms overhead (most active embeds are cached)
- S3 GET (Hetzner Object Storage): 20–80ms per object
- For a chat with 10 cold embeds, S3 fetches can be parallelized via `asyncio.gather`
- Acceptable: cold chat loads add ~100ms, which is imperceptible compared to AI response times

---

### Write Path Changes

**`store_embed_handler.py`** — no change for new embeds (always written hot)

**`update_embed` in `embed_methods.py`** — when a cold embed is updated:

1. Fetch cold content from S3
2. Write updated content to Directus (set `content_location = 'hot'`, clear `cold_storage_key`)
3. Delete the S3 cold file
4. Proceed with normal update

This "re-warm on write" ensures versioned embeds return to hot storage after updates.

---

### Deletion Path Changes

`delete_all_embeds_for_chat` in `embed_methods.py` — currently fetches
`id, embed_id, s3_file_keys, is_private, is_shared`. Add `content_location, cold_storage_key`
to this query so the deletion pipeline also deletes the S3 cold file alongside `s3_file_keys`.

No change to logic structure — `_delete_s3_files_for_embeds` just gets two more potential
keys per embed.

---

### Eviction Task Sketch

```python
# New Celery Beat task: app.tasks.embed_cold_storage_tasks.evict_cold_embeds
# Schedule: daily at 04:00 UTC
# Queue: persistence

async def _async_evict_cold_embeds():
    # For each user:
    #   1. Get their 3 most recently active chat hashed_chat_ids
    #   2. Query embeds eligible for eviction (see policy above)
    #      WHERE updated_at < cutoff
    #        AND content_location = 'hot'
    #        AND encryption_mode = 'client'
    #        AND is_shared = false
    #        AND hashed_chat_id NOT IN (3 hot chats)
    #      LIMIT 500 per user per run
    #   3. For each eligible embed:
    #      a. Build cold JSON blob from content fields
    #      b. Encrypt with Vault server key (outer envelope)
    #      c. Upload to S3 at {hashed_user_id}/cold/{embed_id}.enc
    #      d. Update Directus: set content_location='cold',
    #                          cold_storage_key=s3_key,
    #                          encrypted_content=null,
    #                          encrypted_text_preview=null,
    #                          encrypted_diff=null
    pass
```

**Batch size:** 500 embeds/user/run. At 2,000 embeds/user and a 90-day window, a well-populated
user would have ~1,600 cold-eligible embeds. The task handles them over 4 daily runs.

---

### Re-warming on User Activity

When a user opens a previously-cold chat (not in the top-3 window), the `phased_sync_handler`
fetches cold embeds from S3 transparently. However, to avoid re-fetching from S3 on every
subsequent open, the hydrated content is stored in the Redis embed cache (`embed:{embed_id}`,
72h TTL) just as hot embeds are. This makes the second and subsequent opens fast.

The embed is NOT promoted back to hot in Directus on read (only on write). This avoids
thrashing the eviction cycle for occasionally-visited old chats.

---

### Testing Plan

Before implementing, write E2E Playwright specs covering:

1. **Hot embed load** — create a chat, trigger an embed, verify it loads in the sync
2. **Cold embed load** — manually set `content_location='cold'` on a test embed in the DB,
   upload a test cold file to S3, reload the chat; assert the embed renders correctly
3. **Cold embed update** — modify a cold embed; assert it returns to hot in Directus and
   S3 cold file is deleted
4. **Cold embed deletion** — delete a chat containing cold embeds; assert S3 cold files
   are cleaned up
5. **Eviction task dry-run** — run the eviction task with `--dry-run`; assert the correct
   embeds are selected without modifying any records

---

### Migration Path (when to trigger Phase 3)

Trigger implementation when ANY of these is true:

- `SELECT pg_relation_size('embeds') > 5368709120` (5 GB table data size)
- `SELECT COUNT(*) FROM embeds > 500000`
- Directus query latency for `get_embeds_by_hashed_chat_id` regularly exceeds 50ms
  (check OpenObserve APM)

At current growth: earliest trigger expected **2028**.

---

### Files to Touch (implementation checklist)

| File                                                                               | Change                                                         |
| ---------------------------------------------------------------------------------- | -------------------------------------------------------------- |
| `backend/core/directus/schemas/embeds.yml`                                         | Add `content_location` + `cold_storage_key` fields             |
| `backend/scripts/migrate_embed_cold_storage.py`                                    | One-time SQL migration to add columns + index                  |
| `backend/core/api/app/services/directus/embed_methods.py`                          | `update_embed` re-warm path; add cold fields to deletion query |
| `backend/core/api/app/routes/handlers/websocket_handlers/phased_sync_handler.py`   | `_hydrate_cold_embeds` call                                    |
| `backend/core/api/app/routes/handlers/websocket_handlers/request_embed_handler.py` | `_hydrate_cold_embeds` call                                    |
| `backend/core/api/app/tasks/embed_cold_storage_tasks.py`                           | New eviction task                                              |
| `backend/core/api/app/tasks/celery_config.py`                                      | Register task + beat schedule at 04:00 UTC                     |
| `frontend/packages/ui/src/components/settings/privacy/SettingsAutoDeletion.svelte` | No change needed (cold storage is transparent)                 |
| `docs/architecture/embeds.md`                                                      | Update to reference cold storage                               |

---

_Last updated: 2026-03-17 by session 9747 (claude-sonnet-4-6)_
