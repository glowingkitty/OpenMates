# TODO: Activity History Implementation

Based on the requirements in `.context/chat_processing.md` and current progress.

## Backend (`backend/core/api/`)

### `app/routes/websockets.py`
- [ ] Implement `draft_update` message handler:
    - [ ] Fetch current draft version from cache/DB.
    - [ ] Compare versions.
    - [ ] On match: Save new content/version, broadcast `draft_updated`.
    - [ ] On mismatch: Send `draft_conflict`.
- [ ] Implement handlers for other message types:
    - [ ] `chat_message_update` (real-time streaming for open chat)
    - [ ] `chat_message_received` (full message for background chats)
    - [ ] `chat_added` (broadcast)
    - [ ] `chat_deleted` (broadcast)
    - [ ] `chat_metadata_updated` (broadcast with version)
    - [ ] `initial_sync_data` (send on connect)
    - [ ] `chat_update_request` (client-initiated metadata changes with versioning)
- [ ] Refine `ConnectionManager` / auth logic if needed (e.g., token refresh).

### `app/services/cache.py` (`CacheService`)
- [ ] Add methods for storing/retrieving/updating drafts with version numbers (e.g., `get_draft_with_version`, `update_draft_content`).
- [ ] Add methods for managing chat list metadata if cached.

### `app/services/directus.py` (`DirectusService`)
- [ ] Ensure methods exist to fetch/update chat metadata and potentially drafts if Directus is the persistent store.