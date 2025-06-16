# backend/core/api/app/services/directus/usage.py
#
# This module contains the DirectusService methods for interacting with the
# 'usage' collection in Directus.

import logging
from typing import Dict, Any, Optional, List
import json

from backend.core.api.app.utils.encryption import EncryptionService

logger = logging.getLogger(__name__)

class UsageMethods:
    def __init__(self, sdk, encryption_service: EncryptionService):
        self.sdk = sdk
        self.encryption_service = encryption_service
        self.collection = "usage"

    async def create_usage_entry(
        self,
        user_id_hash: str,
        app_id: str,
        skill_id: str,
        usage_type: str,
        timestamp: int,
        credits_charged: int,
        user_vault_key_id: str,
        model_used: Optional[str] = None,
        chat_id: Optional[str] = None,
        message_id: Optional[str] = None,
        cost_system_prompt_credits: Optional[int] = None,
        cost_history_credits: Optional[int] = None,
        cost_response_credits: Optional[int] = None,
        actual_input_tokens: Optional[int] = None,
        actual_output_tokens: Optional[int] = None,
    ) -> Optional[str]:
        """
        Creates a new usage entry in Directus.
        Encrypts fields that need to be protected.
        """
        log_prefix = f"DirectusService ({self.collection}):"
        logger.info(f"{log_prefix} Creating new usage entry for user '{user_id_hash}'.")

        try:
            # Encryption key is the user_id_hash for usage entries
            encryption_key_id = user_vault_key_id

            # Encrypt all fields that require it
            encrypted_credits_costs_total_tuple = await self.encryption_service.encrypt_with_user_key(
                key_id=encryption_key_id, plaintext=str(credits_charged)
            )
            encrypted_input_tokens_tuple = await self.encryption_service.encrypt_with_user_key(
                key_id=encryption_key_id, plaintext=str(actual_input_tokens)
            ) if actual_input_tokens is not None else (None, None)
            encrypted_output_tokens_tuple = await self.encryption_service.encrypt_with_user_key(
                key_id=encryption_key_id, plaintext=str(actual_output_tokens)
            ) if actual_output_tokens is not None else (None, None)

            encrypted_credits_costs_total = encrypted_credits_costs_total_tuple[0] if encrypted_credits_costs_total_tuple else None
            encrypted_input_tokens = encrypted_input_tokens_tuple[0] if encrypted_input_tokens_tuple else None
            encrypted_output_tokens = encrypted_output_tokens_tuple[0] if encrypted_output_tokens_tuple else None


            if not encrypted_credits_costs_total:
                logger.error(f"{log_prefix} Failed to encrypt total credits. Aborting usage entry creation.")
                return None

            payload = {
                "user_id_hash": user_id_hash,
                "app_id": app_id,
                "skill_id": skill_id,
                "type": usage_type,
                "created_at": timestamp,
                "updated_at": timestamp,
                "encrypted_credits_costs_total": encrypted_credits_costs_total,
            }
            
            # Add optional fields if they exist
            if chat_id:
                payload["chat_id"] = chat_id
            if message_id:
                payload["message_id"] = message_id
            if model_used:
                payload["model_used"] = model_used
            if encrypted_input_tokens:
                payload["encrypted_input_tokens"] = encrypted_input_tokens
            if encrypted_output_tokens:
                payload["encrypted_output_tokens"] = encrypted_output_tokens

            success, response_data = await self.sdk.create_item(self.collection, payload)
            
            if success and response_data and response_data.get("id"):
                entry_id = response_data["id"]
                logger.info(f"{log_prefix} Successfully created usage entry with ID: {entry_id}")
                return entry_id
            else:
                logger.error(f"{log_prefix} Failed to create usage entry. Response: {response_data}")
                return None

        except Exception as e:
            logger.error(f"{log_prefix} Error creating usage entry: {e}", exc_info=True)
            return None
