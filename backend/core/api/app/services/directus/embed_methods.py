"""
Directus methods for embed operations.
Handles CRUD operations for embeds collection in Directus.
"""
import logging
from typing import List, Dict, Any, Optional, TYPE_CHECKING
import hashlib

if TYPE_CHECKING:
    from backend.core.api.app.services.directus.directus import DirectusService

logger = logging.getLogger(__name__)

# Fields for embed operations
EMBED_ALL_FIELDS = (
    "id,"
    "embed_id,"
    "hashed_chat_id,"
    "hashed_message_id,"
    "hashed_task_id,"
    "encrypted_type,"
    "status,"
    "hashed_user_id,"
    # encryption_key_embed moved to embed_keys collection for wrapped key architecture
    "is_private,"
    "is_shared,"
    "shared_with_users,"
    "embed_ids,"
    "encrypted_content,"
    "encrypted_text_preview,"
    "parent_embed_id,"
    "version_number,"
    "encrypted_diff,"
    "file_path,"
    "content_hash,"
    "encryption_mode,"
    "vault_key_id,"
    "created_at,"
    "updated_at"
)

# Fields for embed_keys collection (wrapped key architecture)
EMBED_KEY_ALL_FIELDS = (
    "id,"
    "hashed_embed_id,"
    "key_type,"
    "hashed_chat_id,"
    "encrypted_embed_key,"
    "hashed_user_id,"
    "created_at"
)

EMBED_BASIC_FIELDS = (
    "id,"
    "embed_id,"
    "hashed_chat_id,"
    "status,"
    "hashed_user_id,"
    "created_at"
)


class EmbedMethods:
    """Methods for interacting with embeds collection in Directus."""
    
    def __init__(self, directus_service_instance: 'DirectusService'):
        self.directus_service = directus_service_instance
    
    async def get_embed_by_id(self, embed_id: str) -> Optional[Dict[str, Any]]:
        """
        Fetch an embed by its embed_id.
        
        Args:
            embed_id: The unique embed identifier
            
        Returns:
            Embed dictionary if found, None otherwise
        """
        logger.debug(f"Fetching embed with embed_id: {embed_id}")
        params = {
            'filter[embed_id][_eq]': embed_id,
            'fields': EMBED_ALL_FIELDS,
            'limit': 1
        }
        try:
            response = await self.directus_service.get_items('embeds', params=params, no_cache=True)
            if response and isinstance(response, list) and len(response) > 0:
                logger.debug(f"Successfully fetched embed {embed_id}")
                return response[0]
            else:
                logger.debug(f"Embed not found for embed_id: {embed_id}")
                return None
        except Exception as e:
            logger.error(f"Error fetching embed {embed_id}: {e}", exc_info=True)
            return None
    
    async def get_embeds_by_hashed_task_id(self, hashed_task_id: str) -> List[Dict[str, Any]]:
        """
        Fetch embeds by hashed_task_id (for long-running task updates).
        
        Args:
            hashed_task_id: SHA256 hash of the task_id
            
        Returns:
            List of embeds matching the hashed_task_id
        """
        logger.debug(f"Fetching embeds with hashed_task_id: {hashed_task_id[:16]}...")
        params = {
            'filter[hashed_task_id][_eq]': hashed_task_id,
            'fields': EMBED_ALL_FIELDS
        }
        try:
            response = await self.directus_service.get_items('embeds', params=params, no_cache=True)
            if response and isinstance(response, list):
                logger.debug(f"Found {len(response)} embed(s) for hashed_task_id")
                return response
            else:
                return []
        except Exception as e:
            logger.error(f"Error fetching embeds by hashed_task_id: {e}", exc_info=True)
            return []
    
    async def get_embeds_by_hashed_chat_id(self, hashed_chat_id: str) -> List[Dict[str, Any]]:
        """
        Fetch all embeds for a chat by hashed_chat_id.
        
        Args:
            hashed_chat_id: SHA256 hash of the chat_id
            
        Returns:
            List of embeds for the chat
        """
        logger.debug(f"Fetching embeds for hashed_chat_id: {hashed_chat_id[:16]}...")
        params = {
            'filter[hashed_chat_id][_eq]': hashed_chat_id,
            'fields': EMBED_ALL_FIELDS,
            'sort': '-created_at'
        }
        try:
            response = await self.directus_service.get_items('embeds', params=params, no_cache=True)
            if response and isinstance(response, list):
                logger.debug(f"Found {len(response)} embed(s) for chat")
                return response
            else:
                return []
        except Exception as e:
            logger.error(f"Error fetching embeds by hashed_chat_id: {e}", exc_info=True)
            return []

    async def get_embeds_by_hashed_chat_ids(self, hashed_chat_ids: List[str]) -> List[Dict[str, Any]]:
        """
        Fetch all embeds for multiple chats by hashed_chat_ids.
        
        Args:
            hashed_chat_ids: List of SHA256 hashes of chat_ids
            
        Returns:
            List of embeds for the chats
        """
        if not hashed_chat_ids:
            return []
            
        logger.debug(f"Fetching embeds for {len(hashed_chat_ids)} hashed_chat_ids...")
        params = {
            'filter[hashed_chat_id][_in]': hashed_chat_ids,
            'fields': EMBED_ALL_FIELDS,
            'sort': '-created_at',
            'limit': -1
        }
        try:
            response = await self.directus_service.get_items('embeds', params=params, no_cache=True)
            if response and isinstance(response, list):
                logger.debug(f"Found {len(response)} embed(s) for {len(hashed_chat_ids)} chats")
                return response
            else:
                return []
        except Exception as e:
            logger.error(f"Error fetching embeds by hashed_chat_ids: {e}", exc_info=True)
            return []
    
    async def create_embed(self, embed_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Create a new embed in Directus.
        
        Args:
            embed_data: Dictionary containing embed fields (embed_id, hashed_chat_id, etc.)
            
        Returns:
            Created embed dictionary if successful, None otherwise
        """
        logger.debug(f"Creating embed with embed_id: {embed_data.get('embed_id', 'unknown')}")
        try:
            # Use create_item from api_methods
            from backend.core.api.app.services.directus.api_methods import create_item
            # FIX: create_item returns a tuple (success: bool, data: dict)
            # Must unpack the tuple to check success and get the actual data
            success, created_embed = await create_item(
                self.directus_service,
                'embeds',
                embed_data
            )
            if success and created_embed:
                logger.info(f"Successfully created embed {embed_data.get('embed_id', 'unknown')}")
                
                # Update Global Stats (Incremental)
                try:
                    await self.directus_service.cache.increment_stat("embeds_created")
                except Exception as stats_err:
                    logger.error(f"Error updating global stats after embed creation: {stats_err}")
                    
                return created_embed
            else:
                logger.error(f"Failed to create embed {embed_data.get('embed_id', 'unknown')}: {created_embed}")
                return None
        except Exception as e:
            logger.error(f"Error creating embed: {e}", exc_info=True)
            return None
    
    async def update_embed(self, embed_id: str, update_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Update an existing embed in Directus.
        
        Args:
            embed_id: The embed_id of the embed to update
            update_data: Dictionary containing fields to update
            
        Returns:
            Updated embed dictionary if successful, None otherwise
        """
        logger.debug(f"Updating embed with embed_id: {embed_id}")
        try:
            # First, get the Directus ID
            embed = await self.get_embed_by_id(embed_id)
            if not embed:
                logger.error(f"Embed not found for update: {embed_id}")
                return None
            
            directus_id = embed.get('id')
            if not directus_id:
                logger.error(f"No Directus ID found for embed: {embed_id}")
                return None
            
            # Update the embed - ensure fresh auth token
            url = f"{self.directus_service.base_url}/items/embeds/{directus_id}"
            token = await self.directus_service.ensure_auth_token()
            if not token:
                logger.error(f"Failed to get auth token for embed update: {embed_id}")
                return None
            headers = {"Authorization": f"Bearer {token}"}
            
            response = await self.directus_service._client.patch(url, json=update_data, headers=headers)
            response.raise_for_status()
            updated_embed = response.json().get('data')
            logger.info(f"Successfully updated embed {embed_id}")
            return updated_embed
        except Exception as e:
            logger.error(f"Error updating embed {embed_id}: {e}", exc_info=True)
            return None
    
    async def get_embed_by_content_hash(self, content_hash: str, hashed_user_id: str) -> Optional[Dict[str, Any]]:
        """
        Find an embed by content_hash (for duplicate detection).
        
        Args:
            content_hash: SHA256 hash of the embed content
            hashed_user_id: Hashed user ID to filter by
            
        Returns:
            Existing embed if found, None otherwise
        """
        logger.debug(f"Checking for duplicate embed with content_hash: {content_hash[:16]}...")
        params = {
            'filter[content_hash][_eq]': content_hash,
            'filter[hashed_user_id][_eq]': hashed_user_id,
            'fields': EMBED_ALL_FIELDS,
            'limit': 1,
            'sort': '-created_at'  # Get most recent version
        }
        try:
            response = await self.directus_service.get_items('embeds', params=params, no_cache=True)
            if response and isinstance(response, list) and len(response) > 0:
                logger.debug("Found duplicate embed with content_hash")
                return response[0]
            else:
                return None
        except Exception as e:
            logger.error(f"Error checking for duplicate embed: {e}", exc_info=True)
            return None
    
    async def get_embed_keys_by_hashed_chat_id(self, hashed_chat_id: str, include_master_keys: bool = True) -> List[Dict[str, Any]]:
        """
        Fetch all embed_keys entries for a chat by hashed_chat_id.
        
        This returns wrapped embed keys that can be unwrapped to access embed content:
        - key_type='chat': AES(embed_key, chat_key) for shared chat access
        - key_type='master': AES(embed_key, master_key) for owner cross-chat access (if include_master_keys=True)
        
        The wrapped key architecture enables offline-first chat sharing:
        - Each embed has multiple key wrappers stored in embed_keys collection
        - key_type='master': AES(embed_key, master_key) for owner cross-chat access
        - key_type='chat': AES(embed_key, chat_key) for shared chat access
        
        Args:
            hashed_chat_id: SHA256 hash of the chat_id
            include_master_keys: If True (default), also fetch master key entries for the same embeds
            
        Returns:
            List of embed_keys entries for the chat (both chat and master key entries)
        """
        logger.debug(f"Fetching embed_keys for hashed_chat_id: {hashed_chat_id[:16]}... (include_master_keys={include_master_keys})")
        
        all_embed_keys = []
        
        # First, fetch chat key entries (these have hashed_chat_id set)
        chat_key_params = {
            'filter[hashed_chat_id][_eq]': hashed_chat_id,
            'filter[key_type][_eq]': 'chat',
            'fields': EMBED_KEY_ALL_FIELDS,
            'limit': -1
        }
        try:
            chat_key_response = await self.directus_service.get_items('embed_keys', params=chat_key_params, no_cache=True)
            if chat_key_response and isinstance(chat_key_response, list):
                logger.debug(f"Found {len(chat_key_response)} chat key entries for chat")
                all_embed_keys.extend(chat_key_response)
                
                # If we should include master keys, fetch them using the hashed_embed_ids from chat keys
                if include_master_keys and chat_key_response:
                    # Get unique hashed_embed_ids from chat keys
                    hashed_embed_ids = list(set(k.get('hashed_embed_id') for k in chat_key_response if k.get('hashed_embed_id')))
                    
                    if hashed_embed_ids:
                        # Fetch master key entries for these embeds
                        # Use _in filter to get all in one query
                        master_key_params = {
                            'filter[hashed_embed_id][_in]': ','.join(hashed_embed_ids),
                            'filter[key_type][_eq]': 'master',
                            'fields': EMBED_KEY_ALL_FIELDS,
                            'limit': -1
                        }
                        try:
                            master_key_response = await self.directus_service.get_items('embed_keys', params=master_key_params, no_cache=True)
                            if master_key_response and isinstance(master_key_response, list):
                                logger.debug(f"Found {len(master_key_response)} master key entries for chat embeds")
                                all_embed_keys.extend(master_key_response)
                        except Exception as e:
                            logger.warning(f"Error fetching master key entries: {e}")
            
            logger.info(f"Total embed_keys for chat: {len(all_embed_keys)} (chat + master)")
            return all_embed_keys
        except Exception as e:
            logger.error(f"Error fetching embed_keys by hashed_chat_id: {e}", exc_info=True)
            return []

    async def get_embed_keys_by_hashed_chat_ids_batch(
        self, 
        hashed_chat_ids: List[str], 
        include_master_keys: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Batch fetch all embed_keys entries for multiple chats by their hashed_chat_ids.
        
        This is an optimized version of get_embed_keys_by_hashed_chat_id that fetches
        embed_keys for multiple chats in just 2 database queries instead of 2 per chat.
        
        Performance: For 20 chats, this reduces queries from 40 to 2 (95% reduction).
        
        Args:
            hashed_chat_ids: List of SHA256 hashes of chat_ids
            include_master_keys: If True (default), also fetch master key entries for the same embeds
            
        Returns:
            List of all embed_keys entries for all chats (both chat and master key entries)
        """
        if not hashed_chat_ids:
            return []
            
        logger.debug(f"Batch fetching embed_keys for {len(hashed_chat_ids)} chats (include_master_keys={include_master_keys})")
        
        all_embed_keys = []
        
        # First, fetch ALL chat key entries for all chats in one query using _in filter
        # Directus supports comma-separated values for _in filter
        chat_key_params = {
            'filter[hashed_chat_id][_in]': ','.join(hashed_chat_ids),
            'filter[key_type][_eq]': 'chat',
            'fields': EMBED_KEY_ALL_FIELDS,
            'limit': -1,
            # Add timestamp to prevent caching issues during sync
            '_ts': str(int(__import__('time').time() * 1000000000))
        }
        
        try:
            chat_key_response = await self.directus_service.get_items('embed_keys', params=chat_key_params, no_cache=True)
            if chat_key_response and isinstance(chat_key_response, list):
                logger.debug(f"Batch found {len(chat_key_response)} chat key entries for {len(hashed_chat_ids)} chats")
                all_embed_keys.extend(chat_key_response)
                
                # If we should include master keys, fetch them using the hashed_embed_ids from chat keys
                if include_master_keys and chat_key_response:
                    # Get unique hashed_embed_ids from all chat keys
                    hashed_embed_ids = list(set(
                        k.get('hashed_embed_id') 
                        for k in chat_key_response 
                        if k.get('hashed_embed_id')
                    ))
                    
                    if hashed_embed_ids:
                        # Fetch ALL master key entries for these embeds in one query
                        master_key_params = {
                            'filter[hashed_embed_id][_in]': ','.join(hashed_embed_ids),
                            'filter[key_type][_eq]': 'master',
                            'fields': EMBED_KEY_ALL_FIELDS,
                            'limit': -1,
                            '_ts': str(int(__import__('time').time() * 1000000000))
                        }
                        try:
                            master_key_response = await self.directus_service.get_items('embed_keys', params=master_key_params, no_cache=True)
                            if master_key_response and isinstance(master_key_response, list):
                                logger.debug(f"Batch found {len(master_key_response)} master key entries for {len(hashed_embed_ids)} embeds")
                                all_embed_keys.extend(master_key_response)
                        except Exception as e:
                            logger.warning(f"Error batch fetching master key entries: {e}")
            
            logger.info(f"[BATCH] Total embed_keys for {len(hashed_chat_ids)} chats: {len(all_embed_keys)} (chat + master) - 2 queries instead of {len(hashed_chat_ids) * 2}")
            return all_embed_keys
            
        except Exception as e:
            logger.error(f"Error batch fetching embed_keys by hashed_chat_ids: {e}", exc_info=True)
            return []

    async def get_embed_keys_by_embed_id(self, embed_id: str) -> List[Dict[str, Any]]:
        """
        Fetch all embed_keys entries for an embed by embed_id.
        
        This method hashes the embed_id and queries the embed_keys collection.
        Returns all key types (both 'chat' and 'master') for the embed.
        
        This is used when sharing embeds to retrieve wrapped keys that allow
        recipients to decrypt the embed content.
        
        Args:
            embed_id: The unique embed identifier (UUID string)
            
        Returns:
            List of embed_keys entries for the embed (both chat and master key entries)
        """
        # Hash the embed_id to get hashed_embed_id
        hashed_embed_id = hashlib.sha256(embed_id.encode()).hexdigest()
        logger.debug(f"Fetching embed_keys for embed_id: {embed_id} (hashed: {hashed_embed_id[:16]}...)")
        
        params = {
            'filter[hashed_embed_id][_eq]': hashed_embed_id,
            'fields': EMBED_KEY_ALL_FIELDS,
            'limit': -1  # Get all keys for this embed
        }
        
        try:
            response = await self.directus_service.get_items('embed_keys', params=params, no_cache=True)
            if response and isinstance(response, list):
                logger.debug(f"Found {len(response)} embed_key entries for embed {embed_id}")
                return response
            else:
                logger.debug(f"No embed_keys found for embed_id: {embed_id}")
                return []
        except Exception as e:
            logger.error(f"Error fetching embed_keys by embed_id {embed_id}: {e}", exc_info=True)
            return []

    async def get_embed_keys_by_embed_id_and_type(
        self,
        hashed_embed_id: str,
        key_type: str,
        hashed_chat_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Fetch embed_keys entries matching the exact hashed_embed_id, key_type, and hashed_chat_id.
        
        Used for deduplication - checking if a specific key already exists before creating it.
        This prevents race conditions where multiple handlers might try to store the same key.
        
        Args:
            hashed_embed_id: SHA256 hash of the embed_id (already hashed)
            key_type: Either 'master' or 'chat'
            hashed_chat_id: For chat keys, the SHA256 hash of chat_id. None for master keys.
            
        Returns:
            List of matching embed_keys entries (should be 0 or 1)
        """
        logger.debug(
            f"Checking for existing embed_key: hashed_embed_id={hashed_embed_id[:16]}..., "
            f"key_type={key_type}, hashed_chat_id={hashed_chat_id[:16] if hashed_chat_id else 'null'}..."
        )
        
        # Build filter for exact match
        params = {
            'filter[hashed_embed_id][_eq]': hashed_embed_id,
            'filter[key_type][_eq]': key_type,
            'fields': EMBED_KEY_ALL_FIELDS,
            'limit': 1
        }
        
        # For chat keys, also filter by hashed_chat_id
        # For master keys, hashed_chat_id should be null
        if key_type == 'chat' and hashed_chat_id:
            params['filter[hashed_chat_id][_eq]'] = hashed_chat_id
        elif key_type == 'master':
            params['filter[hashed_chat_id][_null]'] = 'true'
        
        try:
            response = await self.directus_service.get_items('embed_keys', params=params, no_cache=True)
            if response and isinstance(response, list):
                logger.debug(f"Found {len(response)} existing embed_key(s) matching criteria")
                return response
            else:
                return []
        except Exception as e:
            logger.error(f"Error checking for existing embed_key: {e}", exc_info=True)
            return []

    async def create_embed_key(self, embed_key_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Create a new embed_key entry in Directus.
        
        **Performance Note**: This method does NOT check for existing keys before creating.
        The client is responsible for ensuring no duplicate keys are sent. This avoids
        unnecessary database queries and improves performance.

        Used when:
        - Creating a new root embed (creates both master and chat key wrappers)
        - Copying an embed to a new chat (creates new chat key wrapper)

        **NOT used for child embeds**: Child embeds with parent_embed_id automatically inherit
        the parent's encryption key. The client will decrypt the parent's key and use it to
        encrypt the child content. Server stores only the parent's wrapped keys in embed_keys collection.

        Args:
            embed_key_data: Dictionary containing embed_key fields

        Returns:
            Created embed_key dictionary if successful, None otherwise
        """
        hashed_embed_id = embed_key_data.get('hashed_embed_id')
        key_type = embed_key_data.get('key_type')
        
        logger.debug(f"Creating embed_key with hashed_embed_id: {hashed_embed_id[:16] if hashed_embed_id else 'unknown'}..., key_type={key_type}")
        
        try:
            from backend.core.api.app.services.directus.api_methods import create_item
            # FIX: create_item returns a tuple (success: bool, data: dict)
            # Must unpack the tuple to check success and get the actual data
            success, created_key = await create_item(
                self.directus_service,
                'embed_keys',
                embed_key_data
            )
            if success and created_key:
                logger.info(f"Successfully created embed_key for {hashed_embed_id[:16] if hashed_embed_id else 'unknown'}...")
                return created_key
            else:
                logger.error(f"Failed to create embed_key: {created_key}")
                return None
        except Exception as e:
            logger.error(f"Error creating embed_key: {e}", exc_info=True)
            return None

    async def delete_all_embeds_for_chat(
        self,
        hashed_chat_id: str,
        s3_service=None,
        user_id: Optional[str] = None,
    ) -> tuple[bool, list[str]]:
        """
        Deletes ALL embeds for a specific chat from Directus.
        Also deletes associated S3 files (e.g., generated images) if s3_service is provided.

        Deletion policy (per product spec):
        - Private / non-shared embeds are always deleted.
        - Shared embeds are ALSO deleted if they are not referenced by any OTHER chat
          belonging to the same user. If no user_id is supplied the old behaviour
          (shared embeds are kept) is preserved for safety.

        Args:
            hashed_chat_id: SHA256 hash of the chat_id to delete embeds for.
            s3_service:     Optional S3UploadService for deleting associated S3 files.
            user_id:        Optional plaintext user_id — used to find the user's other
                            chats so we can decide whether a shared embed is still needed.

        Returns:
            Tuple of (success: bool, deleted_embed_uuid_ids: list[str]).
            The embed UUID list is needed by the caller to clean up upload_files records
            and update the storage counter.
        """
        logger.info(
            f"Attempting to delete all embeds for hashed_chat_id: {hashed_chat_id[:16]}... from Directus."
        )
        deleted_embed_uuid_ids: list[str] = []
        try:
            # ------------------------------------------------------------------
            # Step 1: Fetch ALL embeds for this chat (private + shared)
            # ------------------------------------------------------------------
            params_all = {
                'filter[hashed_chat_id][_eq]': hashed_chat_id,
                'fields': 'id,embed_id,s3_file_keys,is_private,is_shared',
                'limit': -1,
            }
            all_embeds = await self.directus_service.get_items('embeds', params=params_all, no_cache=True)

            if not all_embeds or not isinstance(all_embeds, list) or len(all_embeds) == 0:
                logger.info(
                    f"No embeds found for hashed_chat_id: {hashed_chat_id[:16]}... (nothing to delete)"
                )
                return True, []

            # Split into private (always delete) and shared (conditional delete)
            private_embeds = [
                e for e in all_embeds
                if e.get('is_private') is True or e.get('is_shared') is False
            ]
            shared_embeds = [
                e for e in all_embeds
                if e.get('is_private') is not True and e.get('is_shared') is True
            ]

            logger.info(
                f"Found {len(private_embeds)} private and {len(shared_embeds)} shared embed(s) "
                f"for hashed_chat_id: {hashed_chat_id[:16]}..."
            )

            # ------------------------------------------------------------------
            # Step 2: Decide which shared embeds to delete.
            # A shared embed is deletable when it is NOT referenced by any other
            # chat of the same user (i.e. its hashed_chat_id only points here).
            # ------------------------------------------------------------------
            shared_embeds_to_delete: list[dict] = []
            shared_embeds_to_keep: list[dict] = []

            if shared_embeds and user_id:
                hashed_user_id = hashlib.sha256(user_id.encode()).hexdigest()
                for embed in shared_embeds:
                    embed_id = embed.get('embed_id')
                    if not embed_id:
                        # No embed_id — treat as deletable
                        shared_embeds_to_delete.append(embed)
                        continue

                    # Check whether any OTHER chat of this user references the same embed_id.
                    # We look for embeds with the same embed_id but a different hashed_chat_id
                    # that still belong to the same user (via hashed_user_id).
                    other_ref_params = {
                        'filter[embed_id][_eq]': embed_id,
                        'filter[hashed_user_id][_eq]': hashed_user_id,
                        'filter[hashed_chat_id][_neq]': hashed_chat_id,
                        'fields': 'id',
                        'limit': 1,
                    }
                    other_refs = await self.directus_service.get_items(
                        'embeds', params=other_ref_params, no_cache=True
                    )
                    if other_refs and len(other_refs) > 0:
                        # Still referenced by another chat — keep it
                        shared_embeds_to_keep.append(embed)
                        logger.debug(
                            f"Keeping shared embed {embed_id[:8]}... — still used in another chat"
                        )
                    else:
                        # No other reference — delete it
                        shared_embeds_to_delete.append(embed)
                        logger.debug(
                            f"Marking shared embed {embed_id[:8]}... for deletion — no other chat references it"
                        )
            else:
                # No user_id provided: fall back to the old behaviour (keep all shared embeds)
                shared_embeds_to_keep = shared_embeds

            if shared_embeds_to_keep:
                logger.info(
                    f"Keeping {len(shared_embeds_to_keep)} shared embed(s) still referenced by other chats."
                )

            # ------------------------------------------------------------------
            # Step 3: Build the final list of embeds to delete
            # ------------------------------------------------------------------
            embeds_to_delete = private_embeds + shared_embeds_to_delete

            if not embeds_to_delete:
                logger.info("All embeds are still needed — nothing to delete.")
                return True, []

            directus_ids = [e.get('id') for e in embeds_to_delete if e.get('id')]
            embed_uuid_ids = [e.get('embed_id') for e in embeds_to_delete if e.get('embed_id')]

            # ------------------------------------------------------------------
            # Step 4: Delete S3 files, then Directus records
            # ------------------------------------------------------------------
            if s3_service:
                await self._delete_s3_files_for_embeds(embeds_to_delete, s3_service)

            success = await self.directus_service.bulk_delete_items(
                collection='embeds', item_ids=directus_ids
            )

            if success:
                deleted_embed_uuid_ids = embed_uuid_ids
                logger.info(
                    f"Successfully deleted {len(directus_ids)} embed(s) for "
                    f"hashed_chat_id: {hashed_chat_id[:16]}..."
                )
            else:
                logger.warning(
                    f"Bulk delete failed for embeds of hashed_chat_id: {hashed_chat_id[:16]}..."
                )

            return success, deleted_embed_uuid_ids

        except Exception as e:
            logger.error(
                f"Error deleting all embeds for hashed_chat_id: {hashed_chat_id[:16]}...: {e}",
                exc_info=True,
            )
            return False, []

    async def delete_upload_files_for_embeds(self, embed_ids: List[str]) -> int:
        """
        Delete upload_files records whose embed_id is in the provided list.

        Called after embed + S3 deletion to clean up the deduplication records and
        free storage counter space. Returns the total file_size_bytes freed so the
        caller can decrement the user's storage_used_bytes counter.

        Args:
            embed_ids: List of embed UUID strings (from the embed.embed_id field).

        Returns:
            Total bytes freed (sum of file_size_bytes for all deleted records).
        """
        if not embed_ids:
            return 0

        total_bytes_freed = 0
        try:
            # Directus filter: embed_id IN (embed_ids)
            # We build an _in filter which is most efficient for bulk lookups.
            params = {
                'filter[embed_id][_in]': ','.join(embed_ids),
                'fields': 'id,embed_id,file_size_bytes',
                'limit': -1,
            }
            records = await self.directus_service.get_items(
                'upload_files', params=params, no_cache=True
            )

            if not records or not isinstance(records, list) or len(records) == 0:
                logger.debug(
                    f"No upload_files records found for {len(embed_ids)} embed_id(s). Nothing to clean up."
                )
                return 0

            directus_ids = [r.get('id') for r in records if r.get('id')]
            total_bytes_freed = sum(
                int(r.get('file_size_bytes') or 0) for r in records
            )

            logger.info(
                f"Deleting {len(directus_ids)} upload_files record(s), "
                f"freeing {total_bytes_freed:,} bytes."
            )

            success = await self.directus_service.bulk_delete_items(
                collection='upload_files', item_ids=directus_ids
            )
            if not success:
                logger.warning(
                    f"Bulk delete of upload_files failed for embed_ids: {embed_ids[:5]}..."
                )
                return 0

            return total_bytes_freed

        except Exception as e:
            logger.error(
                f"Error deleting upload_files for embed_ids {embed_ids[:5]}...: {e}",
                exc_info=True,
            )
            return 0

    async def delete_embeds_for_message(self, hashed_chat_id: str, hashed_message_id: str, s3_service=None) -> list:
        """
        Deletes embeds for a specific message from Directus.
        Only deletes embeds that are private/not shared (same logic as delete_all_embeds_for_chat).
        Also deletes associated S3 files and embed_keys.
        
        Args:
            hashed_chat_id: SHA256 hash of the chat_id
            hashed_message_id: SHA256 hash of the message_id
            s3_service: Optional S3UploadService instance for deleting associated S3 files
            
        Returns:
            List of embed_id strings that were deleted (for cache cleanup)
        """
        logger.info(
            f"Attempting to delete embeds for hashed_message_id: {hashed_message_id[:16]}... "
            f"in hashed_chat_id: {hashed_chat_id[:16]}... from Directus."
        )
        deleted_embed_ids = []
        try:
            # Query for embeds belonging to this message that are not shared
            params = {
                'filter[hashed_chat_id][_eq]': hashed_chat_id,
                'filter[hashed_message_id][_eq]': hashed_message_id,
                'filter[_or][0][is_private][_eq]': True,
                'filter[_or][1][is_shared][_eq]': False,
                'fields': 'id,embed_id,s3_file_keys',
                'limit': -1
            }
            
            response = await self.directus_service.get_items('embeds', params=params, no_cache=True)
            
            if not response or not isinstance(response, list) or len(response) == 0:
                logger.info(
                    f"No private embeds found for hashed_message_id: {hashed_message_id[:16]}... "
                    f"in hashed_chat_id: {hashed_chat_id[:16]}... (nothing to delete)"
                )
                return []
            
            directus_ids = [embed.get('id') for embed in response if embed.get('id')]
            embed_uuid_ids = [embed.get('embed_id') for embed in response if embed.get('embed_id')]
            
            logger.info(
                f"Found {len(directus_ids)} private embed(s) to delete for hashed_message_id: {hashed_message_id[:16]}..."
            )
            
            if not directus_ids:
                return []
            
            # Delete associated S3 files before deleting embed records
            if s3_service:
                await self._delete_s3_files_for_embeds(response, s3_service)
            
            # Delete associated embed_keys for these embeds
            for embed_uuid_id in embed_uuid_ids:
                try:
                    await self._delete_embed_keys_for_embed(embed_uuid_id)
                except Exception as key_err:
                    logger.warning(f"Failed to delete embed_keys for embed {embed_uuid_id}: {key_err}")
            
            # Bulk delete embed records
            success = await self.directus_service.bulk_delete_items(collection='embeds', item_ids=directus_ids)
            
            if success:
                deleted_embed_ids = embed_uuid_ids
                logger.info(
                    f"Successfully deleted {len(directus_ids)} embeds for hashed_message_id: "
                    f"{hashed_message_id[:16]}... (embed_ids: {embed_uuid_ids[:5]}...)"
                )
            else:
                logger.warning(
                    f"Bulk delete failed for embeds of hashed_message_id: {hashed_message_id[:16]}..."
                )
            
            return deleted_embed_ids
        except Exception as e:
            logger.error(
                f"Error deleting embeds for hashed_message_id: {hashed_message_id[:16]}...: {e}",
                exc_info=True
            )
            return deleted_embed_ids

    async def _delete_embed_keys_for_embed(self, embed_id: str) -> bool:
        """
        Deletes all embed_keys entries for a specific embed from Directus.
        
        Args:
            embed_id: The embed_id (UUID) to delete keys for
            
        Returns:
            True if successful, False otherwise
        """
        try:
            import hashlib
            hashed_embed_id = hashlib.sha256(embed_id.encode()).hexdigest()
            
            params = {
                'filter[hashed_embed_id][_eq]': hashed_embed_id,
                'fields': 'id',
                'limit': -1
            }
            
            response = await self.directus_service.get_items('embed_keys', params=params, no_cache=True)
            
            if not response or not isinstance(response, list) or len(response) == 0:
                return True
            
            key_ids = [key.get('id') for key in response if key.get('id')]
            if not key_ids:
                return True
            
            success = await self.directus_service.bulk_delete_items(collection='embed_keys', item_ids=key_ids)
            if success:
                logger.debug(f"Deleted {len(key_ids)} embed_keys for embed {embed_id}")
            return success
        except Exception as e:
            logger.error(f"Error deleting embed_keys for embed {embed_id}: {e}", exc_info=True)
            return False

    async def _delete_s3_files_for_embeds(self, embeds: list, s3_service) -> None:
        """
        Delete S3 files associated with embeds (e.g., generated images).
        
        Reads the s3_file_keys field from each embed record and deletes the corresponding
        S3 objects. Failures are logged but do not prevent embed deletion.
        
        Args:
            embeds: List of embed dicts (must include 's3_file_keys' field)
            s3_service: S3UploadService instance
        """
        total_deleted = 0
        total_failed = 0
        
        for embed in embeds:
            s3_file_keys = embed.get('s3_file_keys')
            if not s3_file_keys or not isinstance(s3_file_keys, list):
                continue
            
            embed_id = embed.get('embed_id', 'unknown')
            
            for file_entry in s3_file_keys:
                if not isinstance(file_entry, dict):
                    continue
                    
                bucket_key = file_entry.get('bucket')
                file_key = file_entry.get('key')
                
                if not bucket_key or not file_key:
                    continue
                
                try:
                    await s3_service.delete_file(bucket_key=bucket_key, file_key=file_key)
                    total_deleted += 1
                    logger.debug(f"Deleted S3 file for embed {embed_id}: {bucket_key}/{file_key}")
                except Exception as e:
                    total_failed += 1
                    logger.warning(f"Failed to delete S3 file for embed {embed_id}: {bucket_key}/{file_key}: {e}")
        
        if total_deleted > 0 or total_failed > 0:
            logger.info(f"S3 cleanup for embed deletion: {total_deleted} files deleted, {total_failed} failures")

