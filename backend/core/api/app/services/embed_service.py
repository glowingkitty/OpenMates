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

from toon_format import encode, decode
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
    - Creating "processing" placeholders that update when skill completes
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

    async def create_processing_embed_placeholder(
        self,
        app_id: str,
        skill_id: str,
        chat_id: str,
        message_id: str,
        user_id: str,
        user_id_hash: str,
        user_vault_key_id: str,
        task_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        log_prefix: str = ""
    ) -> Optional[Dict[str, Any]]:
        """
        Create a "processing" embed placeholder immediately when skill starts.
        This allows the frontend to show the skill execution immediately.

        The embed will be updated with actual results when skill completes.

        Args:
            app_id: The app ID that owns the skill
            skill_id: The skill ID being executed
            chat_id: Chat ID where the embed is created
            message_id: Message ID that references the embed
            user_id: User ID (UUID)
            user_id_hash: Hashed user ID
            user_vault_key_id: User's vault key ID for encryption
            task_id: Optional task ID for tracking
            metadata: Optional metadata (query, provider, etc.)
            log_prefix: Logging prefix for this operation

        Returns:
            Dictionary with:
            - embed_id: The embed_id of the placeholder
            - embed_reference: JSON string for embedding in message markdown
            None if creation fails
        """
        try:
            # Hash sensitive IDs for privacy protection
            hashed_chat_id = hashlib.sha256(chat_id.encode()).hexdigest()
            hashed_message_id = hashlib.sha256(message_id.encode()).hexdigest()
            hashed_task_id = hashlib.sha256(task_id.encode()).hexdigest() if task_id else None

            # Generate embed_id for placeholder
            embed_id = str(uuid.uuid4())

            # Create minimal placeholder content with metadata
            # CRITICAL: Include all metadata (query, provider, etc.) in placeholder
            # This ensures the frontend can display the query immediately while skill executes
            placeholder_content = {
                "app_id": app_id,
                "skill_id": skill_id,
                "status": "processing",
                **(metadata or {})
            }
            
            # Log metadata for debugging (especially query for web search)
            if metadata:
                logger.debug(
                    f"{log_prefix} Creating placeholder with metadata: "
                    f"query={metadata.get('query', 'NOT FOUND')}, "
                    f"provider={metadata.get('provider', 'NOT FOUND')}, "
                    f"keys={list(metadata.keys())}"
                )

            # Convert to TOON format
            placeholder_toon = encode(placeholder_content)

            # Encrypt with vault key for server cache
            encrypted_content, _ = await self.encryption_service.encrypt_with_user_key(
                placeholder_toon,
                user_vault_key_id
            )

            # Create placeholder embed entry
            embed_data = {
                "embed_id": embed_id,
                "type": "app_skill_use",
                "chat_id": chat_id,
                "message_id": message_id,
                "hashed_chat_id": hashed_chat_id,
                "hashed_message_id": hashed_message_id,
                "hashed_task_id": hashed_task_id,
                "status": "processing",
                "hashed_user_id": user_id_hash,
                "share_mode": "private",
                "embed_ids": None,  # Will be populated when skill completes (for composite)
                "encrypted_content": encrypted_content,
                "created_at": int(datetime.now().timestamp()),
                "updated_at": int(datetime.now().timestamp())
            }

            # Cache placeholder embed
            await self._cache_embed(embed_id, embed_data, chat_id, user_id_hash)

            # SEND PLAINTEXT TOON TO CLIENT via WebSocket
            # This ensures the client has the embed data immediately to render the placeholder
            await self.send_embed_data_to_client(
                embed_id=embed_id,
                embed_type="app_skill_use",
                content_toon=placeholder_toon,  # PLAINTEXT TOON
                chat_id=chat_id,
                message_id=message_id,
                user_id=user_id,
                user_id_hash=user_id_hash,
                status="processing",
                task_id=task_id,
                share_mode="private",
                created_at=embed_data["created_at"],
                updated_at=embed_data["updated_at"],
                log_prefix=log_prefix
            )

            logger.info(f"{log_prefix} Created processing placeholder embed {embed_id} for {app_id}.{skill_id}")

            # Generate embed reference JSON
            embed_reference = json.dumps({
                "type": "app_skill_use",
                "embed_id": embed_id
            })

            return {
                "embed_id": embed_id,
                "embed_reference": embed_reference
            }

        except Exception as e:
            logger.error(f"{log_prefix} Error creating processing embed placeholder: {e}", exc_info=True)
            return None

    async def _get_cached_embed_toon(
        self,
        embed_id: str,
        user_vault_key_id: str,
        log_prefix: str = ""
    ) -> Optional[str]:
        """
        Retrieve an embed from cache and decrypt its content, returning as TOON string.
        
        This preserves the space savings of TOON format (30-60% vs JSON) while providing
        decrypted content for LLM processing.
        
        Args:
            embed_id: The embed identifier
            user_vault_key_id: User's vault key ID for decryption
            log_prefix: Logging prefix for this operation
            
        Returns:
            Decrypted TOON string or None if not found
        """
        try:
            cache_key = f"embed:{embed_id}"
            client = await self.cache_service.client
            if not client:
                logger.warning(f"{log_prefix} Redis client not available")
                return None
                
            embed_json = await client.get(cache_key)
            if not embed_json:
                logger.debug(f"{log_prefix} Embed {embed_id} not found in cache")
                return None
                
            import json as json_lib
            embed_data = json_lib.loads(embed_json)
            
            # Decrypt content using vault key
            encrypted_content = embed_data.get("encrypted_content")
            if not encrypted_content:
                logger.debug(f"{log_prefix} Embed {embed_id} has no encrypted_content")
                return None
                
            # decrypt_with_user_key returns Optional[str], not a tuple
            plaintext_toon = await self.encryption_service.decrypt_with_user_key(
                encrypted_content,
                user_vault_key_id
            )
            
            if not plaintext_toon:
                logger.warning(f"{log_prefix} Failed to decrypt embed {embed_id} content")
                return None
                
            # Return TOON string as-is (don't decode - preserves space savings)
            logger.debug(f"{log_prefix} Retrieved and decrypted embed {embed_id} from cache (TOON format)")
            return plaintext_toon
            
        except Exception as e:
            logger.error(f"{log_prefix} Error retrieving embed {embed_id} from cache: {e}", exc_info=True)
            return None

    async def _get_cached_embed(
        self,
        embed_id: str,
        user_vault_key_id: str,
        log_prefix: str = ""
    ) -> Optional[Dict[str, Any]]:
        """
        Retrieve an embed from cache and decrypt its content, returning the full embed data dictionary.
        
        This is used when we need to access metadata (query, provider, etc.) from a cached embed.
        
        Args:
            embed_id: The embed identifier
            user_vault_key_id: User's vault key ID for decryption
            log_prefix: Logging prefix for this operation
            
        Returns:
            Decrypted embed data dictionary or None if not found
        """
        try:
            cache_key = f"embed:{embed_id}"
            client = await self.cache_service.client
            if not client:
                logger.warning(f"{log_prefix} Redis client not available")
                return None
                
            embed_json = await client.get(cache_key)
            if not embed_json:
                logger.debug(f"{log_prefix} Embed {embed_id} not found in cache")
                return None
                
            import json as json_lib
            embed_data = json_lib.loads(embed_json)
            
            # Decrypt content using vault key if present
            encrypted_content = embed_data.get("encrypted_content")
            if encrypted_content:
                plaintext_content = await self.encryption_service.decrypt_with_user_key(
                    encrypted_content,
                    user_vault_key_id
                )
                
                if plaintext_content:
                    # Parse TOON content to extract metadata
                    try:
                        decoded_content = decode(plaintext_content)
                        
                        # Log what was decoded for debugging
                        logger.debug(
                            f"{log_prefix} Decoded TOON content. Type: {type(decoded_content)}, "
                            f"Is dict: {isinstance(decoded_content, dict)}"
                        )
                        if isinstance(decoded_content, dict):
                            logger.debug(
                                f"{log_prefix} Decoded TOON keys: {list(decoded_content.keys())}, "
                                f"Has 'query': {'query' in decoded_content}, "
                                f"Has 'provider': {'provider' in decoded_content}"
                            )
                            # Merge decoded content into embed_data for easy access
                            # The decoded content contains the actual data (query, provider, etc.)
                            embed_data.update(decoded_content)
                            logger.debug(
                                f"{log_prefix} After merge, embed_data has 'query': {'query' in embed_data}, "
                                f"'provider': {'provider' in embed_data}"
                            )
                        else:
                            logger.warning(
                                f"{log_prefix} Decoded TOON content is not a dict, got {type(decoded_content)}"
                            )
                    except Exception as decode_err:
                        logger.warning(
                            f"{log_prefix} Could not decode TOON content for metadata extraction: {decode_err}",
                            exc_info=True
                        )
                        # Continue without decoded content - metadata might be in embed_data already
                else:
                    logger.warning(f"{log_prefix} Failed to decrypt embed {embed_id} content")
            
            logger.debug(
                f"{log_prefix} Retrieved embed {embed_id} from cache. Final keys: {list(embed_data.keys())}, "
                f"query={embed_data.get('query', 'NOT FOUND')}"
            )
            return embed_data
            
        except Exception as e:
            logger.error(f"{log_prefix} Error retrieving embed {embed_id} from cache: {e}", exc_info=True)
            return None

    async def resolve_embed_references_in_content(
        self,
        content: str,
        user_vault_key_id: str,
        log_prefix: str = ""
    ) -> str:
        """
        Resolve embed references in message content by replacing JSON code blocks
        with actual embed content from cache (as TOON format).
        
        According to embeds architecture, messages contain embed references like:
        ```json
        {"type": "app_skill_use", "embed_id": "..."}
        ```
        
        This function:
        1. Parses message markdown to find JSON code blocks with embed references
        2. For each embed reference, loads embed from cache
        3. Decrypts TOON content (but keeps as TOON string - not decoded to JSON)
        4. Replaces embed reference JSON block with TOON code block containing embed content
        
        CRITICAL: TOON format is preserved (not decoded to JSON) to maintain space savings
        (30-60% token reduction vs JSON). LLM can process TOON format directly.
        
        Args:
            content: Message content (markdown) that may contain embed references
            user_vault_key_id: User's vault key ID for decryption
            log_prefix: Logging prefix for this operation
            
        Returns:
            Content with embed references resolved (replaced with TOON code blocks)
        """
        import re
        import json as json_lib
        
        # Pattern to match JSON code blocks that might contain embed references
        # Format: ```json\n{...}\n```
        json_block_pattern = r'```json\s*\n([\s\S]*?)\n```'
        
        # Find all embed references first
        embed_refs = []
        for match in re.finditer(json_block_pattern, content):
            json_content = match.group(1).strip()
            try:
                embed_ref = json_lib.loads(json_content)
                if isinstance(embed_ref, dict):
                    embed_type = embed_ref.get("type")
                    embed_id = embed_ref.get("embed_id")
                    if embed_type and embed_id:
                        embed_refs.append({
                            "match": match,
                            "embed_id": embed_id,
                            "embed_type": embed_type,
                            "full_match": match.group(0)
                        })
            except json_lib.JSONDecodeError:
                continue
        
        # If no embed references found, return original content
        if not embed_refs:
            return content
        
        # Resolve all embed references (async)
        resolved_parts = []
        last_end = 0
        
        for embed_ref_info in embed_refs:
            match = embed_ref_info["match"]
            embed_id = embed_ref_info["embed_id"]
            embed_type = embed_ref_info["embed_type"]
            
            # Add content before this match
            resolved_parts.append(content[last_end:match.start()])
            
            # Load embed from cache (returns TOON string, not decoded)
            toon_content = await self._get_cached_embed_toon(embed_id, user_vault_key_id, log_prefix)
            
            if not toon_content:
                # CRITICAL: If embed not found in cache, log a warning but continue with reference
                # This allows the LLM to process the request even if embeds are missing from cache
                # The embed reference will be included in the message history, which is better than failing
                logger.warning(
                    f"{log_prefix} Embed {embed_id} not found in cache during resolution. "
                    f"This may indicate embeds expired from cache (24h TTL) or were not cached properly. "
                    f"Keeping embed reference in message content. LLM will receive reference instead of content."
                )
                resolved_parts.append(embed_ref_info["full_match"])  # Keep original reference
            else:
                # Replace embed reference with TOON content directly
                # TOON format is space-efficient (30-60% savings vs JSON) and LLM can process it
                # Format as code block to preserve TOON structure
                resolved_text = f"```toon\n{toon_content}\n```"
                
                logger.debug(f"{log_prefix} Resolved embed reference {embed_id} ({embed_type}) with TOON content ({len(toon_content)} chars)")
                resolved_parts.append(resolved_text)
            
            last_end = match.end()
        
        # Add remaining content after last match
        resolved_parts.append(content[last_end:])
        
        return "".join(resolved_parts)

    async def update_embed_with_results(
        self,
        embed_id: str,
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
        Update an existing "processing" embed with actual skill results.

        For composite results (web search, places, events):
        - Creates child embed entries (one per result)
        - Updates parent embed with embed_ids array

        For single results:
        - Updates embed with result content

        Args:
            embed_id: The embed_id to update (from placeholder)
            app_id: The app ID that owns the skill
            skill_id: The skill ID that was executed
            results: List of skill result dictionaries
            chat_id: Chat ID where the embed is created
            message_id: Message ID that references the embed
            user_id_hash: Hashed user ID
            user_vault_key_id: User's vault key ID for encryption
            task_id: Optional task ID for long-running tasks
            log_prefix: Logging prefix for this operation

        Returns:
            Dictionary with:
            - embed_id: The embed_id (same as input)
            - child_embed_ids: List of child embed IDs (if composite)
            - status: "finished" or "error"
            None if update fails
        """
        if not results or len(results) == 0:
            logger.warning(f"{log_prefix} No results to update embed {embed_id}")
            return None

        try:
            # Hash sensitive IDs for privacy protection
            hashed_chat_id = hashlib.sha256(chat_id.encode()).hexdigest()
            hashed_message_id = hashlib.sha256(message_id.encode()).hexdigest()
            hashed_task_id = hashlib.sha256(task_id.encode()).hexdigest() if task_id else None

            # Determine if this is a composite result (web search, places, events)
            is_composite = skill_id in ["search", "places_search", "events_search"]

            child_embed_ids = []

            # Retrieve original placeholder metadata (query, provider, etc.)
            # This ensures we preserve the original metadata when updating the embed
            original_content = await self._get_cached_embed(embed_id, user_vault_key_id, log_prefix)
            original_metadata = {}
            if original_content:
                # Extract metadata fields that should be preserved
                # The decoded TOON content is merged into embed_data, so check both places
                # CRITICAL: Log what we actually retrieved for debugging
                logger.debug(
                    f"{log_prefix} Retrieved original_content from cache. "
                    f"Keys: {list(original_content.keys())}, "
                    f"Has 'query': {'query' in original_content}, "
                    f"Has 'provider': {'provider' in original_content}, "
                    f"Has 'app_id': {'app_id' in original_content}, "
                    f"Has 'skill_id': {'skill_id' in original_content}"
                )
                
                # Extract metadata fields that should be preserved
                for key in ['query', 'provider', 'url', 'input_data']:
                    if key in original_content:
                        original_metadata[key] = original_content[key]
                        logger.debug(f"{log_prefix} Found metadata key '{key}': {original_metadata[key]}")
                    else:
                        logger.debug(f"{log_prefix} Metadata key '{key}' not found in original_content")
                
                # CRITICAL: Log detailed metadata extraction for debugging
                logger.info(
                    f"{log_prefix} Preserving original metadata: {list(original_metadata.keys())} "
                    f"(query={original_metadata.get('query', 'NOT FOUND')}, "
                    f"provider={original_metadata.get('provider', 'NOT FOUND')})"
                )
            else:
                logger.warning(f"{log_prefix} Could not retrieve original embed metadata for {embed_id}")

            if is_composite:
                # Create child embeds (one per result)
                # Maps search (app_id="maps", skill_id="search") should create "place" embeds
                # Web search (app_id="web", skill_id="search") should create "website" embeds
                if app_id == "maps" and skill_id == "search":
                    child_type = "place"
                elif skill_id == "search":
                    child_type = "website"  # Web search, news search, videos search
                elif skill_id == "places_search":
                    child_type = "place"
                elif skill_id == "events_search":
                    child_type = "event"
                else:
                    child_type = "website"  # Default fallback

                for result in results:
                    # Generate embed_id for child
                    child_embed_id = str(uuid.uuid4())

                    # Convert result to TOON format (PLAINTEXT)
                    flattened_result = _flatten_for_toon_tabular(result)
                    content_toon = encode(flattened_result)

                    # Calculate text length for child embed
                    text_length_chars = len(content_toon)

                    # Create child embed entry
                    created_at = int(datetime.now().timestamp())
                    child_embed_data = {
                        "embed_id": child_embed_id,
                        "type": child_type,
                        "chat_id": chat_id,
                        "message_id": message_id,
                        "hashed_chat_id": hashed_chat_id,
                        "hashed_message_id": hashed_message_id,
                        "hashed_task_id": hashed_task_id,
                        "status": "finished",
                        "hashed_user_id": user_id_hash,
                        "share_mode": "private",
                        "text_length_chars": text_length_chars,
                        "created_at": created_at,
                        "updated_at": created_at
                    }

                    # Encrypt with vault key for server-side cache
                    encrypted_content, _ = await self.encryption_service.encrypt_with_user_key(
                        content_toon,
                        user_vault_key_id
                    )
                    child_embed_data["encrypted_content"] = encrypted_content

                    # Cache child embed (server-side, vault-encrypted)
                    await self._cache_embed(child_embed_id, child_embed_data, chat_id, user_id_hash)

                    # SEND PLAINTEXT TOON TO CLIENT via WebSocket
                    await self.send_embed_data_to_client(
                        embed_id=child_embed_id,
                        embed_type=child_type,
                        content_toon=content_toon,  # PLAINTEXT TOON
                        chat_id=chat_id,
                        message_id=message_id,
                        user_id=user_id,
                        user_id_hash=user_id_hash,
                        status="finished",
                        task_id=task_id,
                        text_length_chars=text_length_chars,
                        created_at=created_at,
                        updated_at=created_at,
                        log_prefix=log_prefix
                    )

                    child_embed_ids.append(child_embed_id)
                    logger.debug(f"{log_prefix} Created child embed {child_embed_id} (type: {child_type})")

                # Update parent embed with child embed_ids and results
                # Include original metadata (query, provider, etc.) for proper frontend rendering
                # CRITICAL: original_metadata must include query for web search embeds to display correctly
                parent_content = {
                    "app_id": app_id,
                    "skill_id": skill_id,
                    "result_count": len(results),
                    "embed_ids": child_embed_ids,
                    "status": "finished",
                    **original_metadata  # Preserve query, provider, url, etc. from placeholder
                }
                
                # Log final parent content to verify query is included
                logger.info(
                    f"{log_prefix} Parent embed content includes: "
                    f"query={parent_content.get('query', 'MISSING')}, "
                    f"provider={parent_content.get('provider', 'MISSING')}, "
                    f"result_count={parent_content.get('result_count')}"
                )

                # Convert to TOON (PLAINTEXT)
                flattened_parent = _flatten_for_toon_tabular(parent_content)
                parent_content_toon = encode(flattened_parent)

                # Calculate text length for parent embed
                parent_text_length_chars = len(parent_content_toon)

                # Encrypt with vault key
                encrypted_parent_content, _ = await self.encryption_service.encrypt_with_user_key(
                    parent_content_toon,
                    user_vault_key_id
                )

                # Update parent embed in cache
                updated_at = int(datetime.now().timestamp())
                updated_embed_data = {
                    "embed_id": embed_id,
                    "type": "app_skill_use",
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "hashed_chat_id": hashed_chat_id,
                    "hashed_message_id": hashed_message_id,
                    "hashed_task_id": hashed_task_id,
                    "status": "finished",
                    "hashed_user_id": user_id_hash,
                    "share_mode": "private",
                    "embed_ids": child_embed_ids,  # JSON array
                    "encrypted_content": encrypted_parent_content,
                    "text_length_chars": parent_text_length_chars,
                    "created_at": updated_at,
                    "updated_at": updated_at
                }

                # Update cache (overwrites placeholder)
                await self._cache_embed(embed_id, updated_embed_data, chat_id, user_id_hash)

                # SEND PLAINTEXT TOON TO CLIENT via WebSocket
                await self.send_embed_data_to_client(
                    embed_id=embed_id,
                    embed_type="app_skill_use",
                    content_toon=parent_content_toon,  # PLAINTEXT TOON
                    chat_id=chat_id,
                    message_id=message_id,
                    user_id=user_id,
                    user_id_hash=user_id_hash,
                    status="finished",
                    task_id=task_id,
                    embed_ids=child_embed_ids,
                    text_length_chars=parent_text_length_chars,
                    created_at=updated_at,
                    updated_at=updated_at,
                    log_prefix=log_prefix
                )

                logger.info(f"{log_prefix} Updated embed {embed_id} with {len(child_embed_ids)} child embeds")

                return {
                    "embed_id": embed_id,
                    "child_embed_ids": child_embed_ids,
                    "status": "finished"
                }

            else:
                # Single result - update embed with result content
                # Convert result to TOON format (PLAINTEXT)
                if len(results) == 1:
                    flattened_result = _flatten_for_toon_tabular(results[0])
                    content_toon = encode(flattened_result)
                else:
                    # Multiple results but not composite
                    flattened_results = [_flatten_for_toon_tabular(result) for result in results]
                    content_toon = encode({"results": flattened_results, "count": len(results)})

                # Calculate text length
                single_text_length_chars = len(content_toon)

                # Encrypt with vault key
                encrypted_content, _ = await self.encryption_service.encrypt_with_user_key(
                    content_toon,
                    user_vault_key_id
                )

                # Update embed in cache
                updated_at = int(datetime.now().timestamp())
                updated_embed_data = {
                    "embed_id": embed_id,
                    "type": "app_skill_use",
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "hashed_chat_id": hashed_chat_id,
                    "hashed_message_id": hashed_message_id,
                    "hashed_task_id": hashed_task_id,
                    "status": "finished",
                    "hashed_user_id": user_id_hash,
                    "share_mode": "private",
                    "embed_ids": None,  # No child embeds
                    "encrypted_content": encrypted_content,
                    "text_length_chars": single_text_length_chars,
                    "created_at": updated_at,
                    "updated_at": updated_at
                }

                # Update cache (overwrites placeholder)
                await self._cache_embed(embed_id, updated_embed_data, chat_id, user_id_hash)

                # SEND PLAINTEXT TOON TO CLIENT via WebSocket
                await self.send_embed_data_to_client(
                    embed_id=embed_id,
                    embed_type="app_skill_use",
                    content_toon=content_toon,  # PLAINTEXT TOON
                    chat_id=chat_id,
                    message_id=message_id,
                    user_id=user_id,
                    user_id_hash=user_id_hash,
                    status="finished",
                    task_id=task_id,
                    text_length_chars=single_text_length_chars,
                    created_at=updated_at,
                    updated_at=updated_at,
                    log_prefix=log_prefix
                )

                logger.info(f"{log_prefix} Updated single embed {embed_id}")

                return {
                    "embed_id": embed_id,
                    "child_embed_ids": [],
                    "status": "finished"
                }

        except Exception as e:
            logger.error(f"{log_prefix} Error updating embed {embed_id} with results: {e}", exc_info=True)
            return None

    async def send_embed_data_to_client(
        self,
        embed_id: str,
        embed_type: str,
        content_toon: str,
        chat_id: str,
        message_id: str,
        user_id: str,
        user_id_hash: str,
        status: str = "finished",
        text_preview: Optional[str] = None,
        task_id: Optional[str] = None,
        embed_ids: Optional[List[str]] = None,
        parent_embed_id: Optional[str] = None,
        version_number: Optional[int] = None,
        file_path: Optional[str] = None,
        content_hash: Optional[str] = None,
        text_length_chars: Optional[int] = None,
        share_mode: str = "private",
        created_at: Optional[int] = None,
        updated_at: Optional[int] = None,
        log_prefix: str = ""
    ) -> bool:
        """
        Send PLAINTEXT TOON embed content to client via WebSocket for client-side encryption and storage.

        CRITICAL: This sends PLAINTEXT content to the client. The client will:
        1. Receive plaintext TOON
        2. IMMEDIATELY encrypt with master key (NEVER stores plaintext!)
        3. Store encrypted in IndexedDB
        4. Send client-encrypted back to server via store_embed event

        Args:
            embed_id: The embed identifier
            embed_type: Plaintext embed type (client will encrypt before storage)
            content_toon: Plaintext TOON-encoded string (client will encrypt before storage)
            chat_id: Plaintext chat_id (client will hash before sending to server)
            message_id: Plaintext message_id (client will hash before sending to server)
            user_id: User ID (UUID)
            user_id_hash: Hashed user ID for channel targeting
            status: Embed status
            text_preview: Plaintext text preview (client will encrypt)
            task_id: Optional task ID (client will hash)
            embed_ids: For composite embeds (app_skill_use)
            parent_embed_id: For versioned embeds
            version_number: For versioned embeds
            file_path: For code/file embeds
            content_hash: SHA256 hash for deduplication
            text_length_chars: Character count for text-based embeds (auto-calculated if not provided)
            share_mode: Sharing mode
            created_at: Unix timestamp
            updated_at: Unix timestamp
            log_prefix: Logging prefix

        Returns:
            True if event was published successfully, False otherwise
        """
        try:
            # Auto-calculate text_length_chars if not provided
            # For text-based embeds: code, table, document, app_skill_use
            if text_length_chars is None:
                # Count characters in TOON content for text-based embeds
                text_length_chars = len(content_toon)

            # Build send_embed_data payload with PLAINTEXT content
            payload = {
                "event": "send_embed_data",
                "type": "send_embed_data",
                "event_for_client": "send_embed_data",
                "payload": {
                    "embed_id": embed_id,
                    "type": embed_type,  # PLAINTEXT (client will encrypt)
                    "content": content_toon,  # PLAINTEXT TOON (client will encrypt)
                    "status": status,
                    "chat_id": chat_id,  # PLAINTEXT (client will hash before sending back)
                    "message_id": message_id,  # PLAINTEXT (client will hash)
                    "user_id": user_id,
                    "share_mode": share_mode,
                    "text_length_chars": text_length_chars,  # Character count for LLM compression decision
                    "createdAt": created_at or int(datetime.now().timestamp()),
                    "updatedAt": updated_at or int(datetime.now().timestamp())
                }
            }

            # Add optional fields
            if text_preview is not None:
                payload["payload"]["text_preview"] = text_preview  # PLAINTEXT (client will encrypt)
            if task_id is not None:
                payload["payload"]["task_id"] = task_id  # PLAINTEXT (client will hash)
            if embed_ids is not None:
                payload["payload"]["embed_ids"] = embed_ids
            if parent_embed_id is not None:
                payload["payload"]["parent_embed_id"] = parent_embed_id
            if version_number is not None:
                payload["payload"]["version_number"] = version_number
            if file_path is not None:
                payload["payload"]["file_path"] = file_path
            if content_hash is not None:
                payload["payload"]["content_hash"] = content_hash

            # Publish to Redis for WebSocket delivery
            client = await self.cache_service.client
            if client:
                import json as json_lib
                channel_key = f"websocket:user:{user_id_hash}"
                await client.publish(channel_key, json_lib.dumps(payload))
                logger.debug(f"{log_prefix} Published send_embed_data event for embed {embed_id} (plaintext TOON)")
                return True
            else:
                logger.warning(f"{log_prefix} Redis client not available, skipping send_embed_data event")
                return False

        except Exception as e:
            logger.error(f"{log_prefix} Error sending embed data to client: {e}", exc_info=True)
            return False

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
            # Check both app_id and skill_id to determine composite vs single
            # Maps search uses skill_id "search" but should create "place" embeds, not "website" embeds
            is_composite = skill_id in ["search", "places_search", "events_search"]
            
            child_embed_ids = []
            
            if is_composite:
                # Create child embeds (one per result)
                # Maps search (app_id="maps", skill_id="search") should create "place" embeds
                # Web search (app_id="web", skill_id="search") should create "website" embeds
                if app_id == "maps" and skill_id == "search":
                    child_type = "place"
                elif skill_id == "search":
                    child_type = "website"  # Web search, news search, videos search
                elif skill_id == "places_search":
                    child_type = "place"
                elif skill_id == "events_search":
                    child_type = "event"
                else:
                    child_type = "website"  # Default fallback
                
                for result in results:
                    # Generate embed_id for child
                    child_embed_id = str(uuid.uuid4())
                    
                    # Convert result to TOON format
                    flattened_result = _flatten_for_toon_tabular(result)
                    content_toon = encode(flattened_result)
                    
                    # Create child embed entry
                    child_embed_data = {
                        "embed_id": child_embed_id,
                        "type": child_type,
                        "chat_id": chat_id,
                        "message_id": message_id,
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
                    "type": "app_skill_use",
                    "chat_id": chat_id,
                    "message_id": message_id,
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
                # Non-composite result - create single app_skill_use embed
                # All skills return results as an array, so we always structure it consistently
                embed_id = str(uuid.uuid4())
                
                # Flatten all results for TOON encoding
                flattened_results = [_flatten_for_toon_tabular(result) for result in results]
                
                # Wrap with app_id and skill_id metadata for frontend rendering
                # This ensures the frontend can identify which skill was executed
                # and render the appropriate preview component
                # Structure matches composite results pattern: app_id, skill_id, results array
                content_with_metadata = {
                    "app_id": app_id,
                    "skill_id": skill_id,
                    "results": flattened_results,
                    "result_count": len(results)
                }
                content_toon = encode(_flatten_for_toon_tabular(content_with_metadata))
                
                # Encrypt with vault key
                encrypted_content, _ = await self.encryption_service.encrypt_with_user_key(
                    content_toon,
                    user_vault_key_id
                )
                
                embed_data = {
                    "embed_id": embed_id,
                    "type": "app_skill_use",
                    "chat_id": chat_id,
                    "message_id": message_id,
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
