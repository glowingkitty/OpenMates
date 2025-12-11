"""
Payment Tier Service

Handles payment tier system logic for limiting monthly spending based on user trust level.
Tiers are based on consecutive months without chargebacks.

Tier System:
- Tier 0: No card payments allowed (SEPA transfer only) - after 2+ chargebacks
- Tier 1: 75€/month (new users or after 1 chargeback)
- Tier 2: 150€/month (3 months without chargeback)
- Tier 3: 300€/month (6 months without chargeback)
- Tier 4: 500€/month (12 months without chargeback)

Chargeback Penalty System (Graduated):
- First chargeback: Reset to Tier 1 (75€/month limit)
- Second chargeback: Reset to Tier 0 (no card payments, SEPA only)

This service provides efficient O(1) tier checking by using cached values on the user record,
avoiding expensive invoice queries on every purchase.
"""

import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Tuple
from decimal import Decimal

from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.utils.encryption import EncryptionService

logger = logging.getLogger(__name__)

# Tier limits in EUR (monthly spending limits)
# Tier 0 has no limit (0.0) because card payments are not allowed
TIER_LIMITS = {
    0: 0.0,    # No card payments allowed (SEPA only) - after 2+ chargebacks
    1: 75.0,   # New users or after 1 chargeback
    2: 150.0,  # 3 months without chargeback
    3: 300.0,  # 6 months without chargeback
    4: 500.0,  # 12 months without chargeback
}

# Tier progression requirements (months without chargeback)
TIER_REQUIREMENTS = {
    1: 0,   # New users start at tier 1
    2: 3,   # Tier 2 requires 3 months
    3: 6,   # Tier 3 requires 6 months
    4: 12,  # Tier 4 requires 12 months
}


class PaymentTierService:
    """Service for managing payment tier system and limits."""
    
    def __init__(
        self,
        cache_service: CacheService,
        directus_service: DirectusService,
        encryption_service: EncryptionService,
    ):
        self.cache_service = cache_service
        self.directus_service = directus_service
        self.encryption_service = encryption_service

    def convert_to_eur(self, amount: float, currency: str) -> float:
        """
        Convert an amount from any currency to EUR.
        Uses approximate exchange rates (updated periodically).
        
        Args:
            amount: Amount in the source currency
            currency: Source currency code (lowercase: eur, usd, jpy)
            
        Returns:
            Amount in EUR
        """
        currency_lower = currency.lower()
        
        if currency_lower == "eur":
            return amount
        elif currency_lower == "usd":
            # Approximate: 1 USD ≈ 0.92 EUR (as of 2024)
            return amount * 0.92
        elif currency_lower == "jpy":
            # Approximate: 1 JPY ≈ 0.0062 EUR (as of 2024)
            return amount * 0.0062
        else:
            logger.warning(f"Unknown currency {currency}, assuming EUR")
            return amount

    def get_tier_limit(self, tier: int) -> float:
        """
        Get the monthly spending limit for a given tier.
        
        Args:
            tier: Tier number (0-4)
            
        Returns:
            Monthly limit in EUR (0.0 for Tier 0 means no card payments allowed)
        """
        return TIER_LIMITS.get(tier, TIER_LIMITS[1])
    
    def is_card_payment_allowed(self, tier: int) -> bool:
        """
        Check if card payments are allowed for a given tier.
        
        Args:
            tier: Tier number (0-4)
            
        Returns:
            True if card payments are allowed, False if only SEPA is allowed (Tier 0)
        """
        return tier != 0

    def get_required_months_for_tier(self, tier: int) -> int:
        """
        Get the required months without chargeback for a given tier.
        
        Args:
            tier: Tier number (1-4)
            
        Returns:
            Required months without chargeback
        """
        return TIER_REQUIREMENTS.get(tier, 0)

    def calculate_tier_from_months(self, months_without_chargeback: int) -> int:
        """
        Calculate the appropriate tier based on months without chargeback.
        
        Args:
            months_without_chargeback: Number of consecutive months without chargeback
            
        Returns:
            Tier number (1-4)
        """
        # Find the highest tier the user qualifies for
        for tier in sorted(TIER_REQUIREMENTS.keys(), reverse=True):
            if months_without_chargeback >= TIER_REQUIREMENTS[tier]:
                return tier
        return 1  # Default to tier 1

    def get_current_month_start_timestamp(self) -> int:
        """
        Get the Unix timestamp for the start of the current calendar month.
        
        Returns:
            Unix timestamp (seconds) for the start of the current month
        """
        now = datetime.now(timezone.utc)
        month_start = datetime(now.year, now.month, 1, 0, 0, 0, tzinfo=timezone.utc)
        return int(month_start.timestamp())

    async def get_current_month_spending(
        self,
        user_id: str,
        user_data: Dict[str, Any],
        vault_key_id: str
    ) -> Tuple[float, bool]:
        """
        Get the user's current month spending in EUR, resetting if a new month has started.
        
        Args:
            user_id: User ID
            user_data: User data from cache
            vault_key_id: User's vault key ID for decryption
            
        Returns:
            Tuple of (current_month_spending_eur, was_reset)
            - current_month_spending_eur: Total EUR spent this month
            - was_reset: Whether the counter was reset (new month started)
        """
        current_month_start = self.get_current_month_start_timestamp()
        stored_month_start = user_data.get("current_month_start_timestamp", 0)
        
        # Check if we need to reset (new month started)
        if stored_month_start != current_month_start:
            logger.info(f"New month detected for user {user_id}. Resetting monthly spending counter.")
            # Reset monthly spending
            encrypted_zero = await self.encryption_service.encrypt_with_user_key(
                "0.0", vault_key_id
            )
            
            # Update user record
            update_payload = {
                "encrypted_current_month_spending_eur": encrypted_zero[0],
                "current_month_start_timestamp": current_month_start
            }
            await self.directus_service.update_user(user_id, update_payload)
            
            # Update cache
            user_data["encrypted_current_month_spending_eur"] = encrypted_zero[0]
            user_data["current_month_start_timestamp"] = current_month_start
            await self.cache_service.set_user(user_data, user_id=user_id)
            
            return 0.0, True
        
        # Decrypt current spending
        encrypted_spending = user_data.get("encrypted_current_month_spending_eur")
        if not encrypted_spending:
            return 0.0, False
        
        try:
            decrypted_spending_str = await self.encryption_service.decrypt_with_user_key(
                encrypted_spending, vault_key_id
            )
            if decrypted_spending_str:
                return float(decrypted_spending_str), False
        except Exception as e:
            logger.error(f"Error decrypting monthly spending for user {user_id}: {str(e)}")
        
        return 0.0, False

    async def check_tier_limit(
        self,
        user_id: str,
        purchase_amount: float,
        currency: str
    ) -> Tuple[bool, Optional[str], int, float]:
        """
        Check if a purchase would exceed the user's tier limit.
        
        This is the main method called before creating a payment order.
        It efficiently checks limits using cached values without querying invoices.
        
        Args:
            user_id: User ID
            purchase_amount: Purchase amount in the specified currency
            currency: Purchase currency (eur, usd, jpy) - will be converted to EUR
            
        Returns:
            Tuple of (is_allowed, error_message, current_tier, current_spending)
            - is_allowed: Whether the purchase is allowed
            - error_message: Error message if not allowed, None if allowed
            - current_tier: User's current tier
            - current_spending: Current month's spending in EUR
        """
        # Convert purchase amount to EUR for comparison
        purchase_amount_eur = self.convert_to_eur(purchase_amount, currency)
        # Get user data from cache
        user_data = await self.cache_service.get_user_by_id(user_id)
        if not user_data:
            # Fetch from Directus if not in cache
            profile_success, user_profile, _ = await self.directus_service.get_user_profile(user_id)
            if not profile_success or not user_profile:
                logger.error(f"User {user_id} not found for tier check")
                return False, "User not found", 1, 0.0
            
            user_data = user_profile
            await self.cache_service.set_user(user_data, user_id=user_id)
        
        # Get tier (default to 1 if not set)
        current_tier = user_data.get("payment_tier", 1)
        if current_tier < 0 or current_tier > 4:
            current_tier = 1
        
        # Check if card payments are allowed (Tier 0 = no card payments)
        if not self.is_card_payment_allowed(current_tier):
            error_msg = (
                f"Card payments are not allowed for your account due to previous chargebacks. "
                f"Please use SEPA bank transfer for purchases. Contact support if you believe this is an error."
            )
            logger.warning(
                f"Card payment blocked for user {user_id}: Tier 0 (no card payments allowed)"
            )
            return False, error_msg, current_tier, 0.0
        
        # Get vault key for decryption
        vault_key_id = user_data.get("vault_key_id")
        if not vault_key_id:
            logger.error(f"User {user_id} missing vault_key_id for tier check")
            return False, "User configuration error", current_tier, 0.0
        
        # Get current month spending (resets if new month)
        current_spending, _ = await self.get_current_month_spending(
            user_id, user_data, vault_key_id
        )
        
        # Get tier limit
        tier_limit = self.get_tier_limit(current_tier)
        
        # Check if purchase would exceed limit
        new_total = current_spending + purchase_amount_eur
        if new_total > tier_limit:
            error_msg = (
                f"Purchase would exceed your monthly limit of {tier_limit:.2f}€. "
                f"Current spending: {current_spending:.2f}€, Purchase: {purchase_amount_eur:.2f}€. "
                f"Your limit will reset at the start of next month. "
                f"Consider using SEPA transfer for larger purchases."
            )
            logger.warning(
                f"Tier limit exceeded for user {user_id}: "
                f"tier={current_tier}, limit={tier_limit}€, "
                f"current={current_spending:.2f}€, purchase={purchase_amount_eur:.2f}€"
            )
            return False, error_msg, current_tier, current_spending
        
        return True, None, current_tier, current_spending

    async def update_monthly_spending(
        self,
        user_id: str,
        purchase_amount_eur: float,
        vault_key_id: str
    ) -> None:
        """
        Update the user's monthly spending counter after a successful purchase.
        
        Args:
            user_id: User ID
            purchase_amount_eur: Purchase amount in EUR
            vault_key_id: User's vault key ID for encryption
        """
        # Get user data
        user_data = await self.cache_service.get_user_by_id(user_id)
        if not user_data:
            profile_success, user_profile, _ = await self.directus_service.get_user_profile(user_id)
            if not profile_success or not user_profile:
                logger.error(f"User {user_id} not found for spending update")
                return
            user_data = user_profile
        
        # Get current spending (this will reset if new month)
        current_spending, _ = await self.get_current_month_spending(
            user_id, user_data, vault_key_id
        )
        
        # Add purchase amount
        new_spending = current_spending + purchase_amount_eur
        
        # Encrypt and update
        encrypted_spending = await self.encryption_service.encrypt_with_user_key(
            str(new_spending), vault_key_id
        )
        
        update_payload = {
            "encrypted_current_month_spending_eur": encrypted_spending[0]
        }
        await self.directus_service.update_user(user_id, update_payload)
        
        # Update cache
        user_data["encrypted_current_month_spending_eur"] = encrypted_spending[0]
        await self.cache_service.set_user(user_data, user_id=user_id)
        
        logger.info(
            f"Updated monthly spending for user {user_id}: "
            f"{current_spending:.2f}€ -> {new_spending:.2f}€"
        )

    async def handle_chargeback(
        self,
        user_id: str,
        invoice_order_id: str,
        chargeback_date: datetime
    ) -> None:
        """
        Handle a chargeback event with graduated penalty system:
        - First chargeback: Reset to Tier 1 (75€/month limit)
        - Second chargeback: Reset to Tier 0 (no card payments, SEPA only)
        
        Args:
            user_id: User ID
            invoice_order_id: Order ID of the invoice with chargeback
            chargeback_date: Date when chargeback occurred
        """
        logger.warning(
            f"Processing chargeback for user {user_id}, order {invoice_order_id}, "
            f"date {chargeback_date.isoformat()}"
        )
        
        # Get user data
        user_data = await self.cache_service.get_user_by_id(user_id)
        if not user_data:
            profile_success, user_profile, _ = await self.directus_service.get_user_profile(user_id)
            if not profile_success or not user_profile:
                logger.error(f"User {user_id} not found for chargeback handling")
                return
            user_data = user_profile
        
        # Get current chargeback count
        current_chargeback_count = user_data.get("chargeback_count", 0)
        new_chargeback_count = current_chargeback_count + 1
        
        # Reset consecutive months counter
        # Update last chargeback date
        chargeback_iso = chargeback_date.isoformat()
        
        # Graduated penalty system:
        # - First chargeback (count = 1): Tier 1 (75€/month)
        # - Second chargeback (count >= 2): Tier 0 (no card payments)
        if new_chargeback_count == 1:
            # First chargeback: Reset to Tier 1
            new_tier = 1
            logger.info(
                f"First chargeback for user {user_id}. "
                f"Resetting to Tier 1 (75€/month limit)."
            )
        else:
            # Second or more chargeback: Reset to Tier 0 (no card payments)
            new_tier = 0
            logger.warning(
                f"Second or subsequent chargeback for user {user_id} "
                f"(chargeback_count={new_chargeback_count}). "
                f"Resetting to Tier 0 (no card payments, SEPA only)."
            )
        
        update_payload = {
            "chargeback_count": new_chargeback_count,
            "consecutive_months_without_chargeback": 0,
            "last_chargeback_date": chargeback_iso,
            "payment_tier": new_tier
        }
        
        await self.directus_service.update_user(user_id, update_payload)
        
        # Update cache
        user_data["chargeback_count"] = new_chargeback_count
        user_data["consecutive_months_without_chargeback"] = 0
        user_data["last_chargeback_date"] = chargeback_iso
        user_data["payment_tier"] = new_tier
        await self.cache_service.set_user(user_data, user_id=user_id)
        
        logger.info(
            f"Updated tier for user {user_id} due to chargeback. "
            f"Chargeback count: {current_chargeback_count} → {new_chargeback_count}, "
            f"Tier: {user_data.get('payment_tier', 1)} → {new_tier}, "
            f"Months counter reset to 0."
        )

    async def handle_successful_payment(
        self,
        user_id: str,
        payment_date: datetime
    ) -> None:
        """
        Handle a successful payment - check if we should increment months counter and upgrade tier.
        
        This checks if this is the first payment in a new month, and if so, increments
        the consecutive months counter and potentially upgrades the tier.
        
        Args:
            user_id: User ID
            payment_date: Date of the successful payment
        """
        # Get user data
        user_data = await self.cache_service.get_user_by_id(user_id)
        if not user_data:
            profile_success, user_profile, _ = await self.directus_service.get_user_profile(user_id)
            if not profile_success or not user_profile:
                logger.error(f"User {user_id} not found for payment handling")
                return
            user_data = user_profile
        
        last_payment_date_str = user_data.get("last_successful_payment_date")
        current_months = user_data.get("consecutive_months_without_chargeback", 0)
        current_tier = user_data.get("payment_tier", 1)
        
        # Check if this payment is in a different month than the last payment
        should_increment = False
        if last_payment_date_str:
            try:
                last_payment_date = datetime.fromisoformat(last_payment_date_str.replace('Z', '+00:00'))
                # Check if payment is in a different month
                if (payment_date.year != last_payment_date.year or 
                    payment_date.month != last_payment_date.month):
                    should_increment = True
            except Exception as e:
                logger.warning(f"Error parsing last_payment_date for user {user_id}: {str(e)}")
                should_increment = True  # If we can't parse, assume new month
        else:
            # First payment ever
            should_increment = True
        
        if should_increment:
            new_months = current_months + 1
            
            # Get chargeback count to determine max tier
            chargeback_count = user_data.get("chargeback_count", 0)
            
            # Users with chargebacks cannot progress beyond Tier 1
            # Tier 0 users (2+ chargebacks) cannot progress at all via card payments
            if chargeback_count >= 2:
                # User is at Tier 0 (no card payments) - cannot progress via card payments
                # They can only use SEPA transfers
                new_tier = 0
                logger.info(
                    f"User {user_id} has {chargeback_count} chargebacks (Tier 0). "
                    f"Tier progression blocked. SEPA transfers only."
                )
            elif chargeback_count == 1:
                # User has 1 chargeback - max tier is 1
                calculated_tier = self.calculate_tier_from_months(new_months)
                new_tier = min(calculated_tier, 1)  # Cap at Tier 1
                logger.info(
                    f"User {user_id} has 1 chargeback. "
                    f"Tier progression capped at Tier 1 (calculated: {calculated_tier})."
                )
            else:
                # No chargebacks - normal tier progression
                new_tier = self.calculate_tier_from_months(new_months)
            
            update_payload = {
                "consecutive_months_without_chargeback": new_months,
                "last_successful_payment_date": payment_date.isoformat()
            }
            
            # Only update tier if it increased (and user is not at Tier 0)
            if new_tier > current_tier and current_tier != 0:
                update_payload["payment_tier"] = new_tier
                logger.info(
                    f"User {user_id} upgraded to tier {new_tier} "
                    f"({new_months} months without chargeback)"
                )
            else:
                logger.info(
                    f"User {user_id} payment recorded. "
                    f"Months without chargeback: {new_months}, tier: {current_tier} "
                    f"(chargeback_count: {chargeback_count})"
                )
            
            await self.directus_service.update_user(user_id, update_payload)
            
            # Update cache
            user_data["consecutive_months_without_chargeback"] = new_months
            user_data["last_successful_payment_date"] = payment_date.isoformat()
            if new_tier > current_tier:
                user_data["payment_tier"] = new_tier
            await self.cache_service.set_user(user_data, user_id=user_id)
