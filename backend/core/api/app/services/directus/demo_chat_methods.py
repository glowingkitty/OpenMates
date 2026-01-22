# backend/core/api/app/services/directus/demo_chat_methods.py
"""
Methods for managing demo chats.

Demo chats are shared chats that are shown to non-authenticated users as examples
of the platform's capabilities. When a user shares a chat with "share with community" active,
the admin can approve it to become a demo chat.
"""

import logging
import re
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
        follow_up_suggestions: Optional[List[str]] = None,
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
            follow_up_suggestions: Optional follow-up suggestions
            approved_by_admin: Whether this demo chat has been approved by admin

        Returns:
            Created demo chat item or None if failed
        """
        try:
            # Generate a sequential demo ID (demo-1, demo-2, demo-3, etc.)
            # Query all existing demo chats to find the highest number
            existing_demos = await self.directus_service.get_items("demo_chats", {
                "filter": {"is_active": {"_eq": True}},
                "fields": ["demo_id"]
            })
            
            # Extract numbers from demo_ids that match the pattern demo-{number}
            max_number = 0
            for demo in existing_demos or []:
                demo_id_str = demo.get("demo_id", "")
                # Match pattern: demo-{number}
                match = re.match(r"^demo-(\d+)$", demo_id_str)
                if match:
                    number = int(match.group(1))
                    max_number = max(max_number, number)
            
            # Generate the next sequential ID
            next_number = max_number + 1
            demo_id = f"demo-{next_number}"

            demo_chat_data = {
                "demo_id": demo_id,
                "original_chat_id": chat_id,
                "encrypted_key": encryption_key,  # Store the encryption key securely
                "category": category,
                "status": "translating",
                "approved_by_admin": approved_by_admin,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "is_active": True
            }

            # Create the demo chat entry
            success, created_item = await self.directus_service.create_item("demo_chats", demo_chat_data)
            if success and created_item:
                # Store the original title/summary in the translation table for 'en' initially
                # This will be overwritten by the translation task
                # But we need it for immediate display if needed
                initial_translation = {
                    "demo_id": demo_id,
                    "language": "en",
                    "title": title,
                    "summary": summary,
                    "follow_up_suggestions": follow_up_suggestions
                }
                await self.directus_service.create_item("demo_chat_translations", initial_translation)

                logger.info(f"Created demo chat {demo_id} for chat {chat_id}")
                return created_item
            else:
                logger.error(f"Failed to create demo chat for chat {chat_id}: {created_item}")
                return None

        except Exception as e:
            logger.error(f"Error creating demo chat for chat {chat_id}: {e}", exc_info=True)
            return None

    async def get_demo_chat_translation(self, demo_id: str, language: str) -> Optional[Dict[str, Any]]:
        """Get translated metadata for a demo chat."""
        try:
            params = {
                "filter": {
                    "demo_id": {"_eq": demo_id},
                    "language": {"_eq": language}
                },
                "limit": 1
            }
            items = await self.directus_service.get_items("demo_chat_translations", params)
            return items[0] if items else None
        except Exception as e:
            logger.error(f"Error fetching demo chat translation: {e}")
            return None

    async def get_demo_messages(self, demo_id: str, language: str) -> List[Dict[str, Any]]:
        """Get translated and encrypted messages for a demo chat."""
        try:
            params = {
                "filter": {
                    "demo_id": {"_eq": demo_id},
                    "language": {"_eq": language}
                },
                "sort": ["message_order"]
            }
            return await self.directus_service.get_items("demo_messages", params)
        except Exception as e:
            logger.error(f"Error fetching demo messages: {e}")
            return []

    async def get_demo_embeds(self, demo_id: str, language: str) -> List[Dict[str, Any]]:
        """Get translated and encrypted embeds for a demo chat."""
        try:
            params = {
                "filter": {
                    "demo_id": {"_eq": demo_id},
                    "language": {"_eq": language}
                },
                "sort": ["embed_order"]
            }
            return await self.directus_service.get_items("demo_embeds", params)
        except Exception as e:
            logger.error(f"Error fetching demo embeds: {e}")
            return []

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
        """
        try:
            # Check cache first if approved_only=True (public requests)
            if approved_only:
                # Public requests should use language-specific methods now
                # This is a fallback
                cached_demos = await self.directus_service.cache.get_demo_chats_list("en")
                if cached_demos is not None:
                    return cached_demos

            filter_conditions = {
                "is_active": {"_eq": True}
            }

            if approved_only:
                filter_conditions["approved_by_admin"] = {"_eq": True}
                filter_conditions["status"] = {"_eq": "published"}

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
                # Invalidate cache
                await self.directus_service.cache.clear_demo_chats_cache()
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
                # Invalidate cache
                await self.directus_service.cache.clear_demo_chats_cache()
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
            # Check cache first if approved_only=True (public requests)
            if approved_only:
                cached_demos = await self.directus_service.cache.get_demo_chats_list(category=category)
                if cached_demos is not None:
                    logger.debug(f"Cache HIT: Returning demo chats for category '{category}' from cache")
                    return cached_demos

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
            
            # Cache the result for public requests
            if approved_only and items is not None:
                await self.directus_service.cache.set_demo_chats_list(items, category=category)
                
            return items or []

        except Exception as e:
            logger.error(f"Error fetching demo chats by category {category}: {e}", exc_info=True)
            return []