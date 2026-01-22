# Granular Settings & Memories Cache Architecture

## Overview

This document describes the **granular, app-specific** cache architecture for user settings and memories, where each app's different settings and memories types are cached with separate sub-keys for fine-grained management and eviction.

## Granular Cache Key Structure

### Core Pattern
```
user:{user_id}:chat:{chat_id}:app:{app_id}:{data_type}:{item_key}
```

### Examples
```
# Travel app
user:alice123:chat:abc456:app:travel:settings:preferences
user:alice123:chat:abc456:app:travel:memories:trips
user:alice123:chat:abc456:app:travel:memories:destinations

# Code app
user:bob789:chat:def123:app:code:settings:languages
user:bob789:chat:def123:app:code:memories:projects
user:bob789:chat:def123:app:code:memories:repositories

# Maps app
user:charlie456:chat:ghi789:app:maps:settings:location_preferences
user:charlie456:chat:ghi789:app:maps:memories:recent_searches
user:charlie456:chat:ghi789:app:maps:memories:favorite_places

# Web app
user:diana789:chat:jkl012:app:web:settings:search_preferences
user:diana789:chat:jkl012:app:web:settings:privacy_settings
user:diana789:chat:jkl012:app:web:memories:browsing_history
user:diana789:chat:jkl012:app:web:memories:bookmarks
```

## Data Flow with Granular Structure

### 1. AI Preprocessing Request (Enhanced)
```json
{
  "type": "settings_memory_request",
  "request_id": "req_abc123",
  "user_hash": "a1b2c3d4",
  "required_data": {
    "travel": {
      "settings": ["preferences"],
      "memories": ["trips", "destinations"]
    },
    "code": {
      "settings": ["languages", "frameworks"],
      "memories": ["projects"]
    },
    "maps": {
      "settings": ["location_preferences"],
      "memories": ["recent_searches"]
    }
  },
  "cache_policy": "granular_user_scoped_lru_eviction"
}
```

### 2. Client Response (Granular Approval)
```json
{
  "type": "settings_memory_response",
  "request_id": "req_abc123",
  "user_hash": "a1b2c3d4",
  "approved_data": {
    "travel": {
      "settings": {
        "preferences": {
          "budget_range": "$100-500",
          "transport_mode": "flights",
          "accommodation_type": "hotels"
        }
      },
      "memories": {
        "trips": ["Paris 2023", "Tokyo 2024"],
        "destinations": null  // User declined
      }
    },
    "code": {
      "settings": {
        "languages": ["Python", "TypeScript"],
        "frameworks": ["FastAPI", "React"]
      },
      "memories": {
        "projects": ["OpenMates", "PersonalBlog"]
      }
    },
    "maps": {
      "settings": {
        "location_preferences": {"radius": "5km", "units": "metric"}
      },
      "memories": {
        "recent_searches": ["coffee shops", "gas stations"]
      }
    }
  }
}
```

### 3. Server-Side Granular Caching
```python
# Cache each app's data with separate keys
for app_id, app_data in approved_data.items():
    # Cache settings
    if "settings" in app_data:
        for setting_key, setting_value in app_data["settings"].items():
            cache_key = f"user:{user_id}:chat:{chat_id}:app:{app_id}:settings:{setting_key}"
            await cache_service.set(cache_key, {
                "user_id": user_id,
                "chat_id": chat_id,
                "app_id": app_id,
                "data_type": "settings",
                "item_key": setting_key,
                "data": setting_value,
                "cached_at": timestamp,
                "expires_at": timestamp + 259200  # 72h
            }, ttl=259200)

    # Cache memories
    if "memories" in app_data:
        for memory_key, memory_value in app_data["memories"].items():
            if memory_value is not None:  # User approved this memory type
                cache_key = f"user:{user_id}:chat:{chat_id}:app:{app_id}:memories:{memory_key}"
                await cache_service.set(cache_key, {
                    "user_id": user_id,
                    "chat_id": chat_id,
                    "app_id": app_id,
                    "data_type": "memories",
                    "item_key": memory_key,
                    "data": memory_value,
                    "cached_at": timestamp,
                    "expires_at": timestamp + 259200  # 72h
                }, ttl=259200)
```

## Chat History Storage (Enhanced)

### Granular Metadata in JSON Blocks
```json
{
  "role": "assistant",
  "content": "```json\n{\"type\":\"settings_memory_request\",\"user_hash\":\"a1b2c3d4\",\"requested_items\":{\"travel\":{\"settings\":[\"preferences\"],\"memories\":[\"trips\",\"destinations\"]},\"code\":{\"settings\":[\"languages\"],\"memories\":[\"projects\"]}},\"user_approved\":{\"travel\":{\"settings\":[\"preferences\"],\"memories\":[\"trips\"]},\"code\":{\"settings\":[\"languages\"],\"memories\":[\"projects\"]}},\"cache_status\":\"granular_user_scoped\",\"ttl\":\"72h_plus_lru_eviction\"}\n```\n\nI can help you plan your trip using your travel preferences and past trip experience, plus suggest coding approaches based on your preferred languages.",
  "message_id": "msg_xyz789"
}
```

## Backend Implementation (Granular)

### 1. Enhanced Cache Service Methods

```python
# In backend/core/api/app/services/cache_chat_mixin.py

async def cache_user_app_data(
    self,
    user_id: str,
    chat_id: str,
    app_id: str,
    data_type: str,  # "settings" or "memories"
    item_key: str,   # "trips", "preferences", etc.
    data: Any,
    ttl: int = SETTINGS_MEMORIES_TTL
) -> bool:
    """Cache specific app data item with granular key"""
    cache_key = f"user:{user_id}:chat:{chat_id}:app:{app_id}:{data_type}:{item_key}"

    cache_payload = {
        "user_id": user_id,
        "chat_id": chat_id,
        "app_id": app_id,
        "data_type": data_type,
        "item_key": item_key,
        "data": data,
        "cached_at": int(time.time()),
        "expires_at": int(time.time()) + ttl
    }

    try:
        await self.set(cache_key, cache_payload, ttl=ttl)
        logger.info(f"Cached {app_id}:{data_type}:{item_key} for user {user_id[:8]}..., chat {chat_id}")
        return True
    except Exception as e:
        logger.error(f"Error caching {app_id}:{data_type}:{item_key}: {e}")
        return False

async def get_user_app_data(
    self,
    user_id: str,
    chat_id: str,
    app_id: str,
    data_type: str,
    item_key: str
) -> Optional[Dict[str, Any]]:
    """Retrieve specific app data item"""
    cache_key = f"user:{user_id}:chat:{chat_id}:app:{app_id}:{data_type}:{item_key}"

    try:
        cached_data = await self.get(cache_key)
        if cached_data:
            logger.debug(f"Cache HIT: {app_id}:{data_type}:{item_key} for user {user_id[:8]}...")
            return cached_data
        return None
    except Exception as e:
        logger.error(f"Error retrieving {app_id}:{data_type}:{item_key}: {e}")
        return None

async def get_user_chat_all_cached_data(
    self,
    user_id: str,
    chat_id: str
) -> Dict[str, Dict[str, Dict[str, Any]]]:
    """Get all cached data for user+chat, organized by app"""
    pattern = f"user:{user_id}:chat:{chat_id}:app:*"

    try:
        client = await self.client
        if not client:
            return {}

        keys = await client.keys(pattern)
        result = {}

        for key in keys:
            # Parse key: user:uid:chat:cid:app:appid:datatype:itemkey
            parts = key.split(':')
            if len(parts) >= 8:
                app_id = parts[5]
                data_type = parts[6]
                item_key = parts[7]

                cached_data = await client.get(key)
                if cached_data:
                    if app_id not in result:
                        result[app_id] = {"settings": {}, "memories": {}}

                    try:
                        import json
                        data = json.loads(cached_data)
                        result[app_id][data_type][item_key] = data["data"]
                    except Exception as e:
                        logger.error(f"Error parsing cached data for {key}: {e}")

        return result
    except Exception as e:
        logger.error(f"Error getting all cached data for user {user_id[:8]}..., chat {chat_id}: {e}")
        return {}

async def purge_user_chat_app_data(
    self,
    user_id: str,
    chat_id: str,
    app_id: Optional[str] = None,
    data_type: Optional[str] = None,
    item_key: Optional[str] = None
) -> int:
    """Purge cached data with granular control

    Examples:
    - purge_user_chat_app_data(user, chat) -> purge all for user+chat
    - purge_user_chat_app_data(user, chat, "travel") -> purge all travel data
    - purge_user_chat_app_data(user, chat, "travel", "memories") -> purge travel memories
    - purge_user_chat_app_data(user, chat, "travel", "memories", "trips") -> purge travel trips
    """

    # Build pattern based on specificity
    if item_key:
        pattern = f"user:{user_id}:chat:{chat_id}:app:{app_id}:{data_type}:{item_key}"
    elif data_type:
        pattern = f"user:{user_id}:chat:{chat_id}:app:{app_id}:{data_type}:*"
    elif app_id:
        pattern = f"user:{user_id}:chat:{chat_id}:app:{app_id}:*"
    else:
        pattern = f"user:{user_id}:chat:{chat_id}:app:*"

    try:
        client = await self.client
        if not client:
            return 0

        keys = await client.keys(pattern)
        if not keys:
            return 0

        # Delete all matching keys
        await client.delete(*keys)

        logger.info(f"Purged {len(keys)} cache entries for pattern: {pattern}")
        return len(keys)
    except Exception as e:
        logger.error(f"Error purging cache with pattern {pattern}: {e}")
        return 0

async def cache_user_chat_granular_data(
    self,
    user_id: str,
    chat_id: str,
    approved_data: Dict[str, Dict[str, Dict[str, Any]]]
) -> Dict[str, int]:
    """Cache all approved data with granular keys

    Returns count of cached items per app
    """
    cached_counts = {}

    for app_id, app_data in approved_data.items():
        cached_counts[app_id] = 0

        # Cache settings
        if "settings" in app_data:
            for setting_key, setting_value in app_data["settings"].items():
                success = await self.cache_user_app_data(
                    user_id, chat_id, app_id, "settings", setting_key, setting_value
                )
                if success:
                    cached_counts[app_id] += 1

        # Cache memories
        if "memories" in app_data:
            for memory_key, memory_value in app_data["memories"].items():
                if memory_value is not None:  # User approved this memory type
                    success = await self.cache_user_app_data(
                        user_id, chat_id, app_id, "memories", memory_key, memory_value
                    )
                    if success:
                        cached_counts[app_id] += 1

    return cached_counts
```

### 2. Enhanced LRU Cleanup (Granular)

```python
# In cache_legacy_mixin.py

async def cleanup_user_evicted_chat_granular_cache(
    self,
    user_id: str,
    evicted_chat_ids: List[str]
) -> Dict[str, int]:
    """Clean up all granular cache entries for evicted chats"""
    total_cleaned = {}

    for chat_id in evicted_chat_ids:
        # Purge all app data for this user+chat
        cleaned_count = await self.purge_user_chat_app_data(user_id, chat_id)
        total_cleaned[chat_id] = cleaned_count

        if cleaned_count > 0:
            logger.info(f"Auto-purged {cleaned_count} granular cache entries for user {user_id[:8]}..., evicted chat {chat_id}")

    return total_cleaned
```

## API Endpoints (Granular)

### 1. Granular Cache Management

```python
# Enhanced settings_memories_routes.py

@router.post("/{chat_id}/cache-granular")
async def cache_granular_data(
    chat_id: str,
    payload: Dict[str, Any],
    current_user: dict = Depends(get_current_user)
):
    """Cache user-approved granular settings and memories"""
    user_id = current_user["id"]

    if "approved_data" not in payload:
        raise HTTPException(400, "Missing approved_data")

    cached_counts = await cache_service.cache_user_chat_granular_data(
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
        "ttl": "72h_plus_lru_eviction"
    }

@router.get("/{chat_id}/my-cached-data")
async def get_my_cached_data(
    chat_id: str,
    app_id: Optional[str] = None,
    data_type: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """Get cached data with optional filtering"""
    user_id = current_user["id"]

    if app_id and data_type:
        # Get specific app's data type
        pattern = f"user:{user_id}:chat:{chat_id}:app:{app_id}:{data_type}:*"
        # Implementation to get specific data
    else:
        # Get all cached data for this user+chat
        all_data = await cache_service.get_user_chat_all_cached_data(user_id, chat_id)

        return {
            "user_hash": hash_user_id(user_id),
            "chat_id": chat_id,
            "cached_data": all_data,
            "apps_with_data": list(all_data.keys())
        }

@router.delete("/{chat_id}/purge-cache")
async def purge_granular_cache(
    chat_id: str,
    app_id: Optional[str] = None,
    data_type: Optional[str] = None,
    item_key: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """Purge cache with granular control"""
    user_id = current_user["id"]

    purged_count = await cache_service.purge_user_chat_app_data(
        user_id=user_id,
        chat_id=chat_id,
        app_id=app_id,
        data_type=data_type,
        item_key=item_key
    )

    return {
        "success": True,
        "purged_items": purged_count,
        "scope": f"app:{app_id or 'all'}, type:{data_type or 'all'}, key:{item_key or 'all'}"
    }
```

## Frontend Implementation (Granular)

### Enhanced Approval UI

```typescript
// Enhanced settings approval component

interface GranularApprovalData {
    [app_id: string]: {
        settings: {[key: string]: boolean};  // User's approval for each setting
        memories: {[key: string]: boolean};  // User's approval for each memory type
    };
}

class GranularSettingsMemoriesHandler {
    async showGranularApprovalUI(
        request: SettingsMemoryRequest
    ): Promise<{approved: boolean; data: Record<string, any>}> {

        return new Promise((resolve) => {
            const dialog = createGranularApprovalDialog({
                title: '🔒 Granular Settings & Memory Approval',
                subtitle: 'Choose exactly what to share (cached privately per app/type)',
                apps: request.required_data,
                onSubmit: (approvals: GranularApprovalData) => {
                    // Convert approvals to actual data
                    const approvedData = this.buildApprovedData(approvals);
                    resolve({ approved: true, data: approvedData });
                },
                onCancel: () => resolve({ approved: false, data: {} })
            });
        });
    }

    private buildApprovedData(approvals: GranularApprovalData): Record<string, any> {
        const result = {};

        for (const [appId, appApprovals] of Object.entries(approvals)) {
            result[appId] = {
                settings: {},
                memories: {}
            };

            // Get actual settings data for approved items
            for (const [settingKey, approved] of Object.entries(appApprovals.settings)) {
                if (approved) {
                    result[appId].settings[settingKey] = this.getUserSettingData(appId, settingKey);
                }
            }

            // Get actual memory data for approved items
            for (const [memoryKey, approved] of Object.entries(appApprovals.memories)) {
                if (approved) {
                    result[appId].memories[memoryKey] = this.getUserMemoryData(appId, memoryKey);
                }
            }
        }

        return result;
    }
}
```

## AI/LLM Integration (Granular Context)

### Granular Context Preparation

```python
async def prepare_granular_chat_context(
    chat_id: str,
    user_id: str,
    chat_history: List[Dict]
) -> List[Dict]:
    """Inject granular cached data into chat context"""

    # Get all cached data for this user+chat
    all_cached_data = await cache_service.get_user_chat_all_cached_data(user_id, chat_id)

    if not all_cached_data:
        return chat_history

    user_hash = hash_user_id(user_id)
    enhanced_history = []

    for message in chat_history:
        content = message.get("content", "")

        if "settings_memory_request" in content:
            try:
                json_data = extract_json_from_content(content)
                if json_data and json_data.get("user_hash") == user_hash:
                    # Build granular context from cached data
                    granular_context = format_granular_cached_data_for_llm(all_cached_data)

                    # Replace JSON with natural language
                    message["content"] = content.replace(
                        extract_json_block(content),
                        f"\n\nUser's relevant app data:\n{granular_context}"
                    )
            except Exception as e:
                logger.error(f"Error processing granular cache: {e}")

        enhanced_history.append(message)

    return enhanced_history

def format_granular_cached_data_for_llm(cached_data: Dict[str, Dict[str, Dict[str, Any]]]) -> str:
    """Convert granular cached data to natural language"""
    context_parts = []

    for app_id, app_data in cached_data.items():
        app_context = f"**{app_id.title()} App:**"

        # Format settings
        if app_data.get("settings"):
            settings_list = []
            for setting_key, setting_value in app_data["settings"].items():
                settings_list.append(f"{setting_key}: {setting_value}")
            if settings_list:
                app_context += f"\n- Settings: {', '.join(settings_list)}"

        # Format memories
        if app_data.get("memories"):
            for memory_key, memory_value in app_data["memories"].items():
                if isinstance(memory_value, list):
                    memory_text = ", ".join(str(item) for item in memory_value[:3])
                    app_context += f"\n- {memory_key.title()}: {memory_text}"
                else:
                    app_context += f"\n- {memory_key.title()}: {memory_value}"

        context_parts.append(app_context)

    return "\n\n".join(context_parts)
```

## Benefits of Granular Architecture

✅ **Fine-Grained Control**: Users can approve travel:trips but decline travel:destinations
✅ **Selective Eviction**: Can purge just code:projects while keeping travel:preferences
✅ **App Isolation**: Each app's data is completely separate in cache
✅ **Scalable**: Easy to add new apps/settings/memory types
✅ **Transparent**: Users see exactly what's cached per app/type
✅ **Performance**: Only load relevant data for each AI request
✅ **Privacy**: Granular user control over what data is shared vs cached

This granular approach provides maximum flexibility while maintaining the same privacy and performance benefits!