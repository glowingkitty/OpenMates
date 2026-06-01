---
status: active
last_verified: 2026-06-01
key_files:
  - backend/core/api/app/routes/handlers/websocket_handlers/phased_sync_handler.py
  - frontend/packages/ui/src/services/chatSyncServiceHandlersCoreSync.ts
  - frontend/packages/ui/src/services/chatSyncMerge.ts
---

# Startup Sync Handler

The backend startup sync handler assembles encrypted chat metadata and bounded recent content for WebSocket sync. The high-level flow is documented in [Sync Architecture](./data/sync.md); this note records the handler-specific invariants that keep startup fast and prevent partial Redis cache data from erasing client-decryptable metadata.

## Startup Content Boundary

`handle_phased_sync_request(..., phase="all")` must not run Phase 3 background message/embed sync. Web startup is limited to:

- Phase 1a shell metadata, suggestions, inspirations, and sub-chat preview metadata.
- Phase 1b full content for at most 10 recent parent chats.
- Phase 2 metadata-only sync for the recent 100-chat window.
- App settings/memories sync.

Phase 3 is reserved for explicit/offline prefetch requests. It must not be part of default web login/startup.

## Phase 1a Contract

Phase 1a sends last-opened and recent chat metadata before message and embed content. Redis can be partially warm, so the handler must treat cached list-item data as incomplete when encrypted header fields or versions are missing.

Before sending `phase_1_last_chat_ready`, the handler fills missing Phase 1a encrypted metadata from Directus. If the Redis versions key is missing, Directus `messages_v` and `title_v` are used too. If Redis versions are present, cached versions remain authoritative and Directus only fills missing encrypted fields.

Phase 1a may include direct child sub-chat metadata for preview cards, but the list returned to Phase 1b must contain only parent chat IDs.

## Phase 1b Contract

Phase 1b sends full content only for the 10 most recent parent chats. Parent chats are rows where `is_sub_chat` is false and `parent_id` is empty.

Phase 1b must not fetch or send sub-chat messages, sub-chat embeds, sub-chat embed keys, or sub-chat Code Run outputs. Sub-chat content loads through `request_chat_content_batch` when the sub-chat is opened.

## Phase 2 Contract

Phase 2 is metadata-only for the recent 100-chat window. It must not include messages, embeds, embed keys, Code Run outputs, or compression checkpoints.

If the user has more than 100 chats, the frontend triggers `sync_metadata_chats` after Phase 2 because Phase 3 no longer runs during web startup.

## Client Merge Contract

The frontend Phase 1a handler must call the shared `mergeServerChatWithLocal()` policy. It must not directly overwrite IndexedDB with raw Phase 1a payload fields, because `null` encrypted metadata would remove data that can still decrypt locally.
