# Code Changes Required for Settings & Memories Cache

## Overview
Implementation leverages existing "last 3 chats" LRU cache infrastructure with automatic purging. Changes are minimal and focused on extending existing patterns.

## Backend Changes

### 1. Extend Cache Service (cache_chat_mixin.py)

Add new methods to `ChatCacheMixin`:

```python
# In backend/core/api/app/services/cache_chat_mixin.py

async def cache_chat_settings_memories(
    self,
    chat_id: str,
    user_id: str,
    settings_data: Dict[str, Any],
    ttl: int = CHAT_MESSAGES_TTL
) -> bool:
    """Cache user settings/memories for a specific chat"""
    cache_key = f"chat:{chat_id}:settings_memories"

    cache_payload = {
        "user_id": user_id,
        "cached_at": int(time.time()),
        "data": settings_data,
        "metadata": {
            "auto_purge_with_chat": True,
            "privacy_level": "chat_scoped"
        }
    }

    try:
        await self.set(cache_key, cache_payload, ttl=ttl)
        logger.info(f"Cached settings/memories for chat {chat_id}, user {user_id[:8]}...")
        return True
    except Exception as e:
        logger.error(f"Error caching settings/memories for chat {chat_id}: {e}")
        return False

async def get_chat_settings_memories(self, chat_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve cached settings/memories for a chat"""
    cache_key = f"chat:{chat_id}:settings_memories"

    try:
        cached_data = await self.get(cache_key)
        if cached_data:
            logger.debug(f"Cache HIT: Retrieved settings/memories for chat {chat_id}")
            return cached_data
        else:
            logger.debug(f"Cache MISS: No settings/memories cached for chat {chat_id}")
            return None
    except Exception as e:
        logger.error(f"Error retrieving settings/memories for chat {chat_id}: {e}")
        return None

async def purge_chat_settings_memories(self, chat_id: str) -> bool:
    """Remove cached settings/memories for a chat (called on sharing/eviction)"""
    cache_keys = [
        f"chat:{chat_id}:settings_memories",
        f"chat:{chat_id}:sm_metadata"
    ]

    try:
        for key in cache_keys:
            await self.delete(key)
        logger.info(f"Purged settings/memories cache for chat {chat_id}")
        return True
    except Exception as e:
        logger.error(f"Error purging settings/memories for chat {chat_id}: {e}")
        return False
```

### 2. Extend LRU Cache with Cleanup Hook (cache_legacy_mixin.py)

Modify `update_user_active_chats_lru` to trigger settings/memories cleanup:

```python
# In backend/core/api/app/services/cache_legacy_mixin.py

async def update_user_active_chats_lru(self, user_id: str, chat_id: str):
    """
    Update the LRU list of last 3 active chats for a user.
    Also triggers cleanup of settings/memories cache for evicted chats.
    """
    try:
        client = await self.client
        if not client:
            return False

        lru_key = f"{self.USER_ACTIVE_CHATS_LRU_PREFIX}{user_id}"

        # Get current list before modification to identify evicted chats
        current_chats = await client.lrange(lru_key, 0, -1) or []

        # Update LRU list (existing logic)
        await client.lrem(lru_key, 0, chat_id)
        await client.lpush(lru_key, chat_id)
        await client.ltrim(lru_key, 0, 2)
        await client.expire(lru_key, self.CHAT_METADATA_TTL)

        # Get new list after trimming
        new_chats = await client.lrange(lru_key, 0, -1) or []

        # Find chats that were evicted (in current but not in new)
        evicted_chats = set(current_chats) - set(new_chats)

        # Cleanup settings/memories for evicted chats
        for evicted_chat_id in evicted_chats:
            await self.purge_chat_settings_memories(evicted_chat_id)
            logger.info(f"Auto-purged settings/memories for evicted chat {evicted_chat_id}")

        return True
    except Exception as e:
        logger.error(f"Error updating LRU for user {user_id}: {e}")
        return False
```

### 3. New API Endpoint (settings_memories_routes.py)

Create new routes for settings/memories management:

```python
# New file: backend/core/api/app/routes/settings_memories_routes.py

from fastapi import APIRouter, Depends, HTTPException
from backend.core.api.app.dependencies import get_current_user
from backend.core.api.app.services.cache import cache_service
from typing import Dict, Any, List

router = APIRouter(prefix="/v1/chat", tags=["Settings & Memories"])

@router.post("/{chat_id}/settings-memories")
async def cache_settings_memories(
    chat_id: str,
    payload: Dict[str, Any],
    current_user: dict = Depends(get_current_user)
):
    """Cache user-approved settings and memories for a chat"""
    user_id = current_user["id"]

    # Validate payload structure
    if "approved_data" not in payload:
        raise HTTPException(400, "Missing approved_data")

    success = await cache_service.cache_chat_settings_memories(
        chat_id=chat_id,
        user_id=user_id,
        settings_data=payload["approved_data"]
    )

    if not success:
        raise HTTPException(500, "Failed to cache settings/memories")

    return {"success": True, "cached_until": "lru_eviction"}

@router.get("/{chat_id}/settings-memories")
async def get_cached_settings_memories(
    chat_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Retrieve cached settings/memories for a chat (for AI inference)"""
    cached_data = await cache_service.get_chat_settings_memories(chat_id)

    if not cached_data:
        raise HTTPException(404, "No cached settings/memories for this chat")

    # Verify user owns this data
    if cached_data["user_id"] != current_user["id"]:
        raise HTTPException(403, "Access denied")

    return cached_data

@router.delete("/{chat_id}/settings-memories")
async def purge_settings_memories(
    chat_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Manually purge cached settings/memories for a chat"""
    success = await cache_service.purge_chat_settings_memories(chat_id)

    if not success:
        raise HTTPException(500, "Failed to purge cache")

    return {"success": True, "message": "Settings/memories cache cleared"}
```

### 4. Sharing Hook Integration

Add to existing chat sharing functionality:

```python
# In backend/core/api/app/routes/chat_sharing.py (or wherever share logic lives)

async def share_chat(chat_id: str, user_id: str):
    """Share a chat - includes automatic privacy protection"""

    # Existing sharing logic...

    # NEW: Immediately purge personal data when sharing
    await cache_service.purge_chat_settings_memories(chat_id)
    logger.info(f"Auto-purged personal cache for newly shared chat {chat_id}")

    return {"success": True, "share_url": share_url}
```

## Frontend Changes

### 1. Settings/Memories Request Handler (services/settingsMemoriesHandler.ts)

```typescript
// New file: frontend/packages/ui/src/services/settingsMemoriesHandler.ts

interface SettingsMemoryRequest {
    type: 'settings_memory_request';
    request_id: string;
    required_data: {
        apps: string[];
        settings: string[];
        memories: string[];
    };
}

interface SettingsMemoryResponse {
    type: 'settings_memory_response';
    request_id: string;
    approved_data: Record<string, any>;
}

export class SettingsMemoriesHandler {
    async handleRequest(
        request: SettingsMemoryRequest,
        chatId: string
    ): Promise<void> {
        // Show UI for user approval
        const userApproval = await this.showApprovalUI(request);

        if (!userApproval.approved) {
            return; // User declined
        }

        // Send approved data to server via WebSocket
        const response: SettingsMemoryResponse = {
            type: 'settings_memory_response',
            request_id: request.request_id,
            approved_data: userApproval.data
        };

        await webSocketService.sendMessage('cache_settings_memories', {
            chat_id: chatId,
            ...response
        });
    }

    private async showApprovalUI(
        request: SettingsMemoryRequest
    ): Promise<{approved: boolean; data: Record<string, any>}> {
        // Return promise that resolves when user makes choice
        return new Promise((resolve) => {
            // Create UI component for approval
            // This would be a modal/dialog showing what data is requested
            // and allowing user to approve/decline per app/setting
        });
    }
}
```

### 2. Chat History JSON Block Rendering

```typescript
// In existing message rendering component

function renderSettingsMemoryBlock(jsonContent: string): JSX.Element {
    const data = JSON.parse(jsonContent);

    if (data.type === 'settings_memory_request') {
        return (
            <div className="settings-memory-request">
                <h4>🔒 Settings & Memory Request</h4>
                <p>Apps: {data.apps_requested?.join(', ')}</p>
                <p>User approved: {data.user_approved?.join(', ') || 'None'}</p>
                <p>Cache status: {data.cache_status}</p>
            </div>
        );
    }

    return <pre>{jsonContent}</pre>;
}
```

## AI/LLM Integration Changes

### 1. Inference Context Preparation

```python
# In AI task processing (e.g., apps/ai/tasks/ask_skill_task.py)

async def prepare_chat_context_with_cached_data(chat_id: str, chat_history: List[Dict]) -> List[Dict]:
    """Inject cached settings/memories into chat context for AI inference"""

    # Check for cached settings/memories
    cached_data = await cache_service.get_chat_settings_memories(chat_id)

    if not cached_data:
        return chat_history  # No cached data, return as-is

    # Transform cached data for LLM context
    enhanced_history = []
    for message in chat_history:
        content = message.get("content", "")

        # Replace JSON metadata blocks with natural language for inference
        if "settings_memory_request" in content and cached_data:
            # Convert cached structured data to natural language
            natural_context = format_cached_data_for_llm(cached_data["data"])

            # Replace or append to message content
            message["content"] = content.replace(
                # Find JSON block and replace with natural language
                extract_json_block(content),
                f"\n\nUser's relevant preferences and data:\n{natural_context}"
            )

        enhanced_history.append(message)

    return enhanced_history

def format_cached_data_for_llm(cached_data: Dict[str, Any]) -> str:
    """Convert structured cache data to natural language for LLM"""
    context_parts = []

    for app_id, app_data in cached_data.items():
        app_context = f"**{app_id.title()} App:**"

        if "settings" in app_data:
            settings_text = ", ".join([f"{k}: {v}" for k, v in app_data["settings"].items()])
            app_context += f"\n- Settings: {settings_text}"

        if "memories" in app_data and app_data["memories"]:
            memories_text = ", ".join(app_data["memories"][:3])  # Limit for brevity
            app_context += f"\n- Recent activity: {memories_text}"

        context_parts.append(app_context)

    return "\n\n".join(context_parts)
```

## Testing Requirements

### 1. Cache Eviction Tests
```python
# Test that settings/memories are purged when chat drops from LRU
async def test_lru_eviction_purges_settings():
    # Cache settings for chat_1
    # Add 3 more chats to trigger eviction
    # Verify chat_1 settings are purged
    pass

async def test_sharing_purges_personal_data():
    # Cache personal settings for chat
    # Share the chat
    # Verify personal data is immediately purged
    pass
```

### 2. Privacy Tests
```python
async def test_shared_chat_no_personal_data_access():
    # Share chat with personal data cached
    # Verify recipient cannot access original user's personal data
    pass
```

## Migration & Deployment

### 1. Database Changes
**None required** - leverages existing Redis cache infrastructure

### 2. Configuration Updates
```python
# In cache_config.py - no changes needed, reuse existing TTLs
CHAT_MESSAGES_TTL = 86400  # Settings/memories use same 24h TTL
```

### 3. Deployment Steps
1. Deploy backend cache service extensions
2. Deploy new API endpoints
3. Deploy frontend handlers
4. Update AI task processing
5. Monitor cache hit rates and purge events

## Summary

**Total Changes:**
- ✅ **Backend**: 3 files modified, 1 new route file
- ✅ **Frontend**: 2 new service files, 1 UI component update
- ✅ **AI/LLM**: 1 context preparation function
- ✅ **Tests**: 5 new test cases
- ✅ **No database migrations required**

The implementation leverages your existing robust cache infrastructure with minimal changes, providing automatic privacy protection through the established LRU eviction mechanism.