# Settings & Memories Cache Architecture (Revised)

## Overview

This document describes the **user-scoped** architecture for caching user settings and memories, leveraging the existing "last 3 active chats" cache infrastructure with automatic per-user purging and 72-hour safety expiration.

## Current Infrastructure

### Backend Cache System
- **Location**: `backend/core/api/app/services/cache_legacy_mixin.py:12-22`
- **Key Pattern**: `USER_ACTIVE_CHATS_LRU_PREFIX{user_id}`
- **Behavior**: Maintains last 3 active chats per user with automatic LRU eviction
- **TTL**: `CHAT_METADATA_TTL` (24 hours based on `cache_config.py`)
- **Redis Operations**: `LREM` → `LPUSH` → `LTRIM(0,2)` → `EXPIRE`

### Chat Message Caching
- **Location**: `backend/core/api/app/services/cache_chat_mixin.py`
- **Purpose**: "cache last 3 chats for follow-up context" (`cache_config.py:CHAT_MESSAGES_TTL`)
- **Current**: Stores encrypted chat messages with 24h TTL (user-independent)

## New Architecture: User-Scoped Settings & Memories Cache

### Core Principle
**User-scoped cache with chat-based eviction**: Settings and memories are cached per-user but tied to specific chats, with automatic purging when the associated chat drops out of the user's "last 3 active" list, plus additional 72-hour safety expiration.

### Cache Keys Structure
```
# Existing (unchanged)
user:{user_id}:active_chats_lru                         # List of last 3 chat_ids per user
chat:{chat_id}:messages                                 # Encrypted chat messages (24h TTL, user-independent)

# New additions (user-scoped)
user:{user_id}:chat:{chat_id}:settings_memories         # User's settings/memories for specific chat
user:{user_id}:sm_metadata:{chat_id}                   # Metadata about what's cached for this user+chat
```

### TTL Strategy
- **Primary TTL**: 72 hours (safety expiration to prevent indefinite retention)
- **LRU Eviction**: When chat drops from user's "last 3 active" list
- **Manual Purge**: User can clear their own cache anytime
- **Sharing Safe**: Other users cannot access cache (user_id scoped)

### Data Flow

#### 1. AI Preprocessing Request
```json
{
  "type": "settings_memory_request",
  "request_id": "req_abc123",
  "user_hash": "a1b2c3d4...",
  "required_data": {
    "apps": ["maps", "web"],
    "settings": ["location_preferences", "search_settings"],
    "memories": ["recent_searches", "browsing_history"]
  },
  "cache_policy": "user_scoped_lru_eviction"
}
```

#### 2. Client Response
```json
{
  "type": "settings_memory_response",
  "request_id": "req_abc123",
  "user_hash": "a1b2c3d4...",
  "approved_data": {
    "maps": {
      "settings": {"location": "enabled", "radius": "5km"},
      "memories": ["Starbucks on Main St", "Central Park"]
    },
    "web": {
      "settings": {"safe_search": true},
      "memories": null  // User declined
    }
  }
}
```

#### 3. Server-Side Caching
```python
# Cache with user-scoped key for privacy isolation
cache_key = f"user:{user_id}:chat:{chat_id}:settings_memories"
await cache_service.set(cache_key, {
    "user_id": user_id,
    "chat_id": chat_id,
    "cached_at": timestamp,
    "data": approved_data,
    "metadata": {
        "apps_included": ["maps", "web"],
        "user_consent": True,
        "privacy_level": "user_scoped"
    }
}, ttl=259200)  # 72 hours (3 days) safety TTL
```

### Storage Format

#### Chat History (IndexedDB + Directus)
Only the **metadata** is stored permanently with user identification:
```json
{
  "role": "assistant",
  "content": "```json\n{\"type\":\"settings_memory_request\",\"user_hash\":\"a1b2c3d4\",\"apps_requested\":[\"maps\",\"web\"],\"user_approved\":[\"maps\"],\"cache_status\":\"user_scoped_cache\",\"ttl\":\"72h_plus_lru_eviction\"}\n```\n\nI can help you find nearby coffee shops using your location preferences.",
  "message_id": "msg_xyz789"
}
```

#### Server Cache (Redis)
The **actual data** is cached temporarily with user isolation:
```json
{
  "cache_key": "user:user123:chat:abc123:settings_memories",
  "data": {
    "maps": {
      "location_preferences": {"enabled": true, "radius_km": 5},
      "recent_searches": ["coffee", "restaurants"]
    }
  },
  "metadata": {
    "user_id": "user123",
    "chat_id": "abc123",
    "cached_at": 1703875200,
    "user_consent": ["maps"],
    "ttl_strategy": "72h_safety_plus_lru_eviction",
    "expires_at": 1704134400
  }
}
```

### LLM Inference Data Injection

During AI inference, the cached data is dynamically injected per user:

```python
async def prepare_inference_context(chat_id: str, user_id: str, chat_history: List[Dict]) -> List[Dict]:
    # Check if we have cached settings/memories for this user+chat combination
    cache_key = f"user:{user_id}:chat:{chat_id}:settings_memories"
    cached_data = await cache_service.get(cache_key)

    if cached_data:
        # Replace JSON metadata with actual data for inference
        for message in chat_history:
            if "settings_memory_request" in message.get("content", ""):
                # Extract user_hash from JSON and match against current user
                json_data = extract_json_from_content(message["content"])
                if json_data and json_data.get("user_hash") == hash_user_id(user_id):
                    # Replace with natural language version for this user's data
                    message["content"] = format_settings_for_inference(cached_data)

    return chat_history

def format_settings_for_inference(cached_data: dict) -> str:
    """Convert cached settings to natural language for LLM"""
    return f"""The user has shared their preferences:

Maps: Location services enabled with 5km radius. Recent searches include coffee shops and restaurants.
Web: Safe search enabled. Browsing history not shared."""
```

## Privacy & Sharing Safeguards

### User Isolation
- **Cache Key Scoping**: `user:{user_id}:chat:{chat_id}:*` ensures users only access their own cached data
- **No Cross-User Access**: Shared chat recipients cannot access original user's cached settings/memories
- **Multi-User Support**: Each user in a shared chat can cache their own settings/memories independently

### Automatic Purging
- **Primary Trigger**: When chat drops out of user's "last 3 active" LRU list
- **Safety Trigger**: 72-hour TTL expiration
- **Mechanism**: Enhanced `update_user_active_chats_lru()` triggers user-scoped cache cleanup
- **Implementation**: Cleanup hook checks user-scoped cache keys for evicted chats

### Enhanced Privacy Model
```python
async def cleanup_user_chat_cache(user_id: str, evicted_chat_id: str):
    """Clean up user's cache when chat is evicted from their LRU list"""
    cache_keys = [
        f"user:{user_id}:chat:{evicted_chat_id}:settings_memories",
        f"user:{user_id}:sm_metadata:{evicted_chat_id}"
    ]
    for key in cache_keys:
        await cache_service.delete(key)

    logger.info(f"Purged user {user_id[:8]}... cache for evicted chat {evicted_chat_id}")

# No special sharing logic needed - users are naturally isolated
```

### User Transparency
- Chat history shows **what types** of data were requested/approved **per user** (via user_hash)
- Server cache stores **actual data** per user with clear metadata about consent
- Users can manually clear their own cache via `/clear-my-cache/{chat_id}` endpoint
- **Multi-User Visibility**: In shared chats, each user sees their own settings requests in the history

## Shared Chat Scenarios

### Scenario 1: Original User vs. Recipient
```
Chat ABC123 is shared from User A to User B

User A's cache: user:A:chat:ABC123:settings_memories  (contains A's personal data)
User B's cache: user:B:chat:ABC123:settings_memories  (contains B's personal data)

Result: Each user only sees their own data, complete privacy isolation
```

### Scenario 2: Multiple Recipients Build Context
```
User B (recipient) interacts with shared chat:
1. AI requests User B's settings/memories
2. User B approves their own data
3. Cached as: user:B:chat:ABC123:settings_memories
4. User B gets personalized responses based on their data
5. User A's original cache remains untouched and inaccessible to User B
```

## Implementation Benefits

✅ **Leverages Existing Infrastructure**: Extends current LRU eviction with user-scoped keys
✅ **User Isolation**: Each user's cache is completely separate and private
✅ **Privacy by Design**: Auto-purging prevents data accumulation per user
✅ **Sharing Safe**: Users only access their own cached data, never others'
✅ **Multi-User Support**: Shared chats allow each user to build their own context
✅ **Performance**: Recent active chats have immediate context access per user
✅ **User Control**: Transparent per-user cache management
✅ **Compliance Ready**: User-scoped minimal retention aligns with privacy regulations
✅ **72h Safety Net**: Additional TTL prevents indefinite retention

## Code Changes Required

See `CODE_CHANGES_NEEDED_REVISED.md` for detailed implementation steps with user-scoped architecture.