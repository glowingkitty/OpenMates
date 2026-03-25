---
status: active
last_verified: 2026-03-24
key_files:
  - frontend/packages/ui/src/services/cryptoService.ts
  - frontend/packages/ui/src/services/db.ts
  - backend/core/api/app/routes/handlers/websocket_handlers/encrypted_chat_metadata_handler.py
  - backend/core/api/app/routes/handlers/websocket_handlers/message_received_handler.py
  - backend/core/api/app/tasks/persistence_tasks.py
  - backend/core/api/app/utils/encryption.py
  - backend/core/directus/schemas/chats.yml
  - backend/core/directus/schemas/messages.yml
---

# Chat Encryption Implementation

> Field-level encryption details for chat data. All message encryption/decryption happens client-side; the server stores only encrypted blobs.

## Why This Exists

- Documents which fields are encrypted, with which keys, and at which layer
- Provides the implementation reference for the zero-knowledge architecture described in [zero-knowledge-storage.md](./zero-knowledge-storage.md)
- Tracks the dual-phase processing model: plaintext for AI inference, encrypted for storage

## How It Works

### Encryption by Field

#### Client-Side Encrypted (Chat-Specific Key)

These fields are encrypted with a per-chat AES-256-GCM key. The chat key itself is wrapped with the user's master key and stored as `encrypted_chat_key`.

| Field | Collection | Encrypted with |
|-------|-----------|----------------|
| `encrypted_content` | messages | Chat key |
| `encrypted_sender_name` | messages | Chat key |
| `encrypted_category` | messages | Chat key |
| `encrypted_active_focus_id` | chats | Chat key |
| `encrypted_chat_summary` | chats | Chat key |
| `encrypted_chat_tags` | chats | Chat key |
| `encrypted_follow_up_request_suggestions` | chats | Chat key |
| `encrypted_chat_key` | chats | Master key |

#### Client-Side Encrypted (Master Key)

| Field | Collection | Notes |
|-------|-----------|-------|
| `encrypted_title` | chats | Chat title |
| `encrypted_draft_md` | drafts | Draft markdown content |
| `encrypted_draft_preview` | drafts | Draft preview text |

#### Server-Side Encrypted (Vault)

These require server access for processing:

| Field | Collection | Why server-side |
|-------|-----------|----------------|
| `encrypted_credit_balance` | users | Billing validation |
| `encrypted_tfa_secret` | users | 2FA verification |
| `encrypted_username` | users | <!-- VERIFY: is username still server-side or moved to client-side? --> |

#### Plaintext (Needed for Indexing/Sorting)

`chat_id`, `hashed_user_id`, `messages_version`, `title_version`, timestamps (`created_at`, `updated_at`, `last_edited_overall_timestamp`, `last_message_timestamp`), `unread_count`, `message_id`, `client_message_id`, `role`.

### Chat Key Management

1. Client generates 32-byte AES key per chat via `generateChatKey()` in [cryptoService.ts](../../frontend/packages/ui/src/services/cryptoService.ts)
2. Key wrapped with master key via `encryptChatKeyWithMasterKey()`, stored as `chats.encrypted_chat_key`
3. On new device login: all encrypted chat keys downloaded and decrypted with master key
4. Embed keys derived deterministically from chat key via HKDF: `deriveEmbedKeyFromChatKey(chatKey, embedId)`

### Chat Key Immutability Guard

Once a chat has an `encrypted_chat_key`, the server blocks overwrites unless `allow_chat_key_rotation = true` is set (used for hidden-chat hide/unhide). This guard operates at two levels:

- **WebSocket handler:** [encrypted_chat_metadata_handler.py](../../backend/core/api/app/routes/handlers/websocket_handlers/encrypted_chat_metadata_handler.py) compares incoming key fingerprint against cached key
- **Persistence task:** [persistence_tasks.py](../../backend/core/api/app/tasks/persistence_tasks.py) checks Directus before writing

### Dual-Phase Processing Model

**Phase 1 -- AI Processing:** Client sends plaintext content for immediate LLM processing. Server generates metadata (title, category) during preprocessing, streams AI response as markdown.

**Phase 2 -- Encrypted Storage:** Server sends generated metadata back to client. Client encrypts everything (user message, AI response, title, category) with appropriate keys. Client sends encrypted package to server for permanent storage in Directus.

**Critical rule:** server never stores Tiptap JSON (only exists client-side). All server storage is markdown-based.

### Server-Side Encryption Scope

[encryption.py](../../backend/core/api/app/utils/encryption.py) no longer handles chat or draft encryption -- those methods were removed for zero-knowledge. It retains:

- User-specific Vault key management (`create_user_key`, `encrypt_with_user_key`, `decrypt_with_user_key`)
- Email HMAC hashing
- System-level encryption keys (newsletter, issue reports, debug requests, demo chats, creator income, support payments)

## Data Structures

### Chat Schema Additions

In [chats.yml](../../backend/core/directus/schemas/chats.yml):
- `encrypted_chat_summary` (text) -- 2-3 sentence summary, chat-key encrypted
- `encrypted_chat_tags` (json) -- up to 10 tags, chat-key encrypted
- `encrypted_follow_up_request_suggestions` (json) -- 6 suggestions, chat-key encrypted
- `encrypted_chat_key` (string, max 512) -- per-chat AES key wrapped with master key

### Message Schema Additions

In [messages.yml](../../backend/core/directus/schemas/messages.yml):
- `encrypted_sender_name` (string) -- chat-key encrypted
- `encrypted_category` (string) -- chat-key encrypted (replaced former plaintext `category`)

## Edge Cases

- **Multi-device sync:** encrypted chat keys are synced via Directus; each device decrypts with master key
- **Key corruption prevention:** immutability guard ensures a misconfigured device cannot overwrite a chat key and make existing messages undecryptable
- **Array encryption:** `encryptArrayWithChatKey()` / `decryptArrayWithChatKey()` handle JSON array fields (tags, suggestions)
- **Backward compatibility:** frontend handles both encrypted and legacy plaintext data during transition

## Related Docs

- [Zero-Knowledge Storage](./zero-knowledge-storage.md) -- encryption tiers and master key lifecycle
- [Security Architecture](./security.md) -- overall security model
- [Message Processing](../messaging/message-processing.md) -- dual-cache (vault vs client encryption)
