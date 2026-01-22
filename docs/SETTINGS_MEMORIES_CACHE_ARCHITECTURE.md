# Settings & Memories Cache Architecture

## Overview

This document describes the architecture for caching user settings and memories alongside chat data, leveraging the existing "last 3 active chats" cache infrastructure with automatic purging.

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
- **Current**: Stores encrypted chat messages with 24h TTL

## New Architecture: Settings & Memories Cache

### Core Principle
**Leverage existing LRU mechanism**: Settings and memories are cached alongside chat data and automatically purged when a chat drops out of the "last 3 active" list.

### Cache Keys Structure
```
# Existing (unchanged)
user:{user_id}:active_chats_lru     # List of last 3 chat_ids
chat:{chat_id}:messages             # Encrypted chat messages (24h TTL)

# New additions
chat:{chat_id}:settings_memories    # User settings/memories for this chat
chat:{chat_id}:sm_metadata          # Metadata about what's cached
```

### Data Flow

#### 1. AI Preprocessing Request
```json
{
  "type": "settings_memory_request",
  "request_id": "req_abc123",
  "required_data": {
    "apps": ["maps", "web"],
    "settings": ["location_preferences", "search_settings"],
    "memories": ["recent_searches", "browsing_history"]
  },
  "cache_policy": "recent_chat_auto_purge"
}
```

#### 2. Client Response
```json
{
  "type": "settings_memory_response",
  "request_id": "req_abc123",
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
# Cache the approved settings/memories with chat_id as key
cache_key = f"chat:{chat_id}:settings_memories"
await cache_service.set(cache_key, {
    "user_id": user_id,
    "cached_at": timestamp,
    "data": approved_data,
    "metadata": {
        "apps_included": ["maps", "web"],
        "user_consent": True,
        "privacy_level": "chat_scoped"
    }
}, ttl=CHAT_MESSAGES_TTL)  # Same 24h TTL as chat messages
```

### Storage Format

#### Chat History (IndexedDB + Directus)
Only the **metadata** is stored permanently:
```json
{
  "role": "assistant",
  "content": "```json\n{\"type\":\"settings_memory_request\",\"apps_requested\":[\"maps\",\"web\"],\"user_approved\":[\"maps\"],\"cache_status\":\"cached_until_lru_eviction\"}\n```\n\nI can help you find nearby coffee shops using your location preferences.",
  "message_id": "msg_xyz789"
}
```

#### Server Cache (Redis)
The **actual data** is cached temporarily:
```json
{
  "cache_key": "chat:abc123:settings_memories",
  "data": {
    "maps": {
      "location_preferences": {"enabled": true, "radius_km": 5},
      "recent_searches": ["coffee", "restaurants"]
    }
  },
  "metadata": {
    "cached_at": 1703875200,
    "user_consent": ["maps"],
    "auto_purge_with_chat": true
  }
}
```

### LLM Inference Data Injection

During AI inference, the cached data is dynamically injected:

```python
async def prepare_inference_context(chat_id: str, chat_history: List[Dict]) -> List[Dict]:
    # Check if we have cached settings/memories for this chat
    cache_key = f"chat:{chat_id}:settings_memories"
    cached_data = await cache_service.get(cache_key)

    if cached_data:
        # Replace JSON metadata with actual data for inference
        for message in chat_history:
            if "settings_memory_request" in message.get("content", ""):
                # Replace with natural language version
                message["content"] = format_settings_for_inference(cached_data)

    return chat_history

def format_settings_for_inference(cached_data: dict) -> str:
    """Convert cached settings to natural language for LLM"""
    return f"""The user has shared their preferences:

Maps: Location services enabled with 5km radius. Recent searches include coffee shops and restaurants.
Web: Safe search enabled. Browsing history not shared."""
```

## Privacy & Sharing Safeguards

### Automatic Purging
- **Trigger**: When chat drops out of "last 3 active" LRU list
- **Mechanism**: Existing `update_user_active_chats_lru()` triggers cache cleanup
- **Implementation**: Add cleanup hook to existing LRU update function

### Sharing Protection
```python
async def on_chat_shared(chat_id: str):
    """Called when chat becomes shared - immediately purge personal data"""
    cache_keys = [
        f"chat:{chat_id}:settings_memories",
        f"chat:{chat_id}:sm_metadata"
    ]
    for key in cache_keys:
        await cache_service.delete(key)

    logger.info(f"Purged personal cache for shared chat {chat_id}")
```

### User Transparency
- Chat history shows **what types** of data were requested/approved
- Server cache stores **actual data** but with clear metadata about consent
- Users can manually clear cache via `/clear-chat-cache/{chat_id}` endpoint

## Implementation Benefits

✅ **Leverages Existing Infrastructure**: No new cache eviction logic needed
✅ **Privacy by Design**: Auto-purging prevents data accumulation
✅ **Sharing Safe**: Personal data never included in shared contexts
✅ **Performance**: Recent active chats have immediate context access
✅ **User Control**: Transparent about what's cached and when it expires
✅ **Compliance Ready**: Minimal retention aligns with privacy regulations

## Code Changes Required

See `CODE_CHANGES_NEEDED.md` for detailed implementation steps.