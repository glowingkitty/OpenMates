# Correct Settings & Memories Cache Architecture

## Overview

Unified `:settings_memories` cache with specific sub-keys for different data types within each app. No artificial separation between "settings" and "memories" since the distinction is often unclear.

## Correct Cache Key Structure

### Core Pattern
```
user:{user_id}:chat:{chat_id}:settings_memories:{app_id}:{specific_key}
```

### Real Examples
```
# Travel app
user:alice123:chat:abc456:settings_memories:travel:trips
user:alice123:chat:abc456:settings_memories:travel:destinations
user:alice123:chat:abc456:settings_memories:travel:preferences

# Code app
user:bob789:chat:def123:settings_memories:code:projects
user:bob789:chat:def123:settings_memories:code:repositories
user:bob789:chat:def123:settings_memories:code:languages

# Maps app
user:charlie456:chat:ghi789:settings_memories:maps:recent_searches
user:charlie456:chat:ghi789:settings_memories:maps:favorite_places
user:charlie456:chat:ghi789:settings_memories:maps:location_preferences

# Web app
user:diana789:chat:jkl012:settings_memories:web:browsing_history
user:diana789:chat:jkl012:settings_memories:web:bookmarks
user:diana789:chat:jkl012:settings_memories:web:search_preferences

# Finance app
user:eve123:chat:mno345:settings_memories:finance:budget
user:eve123:chat:mno345:settings_memories:finance:transactions
user:eve123:chat:mno345:settings_memories:finance:goals

# Fitness app
user:frank456:chat:pqr678:settings_memories:fitness:workouts
user:frank456:chat:pqr678:settings_memories:fitness:nutrition
user:frank456:chat:pqr678:settings_memories:fitness:goals
```

## Data Flow with Correct Structure

### 1. AI Preprocessing Request
```json
{
  "type": "settings_memory_request",
  "request_id": "req_abc123",
  "user_hash": "a1b2c3d4",
  "required_data": {
    "travel": ["trips", "preferences"],
    "code": ["projects", "languages"],
    "maps": ["recent_searches", "location_preferences"]
  },
  "cache_policy": "unified_settings_memories_per_app_subkey"
}
```

### 2. Client Response
```json
{
  "type": "settings_memory_response",
  "request_id": "req_abc123",
  "user_hash": "a1b2c3d4",
  "approved_data": {
    "travel": {
      "trips": ["Paris 2023", "Tokyo 2024", "NYC 2022"],
      "preferences": {
        "budget": "$100-500",
        "transport": "flights",
        "accommodation": "hotels"
      }
    },
    "code": {
      "projects": ["OpenMates", "PersonalBlog", "MobileApp"],
      "languages": ["Python", "TypeScript", "Go"]
    },
    "maps": {
      "recent_searches": ["coffee shops", "gas stations"],
      "location_preferences": {"radius": "5km", "units": "metric"}
    }
  }
}
```

### 3. Server-Side Caching (Corrected)
```python
# Cache each app's specific data types with separate keys
for app_id, app_data in approved_data.items():
    for data_key, data_value in app_data.items():
        cache_key = f"user:{user_id}:chat:{chat_id}:settings_memories:{app_id}:{data_key}"
        await cache_service.set(cache_key, {
            "user_id": user_id,
            "chat_id": chat_id,
            "app_id": app_id,
            "data_key": data_key,
            "data": data_value,
            "cached_at": timestamp,
            "expires_at": timestamp + 259200  # 72h
        }, ttl=259200)

# Results in cache keys like:
# user:alice123:chat:abc456:settings_memories:travel:trips
# user:alice123:chat:abc456:settings_memories:travel:preferences
# user:alice123:chat:abc456:settings_memories:code:projects
# user:alice123:chat:abc456:settings_memories:code:languages
# user:alice123:chat:abc456:settings_memories:maps:recent_searches
# user:alice123:chat:abc456:settings_memories:maps:location_preferences
```

## Backend Implementation (Corrected)

### 1. Cache Service Methods

```python
# In backend/core/api/app/services/cache_chat_mixin.py

async def cache_user_settings_memory_item(
    self,
    user_id: str,
    chat_id: str,
    app_id: str,
    data_key: str,  # "trips", "projects", "recent_searches", etc.
    data: Any,
    ttl: int = SETTINGS_MEMORIES_TTL
) -> bool:
    """Cache specific settings/memory item with unified key structure"""
    cache_key = f"user:{user_id}:chat:{chat_id}:settings_memories:{app_id}:{data_key}"

    cache_payload = {
        "user_id": user_id,
        "chat_id": chat_id,
        "app_id": app_id,
        "data_key": data_key,
        "data": data,
        "cached_at": int(time.time()),
        "expires_at": int(time.time()) + ttl
    }

    try:
        await self.set(cache_key, cache_payload, ttl=ttl)
        logger.info(f"Cached {app_id}:{data_key} for user {user_id[:8]}..., chat {chat_id}")
        return True
    except Exception as e:
        logger.error(f"Error caching {app_id}:{data_key}: {e}")
        return False

async def get_user_settings_memory_item(
    self,
    user_id: str,
    chat_id: str,
    app_id: str,
    data_key: str
) -> Optional[Dict[str, Any]]:
    """Retrieve specific settings/memory item"""
    cache_key = f"user:{user_id}:chat:{chat_id}:settings_memories:{app_id}:{data_key}"

    try:
        cached_data = await self.get(cache_key)
        if cached_data:
            logger.debug(f"Cache HIT: {app_id}:{data_key} for user {user_id[:8]}...")
            return cached_data
        return None
    except Exception as e:
        logger.error(f"Error retrieving {app_id}:{data_key}: {e}")
        return None

async def get_user_chat_all_settings_memories(
    self,
    user_id: str,
    chat_id: str
) -> Dict[str, Dict[str, Any]]:
    """Get all cached settings/memories for user+chat, organized by app"""
    pattern = f"user:{user_id}:chat:{chat_id}:settings_memories:*"

    try:
        client = await self.client
        if not client:
            return {}

        keys = await client.keys(pattern)
        result = {}

        for key in keys:
            # Parse key: user:uid:chat:cid:settings_memories:appid:datakey
            parts = key.split(':')
            if len(parts) >= 7:
                app_id = parts[5]
                data_key = parts[6]

                cached_data = await client.get(key)
                if cached_data:
                    if app_id not in result:
                        result[app_id] = {}

                    try:
                        import json
                        data = json.loads(cached_data)
                        result[app_id][data_key] = data["data"]
                    except Exception as e:
                        logger.error(f"Error parsing cached data for {key}: {e}")

        return result
    except Exception as e:
        logger.error(f"Error getting all settings/memories for user {user_id[:8]}..., chat {chat_id}: {e}")
        return {}

async def purge_user_settings_memories(
    self,
    user_id: str,
    chat_id: str,
    app_id: Optional[str] = None,
    data_key: Optional[str] = None
) -> int:
    """Purge settings/memories cache with granular control

    Examples:
    - purge_user_settings_memories(user, chat) -> purge all for user+chat
    - purge_user_settings_memories(user, chat, "travel") -> purge all travel data
    - purge_user_settings_memories(user, chat, "travel", "trips") -> purge only travel trips
    """

    if data_key and app_id:
        pattern = f"user:{user_id}:chat:{chat_id}:settings_memories:{app_id}:{data_key}"
    elif app_id:
        pattern = f"user:{user_id}:chat:{chat_id}:settings_memories:{app_id}:*"
    else:
        pattern = f"user:{user_id}:chat:{chat_id}:settings_memories:*"

    try:
        client = await self.client
        if not client:
            return 0

        keys = await client.keys(pattern)
        if not keys:
            return 0

        await client.delete(*keys)

        logger.info(f"Purged {len(keys)} settings/memories entries for pattern: {pattern}")
        return len(keys)
    except Exception as e:
        logger.error(f"Error purging settings/memories with pattern {pattern}: {e}")
        return 0

async def cache_user_chat_settings_memories_bulk(
    self,
    user_id: str,
    chat_id: str,
    approved_data: Dict[str, Dict[str, Any]]
) -> Dict[str, int]:
    """Cache all approved settings/memories data with unified structure

    Returns count of cached items per app
    """
    cached_counts = {}

    for app_id, app_data in approved_data.items():
        cached_counts[app_id] = 0

        for data_key, data_value in app_data.items():
            if data_value is not None:  # User approved this data
                success = await self.cache_user_settings_memory_item(
                    user_id, chat_id, app_id, data_key, data_value
                )
                if success:
                    cached_counts[app_id] += 1

    return cached_counts
```

### 2. LRU Cleanup (Corrected)

```python
# In cache_legacy_mixin.py

async def cleanup_user_evicted_chat_settings_memories(
    self,
    user_id: str,
    evicted_chat_ids: List[str]
) -> Dict[str, int]:
    """Clean up all settings/memories entries for evicted chats"""
    total_cleaned = {}

    for chat_id in evicted_chat_ids:
        # Purge all settings/memories for this user+chat
        cleaned_count = await self.purge_user_settings_memories(user_id, chat_id)
        total_cleaned[chat_id] = cleaned_count

        if cleaned_count > 0:
            logger.info(f"Auto-purged {cleaned_count} settings/memories entries for user {user_id[:8]}..., evicted chat {chat_id}")

    return total_cleaned
```

## API Endpoints (Corrected)

```python
# In settings_memories_routes.py

@router.post("/{chat_id}/cache-settings-memories")
async def cache_settings_memories(
    chat_id: str,
    payload: Dict[str, Any],
    current_user: dict = Depends(get_current_user)
):
    """Cache user-approved settings and memories with unified structure"""
    user_id = current_user["id"]

    if "approved_data" not in payload:
        raise HTTPException(400, "Missing approved_data")

    cached_counts = await cache_service.cache_user_chat_settings_memories_bulk(
        user_id=user_id,
        chat_id=chat_id,
        approved_data=payload["approved_data"]
    )

    total_items = sum(cached_counts.values())

    return {
        "success": True,
        "user_hash": hash_user_id(user_id),
        "cached_items_per_app": cached_counts,
        "total_cached_items": total_items,
        "cache_structure": "unified_settings_memories_with_subkeys",
        "ttl": "72h_plus_lru_eviction"
    }

@router.get("/{chat_id}/my-settings-memories")
async def get_my_settings_memories(
    chat_id: str,
    app_id: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """Get cached settings/memories data"""
    user_id = current_user["id"]

    if app_id:
        # Get specific app's data
        pattern = f"user:{user_id}:chat:{chat_id}:settings_memories:{app_id}:*"
        # Implementation for specific app filtering
    else:
        # Get all cached data
        all_data = await cache_service.get_user_chat_all_settings_memories(user_id, chat_id)

        return {
            "user_hash": hash_user_id(user_id),
            "chat_id": chat_id,
            "cached_data": all_data,
            "apps_with_data": list(all_data.keys())
        }

@router.delete("/{chat_id}/purge-settings-memories")
async def purge_settings_memories(
    chat_id: str,
    app_id: Optional[str] = None,
    data_key: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """Purge settings/memories cache with granular control"""
    user_id = current_user["id"]

    purged_count = await cache_service.purge_user_settings_memories(
        user_id=user_id,
        chat_id=chat_id,
        app_id=app_id,
        data_key=data_key
    )

    return {
        "success": True,
        "purged_items": purged_count,
        "scope": f"app:{app_id or 'all'}, key:{data_key or 'all'}"
    }
```

## Frontend Implementation (Corrected)

```typescript
// Simplified approval structure - no artificial settings/memories split

interface SettingsMemoryRequest {
    type: 'settings_memory_request';
    request_id: string;
    user_hash: string;
    required_data: {
        [app_id: string]: string[];  // List of data keys needed for each app
    };
}

// Example request
{
  "type": "settings_memory_request",
  "user_hash": "a1b2c3d4",
  "required_data": {
    "travel": ["trips", "preferences", "destinations"],
    "code": ["projects", "languages", "repositories"],
    "maps": ["recent_searches", "location_preferences"]
  }
}

// Example approval UI - unified structure
{
  travel: {
    trips: [✓],
    preferences: [✓],
    destinations: [ ]
  },
  code: {
    projects: [✓],
    languages: [✓],
    repositories: [ ]
  },
  maps: {
    recent_searches: [✓],
    location_preferences: [✓]
  }
}
```

## Chat History Format (Corrected)

```json
{
  "role": "assistant",
  "content": "```json\n{\"type\":\"settings_memory_request\",\"user_hash\":\"a1b2c3d4\",\"requested_items\":{\"travel\":[\"trips\",\"preferences\"],\"code\":[\"projects\",\"languages\"]},\"user_approved\":{\"travel\":[\"trips\",\"preferences\"],\"code\":[\"projects\"]},\"cache_structure\":\"unified_settings_memories\",\"ttl\":\"72h_plus_lru_eviction\"}\n```\n\nI can help plan your trip using your travel history and preferences, plus suggest coding approaches based on your projects.",
  "message_id": "msg_xyz789"
}
```

## Key Benefits of Corrected Architecture

✅ **Unified Structure**: No artificial separation - `:settings_memories` contains everything
✅ **Specific Sub-Keys**: `travel:trips`, `code:projects`, `maps:recent_searches` etc.
✅ **Granular Control**: Users approve specific data types like "trips" but decline "destinations"
✅ **Selective Eviction**: Can purge `travel:trips` while keeping `travel:preferences`
✅ **Simple Logic**: No need to categorize data as "setting" vs "memory"
✅ **Scalable**: Easy to add new data types like `finance:budget`, `fitness:workouts`

This is much cleaner and matches your original vision - unified storage with specific sub-keys for granular control!