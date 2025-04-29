# Backend Chats & Drafts Refactor TODO

This file tracks all tasks required to fulfill the requirements in `.context/chats_and_drafts.md` for the backend chat/draft system, including WebSocket, encryption, cache, and Directus integration.

---

## 1. WebSocket Refactor & Splitting

- [x] **Split `websockets.py` into:**
  - `connection_manager.py` (connection/session management)
  - `auth_ws.py` (WebSocket authentication logic)
  - `handlers/initial_sync.py` (initial sync logic)
- [x] Ensure all logic is moved to the correct file, with clean imports and no duplication.
- [x] Remove any remaining logic from `websockets.py` that should be in the split files.
- [x] Ensure all WebSocket message types and payloads match the models in `.context/chats_and_drafts.md`.

---

## 2. WebSocket Message Models & API Compliance

- [x] Implement all Pydantic models as specified in `.context/chats_and_drafts.md` (MessageBase, ChatBase, MessageInDB, ChatInDB, MessageInCache, MessageResponse, ChatResponse, etc.).
- [x] Ensure all WebSocket responses use these models and send decrypted data as required for draft and chat creation/update flows.
- [x] Ensure initial sync (`initial_sync_data`) returns all chats (persisted and draft-only) using the `ChatResponse` model, with all required fields and correct typing.
- [ ] Implement versioning and conflict handling for drafts and titles (partially done, further validation may be needed for all flows).
- [ ] Ensure all message types (`draft_update`, `chat_initiated`, `message_new`, etc.) have correct payloads (done for draft/chat, others to be implemented as message flows are built out).

---

## 3. Encryption & Vault Integration

- [x] On new chat, generate AES-GCM key, store in Vault, and save reference in cache/Directus.
  _Implemented in `websockets.py` (see "draft_update" handler): creates AES-GCM key in Vault, stores reference in cache; persisted to Directus only when first message is sent._
- [x] Encrypt all sensitive chat content (messages, draft, title) before saving to cache/Directus.
  _Draft/title are encrypted before saving to cache (see `websockets.py` and `encryption.py`)._
- [x] Decrypt data before sending over WebSocket.
  _All chat/draft data is decrypted before sending to client in `handle_initial_sync.py`._
- [x] Ensure all encryption/decryption uses the correct key from Vault.
  _Encryption/decryption always uses the chat's Vault key reference._

---

## 4. Cache & Persistence Logic

- [x] Implement LRU logic for last 3 active chats per user in cache (see `update_user_active_chats_lru` and `get_user_active_chats_lru` in `cache.py`).
- [x] Implement 30-minute sliding expiration for chat metadata and drafts (see `set_chat_metadata` and `set_draft` in `cache.py`).
- [x] Save new chat (metadata + vault ref + encrypted draft + version) to Dragonfly cache only.
  _New chats are saved to cache only; persisted to Directus on first message (see `websockets.py`)._
- [x] Persist chat to Directus only when the first message is sent/received.
  _Handled in "chat_message_received" handler in `websockets.py`._
- [x] Ensure cache invalidation/refresh on Directus writes.
  _Cache invalidation/refresh is handled in `create_*` methods (see `websockets.py` and `directus/chat_methods.py`)._

---

## 5. Draft Handling & Versioning

- [ ] Auto-save drafts on triggers (typing pause, blur, visibilitychange).
- [ ] Store draft content as Tiptap JSON, versioned.
- [ ] Reject stale updates, log server-side, discard stale client data.
- [ ] Support offline draft saving and sync on reconnect.

---

## 6. Device Fingerprint & Auth

- [ ] Use API auth tokens + device fingerprint for WebSocket auth.
- [ ] Require 2FA re-validation if fingerprint mismatches.
- [ ] Ensure device cache/DB logic is correct.

---

## 7. Code Quality & Structure

- [ ] Ensure readable code, separation of concerns, and proper module structure.
- [ ] Remove dead code and placeholders.

---

## 8. Testing & Validation

- [ ] Test all flows: new chat, draft update, message send, cache/Directus sync, encryption/decryption.
- [ ] Validate WebSocket output matches frontend expectations.

---

---

## 9. Frontend Chats & Drafts Progress

- [x] Renamed ActivityHistory to Chats in all frontend code and UI.
- [x] Updated all imports, exports, and store actions to use "Chats".
- [x] Verified and aligned initial sync logic (server + IndexedDB merge) with `.context/chats_and_drafts.md` requirements.
- [x] Updated event handling and data models for chats/drafts to match backend and spec.
- [ ] Continue implementing frontend draft versioning, conflict handling, and offline sync as per requirements.
- [ ] Complete auto-save triggers and robust draft state management in MessageInput and related components.

*Last updated: 2025-04-29*
**As each task is completed, update this file with `[x]` and notes.**