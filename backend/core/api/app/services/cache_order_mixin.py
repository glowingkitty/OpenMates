import logging
import time
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

class OrderCacheMixin:
    """Mixin for order-specific caching methods"""

    async def set_order(self, order_id: str, user_id: str, credits_amount: int, status: str = "created", ttl: int = 86400) -> bool:
        """Cache order metadata and status."""
        try:
            if not order_id or not user_id or credits_amount is None:
                logger.error("Cannot cache order: missing order_id, user_id, or credits_amount.")
                return False
            order_cache_key = f"{self.ORDER_KEY_PREFIX}{order_id}"
            order_data = {
                "order_id": order_id,
                "user_id": user_id,
                "credits_amount": credits_amount,
                "status": status,
                "timestamp": int(time.time())
            }
            logger.debug(f"Setting order in cache: {order_data}")
            return await self.set(order_cache_key, order_data, ttl=ttl)
        except Exception as e:
            logger.error(f"Error caching order {order_id}: {str(e)}")
            return False

    async def get_order(self, order_id: str) -> Optional[Dict]:
        """Get order metadata and status from cache."""
        try:
            if not order_id:
                return None
            order_cache_key = f"{self.ORDER_KEY_PREFIX}{order_id}"
            logger.debug(f"Getting order from cache: {order_id}")
            return await self.get(order_cache_key)
        except Exception as e:
            logger.error(f"Error getting order {order_id} from cache: {str(e)}")
            return None

    async def update_order_status(self, order_id: str, status: str) -> bool:
        """Update the status of an order in cache."""
        try:
            if not order_id or not status:
                return False
            order_cache_key = f"{self.ORDER_KEY_PREFIX}{order_id}"
            order_data = await self.get(order_cache_key)
            if not order_data:
                logger.warning(f"Cannot update order status: no existing data for order {order_id}")
                return False
            order_data["status"] = status
            logger.debug(f"Updating order {order_id} status to {status}")
            return await self.set(order_cache_key, order_data, ttl=self.SESSION_TTL) # Assuming order TTL is similar to session
        except Exception as e:
            logger.error(f"Error updating order {order_id} status in cache: {str(e)}")
            return False

    async def update_order(self, order_id: str, updated_fields: Dict) -> bool:
        """Update arbitrary fields of an order in cache."""
        try:
            if not order_id or not updated_fields:
                return False
            order_cache_key = f"{self.ORDER_KEY_PREFIX}{order_id}"
            order_data = await self.get(order_cache_key)
            if not order_data:
                logger.warning(f"Cannot update order: no existing data for order {order_id}")
                return False
            order_data.update(updated_fields)
            logger.debug(f"Updating order {order_id} with fields {updated_fields}")
            return await self.set(order_cache_key, order_data, ttl=self.SESSION_TTL) # Assuming order TTL
        except Exception as e:
            logger.error(f"Error updating order {order_id} in cache: {str(e)}")
            return False

    async def has_pending_orders(self, user_id: str) -> bool:
        """Check if a user has any orders in cache that are not in a final state."""
        try:
            client = await self.client # Ensure client is available
            if not client or not user_id:
                return False

            order_pattern = f"{self.ORDER_KEY_PREFIX}*"
            logger.debug(f"Searching for order keys with pattern: '{order_pattern}' for user {user_id}")
            order_keys = await self.get_keys_by_pattern(order_pattern)
            logger.debug(f"Found {len(order_keys)} potential order keys to check for user {user_id}.")

            final_statuses = {"completed", "failed"}

            for key in order_keys:
                order_data = await self.get(key)
                if isinstance(order_data, dict):
                    order_user_id = order_data.get("user_id")
                    order_status = order_data.get("status", "").lower()

                    if order_user_id == user_id and order_status not in final_statuses:
                        logger.info(f"User {user_id} has a pending order: {order_data.get('order_id')} (Status: {order_status})")
                        return True
            
            logger.debug(f"No pending orders found in cache for user {user_id}.")
            return False
        except Exception as e:
            logger.error(f"Error checking for pending orders for user '{user_id}': {str(e)}")
            return False