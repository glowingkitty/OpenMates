# Sync Architecture - Zero-Knowledge Chat Encryption

## Overview

This document outlines the complete 3-phase sync architecture that aligns with the zero-knowledge chat encryption implementation. The sync process is designed to prioritize user experience while maintaining security through client-side encryption.

## Core Principles

- **Zero-Knowledge Architecture**: All chat encryption/decryption happens on the client side
- **Server Never Has Decryption Keys**: Server only stores encrypted data and processes decrypted content on-demand
- **Phased Sync**: Prioritize last opened chat, then recent chats, then full sync
- **Immediate User Experience**: Open last chat instantly after decryption
- **Encrypted Storage**: All data remains encrypted in IndexedDB

## Sync Security Controls

| Security Control | Implementation | Benefit |
|---|---|---|
| **Client-side decryption** | `frontend/packages/ui/src/services/cryptoService.ts:200-250` | Server never sees plaintext chat data |
| **Encrypted IndexedDB** | `frontend/packages/ui/src/services/db.ts` | Data at rest encrypted on client |
| **AES-256-GCM encryption** | `cryptoService.ts:200-250` | Authenticated encryption (detects tampering) |
| **Master key protection** | `cryptoService.ts:121-155` | SessionStorage only (clears on page close) |
| **Device verification** | `auth_login.py:829-852` | Only authenticated devices receive key data |
| **Rate-limited access** | `auth_login.py:50-51` | Brute force attacks mitigated |

## Sync Process Overview

### Login Flow
1. **Email Lookup**: User enters email → `/lookup` endpoint caches user profile and **starts predictive cache warming** (encrypted data only)
2. **User Authentication**: User enters password + 2FA while cache warming runs in background
3. **Login Success**: User clicks login → Authentication succeeds → **Chats already cached!** ✅
4. **Phased Sync**: Client receives cached data in prioritized phases via WebSocket
5. **Immediate Opening**: Last opened chat is decrypted and opened instantly
6. **Background Sync**: Remaining chats sync in background

### Sync Architecture Diagram

```
┌─────────────────┐    ┌──────────────────────────┐    ┌─────────────────┐
│  Email Lookup   │───▶│  Predictive Cache Start  │───▶│  User Types     │
│  (/lookup)      │    │  (Background Warming)    │    │  Password + 2FA │
└─────────────────┘    └──────────────────────────┘    └─────────────────┘
                                │                                │
                                ▼                                ▼
                    ┌──────────────────┐              ┌─────────────────┐
                    │  Cache Ready! ✅  │◀─────────────│  User Clicks    │
                    │  (Encrypted)     │              │  Login Button   │
                    └──────────────────┘              └─────────────────┘
                                │                                │
                                ▼                                ▼
                    ┌──────────────────┐              ┌─────────────────┐
                    │  Directus DB     │              │  Client Sync    │
                    │  (Encrypted)     │              │  Service        │
                    └──────────────────┘              └─────────────────┘
                                                               │
                                                               ▼
                                                    ┌─────────────────┐
                                                    │  IndexedDB      │
                                                    │  (Encrypted)    │
                                                    └─────────────────┘
                                                               │
                                                               ▼
                                                    ┌─────────────────┐
                                                    │  Memory         │
                                                    │  (Decrypted)    │
                                                    └─────────────────┘
                                                               │
                                                               ▼
                                                    ┌─────────────────┐
                                                    │  UI Display     │
                                                    │  (Decrypted)    │
                                                    └─────────────────┘

Phase 1: Last Opened Chat AND New Chat Suggestions (Immediate)
Phase 2: Last 20 Chats (Quick Access)  
Phase 3: Last 100 Chats (Full Sync)

Key Optimization: Cache warming starts BEFORE authentication completes!
```

## Phased Sync Architecture

### Phase 1: Last Opened Chat AND New Chat Suggestions (Immediate Priority)
**Goal**: Get user into their last opened content as quickly as possible with all needed data

**Process**:
1. **Server**: ALWAYS fetch latest 50 new chat suggestions from Directus
2. **Server**: Check user profile `last_opened` field
3. **Server**: If last opened is a chat (not "new"), load chat metadata and all messages
4. **Server**: Send BOTH chat data (if applicable) AND suggestions via WebSocket "phase_1_last_chat_ready" event
5. **Client**: Store suggestions in IndexedDB
6. **Client**: Dispatch "newChatSuggestionsReady" event for immediate display
7. **Client**: If chat data present, decrypt and store in IndexedDB (encrypted)
8. **Client**: If chat data present, open chat in UI immediately after decryption
9. **Client**: Dispatch "chatOpened" event to update UI state (if chat was opened)

**Data Flow (Chat)**:
```
Directus (Encrypted) → WebSocket (Encrypted) → IndexedDB (Encrypted) → Memory (Decrypted) → UI
```

**Data Flow (Suggestions)**:
```
Directus (Unencrypted) → WebSocket (Unencrypted) → IndexedDB → UI
```

**Directus Requests**:
- Request 1: Get 50 new chat suggestions for user (always)
- Request 2: Get user profile to check `last_opened` field
- Request 3 (if not "new"): Get chat metadata and all messages for that chat_id (encrypted)

**Key Insight**: Phase 1 ALWAYS sends suggestions, ensuring users have immediate content regardless of whether they're viewing a chat or the new chat section.

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

### Phase 2: Last 20 Updated Chats (Quick Access)
**Goal**: Provide quick access to recent chats

**Process**:
1. **Server**: Load last 20 updated chats (by `last_edited_overall_timestamp`)
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
2. **Server**: Send encrypted data in batches via WebSocket "phase_3_last_100_chats_ready" event
3. **Client**: Store all encrypted data in IndexedDB
4. **Client**: Decrypt metadata for chat list display
5. **Client**: Keep messages encrypted until needed for display

**Data Flow**:
```
Directus (Encrypted) → WebSocket (Batched Encrypted) → IndexedDB (Encrypted) → Memory (Decrypted as needed)
```

**Note**: Phase 3 NEVER sends new chat suggestions - they are ALWAYS sent in Phase 1 to ensure immediate availability.

## Predictive Cache Warming Optimization

### Overview
Cache warming now starts **predictively** during the `/lookup` endpoint (when user enters email), rather than waiting until after authentication succeeds. This provides instant sync UX.

### Implementation Details

**Timeline:**
1. User enters email → `/lookup` endpoint called
2. Server caches user profile (username, settings, etc.)
3. **NEW**: Server dispatches `warm_user_cache` Celery task (async, non-blocking)
4. User types password and 2FA code (~10-30 seconds)
5. Cache warming completes in background while user authenticates
6. User clicks "Login" → Authentication succeeds → **Cache already ready!** ✅
7. Instant WebSocket sync (data already in Redis)

**Security Properties:**
- ✅ **Zero-knowledge maintained**: All cached data is encrypted, server cannot decrypt
- ✅ **Rate limiting**: `/lookup` already has `3/minute` rate limit
- ✅ **Deduplication**: Checks `cache_primed` and `warming_in_progress` flags to prevent duplicate work
- ✅ **No premature transmission**: Data remains in server cache until authentication succeeds
- ✅ **Async dispatch**: Doesn't block `/lookup` response, user sees no latency
- ✅ **Fallback protection**: `/login` endpoint still dispatches cache warming if `/lookup` was skipped

**Code Locations:**
- **Primary trigger**: `/lookup` endpoint in `backend/core/api/app/routes/auth_routes/auth_login.py` (lines ~1040-1070)
- **Fallback trigger**: `/login` endpoint in same file (lines ~237-260, ~389-411, ~648-670)
- **Cache warming task**: `backend/core/api/app/tasks/user_cache_tasks.py`

**Deduplication Logic:**
```python
# Check if cache already primed
cache_primed = await cache_service.is_user_cache_primed(user_id)

# Check if warming already in progress
warming_flag = f"cache_warming_in_progress:{user_id}"
is_warming = await cache_service.get(warming_flag)

# Only start if not primed and not already warming
if not cache_primed and not is_warming:
    await cache_service.set(warming_flag, "warming", ttl=300)  # 5 min TTL
    app.send_task('app.tasks.user_cache_tasks.warm_user_cache', ...)
```

**Expected UX Impact:**
- **Before**: 2-5 second wait after login for chats to load
- **After**: Instant sync, chats appear immediately after login

## Architecture Components

### Backend Components

#### 1. Enhanced Cache Warming (`user_cache_tasks.py`)

**Three-Phase Cache Warming:**
- **Phase 1**: Last opened chat AND new chat suggestions (immediate priority)
  - ALWAYS loads new chat suggestions (50 latest)
  - If last opened = chat ID: Also load chat metadata and messages
  - If last opened = "new": Only suggestions (no chat)
- **Phase 2**: Last 20 updated chats (quick access)  
- **Phase 3**: Last 100 updated chats (full sync) - NO suggestions

**Key Features:**
- Sequential phase execution with proper event emission
- Zero-knowledge compliance (server never decrypts data)
- Suggestions ALWAYS loaded in Phase 1 for immediate availability
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
- `phase_2_last_20_chats_ready`: Phase 2 completion  
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
- `phase_2_last_20_chats_ready`: Handle Phase 2 completion
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
- `phase_2_last_20_chats_ready`: Phase 2 complete
- `phase_3_last_100_chats_ready`: Phase 3 complete
- `cache_primed`: Full sync complete
- `sync_status_response`: Sync status update

**Client → Server:**
- `phased_sync_request`: Request specific phases
- `sync_status_request`: Request sync status

### Redis Pub/Sub Events

**Cache Events:**
- `phase_1_last_chat_ready`: Phase 1 completion
- `phase_2_last_20_chats_ready`: Phase 2 completion
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

### Multi-Browser Instance Support

**Device Fingerprinting - Single Hash with SessionID:**

The system uses a clean single-hash approach where each browser instance is treated as a unique device:

**Device Hash Formula:**
```
SHA256(OS:Country:UserID:SessionID)
```

**How It Works:**
1. **SessionID Generation**: Each browser tab/instance generates a unique UUID stored in `sessionStorage`
2. **Login Flow**: Client sends `session_id` in login request body
3. **Device Hash Creation**: Backend generates hash including sessionId and stores in Directus
4. **WebSocket Connection**: Client sends same `session_id` in WebSocket URL: `ws://...?sessionId=abc123`
5. **Hash Verification**: Backend generates same hash and verifies against Directus
6. **Match**: Hashes match → connection authenticated ✅

**Benefits:**
- ✅ **Clean Architecture**: Single hash type, no dual-hash complexity
- ✅ **Explicit Devices**: Each browser instance is a separate "device" entry
- ✅ **No Conflicts**: Arc and Firefox on same physical device have unique hashes
- ✅ **No Overwrites**: ConnectionManager routes messages to correct browser instance
- ✅ **No Ping/Pong Issues**: Each instance has its own WebSocket connection
- ✅ **Security**: Device verification works same as before

**Example - Two Browsers:**
```python
# Arc browser
session_id_arc = "6f5865f1-ff42-4208-83f0-155f0541c90a"
hash_arc = SHA256("Mac OS X:Local:user123:6f5865f1-ff42-4208...")
# → f50cd4d6...

# Firefox browser  
session_id_firefox = "8a7932d2-bb53-5319-94g1-266g0652d01b"
hash_firefox = SHA256("Mac OS X:Local:user123:8a7932d2-bb53-5319...")
# → a71fe3c9...

# Both hashes stored in Directus
# Both connections work independently
```

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