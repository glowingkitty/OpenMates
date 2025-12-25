# backend/core/api/app/services/directus/admin_methods.py
"""
Methods for managing server administrators.
"""

import logging
import hashlib
import secrets
from typing import Dict, Any, Optional
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

class AdminMethods:
    """Methods for managing server administrators"""

    def __init__(self, directus_service):
        self.directus_service = directus_service

    async def create_admin_token(self, duration_seconds: int = 30) -> str:
        """
        Create a temporary admin token that can be used to grant admin privileges.

        Args:
            duration_seconds: How long the token should be valid (default 30 seconds)

        Returns:
            Secure token string
        """
        try:
            # Generate a cryptographically secure token
            token = secrets.token_urlsafe(32)

            # Calculate expiration time
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=duration_seconds)

            # Store token in database
            token_data = {
                "token": hashlib.sha256(token.encode()).hexdigest(),  # Store hashed version
                "expires_at": expires_at.isoformat(),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "used": False
            }

            result = await self.directus_service.create_item("admin_tokens", token_data)
            if result:
                logger.info(f"Created admin token with expiration: {expires_at}")
                return token  # Return unhashed token for use in URL
            else:
                logger.error("Failed to create admin token")
                return None

        except Exception as e:
            logger.error(f"Error creating admin token: {e}", exc_info=True)
            return None

    async def validate_admin_token(self, token: str) -> bool:
        """
        Validate an admin token and mark it as used.

        Args:
            token: The token to validate

        Returns:
            True if token is valid and not expired
        """
        try:
            # Hash the token to compare with stored version
            token_hash = hashlib.sha256(token.encode()).hexdigest()

            # Find token in database
            params = {
                "filter": {
                    "token": {"_eq": token_hash},
                    "used": {"_eq": False}
                },
                "limit": 1
            }

            tokens = await self.directus_service.get_items("admin_tokens", params)
            if not tokens or len(tokens) == 0:
                logger.warning("Admin token not found or already used")
                return False

            token_record = tokens[0]

            # Check if token has expired
            expires_at = datetime.fromisoformat(token_record["expires_at"].replace('Z', '+00:00'))
            if datetime.now(timezone.utc) > expires_at:
                logger.warning("Admin token has expired")
                return False

            # Mark token as used
            await self.directus_service.update_item("admin_tokens", token_record["id"], {
                "used": True,
                "used_at": datetime.now(timezone.utc).isoformat()
            })

            logger.info("Admin token validated and marked as used")
            return True

        except Exception as e:
            logger.error(f"Error validating admin token: {e}", exc_info=True)
            return False

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
                return True

            # Create admin record
            admin_data = {
                "hashed_user_id": hashed_user_id,
                "granted_at": datetime.now(timezone.utc).isoformat(),
                "is_active": True
            }

            result = await self.directus_service.create_item("server_admins", admin_data)
            if result:
                logger.info(f"Granted admin privileges to user {user_id}")
                return True
            else:
                logger.error(f"Failed to grant admin privileges to user {user_id}")
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
                return True
            else:
                logger.error(f"Failed to revoke admin privileges from user {user_id}")
                return False

        except Exception as e:
            logger.error(f"Error revoking admin privileges: {e}", exc_info=True)
            return False

    async def cleanup_expired_tokens(self) -> int:
        """
        Remove expired admin tokens from the database.

        Returns:
            Number of tokens cleaned up
        """
        try:
            # Get all expired tokens
            current_time = datetime.now(timezone.utc).isoformat()
            params = {
                "filter": {
                    "expires_at": {"_lt": current_time}
                }
            }

            expired_tokens = await self.directus_service.get_items("admin_tokens", params)
            if not expired_tokens:
                return 0

            # Delete expired tokens
            deleted_count = 0
            for token in expired_tokens:
                result = await self.directus_service.delete_item("admin_tokens", token["id"])
                if result:
                    deleted_count += 1

            if deleted_count > 0:
                logger.info(f"Cleaned up {deleted_count} expired admin tokens")

            return deleted_count

        except Exception as e:
            logger.error(f"Error cleaning up expired tokens: {e}", exc_info=True)
            return 0