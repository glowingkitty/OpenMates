# backend/core/api/app/services/directus/demo_chat_methods.py
"""
Methods for managing demo chats.

Demo chats are shared chats that are shown to non-authenticated users as examples
of the platform's capabilities. When a user shares a chat with "share with community" active,
the admin can approve it to become a demo chat.
"""

import logging
import hashlib
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

class DemoChatMethods:
    """Methods for managing demo chats"""

    def __init__(self, directus_service):
        self.directus_service = directus_service

    async def create_demo_chat(
        self,
        chat_id: str,
        encryption_key: str,
        title: str,
        summary: Optional[str] = None,
        category: Optional[str] = None,
        approved_by_admin: bool = False
    ) -> Optional[Dict[str, Any]]:
        """
        Create a new demo chat entry.

        Args:
            chat_id: The original chat ID
            encryption_key: The encryption key needed to decrypt the chat
            title: Display title for the demo chat
            summary: Optional description/summary
            category: Optional category for grouping
            approved_by_admin: Whether this demo chat has been approved by admin

        Returns:
            Created demo chat item or None if failed
        """
        try:
            # Generate a unique demo ID (different from the original chat_id)
            demo_id = hashlib.sha256(f"demo_{chat_id}_{datetime.now().isoformat()}".encode()).hexdigest()[:16]

            demo_chat_data = {
                "demo_id": demo_id,
                "original_chat_id": chat_id,
                "encrypted_key": encryption_key,  # Store the encryption key securely
                "title": title,
                "summary": summary,
                "category": category,
                "approved_by_admin": approved_by_admin,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "is_active": True
            }

            # Create the demo chat entry
            result = await self.directus_service.create_item("demo_chats", demo_chat_data)
            if result:
                logger.info(f"Created demo chat {demo_id} for chat {chat_id}")
                return result
            else:
                logger.error(f"Failed to create demo chat for chat {chat_id}")
                return None

        except Exception as e:
            logger.error(f"Error creating demo chat for chat {chat_id}: {e}", exc_info=True)
            return None

    async def get_demo_chat_by_id(self, demo_id: str) -> Optional[Dict[str, Any]]:
        """
        Get demo chat by demo ID.

        Args:
            demo_id: The demo chat identifier

        Returns:
            Demo chat data or None if not found
        """
        try:
            params = {
                "filter": {
                    "demo_id": {"_eq": demo_id},
                    "is_active": {"_eq": True}
                },
                "limit": 1
            }

            items = await self.directus_service.get_items("demo_chats", params)
            if items and len(items) > 0:
                return items[0]
            return None

        except Exception as e:
            logger.error(f"Error fetching demo chat {demo_id}: {e}", exc_info=True)
            return None

    async def get_all_active_demo_chats(self, approved_only: bool = True) -> List[Dict[str, Any]]:
        """
        Get all active demo chats.

        Args:
            approved_only: Whether to only return admin-approved demo chats

        Returns:
            List of demo chat entries
        """
        try:
            filter_conditions = {
                "is_active": {"_eq": True}
            }

            if approved_only:
                filter_conditions["approved_by_admin"] = {"_eq": True}

            params = {
                "filter": filter_conditions,
                "sort": ["-created_at"]  # Newest first
            }

            items = await self.directus_service.get_items("demo_chats", params)
            return items or []

        except Exception as e:
            logger.error(f"Error fetching active demo chats: {e}", exc_info=True)
            return []

    async def approve_demo_chat(self, demo_id: str) -> bool:
        """
        Approve a demo chat for public display.

        Args:
            demo_id: The demo chat identifier

        Returns:
            True if approval was successful
        """
        try:
            updates = {
                "approved_by_admin": True,
                "approved_at": datetime.now(timezone.utc).isoformat()
            }

            result = await self.directus_service.update_item("demo_chats", demo_id, updates)
            if result:
                logger.info(f"Approved demo chat {demo_id}")
                return True
            else:
                logger.error(f"Failed to approve demo chat {demo_id}")
                return False

        except Exception as e:
            logger.error(f"Error approving demo chat {demo_id}: {e}", exc_info=True)
            return False

    async def deactivate_demo_chat(self, demo_id: str) -> bool:
        """
        Deactivate a demo chat (soft delete).

        Args:
            demo_id: The demo chat identifier

        Returns:
            True if deactivation was successful
        """
        try:
            updates = {
                "is_active": False,
                "deactivated_at": datetime.now(timezone.utc).isoformat()
            }

            result = await self.directus_service.update_item("demo_chats", demo_id, updates)
            if result:
                logger.info(f"Deactivated demo chat {demo_id}")
                return True
            else:
                logger.error(f"Failed to deactivate demo chat {demo_id}")
                return False

        except Exception as e:
            logger.error(f"Error deactivating demo chat {demo_id}: {e}", exc_info=True)
            return False

    async def get_demo_chats_by_category(self, category: str, approved_only: bool = True) -> List[Dict[str, Any]]:
        """
        Get demo chats filtered by category.

        Args:
            category: The category to filter by
            approved_only: Whether to only return admin-approved demo chats

        Returns:
            List of demo chat entries in the specified category
        """
        try:
            filter_conditions = {
                "is_active": {"_eq": True},
                "category": {"_eq": category}
            }

            if approved_only:
                filter_conditions["approved_by_admin"] = {"_eq": True}

            params = {
                "filter": filter_conditions,
                "sort": ["-created_at"]
            }

            items = await self.directus_service.get_items("demo_chats", params)
            return items or []

        except Exception as e:
            logger.error(f"Error fetching demo chats by category {category}: {e}", exc_info=True)
            return []