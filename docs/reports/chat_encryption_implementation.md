# Chat Encryption Implementation - Zero-Knowledge Architecture

## Overview

This document provides a comprehensive overview of the current encryption state and a concrete implementation plan to achieve **zero-knowledge architecture** for chat encryption, where all message encryption and decryption happens on the client side, and the server never has access to decryption keys.

## Current Encryption State

### ✅ Already Implemented (Keep As Is)

**Draft Encryption:**
- **Fields**: `encrypted_draft_md` and `encrypted_draft_preview`
- **Method**: Client-side master key encryption using `encryptWithMasterKey`/`decryptWithMasterKey` functions
- **Key Storage**: Master keys stored decrypted in browser sessionStorage/localStorage (client-side only)
- **Server Storage**: Encrypted drafts stored in IndexedDB and Directus (server never has decryption keys)

**Chat Titles:**
- **Field**: `encrypted_title`
- **Method**: Master key encryption (client-side only) ✅
- **Status**: Already properly implemented

**Email Address:**
- **Field**: `encrypted_email_address`
- **Method**: Client-side encryption using email-based secret (requires client connection for decryption) ✅
- **Status**: Already properly implemented

**Username:**
- **Field**: `encrypted_username`
- **Method**: Server-side encryption using user-specific Vault keys ❌ **NEEDS TO BE CHANGED**
- **Current**: Server can decrypt usernames for authentication/display
- **Target**: Move to client-side encryption (requires client connection for decryption)

### ✅ Server-Side Encryption (Keep As Is)

**Credit Balance:**
- **Field**: `encrypted_credit_balance`
- **Method**: Server-side encryption using user-specific Vault keys
- **Reason**: Server needs to validate credits for billing operations

**2FA Secrets:**
- **Field**: `encrypted_tfa_secret`
- **Method**: Server-side encryption using user-specific Vault keys
- **Reason**: Server needs to validate 2FA during authentication

**Payment Method IDs:**
- **Field**: `encrypted_stripe_payment_method_id` (to be implemented)
- **Method**: Server-side encryption using user-specific Vault keys
- **Reason**: Server needs to process payments with Stripe

**User Settings:**
- **Plaintext Settings**: `language`, `darkmode`, `consent_privacy_and_apps_default_settings`, `consent_mates_default_settings` (server-side, needed for functionality)
- **Encrypted Settings**: `encrypted_settings` (currently unused/empty)
- **App-Specific Settings**: `user_app_settings_and_memories` collection (encrypted with user-specific keys, server-side)
- **Reason**: Plaintext settings needed for server functionality, encrypted settings for privacy

### ❌ Current Issues (To Be Fixed)

**Message Content:**
- **Field**: `encrypted_content`
- **Current**: Uses chat-specific AES keys (server-side) ❌
- **Target**: Move to client-side encryption with chat-specific keys

**Chat Focus:**
- **Field**: `encrypted_active_focus_id`
- **Current**: Uses chat-specific AES keys (server-side) ❌
- **Target**: Move to client-side encryption with chat-specific keys

**Mates Array:**
- **Field**: `mates`
- **Current**: Plaintext ❌
- **Target**: Encrypt with chat-specific key

**Message Metadata:**
- **Fields**: `sender_name`, `category`
- **Current**: Plaintext ❌
- **Target**: Encrypt with chat-specific key

## Target Architecture: Zero-Knowledge

### Core Principle

**All message encryption and decryption happens on the client side.** The server never has access to decryption keys (only stores the encrypted encryption keys for sync between devices) and can only process messages when the client provides decrypted content on-demand.

### Message Processing Flow

1. **Client encrypts** all messages with chat-specific keys
2. **Server stores** only encrypted messages (cannot decrypt)
3. **When processing needed**, client decrypts and sends clear text to server
4. **Server processes** clear text (temporary cache for last 3 chats)
5. **Server streams** response to client
6. **Client encrypts** response and stores on server

### What Needs to be Encrypted (Client-Side)

**Chat Metadata:**
- `encrypted_title` ✅ (already client-side encrypted with master key)
- `encrypted_active_focus_id` ❌ **MOVE TO CLIENT-SIDE** with chat-specific key
- `encrypted_mates` ❌ **NEW** - encrypt mates array with chat-specific key

**Message Content:**
- `encrypted_content` ❌ **MOVE TO CLIENT-SIDE** with chat-specific key
- `encrypted_sender_name` ❌ **NEW** - encrypt sender name with chat-specific key
- `encrypted_category` ❌ **NEW** - encrypt category with chat-specific key

**Draft Content (Keep Current):**
- `encrypted_draft_md` ✅ (already client-side encrypted with user-specific key)
- `encrypted_draft_preview` ✅ (already client-side encrypted with user-specific key)

### What Can Remain Plaintext (Needed for Sorting/Indexing)

**Chat Fields:**
- `chat_id`, `hashed_user_id` (identifiers)
- `messages_version`, `title_version` (versioning)
- `last_edited_overall_timestamp`, `created_at`, `updated_at` (timestamps for sorting)
- `unread_count` (counters)
- `last_message_timestamp` (for sorting)

**Message Fields:**
- `message_id`, `client_message_id`, `chat_id` (identifiers)
- `role` (needed for AI processing logic)
- `created_at`, `updated_at` (timestamps)
- `hashed_user_id` (identifier)

## Chat Key Storage Strategy

### Directus-Based Storage (Recommended)

**Why Directus over Vault:**
- **Easy Querying**: Can easily search all chat keys for a user using `hashed_user_id`
- **Relational Data**: Chat keys are directly linked to chat records
- **Simpler Management**: No need for complex Vault KV operations
- **Better Performance**: Direct database queries vs Vault API calls
- **Consistent Architecture**: Already using Directus for chat data

**Chat Key Management Flow:**
1. **Generate**: Client-side AES key per chat (32 bytes)
2. **Encrypt**: Chat key with user's master key
3. **Store**: Encrypted chat key in Directus `chats.encrypted_chat_key` field
4. **Sync**: Server stores encrypted keys for device synchronization
5. **Access**: Client decrypts chat keys using master key

**Device Sync Benefits:**
- New device logs in → downloads all encrypted chat keys for user
- Decrypts with master key → can access all user's chats
- Future chat sharing: store multiple encrypted copies for participants

## Encryption Strategy

### Chat-Specific Keys (Recommended)

**Strategy**: Use chat-specific AES keys for all chat-related encrypted content

**Pros:**
- Better security isolation between chats
- Enables future chat sharing (share chat-specific key)
- Consistent encryption model
- Chat-level access control

**Cons:**
- Requires key management for each chat

**Key Management:**
- Generate unique AES key per chat (client-side)
- Encrypt chat keys with user's master key
- Store encrypted chat keys in Directus `chats` table (`encrypted_chat_key` field)
- Server stores encrypted keys for device sync, never has access to plaintext keys
- Enable key rotation per chat

## Implementation Checklist

### Phase 1: Backend Schema and Infrastructure

#### Database Schema Updates

**File: `backend/core/directus/schemas/chats.yml`**
```yaml
# Add new encrypted fields
encrypted_mates:
  type: json
  note: "[Encrypted] Array of mate categories, encrypted using chat-specific key"

encrypted_chat_key:
  type: string
  length: 512
  note: "[Encrypted] Chat-specific encryption key, encrypted with user's master key for device sync"
```

**File: `backend/core/directus/schemas/messages.yml`**
```yaml
# Add new encrypted fields
encrypted_sender_name:
  type: string
  note: "[Encrypted] Sender name, encrypted using chat-specific key"
encrypted_category:
  type: string  
  note: "[Encrypted] Category, encrypted using chat-specific key"
```

#### Backend Implementation Changes

- [ ] **Update Chat Schema** (`backend/core/directus/schemas/chats.yml`)
  - Add `encrypted_mates` field
  - Add `encrypted_chat_key` field
- [ ] **Update Message Schema** (`backend/core/directus/schemas/messages.yml`)
  - Add `encrypted_sender_name` field
  - Add `encrypted_category` field
- [ ] **Update Chat Methods** (`backend/core/api/app/services/directus/chat_methods.py`)
  - Add encryption/decryption for `mates` field
  - Add encryption/decryption for `encrypted_chat_key` field
  - Update `get_chat_metadata` to decrypt `mates`
  - Update `update_chat_fields_in_directus` to encrypt `mates`
- [ ] **Update Message Handler** (`backend/core/api/app/routes/handlers/websocket_handlers/message_received_handler.py`)
  - Encrypt `sender_name` and `category` before storing
  - Update message creation to include encrypted fields
- [ ] **Update Persistence Tasks** (`backend/core/api/app/tasks/persistence_tasks.py`)
  - Add encrypted `sender_name` and `category` to message creation
  - Update message retrieval to handle encrypted fields
- [ ] **Update Encryption Service** (`backend/core/api/app/utils/encryption.py`)
  - Remove server-side chat encryption methods (`encrypt_with_chat_key`, `decrypt_with_chat_key`)
  - Remove chat-specific AES key management (`CHAT_AES_KEY_KV_PATH`)
  - Keep user-specific encryption methods for billing/2FA operations
  - Remove legacy draft encryption methods (`USER_DRAFT_AES_KEY_KV_PATH`)

### Phase 2: Frontend Encryption Implementation

#### Frontend Implementation Changes

- [ ] **Update Chat Types** (`frontend/packages/ui/src/types/chat.ts`)
  ```typescript
  export interface Chat {
    // ... existing fields
    encrypted_mates?: string | null; // Encrypted mates array
  }
  
  export interface Message {
    // ... existing fields
    encrypted_sender_name?: string; // Encrypted sender name
    encrypted_category?: string; // Encrypted category
  }
  ```
- [ ] **Update Crypto Service** (`frontend/packages/ui/src/services/cryptoService.ts`)
  - Add methods for chat-specific encryption/decryption
  - Add methods for encrypting/decrypting JSON arrays (mates)
  - Add methods for chat key management (generate, encrypt, decrypt)
  - Extend existing encryption methods for chat-specific keys
- [ ] **Update Database Service** (`frontend/packages/ui/src/services/db.ts`)
  - Add encryption/decryption for `mates` field
  - Add encryption/decryption for message `sender_name` and `category`
  - Update message storage/retrieval methods
- [ ] **Update Chat Components**
  - `frontend/packages/ui/src/components/chats/Chat.svelte`
  - `frontend/packages/ui/src/components/ActiveChat.svelte`
  - `frontend/packages/ui/src/services/chatSyncServiceHandlersChatUpdates.ts`
  - `frontend/packages/ui/src/services/chatSyncServiceHandlersCoreSync.ts`
  - Decrypt `mates` for display
  - Decrypt message `sender_name` and `category` for display
  - Update chat list to show decrypted mate information

### Phase 3: AI Processing Updates

- [ ] **Update Stream Consumer** (`backend/apps/ai/tasks/stream_consumer.py`)
  - Remove server-side decryption
  - Work with encrypted content or receive decrypted content from client
- [ ] **Update Ask Skill Task** (`backend/apps/ai/tasks/ask_skill_task.py`)
  - Update to receive decrypted content from client
  - Remove server-side decryption logic
- [ ] **Update Message Received Handler** (`backend/core/api/app/routes/handlers/websocket_handlers/message_received_handler.py`)
  - Remove server-side decryption for AI processing
  - Send decrypted content to AI processing

### Phase 4: Testing and Migration

#### Testing Strategy

- [ ] **Write Unit Tests**
  - Test all new encryption methods
  - Test data integrity (encrypted data decrypts correctly)
  - Test edge cases (empty/null values, special characters)
- [ ] **Write Integration Tests**
  - Test complete chat creation/message flow
  - Test data migration from plaintext to encrypted
  - Test performance impact of encryption/decryption
- [ ] **Write Security Tests**
  - Verify keys are properly isolated
  - Verify no plaintext data leaks to logs/storage
  - Verify proper access control enforcement

#### Data Migration

- [ ] **Data Migration Script**
  - Encrypt existing `mates` data
  - Update existing messages to encrypt `sender_name` and `category`
  - Handle backward compatibility during transition
- [ ] **Gradual Rollout**
  - Deploy backend changes first
  - Update frontend to handle both encrypted and plaintext data
  - Run migration script
  - Remove plaintext fallback code

## Security Considerations

### Key Management
- **Key Rotation**: Implement key rotation for chat-specific keys
- **Key Backup**: Ensure chat keys are backed up for data recovery
- **Key Sharing**: Design for future multi-user chat support

### Access Control
- **User Isolation**: Ensure users can only access their own encrypted data
- **Chat Isolation**: Ensure chat-specific keys are properly isolated
- **Admin Access**: Design admin access patterns for support/debugging

## Files to Modify

### Backend Files
- `backend/core/directus/schemas/chats.yml`
- `backend/core/directus/schemas/messages.yml`
- `backend/core/api/app/services/directus/chat_methods.py`
- `backend/core/api/app/routes/handlers/websocket_handlers/message_received_handler.py`
- `backend/core/api/app/tasks/persistence_tasks.py`
- `backend/core/api/app/utils/encryption.py`
- `backend/apps/ai/tasks/stream_consumer.py`
- `backend/apps/ai/tasks/ask_skill_task.py`

### Frontend Files
- `frontend/packages/ui/src/services/cryptoService.ts`
- `frontend/packages/ui/src/services/db.ts`
- `frontend/packages/ui/src/types/chat.ts`
- `frontend/packages/ui/src/components/chats/Chat.svelte`
- `frontend/packages/ui/src/components/ActiveChat.svelte`
- `frontend/packages/ui/src/services/chatSyncServiceHandlersChatUpdates.ts`
- `frontend/packages/ui/src/services/chatSyncServiceHandlersCoreSync.ts`
- `frontend/packages/ui/src/services/chatSyncServiceSenders.ts`
- `frontend/packages/ui/src/services/chatMetadataCache.ts`

## Next Steps

1. **Review and Approve**: Review this implementation plan
2. **Start with Phase 1**: Begin with backend schema and infrastructure changes
3. **Implement Frontend Changes**: Update crypto service and components
4. **Update AI Processing**: Remove server-side decryption
5. **Testing and Migration**: Comprehensive testing and data migration

---

*This implementation plan ensures that all chat encryption and decryption happens on the client side, with the server only storing encrypted data and processing decrypted content on-demand, achieving true zero-knowledge architecture.*
