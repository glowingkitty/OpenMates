import logging
import time
import json
import os
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

# Path for persisting orders during shutdown (shared volume mounted across containers)
ORDER_BACKUP_PATH = "/shared/cache/pending_orders_backup.json"

class OrderCacheMixin:
    """Mixin for order-specific caching methods"""

    async def set_support_order(
        self,
        order_id: str,
        status: str = "created",
        ttl: int = 3600,
        amount: Optional[int] = None,
        currency: Optional[str] = None,
        support_email: Optional[str] = None,
        user_id: Optional[str] = None,
        email_encryption_key: Optional[str] = None,
        is_recurring: bool = False,
        subscription_id: Optional[str] = None,
    ) -> bool:
        """
        Cache support contribution order metadata.

        Unlike credit purchase orders, support orders may not have a user_id (guest checkout) and
        do not have a credits_amount. We still cache them so the webhook can trigger receipts/email
        reliably and we can do basic idempotency on webhook retries.
        """
        try:
            if not order_id:
                logger.error("Cannot cache support order: missing order_id.")
                return False

            order_cache_key = f"{self.ORDER_KEY_PREFIX}{order_id}"
            order_data: Dict[str, Any] = {
                "order_id": order_id,
                "status": status,
                "timestamp": int(time.time()),
                "order_type": "support_contribution",
                "is_recurring": bool(is_recurring),
            }

            if user_id:
                order_data["user_id"] = user_id
            if amount is not None:
                order_data["amount"] = amount
            if currency:
                order_data["currency"] = currency
            if support_email:
                order_data["support_email"] = support_email
            if email_encryption_key:
                order_data["email_encryption_key"] = email_encryption_key
            if subscription_id:
                order_data["subscription_id"] = subscription_id

            logger.debug(f"Setting support order in cache: {order_data}")
            return await self.set(order_cache_key, order_data, ttl=ttl)
        except Exception as e:
            logger.error(f"Error caching support order {order_id}: {str(e)}")
            return False

    async def set_order(
        self,
        order_id: str,
        user_id: str,
        credits_amount: int,
        status: str = "created",
        ttl: int = 86400,
        email_encryption_key: str = None,
        is_gift_card: bool = False,
        currency: str = None,
        is_auto_topup: bool = False,
        provider: str = None,
    ) -> bool:
        """Cache order metadata and status.

        The `provider` field records which payment provider processed the order
        ("stripe", "polar", or "revolut"). It is used by the invoice email task
        to determine the correct document type (Invoice vs. Payment Confirmation).
        """
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

            # Store email encryption key if provided
            if email_encryption_key:
                order_data["email_encryption_key"] = email_encryption_key

            # Store gift card flag if this is a gift card purchase
            if is_gift_card:
                order_data["is_gift_card"] = True

            # Store currency if provided (for tier system updates)
            if currency:
                order_data["currency"] = currency

            # Store auto top-up flag (used by webhook/email processing)
            if is_auto_topup:
                order_data["is_auto_topup"] = True

            # Store the resolved payment provider ("stripe", "polar", "revolut")
            # Used by the invoice task to select document type and Invoice Ninja handling
            if provider:
                order_data["provider"] = provider

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

    async def dump_pending_orders_to_disk(self) -> int:
        """
        Dump all pending (non-completed, non-failed) orders to disk for persistence across restarts.
        Called during graceful shutdown to prevent payment data loss.
        
        Returns:
            Number of orders saved to disk
        """
        try:
            client = await self.client
            if not client:
                logger.warning("Cannot dump orders to disk: cache client not connected")
                return 0

            # Find all order keys
            order_pattern = f"{self.ORDER_KEY_PREFIX}*"
            order_keys = await self.get_keys_by_pattern(order_pattern)
            
            if not order_keys:
                logger.info("No orders in cache to dump to disk")
                return 0

            # Collect pending orders (exclude completed/failed)
            final_statuses = {"completed", "failed", "failed_missing_cache_data"}
            pending_orders: List[Dict[str, Any]] = []
            
            for key in order_keys:
                order_data = await self.get(key)
                if isinstance(order_data, dict):
                    status = order_data.get("status", "").lower()
                    if status not in final_statuses:
                        # Include the cache key for restoration
                        order_data["_cache_key"] = key
                        pending_orders.append(order_data)
                        logger.debug(f"Including order {order_data.get('order_id')} (status: {status}) for backup")

            if not pending_orders:
                logger.info("No pending orders to dump to disk (all orders are in final state)")
                # Clean up any existing backup file
                if os.path.exists(ORDER_BACKUP_PATH):
                    os.remove(ORDER_BACKUP_PATH)
                return 0

            # Ensure directory exists
            backup_dir = os.path.dirname(ORDER_BACKUP_PATH)
            os.makedirs(backup_dir, exist_ok=True)

            # Write to disk with timestamp
            backup_data = {
                "timestamp": int(time.time()),
                "orders": pending_orders
            }
            
            with open(ORDER_BACKUP_PATH, 'w') as f:
                json.dump(backup_data, f, indent=2)

            logger.info(f"Successfully dumped {len(pending_orders)} pending orders to disk at {ORDER_BACKUP_PATH}")
            return len(pending_orders)

        except Exception as e:
            logger.error(f"Error dumping orders to disk: {str(e)}", exc_info=True)
            return 0

    async def restore_orders_from_disk(self) -> int:
        """
        Restore orders from disk backup into cache.
        Called during startup to recover payment orders after restart.
        
        Returns:
            Number of orders restored to cache
        """
        try:
            if not os.path.exists(ORDER_BACKUP_PATH):
                logger.info("No order backup file found at startup - nothing to restore")
                return 0

            with open(ORDER_BACKUP_PATH, 'r') as f:
                backup_data = json.load(f)

            timestamp = backup_data.get("timestamp", 0)
            orders = backup_data.get("orders", [])
            
            if not orders:
                logger.info("Order backup file is empty - nothing to restore")
                os.remove(ORDER_BACKUP_PATH)
                return 0

            # Check if backup is too old (older than 24 hours = order TTL)
            current_time = int(time.time())
            backup_age_seconds = current_time - timestamp
            backup_age_hours = backup_age_seconds / 3600
            
            if backup_age_seconds > 86400:  # 24 hours
                logger.warning(f"Order backup is {backup_age_hours:.1f} hours old (>24h) - skipping stale restore")
                os.remove(ORDER_BACKUP_PATH)
                return 0

            logger.info(f"Restoring {len(orders)} orders from backup (backup age: {backup_age_hours:.1f} hours)")

            restored_count = 0
            for order_data in orders:
                cache_key = order_data.pop("_cache_key", None)
                order_id = order_data.get("order_id")
                
                if not cache_key or not order_id:
                    logger.warning("Skipping malformed order in backup: missing cache_key or order_id")
                    continue

                # Check if order already exists in cache (might have been re-cached by webhook)
                existing = await self.get(cache_key)
                if existing:
                    logger.debug(f"Order {order_id} already exists in cache - skipping restore")
                    continue

                # Calculate remaining TTL based on original timestamp
                original_timestamp = order_data.get("timestamp", timestamp)
                elapsed = current_time - original_timestamp
                remaining_ttl = max(86400 - elapsed, 3600)  # At least 1 hour TTL remaining

                # Restore to cache
                success = await self.set(cache_key, order_data, ttl=remaining_ttl)
                if success:
                    restored_count += 1
                    logger.info(f"Restored order {order_id} to cache (TTL: {remaining_ttl}s)")
                else:
                    logger.error(f"Failed to restore order {order_id} to cache")

            # Clean up backup file after successful restore
            os.remove(ORDER_BACKUP_PATH)
            logger.info(f"Successfully restored {restored_count}/{len(orders)} orders from disk backup")
            
            return restored_count

        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in order backup file: {str(e)}")
            # Remove corrupted backup
            if os.path.exists(ORDER_BACKUP_PATH):
                os.remove(ORDER_BACKUP_PATH)
            return 0
        except Exception as e:
            logger.error(f"Error restoring orders from disk: {str(e)}", exc_info=True)
            return 0
