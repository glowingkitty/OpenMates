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

    async def create_pending_demo_chat(
        self,
        chat_id: str,
        encryption_key: str,
        title: Optional[str] = None,
        summary: Optional[str] = None,
        category: Optional[str] = None,
        icon: Optional[str] = None,
        follow_up_suggestions: Optional[List[str]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Create a pending demo chat entry with status='waiting_for_confirmation'.
        
        This is called when a user shares a chat with community. The admin must
        approve it before it becomes a published demo chat.
        
        If a demo_chat already exists for this chat:
        - If status='waiting_for_confirmation': update it with new metadata
        - If status is anything else: return None (already processed)
        
        Args:
            chat_id: The original chat ID
            encryption_key: The encryption key needed to decrypt the chat
            title: Display title for the demo chat (will be vault-encrypted)
            summary: Description/summary (will be vault-encrypted)
            category: Category for grouping (will be vault-encrypted)
            icon: Icon name (will be vault-encrypted)
            follow_up_suggestions: Follow-up suggestions list (will be vault-encrypted as JSON)
            
        Returns:
            Created/updated demo chat item or None if failed/already processed
        """
        try:
            # Check if a demo_chat already exists for this chat
            existing_demo = await self.get_demo_chat_by_original_chat_id(chat_id)
            
            if existing_demo:
                # Demo chat already exists
                existing_status = existing_demo.get("status", "")
                if existing_status == "waiting_for_confirmation":
                    # Update existing pending entry with new metadata
                    logger.info(f"Updating existing pending demo chat {existing_demo.get('demo_id')} for chat {chat_id}")
                    return await self._update_pending_demo_chat(
                        existing_demo.get("id"),
                        existing_demo.get("demo_id"),
                        encryption_key, title, summary, category, icon, follow_up_suggestions
                    )
                else:
                    # Already approved/processed - don't create duplicate
                    logger.info(f"Demo chat for chat {chat_id} already exists with status '{existing_status}' - skipping")
                    return None
            
            # Generate a sequential demo ID (demo-1, demo-2, demo-3, etc.)
            existing_demos = await self.directus_service.get_items("demo_chats", {
                "filter": {"is_active": {"_eq": True}},
                "fields": ["demo_id"]
            })
            
            max_number = 0
            for demo in existing_demos or []:
                demo_id_str = demo.get("demo_id", "")
                match = re.match(r"^demo-(\d+)$", demo_id_str)
                if match:
                    number = int(match.group(1))
                    max_number = max(max_number, number)
            
            next_number = max_number + 1
            demo_id = f"demo-{next_number}"
            
            # Encrypt metadata with vault key
            from backend.core.api.app.utils.encryption import DEMO_CHATS_ENCRYPTION_KEY
            encryption_service = self.directus_service.encryption_service
            
            encrypted_title = None
            encrypted_summary = None
            encrypted_category = None
            encrypted_icon = None
            encrypted_follow_up = None
            
            if title:
                encrypted_title, _ = await encryption_service.encrypt(title, key_name=DEMO_CHATS_ENCRYPTION_KEY)
            if summary:
                encrypted_summary, _ = await encryption_service.encrypt(summary, key_name=DEMO_CHATS_ENCRYPTION_KEY)
            if category:
                encrypted_category, _ = await encryption_service.encrypt(category, key_name=DEMO_CHATS_ENCRYPTION_KEY)
            if icon:
                encrypted_icon, _ = await encryption_service.encrypt(icon, key_name=DEMO_CHATS_ENCRYPTION_KEY)
            if follow_up_suggestions:
                import json
                encrypted_follow_up, _ = await encryption_service.encrypt(
                    json.dumps(follow_up_suggestions), 
                    key_name=DEMO_CHATS_ENCRYPTION_KEY
                )
            
            demo_chat_data = {
                "demo_id": demo_id,
                "original_chat_id": chat_id,
                "encrypted_key": encryption_key,
                "encrypted_title": encrypted_title,
                "encrypted_summary": encrypted_summary,
                "encrypted_category": encrypted_category,
                "encrypted_icon": encrypted_icon,
                "encrypted_follow_up_suggestions": encrypted_follow_up,
                "status": "waiting_for_confirmation",
                "approved_by_admin": False,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "is_active": True
            }
            
            success, created_item = await self.directus_service.create_item("demo_chats", demo_chat_data)
            if success and created_item:
                logger.info(f"Created pending demo chat {demo_id} for chat {chat_id}")
                return created_item
            else:
                logger.error(f"Failed to create pending demo chat for chat {chat_id}: {created_item}")
                return None
                
        except Exception as e:
            logger.error(f"Error creating pending demo chat for chat {chat_id}: {e}", exc_info=True)
            return None

    async def create_pending_demo_chat_with_content(
        self,
        chat_id: str,
        title: Optional[str],
        summary: Optional[str],
        category: Optional[str],
        icon: Optional[str],
        follow_up_suggestions: Optional[List[str]],
        decrypted_messages: List[Dict[str, Any]],
        decrypted_embeds: List[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """
        Create a pending demo chat with decrypted content from client (zero-knowledge architecture).
        
        This is the new approach where the client decrypts messages/embeds locally and sends
        plaintext to the server. The server then encrypts everything with Vault and stores it.
        
        Args:
            chat_id: The original chat ID
            title: Demo chat title
            summary: Demo chat summary  
            category: Demo chat category
            icon: Icon name
            follow_up_suggestions: List of follow-up suggestions
            decrypted_messages: List of {role, content, created_at}
            decrypted_embeds: List of {embed_id, type, content, created_at}
            
        Returns:
            Created demo chat item or None if failed
        """
        try:
            from backend.core.api.app.utils.encryption import DEMO_CHATS_ENCRYPTION_KEY
            encryption_service = self.directus_service.encryption_service
            
            # Check if a demo_chat already exists for this chat
            existing_demo = await self.get_demo_chat_by_original_chat_id(chat_id)
            
            if existing_demo:
                # Demo chat already exists
                existing_status = existing_demo.get("status", "")
                if existing_status == "pending_approval":
                    # Update existing pending entry
                    logger.info(f"Updating existing pending demo chat {existing_demo.get('id')} for chat {chat_id}")
                    # We'll update the full content
                    # For now, just log and return existing - full update implementation needed
                    return existing_demo
                else:
                    # Already approved/processed - don't create duplicate
                    logger.info(f"Demo chat for chat {chat_id} already exists with status '{existing_status}' - skipping")
                    return None
            
            # Encrypt metadata with Vault
            encrypted_title = None
            encrypted_summary = None
            encrypted_category = None
            encrypted_icon = None
            encrypted_follow_up = None
            
            if title:
                encrypted_title, _ = await encryption_service.encrypt(title, key_name=DEMO_CHATS_ENCRYPTION_KEY)
            if summary:
                encrypted_summary, _ = await encryption_service.encrypt(summary, key_name=DEMO_CHATS_ENCRYPTION_KEY)
            if category:
                encrypted_category, _ = await encryption_service.encrypt(category, key_name=DEMO_CHATS_ENCRYPTION_KEY)
            if icon:
                encrypted_icon, _ = await encryption_service.encrypt(icon, key_name=DEMO_CHATS_ENCRYPTION_KEY)
            if follow_up_suggestions:
                import json
                encrypted_follow_up, _ = await encryption_service.encrypt(
                    json.dumps(follow_up_suggestions), 
                    key_name=DEMO_CHATS_ENCRYPTION_KEY
                )
            
            # Create demo_chats entry
            from datetime import datetime, timezone
            demo_chat_data = {
                "original_chat_id": chat_id,
                "encrypted_title": encrypted_title,
                "encrypted_summary": encrypted_summary,
                "encrypted_category": encrypted_category,
                "encrypted_icon": encrypted_icon,
                "encrypted_follow_up_suggestions": encrypted_follow_up,
                "status": "pending_approval",
                "approved_by_admin": False,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "is_active": True
            }
            
            success, created_item = await self.directus_service.create_item("demo_chats", demo_chat_data)
            if not success or not created_item:
                logger.error(f"Failed to create pending demo chat for chat {chat_id}")
                return None
            
            demo_chat_id = created_item["id"]  # UUID
            logger.info(f"Created pending demo chat {demo_chat_id} for chat {chat_id}")
            
            # Store messages (encrypted with Vault, in original language only)
            for msg in decrypted_messages:
                encrypted_content, _ = await encryption_service.encrypt(
                    msg["content"], 
                    key_name=DEMO_CHATS_ENCRYPTION_KEY
                )
                
                message_data = {
                    "demo_chat_id": demo_chat_id,
                    "role": msg["role"],
                    "encrypted_content": encrypted_content,
                    "language": "original",  # Mark as original language, will be translated later
                    "original_created_at": datetime.fromtimestamp(msg["created_at"] / 1000, tz=timezone.utc).isoformat() if msg["created_at"] > 1000000000000 else datetime.fromtimestamp(msg["created_at"], tz=timezone.utc).isoformat()
                }
                await self.directus_service.create_item("demo_messages", message_data)
            
            logger.info(f"Stored {len(decrypted_messages)} messages for demo chat {demo_chat_id}")
            
            # Store embeds (encrypted with Vault, in original language only)
            for emb in decrypted_embeds:
                encrypted_content, _ = await encryption_service.encrypt(
                    emb["content"], 
                    key_name=DEMO_CHATS_ENCRYPTION_KEY
                )
                
                embed_data = {
                    "demo_chat_id": demo_chat_id,
                    "original_embed_id": emb["embed_id"],
                    "type": emb["type"],
                    "encrypted_content": encrypted_content,
                    "language": "original",  # Mark as original language
                    "original_created_at": datetime.fromtimestamp(emb["created_at"] / 1000, tz=timezone.utc).isoformat() if emb["created_at"] > 1000000000000 else datetime.fromtimestamp(emb["created_at"], tz=timezone.utc).isoformat()
                }
                await self.directus_service.create_item("demo_embeds", embed_data)
            
            logger.info(f"Stored {len(decrypted_embeds)} embeds for demo chat {demo_chat_id}")
            
            return created_item
                
        except Exception as e:
            logger.error(f"Error creating pending demo chat with content for chat {chat_id}: {e}", exc_info=True)
            return None

    async def _update_pending_demo_chat(
        self,
        item_id: str,
        demo_id: str,
        encryption_key: str,
        title: Optional[str],
        summary: Optional[str],
        category: Optional[str],
        icon: Optional[str],
        follow_up_suggestions: Optional[List[str]]
    ) -> Optional[Dict[str, Any]]:
        """
        Update an existing pending demo chat with new metadata.
        Called when user re-shares a chat with community.
        """
        try:
            from backend.core.api.app.utils.encryption import DEMO_CHATS_ENCRYPTION_KEY
            encryption_service = self.directus_service.encryption_service
            
            updates = {
                "encrypted_key": encryption_key,  # Update encryption key in case it changed
            }
            
            if title:
                encrypted_title, _ = await encryption_service.encrypt(title, key_name=DEMO_CHATS_ENCRYPTION_KEY)
                updates["encrypted_title"] = encrypted_title
            if summary:
                encrypted_summary, _ = await encryption_service.encrypt(summary, key_name=DEMO_CHATS_ENCRYPTION_KEY)
                updates["encrypted_summary"] = encrypted_summary
            if category:
                encrypted_category, _ = await encryption_service.encrypt(category, key_name=DEMO_CHATS_ENCRYPTION_KEY)
                updates["encrypted_category"] = encrypted_category
            if icon:
                encrypted_icon, _ = await encryption_service.encrypt(icon, key_name=DEMO_CHATS_ENCRYPTION_KEY)
                updates["encrypted_icon"] = encrypted_icon
            if follow_up_suggestions:
                import json
                encrypted_follow_up, _ = await encryption_service.encrypt(
                    json.dumps(follow_up_suggestions), 
                    key_name=DEMO_CHATS_ENCRYPTION_KEY
                )
                updates["encrypted_follow_up_suggestions"] = encrypted_follow_up
            
            result = await self.directus_service.update_item("demo_chats", item_id, updates)
            if result:
                logger.info(f"Updated pending demo chat {demo_id}")
                return result
            else:
                logger.error(f"Failed to update pending demo chat {demo_id}")
                return None
                
        except Exception as e:
            logger.error(f"Error updating pending demo chat {demo_id}: {e}", exc_info=True)
            return None

    async def get_demo_chat_by_original_chat_id(self, chat_id: str) -> Optional[Dict[str, Any]]:
        """
        Get demo chat by original chat ID.
        
        Args:
            chat_id: The original chat identifier
            
        Returns:
            Demo chat data or None if not found
        """
        try:
            params = {
                "filter": {
                    "original_chat_id": {"_eq": chat_id},
                    "is_active": {"_eq": True}
                },
                "limit": 1
            }
            
            items = await self.directus_service.get_items("demo_chats", params)
            if items and len(items) > 0:
                return items[0]
            return None
            
        except Exception as e:
            logger.error(f"Error fetching demo chat by original chat ID {chat_id}: {e}", exc_info=True)
            return None

    async def get_pending_demo_chats(self) -> List[Dict[str, Any]]:
        """
        Get all demo chats with status='waiting_for_confirmation'.
        
        Returns:
            List of pending demo chat entries
        """
        try:
            params = {
                "filter": {
                    "status": {"_eq": "waiting_for_confirmation"},
                    "is_active": {"_eq": True}
                },
                "sort": ["-created_at"]
            }
            
            items = await self.directus_service.get_items("demo_chats", params)
            return items or []
            
        except Exception as e:
            logger.error(f"Error fetching pending demo chats: {e}", exc_info=True)
            return []

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
            # First, get the demo chat to find its actual Directus item ID
            demo_chat = await self.get_demo_chat_by_id(demo_id)
            if not demo_chat:
                logger.error(f"Demo chat {demo_id} not found for deactivation")
                return False

            item_id = demo_chat.get("id")  # This is the Directus item ID (UUID)
            if not item_id:
                logger.error(f"Demo chat {demo_id} has no Directus item ID")
                return False

            updates = {
                "is_active": False,
                "deactivated_at": datetime.now(timezone.utc).isoformat()
            }

            result = await self.directus_service.update_item("demo_chats", item_id, updates)
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