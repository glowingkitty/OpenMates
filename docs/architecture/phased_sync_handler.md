---
status: active
last_verified: 2026-05-16
key_files:
  - backend/core/api/app/routes/handlers/websocket_handlers/phased_sync_handler.py
  - frontend/packages/ui/src/services/chatSyncServiceHandlersCoreSync.ts
  - frontend/packages/ui/src/services/chatSyncMerge.ts
---

# Phased Sync Handler

The backend phased sync handler assembles encrypted chat metadata for WebSocket sync. The high-level flow is documented in [Sync Architecture](./data/sync.md); this note records the handler-specific invariant that prevents partial Redis cache data from erasing client-decryptable metadata.

## Phase 1a Contract

Phase 1a sends last-opened and recent chat metadata before message and embed content. Redis can be partially warm, so the handler must treat cached list-item data as incomplete when encrypted header fields or versions are missing.

Before sending `phase_1_last_chat_ready`, the handler fills missing Phase 1a encrypted metadata from Directus. If the Redis versions key is missing, Directus `messages_v` and `title_v` are used too. If Redis versions are present, cached versions remain authoritative and Directus only fills missing encrypted fields.

## Client Merge Contract

The frontend Phase 1a handler must call the shared `mergeServerChatWithLocal()` policy. It must not directly overwrite IndexedDB with raw Phase 1a payload fields, because `null` encrypted metadata would remove data that can still decrypt locally.
