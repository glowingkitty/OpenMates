"""
Embed Service for creating and managing embeds from skill results.
Handles TOON encoding, embed creation, and server-side caching.
"""
import logging
import json
import hashlib
import uuid
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime

from toon_format import encode
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.utils.encryption import EncryptionService

logger = logging.getLogger(__name__)


def _flatten_for_toon_tabular(obj: Any, prefix: str = "") -> Any:
    """
    Flatten nested objects for TOON tabular format encoding.
    This enables TOON to use efficient tabular arrays instead of repeated field names.
    
    Converts:
    - profile: {name: "..."} → profile_name: "..."
    - meta_url: {favicon: "..."} → meta_url_favicon: "..."
    - extra_snippets: [...] → extra_snippets: "|".join([...])
    
    Args:
        obj: Object to flatten (dict, list, or primitive)
        prefix: Prefix for nested keys
        
    Returns:
        Flattened object
    """
    if isinstance(obj, dict):
        flattened = {}
        for key, value in obj.items():
            new_key = f"{prefix}_{key}" if prefix else key
            if isinstance(value, dict):
                flattened.update(_flatten_for_toon_tabular(value, new_key))
            elif isinstance(value, list):
                # For lists, join with pipe separator for simple values, or flatten each item
                if value and isinstance(value[0], (str, int, float, bool, type(None))):
                    flattened[new_key] = "|".join(str(v) for v in value)
                else:
                    flattened_list = [_flatten_for_toon_tabular(item, "") for item in value]
                    flattened[new_key] = flattened_list
            else:
                flattened[new_key] = value
        return flattened
    elif isinstance(obj, list):
        return [_flatten_for_toon_tabular(item, prefix) for item in obj]
    else:
        return obj


class EmbedService:
    """
    Service for creating and managing embeds from skill results.
    
    Handles:
    - Converting skill results to TOON format
    - Creating embed entries (child + parent for composite results)
    - Server-side caching with vault encryption
    - Generating embed references for streaming
    """
    
    def __init__(
        self,
        cache_service: CacheService,
        directus_service: DirectusService,
        encryption_service: EncryptionService
    ):
        self.cache_service = cache_service
        self.directus_service = directus_service
        self.encryption_service = encryption_service
    
    async def create_embeds_from_skill_results(
        self,
        app_id: str,
        skill_id: str,
        results: List[Dict[str, Any]],
        chat_id: str,
        message_id: str,
        user_id: str,
        user_id_hash: str,
        user_vault_key_id: str,
        task_id: Optional[str] = None,
        log_prefix: str = ""
    ) -> Optional[Dict[str, Any]]:
        """
        Create embeds from skill results immediately after skill execution.
        
        For composite results (web search, places, events):
        - Creates child embed entries (one per result)
        - Creates parent app_skill_use embed with embed_ids array
        
        For single results:
        - Creates single app_skill_use embed
        
        Args:
            app_id: The app ID that owns the skill
            skill_id: The skill ID that was executed
            results: List of skill result dictionaries
            chat_id: Chat ID where the embed is created
            message_id: Message ID that references the embed
            user_id: User ID (UUID)
            user_id_hash: Hashed user ID
            user_vault_key_id: User's vault key ID for encryption
            task_id: Optional task ID for long-running tasks
            log_prefix: Logging prefix for this operation
            
        Returns:
            Dictionary with:
            - parent_embed_id: The embed_id of the parent app_skill_use embed
            - embed_reference: JSON string for embedding in message markdown
            - child_embed_ids: List of child embed IDs (if composite)
            None if creation fails
        """
        if not results or len(results) == 0:
            logger.warning(f"{log_prefix} No results to create embeds from")
            return None
        
        try:
            # Hash sensitive IDs for privacy protection
            hashed_chat_id = hashlib.sha256(chat_id.encode()).hexdigest()
            hashed_message_id = hashlib.sha256(message_id.encode()).hexdigest()
            hashed_task_id = hashlib.sha256(task_id.encode()).hexdigest() if task_id else None
            
            # Determine if this is a composite result (web search, places, events)
            # For now, we'll check the skill_id to determine composite vs single
            is_composite = skill_id in ["search", "places_search", "events_search"]
            
            child_embed_ids = []
            
            if is_composite:
                # Create child embeds (one per result)
                child_type = "website" if skill_id == "search" else ("place" if skill_id == "places_search" else "event")
                
                for result in results:
                    # Generate embed_id for child
                    child_embed_id = str(uuid.uuid4())
                    
                    # Convert result to TOON format
                    flattened_result = _flatten_for_toon_tabular(result)
                    content_toon = encode(flattened_result)
                    
                    # Create child embed entry
                    child_embed_data = {
                        "embed_id": child_embed_id,
                        "hashed_chat_id": hashed_chat_id,
                        "hashed_message_id": hashed_message_id,
                        "hashed_task_id": hashed_task_id,
                        "status": "finished",
                        "hashed_user_id": user_id_hash,
                        "share_mode": "private",
                        "created_at": int(datetime.now().timestamp()),
                        "updated_at": int(datetime.now().timestamp())
                    }
                    
                    # Encrypt with vault key for server-side cache
                    encrypted_content, _ = await self.encryption_service.encrypt_with_user_key(
                        content_toon,
                        user_vault_key_id
                    )
                    child_embed_data["encrypted_content"] = encrypted_content
                    
                    # Cache child embed (server-side, vault-encrypted)
                    await self._cache_embed(child_embed_id, child_embed_data, chat_id, user_id_hash)
                    
                    child_embed_ids.append(child_embed_id)
                    logger.debug(f"{log_prefix} Created child embed {child_embed_id} (type: {child_type})")
                
                # Create parent app_skill_use embed
                parent_embed_id = str(uuid.uuid4())
                
                # Parent embed content: metadata about the skill execution
                parent_content = {
                    "app_id": app_id,
                    "skill_id": skill_id,
                    "result_count": len(results),
                    "embed_ids": child_embed_ids
                }
                
                # Convert to TOON
                flattened_parent = _flatten_for_toon_tabular(parent_content)
                parent_content_toon = encode(flattened_parent)
                
                # Encrypt with vault key
                encrypted_parent_content, _ = await self.encryption_service.encrypt_with_user_key(
                    parent_content_toon,
                    user_vault_key_id
                )
                
                parent_embed_data = {
                    "embed_id": parent_embed_id,
                    "hashed_chat_id": hashed_chat_id,
                    "hashed_message_id": hashed_message_id,
                    "hashed_task_id": hashed_task_id,
                    "status": "finished",
                    "hashed_user_id": user_id_hash,
                    "share_mode": "private",
                    "embed_ids": child_embed_ids,  # JSON array
                    "encrypted_content": encrypted_parent_content,
                    "created_at": int(datetime.now().timestamp()),
                    "updated_at": int(datetime.now().timestamp())
                }
                
                # Cache parent embed
                await self._cache_embed(parent_embed_id, parent_embed_data, chat_id, user_id_hash)
                
                logger.info(f"{log_prefix} Created parent embed {parent_embed_id} with {len(child_embed_ids)} child embeds")
                
                # Generate embed reference JSON
                embed_reference = json.dumps({
                    "type": "app_skill_use",
                    "embed_id": parent_embed_id
                })
                
                return {
                    "parent_embed_id": parent_embed_id,
                    "embed_reference": embed_reference,
                    "child_embed_ids": child_embed_ids
                }
            
            else:
                # Single result - create single app_skill_use embed
                embed_id = str(uuid.uuid4())
                
                # Convert result to TOON format
                if len(results) == 1:
                    flattened_result = _flatten_for_toon_tabular(results[0])
                    content_toon = encode(flattened_result)
                else:
                    # Multiple results but not composite (e.g., code generation with multiple files)
                    flattened_results = [_flatten_for_toon_tabular(result) for result in results]
                    content_toon = encode({"results": flattened_results, "count": len(results)})
                
                # Encrypt with vault key
                encrypted_content, _ = await self.encryption_service.encrypt_with_user_key(
                    content_toon,
                    user_vault_key_id
                )
                
                embed_data = {
                    "embed_id": embed_id,
                    "hashed_chat_id": hashed_chat_id,
                    "hashed_message_id": hashed_message_id,
                    "hashed_task_id": hashed_task_id,
                    "status": "finished",
                    "hashed_user_id": user_id_hash,
                    "share_mode": "private",
                    "embed_ids": None,  # No child embeds
                    "encrypted_content": encrypted_content,
                    "created_at": int(datetime.now().timestamp()),
                    "updated_at": int(datetime.now().timestamp())
                }
                
                # Cache embed
                await self._cache_embed(embed_id, embed_data, chat_id, user_id_hash)
                
                logger.info(f"{log_prefix} Created single embed {embed_id}")
                
                # Generate embed reference JSON
                embed_reference = json.dumps({
                    "type": "app_skill_use",
                    "embed_id": embed_id
                })
                
                return {
                    "parent_embed_id": embed_id,
                    "embed_reference": embed_reference,
                    "child_embed_ids": []
                }
        
        except Exception as e:
            logger.error(f"{log_prefix} Error creating embeds from skill results: {e}", exc_info=True)
            return None
    
    async def _cache_embed(
        self,
        embed_id: str,
        embed_data: Dict[str, Any],
        chat_id: str,
        user_id_hash: str
    ) -> None:
        """
        Cache embed in Redis with vault encryption.
        
        Args:
            embed_id: The embed identifier
            embed_data: Embed data dictionary (already vault-encrypted)
            chat_id: Chat ID for indexing
            user_id_hash: Hashed user ID
        """
        try:
            # Cache key: embed:{embed_id} (global cache, one entry per embed)
            cache_key = f"embed:{embed_id}"
            
            # Store embed data (already encrypted with vault key)
            import json as json_lib
            embed_json = json_lib.dumps(embed_data)
            
            # Cache with 24h TTL (same as message cache)
            client = await self.cache_service.client
            if client:
                await client.set(cache_key, embed_json, ex=86400)  # 24 hours
                
                # Add to chat index for eviction tracking
                chat_embed_index_key = f"chat:{chat_id}:embed_ids"
                await client.sadd(chat_embed_index_key, embed_id)
                await client.expire(chat_embed_index_key, 86400)  # 24 hours
                
                logger.debug(f"Cached embed {embed_id} at {cache_key}")
            else:
                logger.warning(f"Redis client not available, skipping embed cache for {embed_id}")
        
        except Exception as e:
            logger.error(f"Error caching embed {embed_id}: {e}", exc_info=True)
            # Don't fail embed creation if caching fails

