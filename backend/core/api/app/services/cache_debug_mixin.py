# backend/core/api/app/services/cache_debug_mixin.py
# 
# Cache mixin for storing debug information about AI request processing.
# Stores the last 10 user requests globally (not per user) with complete
# input/output data for each processor stage (pre-processor, main-processor, post-processor).
#
# ARCHITECTURE:
# - Uses a Redis list to store the last 10 request entries (circular buffer)
# - Each entry is encrypted server-side with a system-level Vault key
# - Auto-expires after 30 minutes for privacy/storage efficiency
# - Entries include chat_id for filtering in the inspection script
#
# CACHE STRUCTURE:
# - Key: "debug:last_requests" (single global list)
# - Value: List of encrypted JSON entries (max 10)
# - Each entry contains:
#   - task_id: Celery task ID
#   - chat_id: Chat ID for filtering
#   - timestamp: Unix timestamp when request was processed
#   - preprocessor_input: Complete preprocessor input data
#   - preprocessor_output: Complete preprocessor output data
#   - main_processor_input: Complete main processor input data
#   - main_processor_output: Complete main processor output data  
#   - postprocessor_input: Complete postprocessor input data
#   - postprocessor_output: Complete postprocessor output data
#
# SECURITY:
# - All data is encrypted with the DEBUG_REQUESTS_ENCRYPTION_KEY (Vault transit)
# - Only accessible via the inspect_last_requests.py script running inside the API container
# - Auto-expires after 30 minutes to minimize data retention
#
# USAGE:
# - Call cache_debug_request_data() from ask_skill_task.py after each processor stage
# - Use inspect_last_requests.py to view/filter debug data

import logging
import json
import time
from typing import Any, Optional, List, Dict

logger = logging.getLogger(__name__)

# TTL for debug request entries (30 minutes)
DEBUG_REQUEST_TTL = 1800  # 30 minutes in seconds

# Maximum number of debug requests to store (circular buffer)
MAX_DEBUG_REQUESTS = 10

# Redis key for the debug requests list
DEBUG_REQUESTS_KEY = "debug:last_requests"


class DebugCacheMixin:
    """
    Mixin for caching debug information about AI request processing.
    
    This mixin provides methods for storing and retrieving the last 10 AI
    request processing debug entries, including complete input/output data
    for each processor stage.
    
    All data is encrypted server-side with a system-level Vault key
    (DEBUG_REQUESTS_ENCRYPTION_KEY) and auto-expires after 30 minutes.
    """

    async def cache_debug_request_entry(
        self,
        encryption_service: Any,  # EncryptionService instance
        task_id: str,
        chat_id: str,
        stage: str,  # "preprocessor", "main_processor", or "postprocessor"
        input_data: Optional[Dict[str, Any]] = None,
        output_data: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Cache debug data for a specific processing stage.
        
        This method updates an existing entry or creates a new one for the task_id.
        If the entry doesn't exist, it creates a new entry with the given data.
        If it exists, it updates only the specified stage data.
        
        Args:
            encryption_service: EncryptionService instance for encrypting data
            task_id: Celery task ID (unique identifier for this request)
            chat_id: Chat ID for filtering requests
            stage: Processing stage ("preprocessor", "main_processor", or "postprocessor")
            input_data: Input data for this stage (will be JSON serialized)
            output_data: Output data for this stage (will be JSON serialized)
            
        Returns:
            True if caching was successful, False otherwise
        """
        client = await self.client
        if not client:
            logger.error("[DEBUG_CACHE] Redis client not available for cache_debug_request_entry")
            return False
        
        try:
            # Step 1: Get all existing entries and find/update the one for this task_id
            existing_entries = await self._get_all_debug_entries(encryption_service)
            
            # Step 2: Find existing entry for this task_id or create new one
            entry = None
            entry_index = -1
            for i, e in enumerate(existing_entries):
                if e.get("task_id") == task_id:
                    entry = e
                    entry_index = i
                    break
            
            if entry is None:
                # Create new entry
                entry = {
                    "task_id": task_id,
                    "chat_id": chat_id,
                    "timestamp": int(time.time()),
                    "preprocessor_input": None,
                    "preprocessor_output": None,
                    "main_processor_input": None,
                    "main_processor_output": None,
                    "postprocessor_input": None,
                    "postprocessor_output": None,
                }
            
            # Step 3: Update the entry with the new stage data
            if stage == "preprocessor":
                if input_data is not None:
                    entry["preprocessor_input"] = input_data
                if output_data is not None:
                    entry["preprocessor_output"] = output_data
            elif stage == "main_processor":
                if input_data is not None:
                    entry["main_processor_input"] = input_data
                if output_data is not None:
                    entry["main_processor_output"] = output_data
            elif stage == "postprocessor":
                if input_data is not None:
                    entry["postprocessor_input"] = input_data
                if output_data is not None:
                    entry["postprocessor_output"] = output_data
            else:
                logger.warning(f"[DEBUG_CACHE] Unknown stage '{stage}' for task {task_id}")
                return False
            
            # Step 4: Update timestamp on each update
            entry["timestamp"] = int(time.time())
            
            # Step 5: Update entry list
            if entry_index >= 0:
                # Update existing entry in place
                existing_entries[entry_index] = entry
            else:
                # Add new entry at the beginning (most recent first)
                existing_entries.insert(0, entry)
                # Trim to MAX_DEBUG_REQUESTS
                if len(existing_entries) > MAX_DEBUG_REQUESTS:
                    existing_entries = existing_entries[:MAX_DEBUG_REQUESTS]
            
            # Step 6: Encrypt and save all entries
            await self._save_all_debug_entries(encryption_service, existing_entries)
            
            logger.debug(f"[DEBUG_CACHE] Cached {stage} data for task {task_id}, chat {chat_id}")
            return True
            
        except Exception as e:
            logger.error(f"[DEBUG_CACHE] Error caching debug data for task {task_id}: {e}", exc_info=True)
            return False

    async def get_debug_requests_for_chat(
        self,
        encryption_service: Any,  # EncryptionService instance
        chat_id: str,
    ) -> List[Dict[str, Any]]:
        """
        Get all debug request entries for a specific chat.
        
        Args:
            encryption_service: EncryptionService instance for decrypting data
            chat_id: Chat ID to filter by
            
        Returns:
            List of debug request entries for the specified chat (decrypted)
        """
        try:
            all_entries = await self._get_all_debug_entries(encryption_service)
            # Filter by chat_id
            filtered = [e for e in all_entries if e.get("chat_id") == chat_id]
            logger.debug(f"[DEBUG_CACHE] Found {len(filtered)} debug entries for chat {chat_id}")
            return filtered
        except Exception as e:
            logger.error(f"[DEBUG_CACHE] Error getting debug entries for chat {chat_id}: {e}", exc_info=True)
            return []

    async def get_all_debug_requests(
        self,
        encryption_service: Any,  # EncryptionService instance
    ) -> List[Dict[str, Any]]:
        """
        Get all debug request entries (for debugging/admin purposes).
        
        Args:
            encryption_service: EncryptionService instance for decrypting data
            
        Returns:
            List of all debug request entries (decrypted)
        """
        try:
            entries = await self._get_all_debug_entries(encryption_service)
            logger.debug(f"[DEBUG_CACHE] Retrieved {len(entries)} total debug entries")
            return entries
        except Exception as e:
            logger.error(f"[DEBUG_CACHE] Error getting all debug entries: {e}", exc_info=True)
            return []

    async def _get_all_debug_entries(
        self,
        encryption_service: Any,
    ) -> List[Dict[str, Any]]:
        """
        Internal method to get and decrypt all debug entries from cache.
        
        Returns empty list if cache is empty or decryption fails.
        """
        client = await self.client
        if not client:
            return []
        
        try:
            # Get the encrypted data from Redis
            encrypted_data = await client.get(DEBUG_REQUESTS_KEY)
            if not encrypted_data:
                return []
            
            # Decode if bytes
            if isinstance(encrypted_data, bytes):
                encrypted_data = encrypted_data.decode('utf-8')
            
            # Decrypt the data
            decrypted_json = await encryption_service.decrypt_debug_request_data(encrypted_data)
            if not decrypted_json:
                logger.warning("[DEBUG_CACHE] Failed to decrypt debug entries")
                return []
            
            # Parse JSON
            entries = json.loads(decrypted_json)
            return entries if isinstance(entries, list) else []
            
        except json.JSONDecodeError as e:
            logger.error(f"[DEBUG_CACHE] JSON decode error for debug entries: {e}")
            return []
        except Exception as e:
            logger.error(f"[DEBUG_CACHE] Error getting debug entries: {e}", exc_info=True)
            return []

    async def _save_all_debug_entries(
        self,
        encryption_service: Any,
        entries: List[Dict[str, Any]],
    ) -> bool:
        """
        Internal method to encrypt and save all debug entries to cache.
        """
        client = await self.client
        if not client:
            return False
        
        try:
            # Serialize to JSON
            entries_json = json.dumps(entries, default=str)
            
            # Encrypt the data
            encrypted_data = await encryption_service.encrypt_debug_request_data(entries_json)
            if not encrypted_data:
                logger.error("[DEBUG_CACHE] Failed to encrypt debug entries")
                return False
            
            # Save to Redis with TTL
            await client.set(DEBUG_REQUESTS_KEY, encrypted_data, ex=DEBUG_REQUEST_TTL)
            
            logger.debug(f"[DEBUG_CACHE] Saved {len(entries)} debug entries to cache")
            return True
            
        except Exception as e:
            logger.error(f"[DEBUG_CACHE] Error saving debug entries: {e}", exc_info=True)
            return False

    async def clear_debug_requests(self) -> bool:
        """
        Clear all debug request entries from cache.
        
        Useful for privacy or when debugging is complete.
        
        Returns:
            True if successful, False otherwise
        """
        client = await self.client
        if not client:
            logger.error("[DEBUG_CACHE] Redis client not available for clear_debug_requests")
            return False
        
        try:
            await client.delete(DEBUG_REQUESTS_KEY)
            logger.info("[DEBUG_CACHE] Cleared all debug request entries")
            return True
        except Exception as e:
            logger.error(f"[DEBUG_CACHE] Error clearing debug entries: {e}", exc_info=True)
            return False
