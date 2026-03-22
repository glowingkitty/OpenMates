# backend/core/api/app/services/creators/revenue_service.py
#
# Creator revenue service for tracking and managing creator income.
# Handles creation of creator_income entries from skill usage and tips.

import logging
import time
import asyncio
from typing import Optional, Dict, Any
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.utils.encryption import (
    EncryptionService,
    CREATOR_INCOME_ENCRYPTION_KEY
)
from backend.shared.python_utils.content_hasher import (
    hash_owner_id,
    hash_content_id,
    hash_app_id,
    hash_skill_id
)

logger = logging.getLogger(__name__)


class CreatorRevenueService:
    """
    Service for managing creator income tracking.
    
    Handles:
    - Creating creator_income entries from skill usage
    - Creating creator_income entries from user tips
    - Encrypting credit amounts for privacy
    - Hashing identifiers for privacy-preserving storage
    """
    
    def __init__(
        self,
        directus_service: DirectusService,
        encryption_service: EncryptionService
    ):
        self.directus_service = directus_service
        self.encryption_service = encryption_service
    
    async def create_income_entry(
        self,
        owner_id: str,
        content_id: str,
        content_type: str,  # 'video' or 'website'
        app_id: str,
        skill_id: str,
        credits: int,
        income_source: str = "skill_usage",  # 'skill_usage' or 'tip'
        processed_at: Optional[int] = None
    ) -> bool:
        """
        Create a creator_income entry asynchronously.
        
        This method is designed to be called as a fire-and-forget async task
        that doesn't block the main skill execution flow.
        
        Args:
            owner_id: Owner identifier (channel ID for videos, domain for websites)
            content_id: Content identifier (video ID or normalized URL)
            content_type: Type of content ('video' or 'website')
            app_id: App ID that executed the skill (e.g., 'videos', 'web')
            skill_id: Skill ID that was executed (e.g., 'get_transcript', 'read')
            credits: Number of credits to reserve for creator
            income_source: Source of income ('skill_usage' or 'tip')
            processed_at: Unix timestamp when content was processed (defaults to now)
        
        Returns:
            True if income entry was created successfully, False otherwise
        
        Note:
            This method logs errors but doesn't raise exceptions to avoid
            breaking skill execution if income tracking fails.
        """
        if credits <= 0:
            logger.debug(f"Skipping creator income entry creation: credits is {credits}")
            return False
        
        if not owner_id or not content_id:
            logger.warning(f"Cannot create creator income entry: missing owner_id or content_id")
            return False
        
        try:
            # Hash all identifiers for privacy
            hashed_owner_id = hash_owner_id(owner_id)
            hashed_content_id = hash_content_id(content_id)
            hashed_app_id = hash_app_id(app_id)
            hashed_skill_id = hash_skill_id(skill_id)
            
            if not all([hashed_owner_id, hashed_content_id, hashed_app_id, hashed_skill_id]):
                logger.error(f"Failed to hash identifiers for creator income entry")
                return False
            
            # Encrypt credits using system key
            encrypted_credits_tuple = await self.encryption_service.encrypt(
                plaintext=str(credits),
                key_name=CREATOR_INCOME_ENCRYPTION_KEY
            )
            encrypted_credits = encrypted_credits_tuple[0]  # Extract ciphertext from tuple
            
            # Use current timestamp if not provided
            if processed_at is None:
                processed_at = int(time.time())
            
            # Create income entry data
            timestamp = int(time.time())
            income_data = {
                "hashed_owner_id": hashed_owner_id,
                "hashed_content_id": hashed_content_id,
                "content_type": content_type,
                "income_source": income_source,
                "hashed_app_id": hashed_app_id,
                "hashed_skill_id": hashed_skill_id,
                "encrypted_credits_reserved": encrypted_credits,
                "processed_at": processed_at,
                "status": "reserved",  # All entries start as reserved until creator claims
                "created_at": timestamp,
                "updated_at": timestamp
            }
            
            # Create entry in Directus
            # create_item returns a tuple (success: bool, data: dict)
            success, result_data = await self.directus_service.create_item(
                collection="creator_income",
                payload=income_data
            )
            
            if success:
                logger.info(
                    f"Created creator income entry: "
                    f"owner={hashed_owner_id[:16]}..., "
                    f"content={hashed_content_id[:16]}..., "
                    f"credits={credits}, "
                    f"source={income_source}"
                )
                return True
            else:
                logger.error(f"Failed to create creator income entry in Directus: {result_data}")
                return False
                
        except Exception as e:
            # Log error but don't raise - income tracking failure shouldn't break skill execution
            logger.error(
                f"Error creating creator income entry: {e}",
                exc_info=True
            )
            return False
    
    async def create_income_entry_async(
        self,
        owner_id: str,
        content_id: str,
        content_type: str,
        app_id: str,
        skill_id: str,
        credits: int,
        income_source: str = "skill_usage",
        processed_at: Optional[int] = None
    ) -> None:
        """
        Create a creator_income entry asynchronously (fire-and-forget).
        
        This is a convenience wrapper that creates an async task.
        Use this when you want to create income entries without blocking.
        
        Args:
            Same as create_income_entry()
        
        Returns:
            None (fire-and-forget)
        """
        # Create async task - fire and forget
        asyncio.create_task(
            self.create_income_entry(
                owner_id=owner_id,
                content_id=content_id,
                content_type=content_type,
                app_id=app_id,
                skill_id=skill_id,
                credits=credits,
                income_source=income_source,
                processed_at=processed_at
            )
        )
