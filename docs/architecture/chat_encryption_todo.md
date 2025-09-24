# Chat Encryption Architecture - Client-Side Encryption Implementation

## Overview

This document outlines the implementation plan to achieve **zero-knowledge architecture** for chat encryption, where all message encryption and decryption happens on the client side, and the server never has access to decryption keys.

## Current Architecture Analysis

### ✅ Already Implemented (Draft Encryption)
- **Draft Encryption**: Uses user-specific AES keys stored in Vault KV (`USER_DRAFT_AES_KEY_KV_PATH`)
- **Client-Side Encryption**: `encryptWithMasterKey`/`decryptWithMasterKey` functions in `cryptoService.ts`
- **Fields Encrypted**: `encrypted_draft_md` and `encrypted_draft_preview`
- **Storage**: Encrypted drafts stored in IndexedDB and Directus

### ❌ Current Chat/Message Encryption (To Be Replaced)
- **Chat Titles**: `encrypted_title` field exists but uses **master key encryption** (client-side only) ✅
- **Message Content**: `encrypted_content` field exists and uses **chat-specific AES keys** (server-side) ❌ **TO BE CHANGED**
- **Chat Focus**: `encrypted_active_focus_id` uses **chat-specific AES keys** (server-side) ❌ **TO BE CHANGED**
- **Mates Array**: `mates` field is **plaintext** ❌ **TO BE ENCRYPTED**

## Target Architecture (Zero-Knowledge)

### Core Principle
**All message encryption and decryption happens on the client side.** The server never has access to decryption keys and can only process messages when the client provides decrypted content on-demand.

### Message Processing Flow (from `/docs/architecture/message_processing.md`)
1. **Client encrypts** all messages with chat-specific keys
2. **Server stores** only encrypted messages (cannot decrypt)
3. **When processing needed**, client decrypts and sends clear text to server
4. **Server processes** clear text (temporary cache for last 3 chats)
5. **Server streams** response to client
6. **Client encrypts** response and stores on server

## Required Changes

### 1. Database Schema Updates

#### Backend Schema Changes (`backend/core/directus/schemas/`)

**File: `chats.yml`**
```yaml
# Add new encrypted field
encrypted_mates:
  type: json
  note: "[Encrypted] Array of mate categories, encrypted using chat-specific key"
```

**File: `messages.yml`**
```yaml
# Add new encrypted fields
encrypted_sender_name:
  type: string
  note: "[Encrypted] Sender name, encrypted using chat-specific key"
encrypted_category:
  type: string  
  note: "[Encrypted] Category, encrypted using chat-specific key"
```

### 2. Backend Implementation Changes

#### Encryption Service Updates (`backend/core/api/app/utils/encryption.py`)

**Current State**: Server-side encryption/decryption for chat content
**Target State**: Client-side encryption only, server stores encrypted data

**Changes Needed**:
- Remove server-side decryption for AI processing
- Keep encryption methods for storage only
- Update key management for chat-specific keys

#### Chat Methods Updates (`backend/core/api/app/services/directus/chat_methods.py`)

**Changes Needed**:
- Add encryption/decryption for `mates` field
- Update `get_chat_metadata` to decrypt `mates`
- Update `update_chat_fields_in_directus` to encrypt `mates`
- Remove server-side decryption for AI processing

#### Message Handler Updates (`backend/core/api/app/routes/handlers/websocket_handlers/message_received_handler.py`)

**Changes Needed**:
- Encrypt `sender_name` and `category` before storing
- Update message creation to include encrypted fields
- Remove server-side decryption for AI processing

#### Persistence Tasks Updates (`backend/core/api/app/tasks/persistence_tasks.py`)

**Changes Needed**:
- Add encrypted `sender_name` and `category` to message creation
- Update message retrieval to handle encrypted fields
- Remove server-side decryption

### 3. Frontend Implementation Changes

#### Crypto Service Updates (`frontend/packages/ui/src/services/cryptoService.ts`)

**Changes Needed**:
- Add methods for chat-specific encryption/decryption
- Add methods for encrypting/decrypting JSON arrays (mates)
- Extend existing `encryptWithMasterKey`/`decryptWithMasterKey` for chat-specific keys

#### Database Service Updates (`frontend/packages/ui/src/services/db.ts`)

**Changes Needed**:
- Add encryption/decryption for `mates` field
- Add encryption/decryption for message `sender_name` and `category`
- Update message storage/retrieval methods

#### Chat Types Updates (`frontend/packages/ui/src/types/chat.ts`)

**Changes Needed**:
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

#### Chat Components Updates

**Files to Update**:
- `frontend/packages/ui/src/components/chats/Chat.svelte`
- `frontend/packages/ui/src/components/ActiveChat.svelte`
- `frontend/packages/ui/src/services/chatSyncServiceHandlersChatUpdates.ts`
- `frontend/packages/ui/src/services/chatSyncServiceHandlersCoreSync.ts`

**Changes Needed**:
- Decrypt `mates` for display
- Decrypt message `sender_name` and `category` for display
- Update chat list to show decrypted mate information

### 4. AI Processing Changes

#### Stream Consumer Updates (`backend/apps/ai/tasks/stream_consumer.py`)

**Changes Needed**:
- Remove server-side decryption
- Work with encrypted content or receive decrypted content from client
- Update AI processing to handle client-provided decrypted content

#### Ask Skill Task Updates (`backend/apps/ai/tasks/ask_skill_task.py`)

**Changes Needed**:
- Update to receive decrypted content from client
- Remove server-side decryption logic
- Ensure AI processing works with client-provided clear text

## Implementation Checklist

### Phase 1: Backend Schema and Infrastructure
- [ ] **Update Chat Schema** (`backend/core/directus/schemas/chats.yml`)
  - Add `encrypted_mates` field
- [ ] **Update Message Schema** (`backend/core/directus/schemas/messages.yml`)
  - Add `encrypted_sender_name` field
  - Add `encrypted_category` field
- [ ] **Update Chat Methods** (`backend/core/api/app/services/directus/chat_methods.py`)
  - Add encryption/decryption for `mates` field
  - Update `get_chat_metadata` to decrypt `mates`
  - Update `update_chat_fields_in_directus` to encrypt `mates`
- [ ] **Update Message Handler** (`backend/core/api/app/routes/handlers/websocket_handlers/message_received_handler.py`)
  - Encrypt `sender_name` and `category` before storing
  - Update message creation to include encrypted fields
- [ ] **Update Persistence Tasks** (`backend/core/api/app/tasks/persistence_tasks.py`)
  - Add encrypted `sender_name` and `category` to message creation
  - Update message retrieval to handle encrypted fields

### Phase 2: Frontend Encryption Implementation
- [ ] **Update Crypto Service** (`frontend/packages/ui/src/services/cryptoService.ts`)
  - Add methods for chat-specific encryption/decryption
  - Add methods for encrypting/decrypting JSON arrays (mates)
  - Extend existing encryption methods for chat-specific keys
- [ ] **Update Database Service** (`frontend/packages/ui/src/services/db.ts`)
  - Add encryption/decryption for `mates` field
  - Add encryption/decryption for message `sender_name` and `category`
  - Update message storage/retrieval methods
- [ ] **Update Chat Types** (`frontend/packages/ui/src/types/chat.ts`)
  - Add `encrypted_mates` field to Chat interface
  - Add `encrypted_sender_name` and `encrypted_category` fields to Message interface
- [ ] **Update Chat Components**
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
- [ ] **Data Migration Script**
  - Encrypt existing `mates` data
  - Update existing messages to encrypt `sender_name` and `category`
  - Handle backward compatibility during transition

## Security Considerations

### Key Management
- **Key Rotation**: Implement key rotation for chat-specific keys
- **Key Backup**: Ensure chat keys are backed up for data recovery
- **Key Sharing**: Design for future multi-user chat support

### Access Control
- **User Isolation**: Ensure users can only access their own encrypted data
- **Chat Isolation**: Ensure chat-specific keys are properly isolated
- **Admin Access**: Design admin access patterns for support/debugging

## Migration Strategy

### Data Migration
1. **Existing Chats**: Add migration script to encrypt existing `mates` data
2. **Existing Messages**: Update existing messages to encrypt `sender_name` and `category`
3. **Gradual Rollout**: Deploy backend changes first, update frontend to handle both encrypted and plaintext data, run migration script, remove plaintext fallback code

### Backward Compatibility
1. **Dual Support**: Support both encrypted and plaintext data during transition
2. **Migration Detection**: Detect unencrypted data and encrypt on access
3. **Version Flags**: Use version fields to track encryption status

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

## Questions for Implementation

1. **Key Strategy**: Should we use chat-specific keys or user-specific keys?
2. **Migration Timeline**: How quickly should we migrate existing data?
3. **AI Processing**: How should we handle AI processing with encrypted content?
4. **Performance**: What's the acceptable performance impact of additional encryption?
5. **Backup/Recovery**: How should we handle key recovery for lost chats?

## Next Steps

1. **Review and Approve**: Review this implementation plan
2. **Detailed Implementation**: Create detailed task breakdown for each phase
3. **Migration Script Design**: Design data migration approach
4. **Testing Plan**: Create comprehensive testing strategy
5. **Security Review**: Conduct security review of proposed changes

---

*This implementation plan aligns with the zero-knowledge architecture described in `/docs/architecture/message_processing.md` and ensures that all chat encryption and decryption happens on the client side, with the server only storing encrypted data and processing decrypted content on-demand.*