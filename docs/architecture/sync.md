# Sync Architecture - Zero-Knowledge Chat Encryption

## Overview

This document outlines the updated sync architecture that aligns with the zero-knowledge chat encryption implementation. The sync process is designed to prioritize user experience while maintaining security through client-side encryption.

## Core Principles

- **Zero-Knowledge Architecture**: All chat encryption/decryption happens on the client side
- **Server Never Has Decryption Keys**: Server only stores encrypted data and processes decrypted content on-demand
- **Phased Sync**: Prioritize last opened chat, then recent chats, then full sync
- **Immediate User Experience**: Open last chat instantly after decryption
- **Encrypted Storage**: All data remains encrypted in IndexedDB


## Sync Process Overview

### Login Flow
1. **Authentication**: User logs in successfully
2. **Cache Warming**: Server-side cache warming starts (encrypted data only)
3. **Phased Sync**: Client receives data in prioritized phases
4. **Immediate Opening**: Last opened chat is decrypted and opened instantly
5. **Background Sync**: Remaining chats sync in background

### Sync Architecture Diagram

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   User Login    │───▶│  Server Cache    │───▶│  Client Sync    │
│                 │    │  Warming         │    │  Service        │
└─────────────────┘    └──────────────────┘    └─────────────────┘
                                │                        │
                                ▼                        ▼
                    ┌──────────────────┐    ┌─────────────────┐
                    │  Directus DB     │    │  IndexedDB      │
                    │  (Encrypted)     │    │  (Encrypted)    │
                    └──────────────────┘    └─────────────────┘
                                │                        │
                                ▼                        ▼
                    ┌──────────────────┐    ┌─────────────────┐
                    │  WebSocket       │    │  Memory         │
                    │  (Encrypted)     │    │  (Decrypted)    │
                    └──────────────────┘    └─────────────────┘
                                                        │
                                                        ▼
                                               ┌─────────────────┐
                                               │  UI Display    │
                                               │  (Decrypted)   │
                                               └─────────────────┘

Phase 1: Last Opened Chat (Immediate)
Phase 2: Last 10 Chats (Quick Access)  
Phase 3: Last 100 Chats (Full Sync)
```

## Phased Sync Architecture

### Phase 1: Last Opened Chat (Immediate Priority)
**Goal**: Get user into their last chat as quickly as possible

**Process**:
1. **Server**: Load last opened chat metadata and all messages from Directus
2. **Server**: Send encrypted chat data via WebSocket "priority_chat_ready" event
3. **Client**: Receive encrypted data and store in IndexedDB (encrypted)
4. **Client**: Decrypt chat metadata and messages using chat-specific key
5. **Client**: Open chat in UI immediately after decryption
6. **Client**: Dispatch "chatOpened" event to update UI state

**Data Flow**:
```
Directus (Encrypted) → WebSocket (Encrypted) → IndexedDB (Encrypted) → Memory (Decrypted) → UI
```

**Directus Requests**:
- Request 1: Get chat metadata by `last_opened` field from user profile
- Request 2: Get all messages for that chat_id
- Both requests return encrypted data only

**Encryption Flow Diagram**:
```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   Directus      │    │   WebSocket      │    │   IndexedDB     │
│   (Encrypted)   │───▶│   (Encrypted)    │───▶│   (Encrypted)   │
└─────────────────┘    └──────────────────┘    └─────────────────┘
                                                        │
                                                        ▼
                                               ┌─────────────────┐
                                               │   Memory        │
                                               │   (Decrypted)   │
                                               └─────────────────┘
                                                        │
                                                        ▼
                                               ┌─────────────────┐
                                               │   UI Display    │
                                               │   (Decrypted)   │
                                               └─────────────────┘

Key Points:
- Server never decrypts data
- All storage remains encrypted
- Decryption only happens in client memory
- UI displays decrypted content
```

### Phase 2: Last 10 Updated Chats (Quick Access)
**Goal**: Provide quick access to recent chats

**Process**:
1. **Server**: Load last 10 updated chats (by `last_edited_overall_timestamp`)
2. **Server**: Send encrypted chat metadata via WebSocket
3. **Client**: Store encrypted data in IndexedDB
4. **Client**: Decrypt chat metadata for display in chat list
5. **Client**: Update chat list UI with decrypted titles and metadata

**Data Flow**:
```
Directus (Encrypted) → WebSocket (Encrypted) → IndexedDB (Encrypted) → Memory (Decrypted) → Chat List UI
```

### Phase 3: Last 100 Updated Chats (Full Sync)
**Goal**: Complete sync of user's recent chat history

**Process**:
1. **Server**: Load last 100 updated chats and their messages
2. **Server**: Send encrypted data in batches via WebSocket
3. **Client**: Store all encrypted data in IndexedDB
4. **Client**: Decrypt metadata for chat list display
5. **Client**: Keep messages encrypted until needed for display

**Data Flow**:
```
Directus (Encrypted) → WebSocket (Batched Encrypted) → IndexedDB (Encrypted) → Memory (Decrypted as needed)
```


## Encryption Strategy

### Chat-Specific Keys
- **Generation**: Client generates unique AES key per chat
- **Encryption**: Chat key encrypted with user's master key
- **Storage**: Encrypted chat key stored in `chats.encrypted_chat_key` field
- **Access**: Client decrypts chat key using master key when needed

### Data Encryption Levels
1. **Chat Metadata**: Encrypted with chat-specific key
   - `encrypted_title`, `encrypted_mates`, `encrypted_active_focus_id`
2. **Message Content**: Encrypted with chat-specific key
   - `encrypted_content`, `encrypted_sender_name`, `encrypted_category`
3. **User Data**: Encrypted with user-specific key
   - `encrypted_draft_md`, `encrypted_draft_preview`, `encrypted_email_address`

### Server-Side Encryption (Keep As Is)
- **Billing Data**: `encrypted_credit_balance`, `encrypted_stripe_payment_method_id`
- **Security Data**: `encrypted_tfa_secret`
- **App Settings**: `user_app_settings_and_memories` collection

## Architecture Components

### Backend Components

#### Cache Warming Tasks
- **Purpose**: Load encrypted chat data from Directus without server-side decryption
- **Phase 1**: Load last opened chat with encrypted metadata and messages
- **Phase 2**: Load last 10 updated chats for quick access
- **Phase 3**: Load last 100 updated chats for full sync
- **Key Principle**: Server never decrypts data, only stores and forwards encrypted content

#### Directus Methods
- **Encrypted Data Retrieval**: Fetch chat metadata and messages in encrypted format
- **No Server Decryption**: All data remains encrypted during server processing
- **Batch Operations**: Efficient retrieval of multiple chats and messages
- **Zero-Knowledge Compliance**: Server has no access to decryption keys

#### WebSocket Handlers
- **Phased Sync Coordination**: Manage the three-phase sync process
- **Event Broadcasting**: Send encrypted data to clients in priority order
- **Connection Management**: Handle multiple device synchronization
- **Error Handling**: Manage sync failures and retries

### Frontend Components

#### Chat Sync Service
- **Phased Sync Management**: Coordinate the three-phase sync process
- **Event Handling**: Listen for server events and manage client responses
- **State Management**: Track sync progress and handle transitions
- **Error Recovery**: Handle sync failures and implement retry logic

#### Chat Components
- **Auto-Open Logic**: Automatically open last chat after Phase 1 sync
- **Decryption Handling**: Decrypt chat data for display while keeping IndexedDB encrypted
- **UI Updates**: Update chat list and active chat based on sync progress
- **Event Dispatching**: Notify other components of sync state changes

#### Database Service
- **Encrypted Storage**: Store all data encrypted in IndexedDB
- **On-Demand Decryption**: Decrypt data only when needed for display
- **Memory Management**: Keep decrypted data in memory, encrypted data persisted
- **Key Management**: Handle chat-specific encryption keys securely

## Event Flow

### Phase 1 Events
1. `priorityChatReady` - Server sends encrypted last opened chat
2. `chatDecrypted` - Client decrypts chat data
3. `chatOpened` - Client opens chat in UI
4. `phase1Complete` - Phase 1 sync complete

### Phase 2 Events
1. `recentChatsReady` - Server sends encrypted recent chats
2. `chatsDecrypted` - Client decrypts chat metadata
3. `chatListUpdated` - Client updates chat list UI
4. `phase2Complete` - Phase 2 sync complete

### Phase 3 Events
1. `fullSyncReady` - Server sends encrypted full chat data
2. `syncComplete` - All phases complete
3. `cachePrimed` - Client cache fully populated

## Performance Optimizations

### Minimize Directus Requests
1. **Batch Requests**: Combine chat metadata and messages in single requests
2. **Parallel Processing**: Run Phase 2 and 3 in parallel where possible
3. **Incremental Updates**: Only sync changed data after initial load
4. **Smart Caching**: Cache encrypted data efficiently

### Client-Side Optimizations
1. **Lazy Decryption**: Only decrypt data when needed for display
2. **Memory Management**: Keep encrypted data in IndexedDB, decrypted in memory
3. **Background Processing**: Decrypt chats in background after Phase 1
4. **Efficient Updates**: Update only changed chat data

## Security Considerations

### Sync-Specific Security
- **Server Never Decrypts**: All decryption happens on client during sync
- **Encrypted Storage**: IndexedDB stores only encrypted data
- **Key Isolation**: Chat keys isolated per chat
- **Memory Security**: Decrypted data only in memory, never persisted
- **Phased Sync Security**: Each sync phase maintains zero-knowledge compliance

### Sync Data Protection
- **Encrypted Transmission**: All sync data encrypted during WebSocket transmission
- **Client-Only Decryption**: Decryption only happens in client memory
- **Secure Key Access**: Chat keys decrypted using master key derived from login credentials
- **Device Sync Security**: Encrypted keys enable secure synchronization across devices

**For comprehensive security architecture including authentication, key management, and encryption details, see [Security Architecture](security.md)**

## Key Management Strategy

### Zero-Knowledge Key Architecture
- **Server Never Has Decryption Keys**: Server cannot decrypt any user data
- **Encrypted Key Storage**: Chat-specific encryption keys are stored on server, encrypted with user's master key
- **Client-Only Decryption**: All decryption happens exclusively on the client side
- **Device Sync**: Encrypted keys enable synchronization across user devices
- **Login-Based Key Derivation**: User login credentials derive the master key for decrypting chat keys

### Key Derivation Flow
```
Login Method → Wrapped Master Key → Master Key → Chat Keys → Data Decryption
     │              │                    │           │            │
     ▼              ▼                    ▼           ▼            ▼
┌─────────┐  ┌─────────────────┐  ┌─────────────┐  ┌─────────┐  ┌─────────┐
│ Login   │  │ Wrapped Master │  │ Master Key  │  │ Chat    │  │ Decrypted│
│ Creds   │  │ Key (Server)   │  │ (Client)    │  │ Keys    │  │ Data    │
└─────────┘  └─────────────────┘  └─────────────┘  └─────────┘  └─────────┘
```

**For detailed key management and security architecture, see [Security Architecture](security.md)**

### Implementation Strategy
- **Clean Implementation**: Build new zero-knowledge architecture from scratch
- **No Legacy Support**: Remove all plaintext data handling
- **Fresh Start**: Implement clean, secure architecture without backward compatibility
- **Performance Focus**: Optimize for zero-knowledge architecture from day one

## Storage Limits and Eviction Policy

### Goal
Keep the local cache fast and predictable. Sync up to 100 most recent chats (plus last opened and drafts). If local storage would overflow, evict the single oldest cached chat entirely.

### Sync Strategy
- **Phase 1**: Load last opened chat first (full), include current drafts
- **Phase 2**: Load last 10 updated chats for quick access
- **Phase 3**: Load last 100 updated chats for full sync
- **Storage Management**: Replace local set with server data during sync

### Eviction on Overflow
- **Trigger**: When new messages arrive or syncing a chat would exceed IndexedDB limits
- **Action**: Delete the oldest chat in the local set (metadata + messages + embed contents) and retry the write
- **Oldest Definition**: Least recent by last_updated/last_opened; pinned chats (if supported later) are not considered oldest

### Older Chats on Demand
- **User Action**: When user scrolls and clicks "Show more"
- **Behavior**: Fetch older messages from server and keep them in memory only (do not persist in IndexedDB)
- **Promotion**: If user sends message or adds draft in older chat, it becomes recent and is persisted
- **Eviction**: To keep the cap, evict the oldest persisted chat if needed

### Parsing Implications
- **Lightweight Messages**: Messages use lightweight embed nodes with `contentRef` and minimal metadata
- **Render-Time Previews**: Previews are derived at render-time
- **On-Demand Loading**: Full content loads/decrypts on demand in fullscreen
- **Fallback Handling**: If evicted `contentRef` is missing locally, fullscreen fetches on demand or reconstructs from canonical markdown when available

## Drafts

### Draft Storage and Sync
- **Server Storage**: Drafts stored on server in chats model "draft" field
- **Multi-Device Sync**: When draft updated on one device, sent to server and distributed to other logged-in devices
- **Server Cache**: Draft saved to server cache for devices coming online after network interruption
- **Encryption**: Cached draft encrypted via client-created wrapped encryption key - server cannot read draft content
- **Cache Expiry**: Cached draft auto-expires after 2 hours, then chat entry in Directus updated with new draft value
- **Deletion Sync**: If draft deleted (message input field empty), sync that change to all devices and server cache

## Opening Chat

### Chat Opening Process
- **Decryption**: When chat opened, decrypt chat and display in web UI
- **Background Decryption**: Consider decrypting all chats in background and keeping them decrypted in memory on client
- **Page Reload**: Note that decryption needs to be redone on page reload
- **Memory Management**: Balance between performance (decrypted in memory) and security (re-decrypt on reload)

## Search

### Search Implementation (Future)
- **Scope**: Cover chats and their content (drafts, messages, files, embedded previews)
- **Settings Search**: Include app settings and memories (with optional hiding from search)
- **Quick Access**: Allow quick access to settings and their options
- **Data Source**: All data stored in IndexedDB
- **Index Building**: Build search index after all chats and messages are synced
- **Privacy**: Maintain zero-knowledge architecture during search operations

## Next Steps

1. **Clean Implementation**: Build new phased sync system with zero-knowledge architecture
2. **Key Management**: Implement secure key derivation and storage
3. **Testing**: Comprehensive testing of zero-knowledge compliance
4. **Deployment**: Deploy clean, secure implementation
5. **Monitoring**: Monitor performance and security of new architecture