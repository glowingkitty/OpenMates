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
        skill_task_id: Optional[str] = None,
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
            task_id: Optional main AI task ID for tracking
            skill_task_id: Optional unique ID for this specific skill invocation (for cancellation).
                          If not provided, one will be generated automatically.
            metadata: Optional metadata (query, provider, etc.)
            log_prefix: Logging prefix for this operation

        Returns:
            Dictionary with:
            - embed_id: The embed_id of the placeholder
            - embed_reference: JSON string for embedding in message markdown
            - skill_task_id: The unique skill task ID for cancellation
            None if creation fails
        """
        try:
            # Hash sensitive IDs for privacy protection
            hashed_chat_id = hashlib.sha256(chat_id.encode()).hexdigest()
            hashed_message_id = hashlib.sha256(message_id.encode()).hexdigest()
            hashed_task_id = hashlib.sha256(task_id.encode()).hexdigest() if task_id else None
            
            # Generate skill_task_id if not provided - this is used for individual skill cancellation
            # CRITICAL: skill_task_id allows cancelling a single skill without stopping the entire AI response
            if not skill_task_id:
                skill_task_id = str(uuid.uuid4())
            hashed_skill_task_id = hashlib.sha256(skill_task_id.encode()).hexdigest()

            # Generate embed_id for placeholder
            embed_id = str(uuid.uuid4())

            # Create minimal placeholder content with metadata
            # CRITICAL: Include all metadata (query, provider, etc.) in placeholder
            # This ensures the frontend can display the query immediately while skill executes
            # CRITICAL: Include task_id and skill_task_id so frontend can:
            #   - task_id: Cancel the entire AI response
            #   - skill_task_id: Cancel just this specific skill (AI continues)
            placeholder_content = {
                "app_id": app_id,
                "skill_id": skill_id,
                "status": "processing",
                **({"task_id": task_id} if task_id else {}),
                "skill_task_id": skill_task_id,  # For individual skill cancellation
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
                "hashed_skill_task_id": hashed_skill_task_id,  # For individual skill cancellation
                "status": "processing",
                "hashed_user_id": user_id_hash,
                "is_private": False,
                "is_shared": False,
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
                is_private=False,
                is_shared=False,
                created_at=embed_data["created_at"],
                updated_at=embed_data["updated_at"],
                log_prefix=log_prefix
            )

            logger.info(
                f"{log_prefix} Created processing placeholder embed {embed_id} for {app_id}.{skill_id} "
                f"with skill_task_id={skill_task_id}"
            )

            # Generate embed reference JSON
            embed_reference = json.dumps({
                "type": "app_skill_use",
                "embed_id": embed_id
            })

            return {
                "embed_id": embed_id,
                "embed_reference": embed_reference,
                "skill_task_id": skill_task_id  # Return skill_task_id for cancellation tracking
            }

        except Exception as e:
            logger.error(f"{log_prefix} Error creating processing embed placeholder: {e}", exc_info=True)
            return None

    async def create_code_embed_placeholder(
        self,
        language: str,
        chat_id: str,
        message_id: str,
        user_id: str,
        user_id_hash: str,
        user_vault_key_id: str,
        task_id: Optional[str] = None,
        filename: Optional[str] = None,
        log_prefix: str = ""
    ) -> Optional[Dict[str, Any]]:
        """
        Create a "processing" code embed placeholder immediately when code block starts.
        This allows the frontend to show the code block embed immediately while code streams.
        
        The embed will be updated with code content as it streams paragraph by paragraph,
        and finalized when the code block closes.
        
        Args:
            language: Programming language (e.g., "python", "javascript", "" for no language)
            chat_id: Chat ID where the embed is created
            message_id: Message ID that references the embed
            user_id: User ID (UUID)
            user_id_hash: Hashed user ID
            user_vault_key_id: User's vault key ID for encryption
            task_id: Optional task ID for tracking
            filename: Optional filename (extracted from language:filename format)
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

            # Create minimal placeholder content with language and filename
            placeholder_content = {
                "type": "code",
                "language": language or "",
                "code": "",  # Empty initially, will be updated as code streams
                "filename": filename,
                "status": "processing",
                "line_count": 0  # Will be updated when content is finalized
            }

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
                "type": "code",
                "chat_id": chat_id,
                "message_id": message_id,
                "hashed_chat_id": hashed_chat_id,
                "hashed_message_id": hashed_message_id,
                "hashed_task_id": hashed_task_id,
                "status": "processing",
                "hashed_user_id": user_id_hash,
                "is_private": False,
                "is_shared": False,
                "embed_ids": None,  # Code embeds don't have child embeds
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
                embed_type="code",
                content_toon=placeholder_toon,  # PLAINTEXT TOON
                chat_id=chat_id,
                message_id=message_id,
                user_id=user_id,
                user_id_hash=user_id_hash,
                status="processing",
                task_id=task_id,
                is_private=False,
                is_shared=False,
                created_at=embed_data["created_at"],
                updated_at=embed_data["updated_at"],
                log_prefix=log_prefix
            )

            logger.info(f"{log_prefix} Created processing code embed placeholder {embed_id} (language: {language or 'none'})")

            # Generate embed reference JSON
            embed_reference = json.dumps({
                "type": "code",
                "embed_id": embed_id
            })

            return {
                "embed_id": embed_id,
                "embed_reference": embed_reference
            }

        except Exception as e:
            logger.error(f"{log_prefix} Error creating code embed placeholder: {e}", exc_info=True)
            return None

    async def update_code_embed_content(
        self,
        embed_id: str,
        code_content: str,
        chat_id: str,
        user_id: str,
        user_id_hash: str,
        user_vault_key_id: str,
        status: str = "processing",
        log_prefix: str = ""
    ) -> bool:
        """
        Update code embed content as code streams paragraph by paragraph.
        
        This method updates the cached embed with new code content and sends
        the updated content to the client via WebSocket.
        
        Args:
            embed_id: The embed identifier
            code_content: The code content to update (accumulated so far)
            chat_id: Chat ID for cache indexing
            user_id: User ID (UUID)
            user_id_hash: Hashed user ID
            user_vault_key_id: User's vault key ID for encryption
            status: Embed status ("processing" while streaming, "finished" when complete)
            log_prefix: Logging prefix for this operation
            
        Returns:
            True if update succeeded, False otherwise
        """
        try:
            # Get existing embed from cache to preserve metadata
            cached_embed = await self._get_cached_embed(embed_id, user_vault_key_id, log_prefix)
            if not cached_embed:
                logger.warning(f"{log_prefix} Code embed {embed_id} not found in cache, cannot update")
                return False

            # Decode existing content to get language and filename
            existing_toon = await self._get_cached_embed_toon(embed_id, user_vault_key_id, log_prefix)
            if existing_toon:
                try:
                    existing_content = decode(existing_toon)
                    language = existing_content.get("language", "")
                    filename = existing_content.get("filename")
                except Exception as e:
                    logger.warning(f"{log_prefix} Failed to decode existing code embed content: {e}")
                    language = ""
                    filename = None
            else:
                language = ""
                filename = None

            # Create updated content with new code
            # Calculate line count for display (count all lines including empty ones)
            line_count = code_content.count('\n') + 1 if code_content else 0
            
            updated_content = {
                "type": "code",
                "language": language,
                "code": code_content,
                "filename": filename,
                "status": status,
                "line_count": line_count
            }

            # Convert to TOON format
            updated_toon = encode(updated_content)

            # Encrypt with vault key for server cache
            encrypted_content, _ = await self.encryption_service.encrypt_with_user_key(
                updated_toon,
                user_vault_key_id
            )

            # Update embed data
            updated_embed_data = {
                **cached_embed,
                "encrypted_content": encrypted_content,
                "status": status,
                "updated_at": int(datetime.now().timestamp())
            }

            # CRITICAL: Check if embed is already finalized to prevent duplicate send_embed_data events
            # If the embed is already "finished" and we're trying to send "finished" again, skip it
            # This prevents duplicate events when update_code_embed_content is called multiple times
            current_status = cached_embed.get("status", "processing")
            should_send_event = True
            if status == "finished" and current_status == "finished":
                # Embed is already finalized - don't send duplicate event
                should_send_event = False
                logger.debug(
                    f"{log_prefix} [EMBED_EVENT] Skipping duplicate send_embed_data for already-finalized embed {embed_id} "
                    f"(current_status={current_status}, new_status={status})"
                )

            # Update cache
            await self._cache_embed(embed_id, updated_embed_data, chat_id, user_id_hash)

            # Send updated content to client via WebSocket (only if not a duplicate finalization)
            if should_send_event:
                # CRITICAL FIX: Pass check_cache_status=False because we already checked the cache
                # status above (at line 440). The cache was updated at line 451 BEFORE this call,
                # so send_embed_data_to_client's default cache check would see the NEW status
                # ("finished") and incorrectly skip sending. This was causing embeds to never
                # be finalized on the frontend because the "finished" event was being dropped.
                await self.send_embed_data_to_client(
                    embed_id=embed_id,
                    embed_type="code",
                    content_toon=updated_toon,  # PLAINTEXT TOON
                    chat_id=chat_id,
                    message_id=cached_embed.get("message_id", ""),
                    user_id=user_id,
                    user_id_hash=user_id_hash,
                    status=status,
                    task_id=cached_embed.get("hashed_task_id"),
                    is_private=cached_embed.get("is_private", False),
                    is_shared=cached_embed.get("is_shared", False),
                    created_at=cached_embed.get("created_at"),
                    updated_at=updated_embed_data["updated_at"],
                    log_prefix=log_prefix,
                    check_cache_status=False  # Already checked above, cache was just updated
                )

            logger.debug(f"{log_prefix} Updated code embed {embed_id} with {len(code_content)} chars (status: {status})")
            return True

        except Exception as e:
            logger.error(f"{log_prefix} Error updating code embed content: {e}", exc_info=True)
            return False

    async def extract_code_blocks_from_user_message(
        self,
        content: str,
        chat_id: str,
        message_id: str,
        user_id: str,
        user_id_hash: str,
        user_vault_key_id: str,
        log_prefix: str = ""
    ) -> Tuple[str, List[Dict[str, Any]]]:
        """
        Extract code blocks from user message content and create embeds for each.
        
        This is called when a user message is received to:
        1. Find all markdown code blocks in the message
        2. Create an embed for each code block
        3. Replace code blocks with embed references
        4. Return modified content and list of created embeds
        
        Args:
            content: User message markdown content
            chat_id: Chat ID
            message_id: Message ID
            user_id: User ID
            user_id_hash: Hashed user ID
            user_vault_key_id: User's vault key ID for encryption
            log_prefix: Logging prefix
            
        Returns:
            Tuple of (modified_content, list_of_embed_data)
            - modified_content: Message with code blocks replaced by embed references
            - list_of_embed_data: List of embed dictionaries to send to client for encrypted storage
        """
        import re
        
        # Pattern to match markdown code blocks with optional language and filename
        # Format: ```language:filename\ncontent\n``` or ```language\ncontent\n``` or ```\ncontent\n```
        # IMPORTANT: Skip JSON blocks that are already embed references
        code_block_pattern = r'```([a-zA-Z0-9_+\-#.]*?)(?::([^\n`]+))?\n([\s\S]*?)\n```'
        
        created_embeds = []
        
        def replace_code_block(match):
            """Replace a code block with an embed reference."""
            nonlocal created_embeds
            
            full_match = match.group(0)
            language = (match.group(1) or '').strip()
            filename = match.group(2).strip() if match.group(2) else None
            code_content = match.group(3)
            
            # FIX: If language/filename not in fence line, check first content line
            # LLMs sometimes put "python:backend/main.py" in content instead of fence line
            # This handles code blocks like:
            # ```
            # python:backend/main.py
            # from fastapi import FastAPI
            # ```
            if (not language or not filename) and code_content:
                lines = code_content.split('\n')
                if lines:
                    first_line = lines[0].strip()
                    # Check if first line matches language:filename pattern
                    if ':' in first_line and not first_line.startswith('#'):
                        lang_file_pattern = r'^([a-zA-Z0-9_+\-#.]+):([^\s:]+)$'
                        lang_file_match = re.match(lang_file_pattern, first_line)
                        if lang_file_match:
                            potential_lang = lang_file_match.group(1)
                            potential_filename = lang_file_match.group(2)
                            # Use extracted values if we don't already have them
                            if not language:
                                language = potential_lang
                                logger.debug(f"{log_prefix} Extracted language from first content line: {language}")
                            if not filename:
                                filename = potential_filename
                                logger.debug(f"{log_prefix} Extracted filename from first content line: {filename}")
                            # Remove the first line from code content since it's metadata
                            code_content = '\n'.join(lines[1:])
                            logger.info(f"{log_prefix} Removed language:filename line from code content")
            
            # Skip JSON blocks that are already embed references
            if language.lower() in ('json', 'json_embed'):
                try:
                    import json as json_lib
                    json_data = json_lib.loads(code_content.strip())
                    if 'embed_id' in json_data or 'embed_ids' in json_data:
                        logger.debug(f"{log_prefix} Skipping existing embed reference JSON block")
                        return full_match  # Keep as-is
                except (json.JSONDecodeError, ValueError):
                    pass  # Not valid JSON, treat as code block
            
            # Generate embed ID
            embed_id = str(uuid.uuid4())
            
            # Create embed content structure
            embed_content = {
                "type": "code",
                "language": language,
                "code": code_content,
                "filename": filename,
                "status": "finished",
                "line_count": code_content.count('\n') + 1 if code_content else 0
            }
            
            # Encode to TOON format
            toon_content = encode(embed_content)
            
            # Create embed data for client storage
            # NOTE: Hashed IDs (hashed_chat_id, hashed_message_id) are computed by the 
            # websocket handler when sending the embed to the client, not here
            embed_data = {
                "embed_id": embed_id,
                "type": "code",
                "content": toon_content,  # TOON-encoded string (cleartext for client to encrypt)
                "status": "finished",
                "language": language,
                "filename": filename,
                "line_count": embed_content["line_count"]
            }
            created_embeds.append(embed_data)
            
            logger.info(f"{log_prefix} Created code embed {embed_id} from user message (language: {language or 'none'}, {embed_content['line_count']} lines)")
            
            # Return embed reference JSON block to replace the code block
            embed_reference = json.dumps({
                "type": "code",
                "embed_id": embed_id
            })
            return f"```json\n{embed_reference}\n```"
        
        try:
            # Replace all code blocks with embed references
            modified_content = re.sub(code_block_pattern, replace_code_block, content)
            
            if created_embeds:
                logger.info(f"{log_prefix} Extracted {len(created_embeds)} code blocks from user message and created embeds")
            
            return modified_content, created_embeds
            
        except Exception as e:
            logger.error(f"{log_prefix} Error extracting code blocks from user message: {e}", exc_info=True)
            return content, []  # Return original content on error

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
        # Embed references now include optional URL field as fallback for LLM inference
        # Format: {"type": "...", "embed_id": "...", "url": "..."} (url is optional but recommended)
        embed_refs = []
        for match in re.finditer(json_block_pattern, content):
            json_content = match.group(1).strip()
            try:
                embed_ref = json_lib.loads(json_content)
                if isinstance(embed_ref, dict):
                    embed_type = embed_ref.get("type")
                    embed_id = embed_ref.get("embed_id")
                    # Extract URL if present - used as fallback when embed is not in cache
                    embed_url = embed_ref.get("url")
                    if embed_type and embed_id:
                        embed_refs.append({
                            "match": match,
                            "embed_id": embed_id,
                            "embed_type": embed_type,
                            "embed_url": embed_url,  # May be None for legacy references
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
            embed_url = embed_ref_info.get("embed_url")  # May be None for legacy references
            
            # Add content before this match
            resolved_parts.append(content[last_end:match.start()])
            
            # Load embed from cache (returns TOON string, not decoded)
            toon_content = await self._get_cached_embed_toon(embed_id, user_vault_key_id, log_prefix)
            
            if not toon_content:
                # CRITICAL: If embed not found in cache, try to use URL as fallback
                # This ensures LLM has at least the URL to work with even if full embed content is missing
                # This can happen due to: cache expiration (24h TTL), encryption errors, or caching failures
                if embed_url:
                    # URL available - create a minimal but useful fallback for LLM
                    # Format as descriptive text so LLM understands what it is
                    fallback_text = f"[{embed_type.upper()} EMBED - URL: {embed_url}]"
                    logger.warning(
                        f"{log_prefix} Embed {embed_id} not found in cache during resolution. "
                        f"Using URL fallback for LLM inference: {embed_url}"
                    )
                    resolved_parts.append(fallback_text)
                else:
                    # No URL available - keep original reference as last resort
                    logger.warning(
                        f"{log_prefix} Embed {embed_id} not found in cache during resolution. "
                        f"No URL fallback available. This may indicate embeds expired from cache (24h TTL) "
                        f"or were not cached properly. Keeping embed reference in message content."
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
        log_prefix: str = "",
        request_metadata: Optional[Dict[str, Any]] = None
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
            request_metadata: Optional metadata from the original request (query, url, provider, etc.)
                             This preserves input parameters in the embed content

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

            # Retrieve original placeholder metadata (query, provider, url, etc.)
            # This ensures we preserve the original metadata when updating the embed
            # Priority: request_metadata (passed in) > original_content (from cache)
            original_content = await self._get_cached_embed(embed_id, user_vault_key_id, log_prefix)
            original_metadata = {}
            
            # First, use request_metadata if provided (most reliable source)
            if request_metadata:
                # Copy all metadata except internal fields
                for key, value in request_metadata.items():
                    if key not in ['request_id']:  # Skip internal tracking fields
                        original_metadata[key] = value
                logger.debug(
                    f"{log_prefix} Using request_metadata for original_metadata: {list(original_metadata.keys())}"
                )
            
            # Fallback to original_content from cache if request_metadata not provided
            if not original_metadata and original_content:
                # Extract metadata fields that should be preserved
                # The decoded TOON content is merged into embed_data, so check both places
                logger.debug(
                    f"{log_prefix} Retrieved original_content from cache. "
                    f"Keys: {list(original_content.keys())}, "
                    f"Has 'query': {'query' in original_content}, "
                    f"Has 'provider': {'provider' in original_content}, "
                    f"Has 'url': {'url' in original_content}, "
                    f"Has 'app_id': {'app_id' in original_content}, "
                    f"Has 'skill_id': {'skill_id' in original_content}"
                )
                
                # Extract common metadata fields that should be preserved
                # Include all common input parameters (query, url, provider, languages, etc.)
                for key in ['query', 'provider', 'url', 'languages', 'input_data', 'count', 'country', 'search_lang', 'safesearch']:
                    if key in original_content:
                        original_metadata[key] = original_content[key]
                        logger.debug(f"{log_prefix} Found metadata key '{key}': {original_metadata[key]}")
                    else:
                        logger.debug(f"{log_prefix} Metadata key '{key}' not found in original_content")
                
                # CRITICAL: Log detailed metadata extraction for debugging
                logger.info(
                    f"{log_prefix} Preserving original metadata from cache: {list(original_metadata.keys())} "
                    f"(query={original_metadata.get('query', 'NOT FOUND')}, "
                    f"url={original_metadata.get('url', 'NOT FOUND')}, "
                    f"provider={original_metadata.get('provider', 'NOT FOUND')})"
                )
            elif not original_metadata:
                logger.warning(f"{log_prefix} Could not retrieve original embed metadata for {embed_id} and no request_metadata provided")

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

                    # DEBUG: Log the result BEFORE flattening to see if thumbnail/meta_url exist
                    logger.info(
                        f"{log_prefix} [EMBED_DEBUG] Child embed {child_embed_id} - RAW result keys: {list(result.keys())}, "
                        f"has_thumbnail={'thumbnail' in result}, "
                        f"has_meta_url={'meta_url' in result}, "
                        f"thumbnail={result.get('thumbnail')}, "
                        f"meta_url={result.get('meta_url')}"
                    )

                    # Convert result to TOON format (PLAINTEXT)
                    flattened_result = _flatten_for_toon_tabular(result)
                    
                    # DEBUG: Log the result AFTER flattening to see if thumbnail_original/meta_url_favicon exist
                    logger.info(
                        f"{log_prefix} [EMBED_DEBUG] Child embed {child_embed_id} - FLATTENED result keys: {list(flattened_result.keys())}, "
                        f"has_thumbnail_original={'thumbnail_original' in flattened_result}, "
                        f"has_meta_url_favicon={'meta_url_favicon' in flattened_result}, "
                        f"thumbnail_original={flattened_result.get('thumbnail_original', 'NOT_FOUND')[:80] if flattened_result.get('thumbnail_original') else 'NOT_FOUND'}..., "
                        f"meta_url_favicon={flattened_result.get('meta_url_favicon', 'NOT_FOUND')[:80] if flattened_result.get('meta_url_favicon') else 'NOT_FOUND'}..."
                    )
                    
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
                        "is_private": False,
                        "is_shared": False,
                        "parent_embed_id": embed_id,  # CRITICAL: Set parent_embed_id for key inheritance
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
                    # CRITICAL: Pass parent_embed_id so child embeds can use parent's key (key inheritance - Option A)
                    # CRITICAL: Pass check_cache_status=False because child embeds are already cached with status="finished"
                    # above. Without this, the duplicate prevention check would skip sending these newly created embeds!
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
                        parent_embed_id=embed_id,  # Set parent_embed_id so frontend can use parent key
                        log_prefix=log_prefix,
                        check_cache_status=False  # Skip cache check - we just created this embed
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
                    "is_private": False,
                    "is_shared": False,
                    "embed_ids": child_embed_ids,  # JSON array
                    "encrypted_content": encrypted_parent_content,
                    "text_length_chars": parent_text_length_chars,
                    "created_at": updated_at,
                    "updated_at": updated_at
                }

                # CRITICAL FIX: Send BEFORE updating cache to avoid duplicate prevention blocking
                # The send_embed_data_to_client with check_cache_status=True will check if cache 
                # already has status=finished and skip. We need to send first, then update cache.
                # This ensures the client receives the parent embed data with embed_ids (child embeds)
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
                    log_prefix=log_prefix,
                    check_cache_status=True  # Enable deduplication check (will pass since cache still has "processing")
                )

                # Update cache AFTER sending (overwrites placeholder with finished status)
                await self._cache_embed(embed_id, updated_embed_data, chat_id, user_id_hash)

                logger.info(f"{log_prefix} Updated embed {embed_id} with {len(child_embed_ids)} child embeds")

                return {
                    "embed_id": embed_id,
                    "child_embed_ids": child_embed_ids,
                    "status": "finished"
                }

            else:
                # Single result - update embed with result content
                # CRITICAL: Wrap results with app_id and skill_id metadata for consistency with create_embeds_from_skill_results
                # This ensures the frontend can identify which skill was executed and render the appropriate preview component
                # Structure matches composite results pattern: app_id, skill_id, results array
                # Also include original_metadata (query, url, provider, etc.) to preserve input parameters
                flattened_results = [_flatten_for_toon_tabular(result) for result in results]
                
                # Wrap with app_id and skill_id metadata (same structure as create_embeds_from_skill_results)
                # Include original_metadata to preserve input parameters (url for videos, query for search, etc.)
                content_with_metadata = {
                    "app_id": app_id,
                    "skill_id": skill_id,
                    "results": flattened_results,
                    "result_count": len(results),
                    "status": "finished",
                    **original_metadata  # Preserve query, url, provider, languages, etc. from placeholder
                }
                
                # Log final content to verify metadata is included
                logger.info(
                    f"{log_prefix} Single result embed content includes: "
                    f"query={content_with_metadata.get('query', 'MISSING')}, "
                    f"url={content_with_metadata.get('url', 'MISSING')}, "
                    f"provider={content_with_metadata.get('provider', 'MISSING')}, "
                    f"result_count={content_with_metadata.get('result_count')}"
                )
                
                content_toon = encode(_flatten_for_toon_tabular(content_with_metadata))

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
                    "is_private": False,
                    "is_shared": False,
                    "embed_ids": None,  # No child embeds
                    "encrypted_content": encrypted_content,
                    "text_length_chars": single_text_length_chars,
                    "created_at": updated_at,
                    "updated_at": updated_at
                }

                # CRITICAL FIX: Send BEFORE updating cache to avoid duplicate prevention blocking
                # This ensures the client receives the embed data before cache is marked as finished
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

                # Update cache AFTER sending (overwrites placeholder with finished status)
                await self._cache_embed(embed_id, updated_embed_data, chat_id, user_id_hash)

                logger.info(f"{log_prefix} Updated single embed {embed_id}")

                return {
                    "embed_id": embed_id,
                    "child_embed_ids": [],
                    "status": "finished"
                }

        except Exception as e:
            logger.error(f"{log_prefix} Error updating embed {embed_id} with results: {e}", exc_info=True)
            return None

    async def update_embed_status_to_error(
        self,
        embed_id: str,
        app_id: str,
        skill_id: str,
        error_message: str,
        chat_id: str,
        message_id: str,
        user_id: str,
        user_id_hash: str,
        user_vault_key_id: str,
        task_id: Optional[str] = None,
        log_prefix: str = ""
    ) -> Optional[Dict[str, Any]]:
        """
        Update an existing "processing" embed to "error" status when skill execution fails.
        
        Args:
            embed_id: The embed_id to update (from placeholder)
            app_id: The app ID that owns the skill
            skill_id: The skill ID that was executed
            error_message: Error message to include in embed content
            chat_id: Chat ID where the embed is created
            message_id: Message ID that references the embed
            user_id: User ID (UUID)
            user_id_hash: Hashed user ID
            user_vault_key_id: User's vault key ID for encryption
            task_id: Optional task ID for tracking
            log_prefix: Logging prefix for this operation
            
        Returns:
            Dictionary with:
            - embed_id: The embed_id (same as input)
            - status: "error"
            None if update fails
        """
        try:
            import hashlib
            from datetime import datetime
            from toon_format import encode
            
            # Hash sensitive IDs for privacy protection
            hashed_chat_id = hashlib.sha256(chat_id.encode()).hexdigest()
            hashed_message_id = hashlib.sha256(message_id.encode()).hexdigest()
            hashed_task_id = hashlib.sha256(task_id.encode()).hexdigest() if task_id else None

            # Retrieve original placeholder metadata (query, provider, etc.)
            # This ensures we preserve the original metadata when updating the embed
            original_content = await self._get_cached_embed(embed_id, user_vault_key_id, log_prefix)
            original_metadata = {}
            if original_content:
                # Extract metadata fields that should be preserved
                for key in ['query', 'provider', 'url', 'input_data']:
                    if key in original_content:
                        original_metadata[key] = original_content[key]
                        logger.debug(f"{log_prefix} Found metadata key '{key}': {original_metadata[key]}")
            
            # Create error content with metadata and error message
            error_content = {
                "app_id": app_id,
                "skill_id": skill_id,
                "status": "error",
                "error": error_message,
                "result_count": 0,
                "embed_ids": None,  # No child embeds for error case
                **original_metadata  # Preserve query, provider, etc. from placeholder
            }
            
            # Convert to TOON (PLAINTEXT)
            flattened_error = _flatten_for_toon_tabular(error_content)
            error_content_toon = encode(flattened_error)
            
            # Calculate text length
            error_text_length_chars = len(error_content_toon)
            
            # Encrypt with vault key
            encrypted_content, _ = await self.encryption_service.encrypt_with_user_key(
                error_content_toon,
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
                "status": "error",
                "hashed_user_id": user_id_hash,
                "is_private": False,
                "is_shared": False,
                "embed_ids": None,  # No child embeds
                "encrypted_content": encrypted_content,
                "text_length_chars": error_text_length_chars,
                "created_at": updated_at,
                "updated_at": updated_at
            }
            
            # Update cache (overwrites placeholder)
            await self._cache_embed(embed_id, updated_embed_data, chat_id, user_id_hash)
            
            # SEND PLAINTEXT TOON TO CLIENT via WebSocket
            await self.send_embed_data_to_client(
                embed_id=embed_id,
                embed_type="app_skill_use",
                content_toon=error_content_toon,  # PLAINTEXT TOON
                chat_id=chat_id,
                message_id=message_id,
                user_id=user_id,
                user_id_hash=user_id_hash,
                status="error",
                task_id=task_id,
                text_length_chars=error_text_length_chars,
                created_at=updated_at,
                updated_at=updated_at,
                log_prefix=log_prefix
            )
            
            logger.info(f"{log_prefix} Updated embed {embed_id} to error status: {error_message}")
            
            return {
                "embed_id": embed_id,
                "child_embed_ids": [],
                "status": "error"
            }
            
        except Exception as e:
            logger.error(f"{log_prefix} Error updating embed {embed_id} to error status: {e}", exc_info=True)
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
        is_private: bool = False,
        is_shared: bool = False,
        created_at: Optional[int] = None,
        updated_at: Optional[int] = None,
        log_prefix: str = "",
        check_cache_status: bool = True  # New parameter to optionally skip cache check
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
            is_private: Whether embed is private (not shared)
            is_shared: Whether embed has been shared (share link generated)
            created_at: Unix timestamp
            updated_at: Unix timestamp
            log_prefix: Logging prefix

        Returns:
            True if event was published successfully, False otherwise
        """
        try:
            # CRITICAL: Deduplication check - prevent sending duplicate "finished" events
            # If check_cache_status is True, verify the embed isn't already finalized
            if check_cache_status and status == "finished":
                try:
                    # Get raw cached embed JSON to check status (status is metadata, not encrypted)
                    cache_key = f"embed:{embed_id}"
                    client = await self.cache_service.client
                    if client:
                        embed_json = await client.get(cache_key)
                        if embed_json:
                            import json as json_lib
                            cached_embed_data = json_lib.loads(embed_json)
                            current_status = cached_embed_data.get("status", "processing")
                            if current_status == "finished":
                                logger.warning(
                                    f"{log_prefix} [EMBED_EVENT] ⚠️ DUPLICATE PREVENTION: Skipping send_embed_data for already-finalized embed {embed_id} "
                                    f"(current_status={current_status}, attempted_status={status}). "
                                    f"This indicates update_code_embed_content or update_embed_with_results was called multiple times."
                                )
                                return False  # Skip sending duplicate event
                except Exception as e:
                    # If cache check fails, log but continue (don't block the send)
                    logger.debug(f"{log_prefix} [EMBED_EVENT] Could not check cache status for deduplication: {e}, proceeding with send")
            
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
                    "is_private": is_private,
                    "is_shared": is_shared,
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
                logger.info(
                    f"{log_prefix} [EMBED_EVENT] Published send_embed_data event for embed {embed_id} "
                    f"(status={status}, type={embed_type}, chat_id={chat_id}, message_id={message_id})"
                )
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
        log_prefix: str = "",
        request_metadata: Optional[Dict[str, Any]] = None
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
                
                # CRITICAL: Generate parent_embed_id FIRST so child embeds can reference it
                # This enables key inheritance: child embeds use parent's encryption key
                parent_embed_id = str(uuid.uuid4())
                
                for result in results:
                    # Generate embed_id for child
                    child_embed_id = str(uuid.uuid4())
                    
                    # Convert result to TOON format
                    flattened_result = _flatten_for_toon_tabular(result)
                    content_toon = encode(flattened_result)
                    
                    # Calculate text length for child embed
                    text_length_chars = len(content_toon)
                    created_at = int(datetime.now().timestamp())
                    
                    # Create child embed entry
                    # CRITICAL: Include parent_embed_id for key inheritance
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
                        "is_private": False,
                        "is_shared": False,
                        "parent_embed_id": parent_embed_id,  # CRITICAL: Set parent for key inheritance
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
                    
                    # CRITICAL: Send child embed to client via WebSocket for client-side encryption and storage
                    # Without this, child embeds only exist in server cache and won't be stored in Directus
                    # CRITICAL: Pass check_cache_status=False because child embeds are already cached with status="finished"
                    # above. Without this, the duplicate prevention check would skip sending these newly created embeds!
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
                        parent_embed_id=parent_embed_id,  # Set parent_embed_id so frontend can use parent key
                        log_prefix=log_prefix,
                        check_cache_status=False  # Skip cache check - we just created this embed
                    )
                    
                    child_embed_ids.append(child_embed_id)
                    logger.debug(f"{log_prefix} Created child embed {child_embed_id} (type: {child_type}, parent: {parent_embed_id})")
                
                # Create parent app_skill_use embed
                # NOTE: parent_embed_id was already generated above (before child embeds)
                
                # Parent embed content: metadata about the skill execution
                # Include request metadata (query, etc.) if provided for proper frontend rendering
                parent_content = {
                    "app_id": app_id,
                    "skill_id": skill_id,
                    "result_count": len(results),
                    "embed_ids": child_embed_ids,
                    "status": "finished"
                }
                
                # Add request metadata (query, provider, etc.) if available
                if request_metadata:
                    if "query" in request_metadata:
                        parent_content["query"] = request_metadata["query"]
                    if "provider" in request_metadata:
                        parent_content["provider"] = request_metadata["provider"]
                    # Add other metadata fields as needed
                    for key in ["country", "search_lang", "safesearch"]:
                        if key in request_metadata:
                            parent_content[key] = request_metadata[key]
                
                # Convert to TOON
                flattened_parent = _flatten_for_toon_tabular(parent_content)
                parent_content_toon = encode(flattened_parent)
                
                # Calculate text length for parent embed
                parent_text_length_chars = len(parent_content_toon)
                parent_created_at = int(datetime.now().timestamp())
                
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
                    "is_private": False,
                    "is_shared": False,
                    "embed_ids": child_embed_ids,  # JSON array
                    "encrypted_content": encrypted_parent_content,
                    "text_length_chars": parent_text_length_chars,
                    "created_at": parent_created_at,
                    "updated_at": parent_created_at
                }
                
                # CRITICAL: Send parent embed to client BEFORE caching to avoid duplicate prevention blocking
                # The cache will have status="finished" after caching, so send_embed_data_to_client's
                # default cache check would skip sending if we cached first.
                await self.send_embed_data_to_client(
                    embed_id=parent_embed_id,
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
                    created_at=parent_created_at,
                    updated_at=parent_created_at,
                    log_prefix=log_prefix
                )
                
                # Cache parent embed AFTER sending
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
                    "result_count": len(results),
                    "status": "finished"
                }
                
                # Add request metadata if available
                if request_metadata:
                    for key in ["query", "provider", "url", "languages", "country", "search_lang", "safesearch"]:
                        if key in request_metadata:
                            content_with_metadata[key] = request_metadata[key]
                
                content_toon = encode(_flatten_for_toon_tabular(content_with_metadata))
                
                # Calculate text length for embed
                single_text_length_chars = len(content_toon)
                single_created_at = int(datetime.now().timestamp())
                
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
                    "is_private": False,
                    "is_shared": False,
                    "embed_ids": None,  # No child embeds
                    "encrypted_content": encrypted_content,
                    "text_length_chars": single_text_length_chars,
                    "created_at": single_created_at,
                    "updated_at": single_created_at
                }
                
                # CRITICAL: Send embed to client BEFORE caching to avoid duplicate prevention blocking
                # The cache will have status="finished" after caching, so send_embed_data_to_client's
                # default cache check would skip sending if we cached first.
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
                    created_at=single_created_at,
                    updated_at=single_created_at,
                    log_prefix=log_prefix
                )
                
                # Cache embed AFTER sending
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
