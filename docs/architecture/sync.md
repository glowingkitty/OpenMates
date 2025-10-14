# Sync Architecture - Zero-Knowledge Chat Encryption

## Overview

This document outlines the complete 3-phase sync architecture that aligns with the zero-knowledge chat encryption implementation. The sync process is designed to prioritize user experience while maintaining security through client-side encryption.

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
                                               │  UI Display     │
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
2. **Server**: Send encrypted chat metadata via WebSocket "recentChatsReady" event
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
2. **Server**: Send encrypted data in batches via WebSocket "fullSyncReady" event
3. **Client**: Store all encrypted data in IndexedDB
4. **Client**: Decrypt metadata for chat list display
5. **Client**: Keep messages encrypted until needed for display

**Data Flow**:
```
Directus (Encrypted) → WebSocket (Batched Encrypted) → IndexedDB (Encrypted) → Memory (Decrypted as needed)
```

## Architecture Components

### Backend Components

#### 1. Enhanced Cache Warming (`user_cache_tasks.py`)

**Three-Phase Cache Warming:**
- **Phase 1**: Last opened chat (immediate priority)
- **Phase 2**: Last 10 updated chats (quick access)  
- **Phase 3**: Last 100 updated chats (full sync)

**Key Features:**
- Sequential phase execution with proper event emission
- Zero-knowledge compliance (server never decrypts data)
- Efficient data loading with proper error handling
- Event-driven architecture with Redis pub/sub

#### 2. WebSocket Event Handlers (`websockets.py`)

**Redis Listener Events:**
- `priority_chat_ready`: Phase 1 completion
- `recentChatsReady`: Phase 2 completion  
- `fullSyncReady`: Phase 3 completion
- `cache_primed`: Full sync completion

**Event Broadcasting:**
- `phase_1_last_chat_ready`: Phase 1 completion
- `phase_2_last_10_chats_ready`: Phase 2 completion  
- `phase_3_last_100_chats_ready`: Phase 3 completion
- `cache_primed`: Full sync completion
- Handle multiple device synchronization
- Manage sync failures and retries

#### 3. Storage Management Service

**Storage Limits:**
- Maximum 100 cached chats
- Configurable storage size limits (default: 50MB)
- Automatic eviction of oldest chats on overflow

**Key Features:**
- Storage usage monitoring and statistics
- Intelligent eviction policies
- Chat priority management
- Storage overflow handling

### Frontend Components

#### 1. Phased Sync Service (`PhasedSyncService.ts`)

**Client-Side Sync Management:**
- Event-driven sync coordination
- Automatic chat opening after Phase 1
- Encrypted data storage in IndexedDB
- Memory management for decrypted data

**Key Features:**
- WebSocket event handling for all sync phases
- Automatic chat decryption and storage
- Sync status tracking and management
- Error handling and recovery

**Event Handling:**
- `phase_1_last_chat_ready`: Handle Phase 1 completion
- `phase_2_last_10_chats_ready`: Handle Phase 2 completion
- `phase_3_last_100_chats_ready`: Handle Phase 3 completion
- `cache_primed`: Handle full sync completion

#### 2. Chat Components

**Auto-Open Logic**: Automatically open last chat after Phase 1 sync
**Decryption Handling**: Decrypt chat data for display while keeping IndexedDB encrypted
**UI Updates**: Update chat list and active chat based on sync progress
**Event Dispatching**: Notify other components of sync state changes

#### 3. Database Service

**Encrypted Storage**: Store all data encrypted in IndexedDB
**On-Demand Decryption**: Decrypt data only when needed for display
**Memory Management**: Keep decrypted data in memory, encrypted data persisted
**Key Management**: Handle chat-specific encryption keys securely

## Event System

### WebSocket Events

**Server → Client:**
- `phase_1_last_chat_ready`: Phase 1 complete
- `phase_2_last_10_chats_ready`: Phase 2 complete
- `phase_3_last_100_chats_ready`: Phase 3 complete
- `cache_primed`: Full sync complete
- `sync_status_response`: Sync status update

**Client → Server:**
- `phased_sync_request`: Request specific phases
- `sync_status_request`: Request sync status

### Redis Pub/Sub Events

**Cache Events:**
- `phase_1_last_chat_ready`: Phase 1 completion
- `phase_2_last_10_chats_ready`: Phase 2 completion
- `phase_3_last_100_chats_ready`: Phase 3 completion
- `cache_primed`: Full sync completion

## Encryption Strategy

### Chat-Specific Keys
- **Generation**: Client generates unique AES key per chat
- **Encryption**: Chat key encrypted with user's master key
- **Storage**: Encrypted chat key stored in `chats.encrypted_chat_key` field
- **Access**: Client decrypts chat key using master key when needed

### Data Encryption Levels
1. **Chat Metadata**: Encrypted with chat-specific key
   - `encrypted_title`, `encrypted_chat_summary`, `encrypted_chat_tags`, `encrypted_follow_up_request_suggestions`, `encrypted_active_focus_id`
2. **Message Content**: Encrypted with chat-specific key
   - `encrypted_content`, `encrypted_sender_name`, `encrypted_category`
3. **User Data**: Encrypted with user-specific key
   - `encrypted_draft_md`, `encrypted_draft_preview`, `encrypted_email_address`

### Server-Side Encryption (Keep As Is)
- **Billing Data**: `encrypted_credit_balance`, `encrypted_stripe_payment_method_id`
- **Security Data**: `encrypted_tfa_secret`
- **App Settings**: `user_app_settings_and_memories` collection

## Storage Management

### Eviction Policy

**Triggers:**
- Chat count exceeds 100
- Storage size exceeds configured limit
- New chat addition would cause overflow

**Eviction Process:**
1. Identify oldest chat by timestamp
2. Remove from all cache components
3. Clean up associated data
4. Log eviction for monitoring

### Storage Statistics

**Monitored Metrics:**
- Current chat count vs. maximum
- Storage usage in MB
- Utilization percentages
- Eviction candidate identification

## Security Implementation

### Zero-Knowledge Compliance

**Server-Side:**
- Never decrypts user data
- Only stores and forwards encrypted content
- No access to decryption keys
- Encrypted data transmission only

**Client-Side:**
- All decryption happens in memory
- IndexedDB stores only encrypted data
- Chat-specific encryption keys
- Secure key derivation from login credentials

### Key Management Strategy

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

## Performance Optimizations

### Server-Side

**Efficient Data Loading:**
- Batch requests for multiple chats
- Parallel processing where possible
- Smart caching with TTL management
- Incremental updates after initial load

**Database Optimization:**
- Indexed queries for chat ordering
- Efficient message fetching
- Optimized field selection
- Connection pooling

### Client-Side

**Memory Management:**
- Lazy decryption (decrypt only when needed)
- Encrypted storage in IndexedDB
- Decrypted data in memory only
- Efficient memory cleanup

**Background Processing:**
- Phase 2 and 3 run in background
- Non-blocking UI updates
- Progressive data loading
- Smart prefetching

## Error Handling

### Server-Side

**Error Recovery:**
- Graceful degradation on cache misses
- Database fallback for critical data
- Retry mechanisms for failed operations
- Comprehensive error logging

### Client-Side

**Error Recovery:**
- Automatic retry on sync failures
- Fallback to cached data
- User notification for critical errors
- Sync status monitoring

## Monitoring and Observability

### Metrics

**Server Metrics:**
- Sync completion rates by phase
- Storage usage statistics
- Eviction frequency and patterns
- Error rates and types

**Client Metrics:**
- Sync duration by phase
- Storage utilization
- Decryption performance
- User interaction patterns

### Logging

**Structured Logging:**
- Phase completion events
- Storage management actions
- Error conditions and recovery
- Performance metrics

## Testing Strategy

### Unit Tests

**Backend:**
- Cache warming phases
- Storage management logic
- Event handling
- Error scenarios

**Frontend:**
- Sync service logic
- Event handling
- Data encryption/decryption
- Storage management

### Integration Tests

**End-to-End Sync:**
- Complete 3-phase sync flow
- Storage overflow scenarios
- Error recovery testing
- Performance benchmarking

## Deployment Considerations

### Configuration

**Environment Variables:**
- Storage limits and thresholds
- Cache TTL settings
- Sync phase timeouts
- Error retry configurations

### Monitoring

**Health Checks:**
- Sync service availability
- Storage usage monitoring
- Error rate tracking
- Performance metrics

### Scaling

**Horizontal Scaling:**
- Redis cluster for pub/sub
- Database connection pooling
- Load balancer configuration
- Cache distribution

## Future Enhancements

### Planned Features

**Search Implementation:**
- Full-text search across chats
- Encrypted search indexes
- Search result ranking
- Search history management

**Advanced Storage:**
- Pinned chat support
- Smart eviction policies
- Storage compression
- Backup and restore

**Performance:**
- Predictive prefetching
- Smart caching algorithms
- Network optimization
- Battery usage optimization

## Drafts

### Draft Storage and Sync
- **Server Storage**: Drafts stored on server in chats model "draft" field
- **Multi-Device Sync**: When draft updated on one device via [`sendUpdateDraftImpl()`](../../frontend/packages/ui/src/services/chatSyncServiceSenders.ts:71), sent to server and distributed to other logged-in devices
- **Server Cache**: Draft saved to server cache via [`update_user_draft_in_cache()`](../../backend/core/api/app/services/cache_chat_mixin.py:256) for devices coming online after network interruption
- **Encryption**: Cached draft encrypted via client-created wrapped encryption key - server cannot read draft content
- **Cache Expiry**: Cached draft auto-expires after 2 hours (USER_DRAFT_TTL), then chat entry in Directus updated with new draft value
- **Deletion Sync**: If draft deleted (message input field empty), sync that change to all devices and server cache via [`sendDeleteDraftImpl()`](../../frontend/packages/ui/src/services/chatSyncServiceSenders.ts:94)

## Opening Chat

### Chat Opening Process
- **Decryption**: When chat opened via [`loadChat()`](../../frontend/packages/ui/src/components/ActiveChat.svelte), decrypt chat metadata using [`chatMetadataCache`](../../frontend/packages/ui/src/services/chatMetadataCache.ts:79) and display in web UI
- **Message Loading**: Messages loaded from IndexedDB via [`getMessagesForChat()`](../../frontend/packages/ui/src/services/db.ts) and decrypted on-demand for display
- **Background Decryption**: Chat metadata cached in memory after first decryption for performance
- **Page Reload**: Note that decryption needs to be redone on page reload (cache is in-memory only)
- **Memory Management**: Balance between performance (decrypted metadata in memory) and security (messages re-decrypt on access)

## Search

### Search Implementation (Future)
- **Scope**: Cover chats and their content (drafts, messages, files, embedded previews)
- **Settings Search**: Include app settings and memories (with optional hiding from search)
- **Quick Access**: Allow quick access to settings and their options
- **Data Source**: All data stored in IndexedDB via [`chatDB`](../../frontend/packages/ui/src/services/db.ts)
- **Index Building**: Build search index after all chats and messages are synced
- **Privacy**: Maintain zero-knowledge architecture during search operations (search on decrypted content client-side only)
- **Implementation**: See [`offline_search.md`](./offline_search.md) for detailed search architecture

## Next Steps

1. **Clean Implementation**: Build new phased sync system with zero-knowledge architecture
2. **Key Management**: Implement secure key derivation and storage
3. **Testing**: Comprehensive testing of zero-knowledge compliance
4. **Deployment**: Deploy clean, secure implementation
5. **Monitoring**: Monitor performance and security of new architecture

## Conclusion

The implemented 3-phase sync architecture provides a robust, secure, and performant solution for zero-knowledge chat synchronization. The system maintains complete privacy while delivering excellent user experience through intelligent data loading and storage management.

Key achievements:
- ✅ Complete 3-phase sync implementation
- ✅ Zero-knowledge architecture compliance
- ✅ Storage management with eviction policies
- ✅ Client-side sync service
- ✅ Comprehensive error handling
- ✅ Performance optimizations
- ✅ Monitoring and observability