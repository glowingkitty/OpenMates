# backend/core/api/app/services/directus/admin_methods.py
"""
Methods for managing server administrators.
"""

import logging
import hashlib
from typing import Dict, Any, Optional
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

class AdminMethods:
    """Methods for managing server administrators"""

    def __init__(self, directus_service):
        self.directus_service = directus_service

    async def make_user_admin(self, user_id: str) -> bool:
        """
        Grant admin privileges to a user.

        Args:
            user_id: The user ID to make admin

        Returns:
            True if successful
        """
        try:
            # Hash the user ID for storage
            hashed_user_id = hashlib.sha256(user_id.encode()).hexdigest()

            # Check if user is already admin
            existing_admin = await self.get_admin_by_user_id(user_id)
            if existing_admin:
                logger.info(f"User {user_id} is already an admin")
                
                # Ensure the is_admin flag is also set on the user record
                try:
                    await self.directus_service.update_user(user_id, {"is_admin": True})
                    # Invalidate user profile cache to ensure fresh data on next request
                    cache_key = f"user_profile:{user_id}"
                    try:
                        await self.directus_service.cache.delete(cache_key)
                        logger.info(f"Invalidated user profile cache for user {user_id}")
                    except Exception as cache_err:
                        logger.warning(f"Failed to invalidate user profile cache: {cache_err}")
                    
                    # Send WebSocket notification to user's connected devices
                    try:
                        await self.directus_service.cache.publish_event(
                            channel=f"user_updates::{user_id}",
                            event_data={
                                "event_for_client": "user_admin_status_updated",
                                "user_id_uuid": user_id,
                                "payload": {"is_admin": True}
                            }
                        )
                        logger.info(f"Published 'user_admin_status_updated' event for user {user_id} via Redis pub/sub")
                    except Exception as pub_err:
                        logger.warning(f"Failed to publish admin status update event: {pub_err}")
                except Exception as e:
                    logger.warning(f"Failed to ensure is_admin flag on already-admin user {user_id}: {e}")
                
                return True

            # Create admin record
            admin_data = {
                "hashed_user_id": hashed_user_id,
                "granted_at": datetime.now(timezone.utc).isoformat(),
                "is_active": True
            }

            success, result = await self.directus_service.create_item("server_admins", admin_data)
            if success:
                logger.info(f"Granted admin privileges to user {user_id}")
                
                # ALSO update the is_admin field on the user record for quick access
                # This ensures compatibility with frontend and other parts of the system
                try:
                    await self.directus_service.update_user(user_id, {"is_admin": True})
                    logger.info(f"Updated user record is_admin flag for user {user_id}")
                    
                    # Invalidate user profile cache to ensure fresh data on next request
                    # This allows the client to see the Server settings section without logout/login
                    cache_key = f"user_profile:{user_id}"
                    try:
                        await self.directus_service.cache.delete(cache_key)
                        logger.info(f"Invalidated user profile cache for user {user_id} - client will see Server settings on next auth check")
                    except Exception as cache_err:
                        logger.warning(f"Failed to invalidate user profile cache: {cache_err}")
                    
                    # Send WebSocket notification to user's connected devices for immediate update
                    try:
                        await self.directus_service.cache.publish_event(
                            channel=f"user_updates::{user_id}",
                            event_data={
                                "event_for_client": "user_admin_status_updated",
                                "user_id_uuid": user_id,
                                "payload": {"is_admin": True}
                            }
                        )
                        logger.info(f"Published 'user_admin_status_updated' event for user {user_id} via Redis pub/sub - devices will update immediately")
                    except Exception as pub_err:
                        logger.warning(f"Failed to publish admin status update event: {pub_err}")
                except Exception as user_update_err:
                    logger.error(f"Failed to update user record is_admin flag: {user_update_err}")
                    # Don't fail the whole operation if this secondary update fails
                
                return True
            else:
                logger.error(f"Failed to grant admin privileges to user {user_id}: {result}")
                return False

        except Exception as e:
            logger.error(f"Error making user admin: {e}", exc_info=True)
            return False

    async def get_admin_by_user_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        """
        Get admin record for a user.

        Args:
            user_id: The user ID to check

        Returns:
            Admin record if user is admin, None otherwise
        """
        try:
            hashed_user_id = hashlib.sha256(user_id.encode()).hexdigest()

            params = {
                "filter": {
                    "hashed_user_id": {"_eq": hashed_user_id},
                    "is_active": {"_eq": True}
                },
                "limit": 1
            }

            admins = await self.directus_service.get_items("server_admins", params)
            if admins and len(admins) > 0:
                return admins[0]
            return None

        except Exception as e:
            logger.error(f"Error getting admin by user ID: {e}", exc_info=True)
            return None

    async def is_user_admin(self, user_id: str) -> bool:
        """
        Check if a user has admin privileges.

        Args:
            user_id: The user ID to check

        Returns:
            True if user is admin
        """
        admin_record = await self.get_admin_by_user_id(user_id)
        return admin_record is not None

    async def revoke_admin_privileges(self, user_id: str) -> bool:
        """
        Revoke admin privileges from a user.

        Args:
            user_id: The user ID to revoke admin from

        Returns:
            True if successful
        """
        try:
            admin_record = await self.get_admin_by_user_id(user_id)
            if not admin_record:
                logger.info(f"User {user_id} is not an admin")
                return True

            # Mark admin record as inactive
            result = await self.directus_service.update_item("server_admins", admin_record["id"], {
                "is_active": False,
                "revoked_at": datetime.now(timezone.utc).isoformat()
            })

            if result:
                logger.info(f"Revoked admin privileges from user {user_id}")
                
                # ALSO update the is_admin field on the user record for quick access
                try:
                    await self.directus_service.update_user(user_id, {"is_admin": False})
                    logger.info(f"Updated user record is_admin flag (False) for user {user_id}")
                    
                    # Invalidate user profile cache to ensure fresh data on next request
                    cache_key = f"user_profile:{user_id}"
                    try:
                        await self.directus_service.cache.delete(cache_key)
                        logger.info(f"Invalidated user profile cache for user {user_id}")
                    except Exception as cache_err:
                        logger.warning(f"Failed to invalidate user profile cache: {cache_err}")
                    
                    # Send WebSocket notification to user's connected devices for immediate update
                    try:
                        await self.directus_service.cache.publish_event(
                            channel=f"user_updates::{user_id}",
                            event_data={
                                "event_for_client": "user_admin_status_updated",
                                "user_id_uuid": user_id,
                                "payload": {"is_admin": False}
                            }
                        )
                        logger.info(f"Published 'user_admin_status_updated' event for user {user_id} via Redis pub/sub - devices will update immediately")
                    except Exception as pub_err:
                        logger.warning(f"Failed to publish admin status update event: {pub_err}")
                except Exception as user_update_err:
                    logger.error(f"Failed to update user record is_admin flag: {user_update_err}")
                
                return True
            else:
                logger.error(f"Failed to revoke admin privileges from user {user_id}")
                return False

        except Exception as e:
            logger.error(f"Error revoking admin privileges: {e}", exc_info=True)
            return False
