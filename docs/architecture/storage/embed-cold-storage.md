---
status: planned
last_verified: 2026-03-24
key_files:
  - backend/core/api/app/services/directus/embed_methods.py
  - backend/core/api/app/routes/handlers/websocket_handlers/phased_sync_handler.py
---

# Embed Cold Storage (Phase 3)

> Planned: offload encrypted embed content from Directus to S3 after 90 days of inactivity. Do not implement until embeds table exceeds ~500K rows or 5 GB.

## Why This Exists

The `encrypted_content` column accounts for 93% of per-row storage in the `embeds` table (avg 2,566 bytes of 2,756 total). At 1M rows, full-row heap is ~2.8 GB vs ~190 MB for metadata-only. Offloading content to S3 keeps Directus fast and small.

## How It Would Work

### Core Idea

Keep embed metadata in Directus forever. Move content fields (`encrypted_content`, `encrypted_text_preview`, `encrypted_diff`) to S3 when an embed has not been accessed in 90 days. Two new fields on `embeds`: `content_location` (`hot`/`cold`) and `cold_storage_key` (S3 path).

### Eviction Policy

Daily Celery Beat task at 04:00 UTC. Eligible if ALL true: `content_location = 'hot'`, `encryption_mode = 'client'`, `is_shared = false`, `updated_at < 90 days ago`, not in user's 3 most recently active chats.

Never evicted: vault-mode embeds (server needs decrypt access), shared embeds (must load fast), composite embeds where any child is ineligible.

### S3 Cold File Format

Bucket: `chatfiles`, key: `{hashed_user_id}/cold/{embed_id}.enc`. Content: server-side AES-256-GCM envelope wrapping a JSON blob `{c, p, d}` of the three already-client-encrypted content fields. Double encryption: inner layer is client-encrypted, outer layer prevents raw S3 access.

### Read/Write Path

**Read:** After fetching embeds from Directus, cold embeds are hydrated from S3 transparently via `_hydrate_cold_embeds()`. Client receives identical response shape. S3 fetches parallelized via `asyncio.gather`. Hydrated content cached in Redis (72h TTL) for subsequent opens. Embeds are NOT promoted back to hot on read (only on write).

**Write:** Cold embed updated -> fetch from S3, write to Directus as hot, delete S3 cold file.

**Delete:** Deletion pipeline includes `cold_storage_key` cleanup alongside existing `s3_file_keys`.

### Trigger Conditions

Implement when ANY is true:
- `pg_relation_size('embeds') > 5 GB`
- `COUNT(*) FROM embeds > 500,000`
- `get_embeds_by_hashed_chat_id` regularly exceeds 50ms

At current growth (~2,000 embeds/month): earliest trigger expected **2028**.

## Related Docs

- [File Upload Pipeline](../infrastructure/file-upload-pipeline.md) -- S3 storage and encryption model
- [Zero-Knowledge Storage](../core/zero-knowledge-storage.md) -- client vs vault encryption modes
