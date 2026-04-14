"""
Bank Transfer Cache Mixin

Provides Redis caching for pending SEPA bank transfer orders.
Two key structures for O(1) lookup:
  - bt_ref:{reference}   → order data  (for webhook matching by transfer reference)
  - bt_order:{order_id}  → order data  (for frontend status polling by order ID)

Both keys have a 7-day TTL matching the order expiry window.
Directus `pending_bank_transfers` collection is the durable store;
Redis is the fast read layer with Directus fallback on cache miss.
"""

import logging
import time
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)


class BankTransferCacheMixin:
    """Mixin for bank transfer order caching methods."""

    async def set_bank_transfer_order(
        self,
        order_id: str,
        user_id: str,
        credits_amount: int,
        amount_expected_cents: int,
        reference: str,
        currency: str = "eur",
        email_encryption_key: Optional[str] = None,
        order_type: str = "credit_purchase",
        support_email: Optional[str] = None,
        expires_at: Optional[str] = None,
    ) -> bool:
        """
        Cache a pending bank transfer order under both reference and order_id keys.

        Args:
            order_id: Internal order ID (bt_<uuid4>)
            user_id: User who initiated the transfer
            credits_amount: Credits to grant on completion
            amount_expected_cents: Expected amount in cents
            reference: Structured reference for matching (OM-{account_id}-{short_id})
            currency: ISO currency code (always "eur" for SEPA)
            email_encryption_key: Client-provided key for email decryption at completion
            order_type: "credit_purchase" or "support_contribution"
            support_email: Plaintext email for support contributions (guest checkout)
            expires_at: ISO datetime when the order expires

        Returns:
            True if both keys were cached successfully
        """
        try:
            if not order_id or not reference:
                logger.error("Cannot cache bank transfer order: missing order_id or reference")
                return False

            order_data: Dict[str, Any] = {
                "order_id": order_id,
                "user_id": user_id,
                "credits_amount": credits_amount,
                "amount_expected_cents": amount_expected_cents,
                "reference": reference,
                "currency": currency,
                "status": "pending",
                "order_type": order_type,
                "timestamp": int(time.time()),
            }

            if email_encryption_key:
                order_data["email_encryption_key"] = email_encryption_key
            if support_email:
                order_data["support_email"] = support_email
            if expires_at:
                order_data["expires_at"] = expires_at

            ttl = self.BANK_TRANSFER_TTL

            # Cache under both keys for O(1) lookup from either direction
            ref_key = f"{self.BANK_TRANSFER_REF_KEY_PREFIX}{reference}"
            order_key = f"{self.BANK_TRANSFER_ORDER_KEY_PREFIX}{order_id}"

            ref_ok = await self.set(ref_key, order_data, ttl=ttl)
            order_ok = await self.set(order_key, order_data, ttl=ttl)

            if ref_ok and order_ok:
                logger.info(
                    f"Cached bank transfer order {order_id} with reference {reference}"
                )
            else:
                logger.warning(
                    f"Partial cache failure for bank transfer {order_id}: "
                    f"ref={ref_ok}, order={order_ok}"
                )

            return ref_ok and order_ok

        except Exception as e:
            logger.error(f"Error caching bank transfer order {order_id}: {e}")
            return False

    async def get_bank_transfer_by_reference(
        self, reference: str
    ) -> Optional[Dict[str, Any]]:
        """
        Look up a pending bank transfer order by its structured reference.

        Used by the webhook handler to match incoming SEPA transfers.

        Args:
            reference: The structured reference from the transfer

        Returns:
            Order data dict, or None if not found in cache
        """
        try:
            if not reference:
                return None
            ref_key = f"{self.BANK_TRANSFER_REF_KEY_PREFIX}{reference}"
            return await self.get(ref_key)
        except Exception as e:
            logger.error(f"Error looking up bank transfer by reference '{reference}': {e}")
            return None

    async def get_bank_transfer_by_order_id(
        self, order_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        Look up a pending bank transfer order by order ID.

        Used by the frontend status polling endpoint.

        Args:
            order_id: The internal order ID (bt_<uuid4>)

        Returns:
            Order data dict, or None if not found in cache
        """
        try:
            if not order_id:
                return None
            order_key = f"{self.BANK_TRANSFER_ORDER_KEY_PREFIX}{order_id}"
            return await self.get(order_key)
        except Exception as e:
            logger.error(f"Error looking up bank transfer by order_id '{order_id}': {e}")
            return None

    async def update_bank_transfer_status(
        self,
        order_id: str,
        reference: str,
        status: str,
        extra_fields: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Update the status of a bank transfer order in both cache keys.

        Args:
            order_id: The internal order ID
            reference: The structured reference
            status: New status (e.g. "completed", "expired", "admin_review")
            extra_fields: Additional fields to set (e.g. received_amount_cents, completed_at)

        Returns:
            True if both keys were updated successfully
        """
        try:
            order_key = f"{self.BANK_TRANSFER_ORDER_KEY_PREFIX}{order_id}"
            ref_key = f"{self.BANK_TRANSFER_REF_KEY_PREFIX}{reference}"

            order_data = await self.get(order_key)
            if not order_data:
                logger.warning(
                    f"Cannot update bank transfer status: no cached data for {order_id}"
                )
                return False

            order_data["status"] = status
            if extra_fields:
                order_data.update(extra_fields)

            ttl = self.BANK_TRANSFER_TTL
            order_ok = await self.set(order_key, order_data, ttl=ttl)
            ref_ok = await self.set(ref_key, order_data, ttl=ttl)

            return order_ok and ref_ok

        except Exception as e:
            logger.error(f"Error updating bank transfer status for {order_id}: {e}")
            return False

    async def delete_bank_transfer_keys(
        self, order_id: str, reference: str
    ) -> bool:
        """
        Remove bank transfer cache keys (used after expiry cleanup).

        Args:
            order_id: The internal order ID
            reference: The structured reference

        Returns:
            True if deletion succeeded
        """
        try:
            order_key = f"{self.BANK_TRANSFER_ORDER_KEY_PREFIX}{order_id}"
            ref_key = f"{self.BANK_TRANSFER_REF_KEY_PREFIX}{reference}"

            client = await self.client
            if client:
                await client.delete(order_key, ref_key)
            return True
        except Exception as e:
            logger.error(f"Error deleting bank transfer keys for {order_id}: {e}")
            return False

    async def get_user_pending_bank_transfers(
        self, user_id: str
    ) -> List[Dict[str, Any]]:
        """
        Find all pending bank transfer orders for a user.

        Scans bt_order:* keys — this is acceptable because the number of
        concurrent bank transfer orders is very small (typically 0-2 per user).

        Args:
            user_id: The user ID to search for

        Returns:
            List of pending order dicts
        """
        try:
            pattern = f"{self.BANK_TRANSFER_ORDER_KEY_PREFIX}*"
            keys = await self.get_keys_by_pattern(pattern)

            pending = []
            for key in keys:
                data = await self.get(key)
                if (
                    isinstance(data, dict)
                    and data.get("user_id") == user_id
                    and data.get("status") == "pending"
                ):
                    pending.append(data)

            return pending
        except Exception as e:
            logger.error(f"Error listing pending bank transfers for user {user_id}: {e}")
            return []
