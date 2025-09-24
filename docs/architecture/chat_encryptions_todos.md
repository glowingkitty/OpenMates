# Chat Encryption Architecture - Client-Side Encryption

## New Architecture Overview

### Core Principle: Zero-Knowledge Architecture

**All message encryption and decryption happens on the client side.** The server never has access to decryption keys and can only process messages when the client provides decrypted content on-demand. Server only caches the last 3 opened chats temporarily for processing.

### Current State Analysis

**Draft Encryption (Already Implemented - Keep As Is):**
- Uses **user-specific AES keys** stored in Vault KV (`USER_DRAFT_AES_KEY_KV_PATH`)
- Encrypts `encrypted_draft_md` and `encrypted_draft_preview` fields
- Client-side encryption/decryption using master key (`encryptWithMasterKey`/`decryptWithMasterKey`)

**Current Chat/Message Encryption (To Be Replaced):**
- Chat titles: `encrypted_title` field exists but uses **master key encryption** (client-side only)
- Message content: `encrypted_content` field exists and uses **chat-specific AES keys** (server-side) ❌ **TO BE CHANGED**
- Chat focus: `encrypted_active_focus_id` uses **chat-specific AES keys** (server-side) ❌ **TO BE CHANGED**

### Key Changes Required

1. **Zero-Knowledge Server**: Server never has decryption keys, cannot decrypt stored data
2. **Client-Controlled Decryption**: Client decrypts messages on-demand for server processing
3. **Temporary Server Cache**: Server only caches last 3 chats temporarily for processing
4. **Encrypted Storage**: Only encrypted messages are stored long-term on server
5. **Client-Side Key Management**: All encryption keys managed and stored client-side

## New Message Flow Architecture

### Zero-Knowledge Architecture Flow

**User Message Flow:**
1. User types message → Client encrypts with chat-specific key
2. Client sends encrypted message to server for storage
3. Client decrypts message and sends clear text to server for AI processing
4. Server processes clear text message (temporary cache)
5. Server streams clear text response to client
6. Client encrypts response with chat-specific key
7. Client sends encrypted response to server for storage

**Key Benefits:**
- **Zero-Knowledge**: Server never has decryption keys
- **Client-Controlled**: All encryption/decryption happens client-side
- **Temporary Processing**: Server only caches last 3 chats temporarily
- **End-to-End Security**: Server cannot decrypt stored data

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

## Recommended Encryption Strategy

### Chat-Specific Keys (Recommended)

**Strategy**: Use chat-specific AES keys for all chat-related encrypted content
- **Pros**: 
  - Better security isolation between chats
  - Enables future chat sharing (share chat-specific key)
  - Consistent encryption model
  - Chat-level access control
- **Cons**: Requires key management for each chat

**Key Management**:
- Generate unique AES key per chat
- Store chat keys in client-side secure storage (IndexedDB with encryption)
- Keys derived from user master key + chat_id for consistency
- Enable key rotation per chat

### User-Specific Keys (Alternative)

**Strategy**: Use same user-specific keys for all user's data
- **Pros**: Simpler key management, consistent with current draft encryption
- **Cons**: Security risk if master key compromised, harder to implement chat sharing

**Recommendation**: Use chat-specific keys for better security and future sharing capabilities.

## Recommended Implementation Plan

### Phase 1: Extend Chat-Specific Encryption (Option 1)

**Backend Changes:**

1. **Update Chat Schema** (`backend/core/directus/schemas/chats.yml`):
   ```yaml
   encrypted_mates:
     type: json
     note: "[Encrypted] Array of mate categories, encrypted using chat-specific key"
   ```

2. **Update Message Schema** (`backend/core/directus/schemas/messages.yml`):
   ```yaml
   encrypted_sender_name:
     type: string
     note: "[Encrypted] Sender name, encrypted using chat-specific key"
   encrypted_category:
     type: string  
     note: "[Encrypted] Category, encrypted using chat-specific key"
   ```

3. **Update Chat Methods** (`backend/core/api/app/services/directus/chat_methods.py`):
   - Add encryption/decryption for `mates` field
   - Update `get_chat_metadata` to decrypt `mates`
   - Update `update_chat_fields_in_directus` to encrypt `mates`

4. **Update Message Handler** (`backend/core/api/app/routes/handlers/websocket_handlers/message_received_handler.py`):
   - Encrypt `sender_name` and `category` before storing
   - Update message creation to include encrypted fields

5. **Update Message Persistence** (`backend/core/api/app/tasks/persistence_tasks.py`):
   - Add encrypted `sender_name` and `category` to message creation
   - Update message retrieval to decrypt these fields

**Frontend Changes:**

1. **Update Chat Types** (`frontend/packages/ui/src/types/chat.ts`):
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

2. **Update Database Service** (`frontend/packages/ui/src/services/db.ts`):
   - Add encryption/decryption for `mates` field
   - Add encryption/decryption for message `sender_name` and `category`
   - Update message storage/retrieval methods

3. **Update Chat Components**:
   - Decrypt `mates` for display
   - Decrypt message `sender_name` and `category` for display
   - Update chat list to show decrypted mate information

4. **Update Crypto Service** (`frontend/packages/ui/src/services/cryptoService.ts`):
   - Add methods for chat-specific encryption/decryption
   - Add methods for encrypting/decrypting JSON arrays (mates)

### Phase 2: End-to-End Encryption (Future)

**Goal**: Ensure server never sees plaintext content

**Changes Needed**:
1. **Client-Side Encryption**: Encrypt all content before sending to server
2. **Server-Side Changes**: Remove decryption for AI processing, work with encrypted content
3. **AI Processing**: Implement encrypted content processing or move AI to client-side

## Migration Strategy

### Data Migration

1. **Existing Chats**: 
   - Add migration script to encrypt existing `mates` data
   - Update existing messages to encrypt `sender_name` and `category`

2. **Gradual Rollout**:
   - Deploy backend changes first
   - Update frontend to handle both encrypted and plaintext data
   - Run migration script
   - Remove plaintext fallback code

### Backward Compatibility

1. **Dual Support**: Support both encrypted and plaintext data during transition
2. **Migration Detection**: Detect unencrypted data and encrypt on access
3. **Version Flags**: Use version fields to track encryption status

## Security Considerations

### Key Management

1. **Key Rotation**: Implement key rotation for chat-specific keys
2. **Key Backup**: Ensure chat keys are backed up for data recovery
3. **Key Sharing**: Design for future multi-user chat support

### Access Control

1. **User Isolation**: Ensure users can only access their own encrypted data
2. **Chat Isolation**: Ensure chat-specific keys are properly isolated
3. **Admin Access**: Design admin access patterns for support/debugging

## Testing Strategy

### Unit Tests

1. **Encryption/Decryption**: Test all new encryption methods
2. **Data Integrity**: Test that encrypted data decrypts correctly
3. **Edge Cases**: Test empty/null values, special characters

### Integration Tests

1. **End-to-End**: Test complete chat creation/message flow
2. **Migration**: Test data migration from plaintext to encrypted
3. **Performance**: Test encryption/decryption performance impact

### Security Tests

1. **Key Isolation**: Verify keys are properly isolated
2. **Data Leakage**: Verify no plaintext data leaks to logs/storage
3. **Access Control**: Verify proper access control enforcement

## Questions for Implementation

1. **Key Strategy**: Should we use chat-specific keys (Option 1) or user-specific keys (Option 2)?
2. **Migration Timeline**: How quickly should we migrate existing data?
3. **AI Processing**: How should we handle AI processing with encrypted content?
4. **Performance**: What's the acceptable performance impact of additional encryption?
5. **Backup/Recovery**: How should we handle key recovery for lost chats?

## Next Steps

1. **Decision on Encryption Strategy**: Choose between Options 1, 2, or 3
2. **Detailed Implementation Plan**: Create detailed task breakdown
3. **Migration Script Design**: Design data migration approach
4. **Testing Plan**: Create comprehensive testing strategy
5. **Security Review**: Conduct security review of proposed changes