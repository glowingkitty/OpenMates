"""
Directus methods for embed operations.
Handles CRUD operations for embeds collection in Directus.
"""
import logging
from typing import List, Dict, Any, Optional
import hashlib

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
    "share_mode,"
    "shared_with_users,"
    "embed_ids,"
    "encrypted_content,"
    "encrypted_text_preview,"
    "parent_embed_id,"
    "version_number,"
    "encrypted_diff,"
    "file_path,"
    "content_hash,"
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
                logger.debug(f"Found duplicate embed with content_hash")
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

    async def delete_all_embeds_for_chat(self, hashed_chat_id: str) -> bool:
        """
        Deletes ALL embeds for a specific chat from Directus.
        
        This is called when a chat is deleted to clean up orphaned embeds.
        Only deletes embeds that:
        1. Are not shared (share_mode != 'shared' or share_mode is null)
        2. Belong exclusively to this chat
        
        Args:
            hashed_chat_id: SHA256 hash of the chat_id to delete embeds for
            
        Returns:
            True if successful, False otherwise
        """
        logger.info(f"Attempting to delete all embeds for hashed_chat_id: {hashed_chat_id[:16]}... from Directus.")
        try:
            # Query for all embeds belonging to this chat that are not shared
            params = {
                'filter[hashed_chat_id][_eq]': hashed_chat_id,
                'filter[_or][0][share_mode][_null]': 'true',  # share_mode is null
                'filter[_or][1][share_mode][_eq]': 'private',  # share_mode is 'private'
                'fields': 'id,embed_id',
                'limit': -1  # Get all
            }
            
            response = await self.directus_service.get_items('embeds', params=params, no_cache=True)
            
            if not response or not isinstance(response, list) or len(response) == 0:
                logger.info(f"No private embeds found for hashed_chat_id: {hashed_chat_id[:16]}... (nothing to delete)")
                return True
            
            embed_ids = [embed.get('id') for embed in response if embed.get('id')]
            embed_uuid_ids = [embed.get('embed_id') for embed in response if embed.get('embed_id')]
            
            logger.info(f"Found {len(embed_ids)} private embed(s) to delete for hashed_chat_id: {hashed_chat_id[:16]}...")
            
            if not embed_ids:
                logger.info("No embed IDs found to delete.")
                return True
            
            # Use bulk delete for efficiency
            success = await self.directus_service.bulk_delete_items(collection='embeds', item_ids=embed_ids)
            
            if success:
                logger.info(f"Successfully deleted {len(embed_ids)} embeds for hashed_chat_id: {hashed_chat_id[:16]}... (embed_ids: {embed_uuid_ids[:5]}...)")
            else:
                logger.warning(f"Bulk delete failed for embeds of hashed_chat_id: {hashed_chat_id[:16]}...")
            
            return success
        except Exception as e:
            logger.error(f"Error deleting all embeds for hashed_chat_id: {hashed_chat_id[:16]}...: {e}", exc_info=True)
            return False

