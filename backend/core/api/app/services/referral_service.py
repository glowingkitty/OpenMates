"""
Referral program service for promotional credit rewards.

This module owns server-side referral attribution and reward eligibility. The
frontend may capture a public #ref code, but purchase rewards are only granted
after a successful server-confirmed payment and a durable pending attribution.

Credits granted here are promotional and non-refundable, matching gift-card
redemption policy. Campaign rows provide an explicit admin-controlled budget.
"""

import hashlib
import logging
import secrets
import string
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.utils.encryption import EncryptionService

logger = logging.getLogger(__name__)

REFERRAL_CODE_LENGTH = 8
REFERRAL_CODE_ALPHABET = string.ascii_uppercase + string.digits
REFERRAL_STATUS_PENDING = "pending"
REFERRAL_STATUS_REWARDED = "rewarded"
REFERRAL_STATUS_EXPIRED = "expired"
REFERRAL_STATUS_REJECTED = "rejected"
DEFAULT_REFERRAL_CREDITS = 2000
DEFAULT_MAX_SUCCESSFUL_REFERRALS = 10
DEFAULT_MIN_PURCHASE_AMOUNT_CENTS = 1000
DEFAULT_ATTRIBUTION_EXPIRES_DAYS = 7


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_datetime(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return None


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


@dataclass
class ReferralRewardResult:
    awarded: bool
    referred_bonus: int = 0
    referrer_bonus: int = 0
    referred_new_total: Optional[int] = None
    referrer_user_id: Optional[str] = None
    referrer_new_total: Optional[int] = None
    reason: Optional[str] = None


class ReferralService:
    """Durable referral attribution and reward logic."""

    def __init__(
        self,
        directus_service: DirectusService,
        cache_service: CacheService,
        encryption_service: EncryptionService,
    ) -> None:
        self.directus = directus_service
        self.cache = cache_service
        self.encryption = encryption_service

    async def get_active_campaign(self) -> Optional[Dict[str, Any]]:
        """Return the first active campaign with remaining budget."""
        now = datetime.now(timezone.utc)
        campaigns = await self.directus.get_items(
            "referral_campaigns",
            {
                "filter": {"is_active": {"_eq": True}},
                "sort": "-created_at",
                "limit": 10,
            },
            admin_required=True,
        )
        for campaign in campaigns or []:
            starts_at = _parse_datetime(campaign.get("starts_at"))
            ends_at = _parse_datetime(campaign.get("ends_at"))
            if starts_at and starts_at > now:
                continue
            if ends_at and ends_at < now:
                continue
            max_total = _safe_int(campaign.get("max_total_credits"))
            awarded = _safe_int(campaign.get("credits_awarded"))
            if max_total <= awarded:
                continue
            return campaign
        return None

    async def get_or_create_profile(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get or create the stable public referral code for a user."""
        user_id_hash = _sha256(user_id)
        existing = await self.directus.get_items(
            "referral_profiles",
            {"filter": {"user_id_hash": {"_eq": user_id_hash}}, "limit": 1},
            admin_required=True,
        )
        if existing:
            return existing[0]

        for _ in range(8):
            code = "".join(secrets.choice(REFERRAL_CODE_ALPHABET) for _ in range(REFERRAL_CODE_LENGTH))
            success, created = await self.directus.create_item(
                "referral_profiles",
                {
                    "user_id": user_id,
                    "user_id_hash": user_id_hash,
                    "referral_code": code,
                    "successful_referrals_count": 0,
                    "created_at": _now_iso(),
                },
                admin_required=True,
            )
            if success and created:
                return created
        logger.error("Failed to create unique referral profile for user %s", user_id)
        return None

    async def has_credit_purchase(self, user_id: str) -> bool:
        """Return true when the user has at least one direct credit purchase invoice."""
        user = await self.directus.get_user_fields_direct(user_id, ["vault_key_id"])
        vault_key_id = user.get("vault_key_id") if user else None
        if not vault_key_id:
            logger.warning(
                "Cannot check referral credit purchase eligibility without vault key for user %s",
                user_id,
            )
            return False

        user_id_hash = _sha256(user_id)
        invoices = await self.directus.get_items(
            "invoices",
            {
                "filter": {
                    "user_id_hash": {"_eq": user_id_hash},
                    "is_gift_card": {"_eq": False},
                    "encrypted_credits_purchased": {"_nnull": True},
                },
                "fields": "id,encrypted_credits_purchased",
                "sort": "-date",
                "limit": 100,
            },
            admin_required=True,
        )
        for invoice in invoices or []:
            try:
                credits_purchased = await self._decrypt_credits(
                    invoice.get("encrypted_credits_purchased"),
                    vault_key_id,
                )
                if credits_purchased > 0:
                    return True
            except Exception as exc:
                logger.warning(
                    "Failed to decrypt referral eligibility invoice %s for user %s: %s",
                    invoice.get("id"),
                    user_id,
                    exc,
                    exc_info=True,
                )
        return False

    async def get_status(self, user_id: str) -> Dict[str, Any]:
        """Return frontend status for showing the referral CTA/settings page."""
        campaign = await self.get_active_campaign()
        has_credit_purchase = await self.has_credit_purchase(user_id) if campaign else False
        profile = await self.get_or_create_profile(user_id) if campaign and has_credit_purchase else None
        max_success = _safe_int(
            campaign.get("max_successful_referrals_per_user") if campaign else None,
            DEFAULT_MAX_SUCCESSFUL_REFERRALS,
        )
        successful_count = _safe_int(profile.get("successful_referrals_count") if profile else 0)
        remaining_budget = 0
        if campaign:
            remaining_budget = max(
                0,
                _safe_int(campaign.get("max_total_credits")) - _safe_int(campaign.get("credits_awarded")),
            )
        return {
            "available": bool(
                campaign
                and has_credit_purchase
                and profile
                and not profile.get("disabled_at")
                and successful_count < max_success
                and remaining_budget >= (
                    _safe_int(campaign.get("credits_per_referrer"), DEFAULT_REFERRAL_CREDITS)
                    + _safe_int(campaign.get("credits_per_referred_user"), DEFAULT_REFERRAL_CREDITS)
                )
            ),
            "referral_code": profile.get("referral_code") if profile else None,
            "successful_referrals_count": successful_count,
            "max_successful_referrals": max_success,
            "credits_per_referrer": _safe_int(campaign.get("credits_per_referrer"), DEFAULT_REFERRAL_CREDITS) if campaign else DEFAULT_REFERRAL_CREDITS,
            "credits_per_referred_user": _safe_int(campaign.get("credits_per_referred_user"), DEFAULT_REFERRAL_CREDITS) if campaign else DEFAULT_REFERRAL_CREDITS,
            "min_purchase_amount_cents": _safe_int(campaign.get("min_purchase_amount_cents"), DEFAULT_MIN_PURCHASE_AMOUNT_CENTS) if campaign else DEFAULT_MIN_PURCHASE_AMOUNT_CENTS,
            "attribution_expires_days": _safe_int(campaign.get("attribution_expires_days"), DEFAULT_ATTRIBUTION_EXPIRES_DAYS) if campaign else DEFAULT_ATTRIBUTION_EXPIRES_DAYS,
        }

    async def capture_referral(self, referred_user_id: str, referral_code: str) -> Dict[str, Any]:
        """Persist a pending referral for the authenticated user if eligible."""
        code = (referral_code or "").strip().upper()
        if not code or len(code) > 32:
            return {"accepted": False, "reason": "invalid_code"}

        campaign = await self.get_active_campaign()
        if not campaign:
            return {"accepted": False, "reason": "no_active_campaign"}

        referred_hash = _sha256(referred_user_id)
        existing = await self.directus.get_items(
            "referral_attributions",
            {"filter": {"referred_user_id_hash": {"_eq": referred_hash}}, "limit": 1},
            admin_required=True,
        )
        if existing:
            return {"accepted": False, "reason": "already_attributed"}

        profiles = await self.directus.get_items(
            "referral_profiles",
            {"filter": {"referral_code": {"_eq": code}}, "limit": 1},
            admin_required=True,
        )
        if not profiles:
            return {"accepted": False, "reason": "unknown_code"}
        profile = profiles[0]
        if profile.get("disabled_at"):
            return {"accepted": False, "reason": "disabled_code"}

        referrer_user_id = profile.get("user_id") or await self._find_user_id_by_hash(
            profile.get("user_id_hash")
        )
        if not referrer_user_id or not await self.has_credit_purchase(referrer_user_id):
            return {"accepted": False, "reason": "referrer_not_eligible"}

        referrer_hash = profile.get("user_id_hash")
        if referrer_hash == referred_hash:
            return {"accepted": False, "reason": "self_referral"}

        max_success = _safe_int(campaign.get("max_successful_referrals_per_user"), DEFAULT_MAX_SUCCESSFUL_REFERRALS)
        if _safe_int(profile.get("successful_referrals_count")) >= max_success:
            return {"accepted": False, "reason": "referrer_limit_reached"}

        expires_days = _safe_int(campaign.get("attribution_expires_days"), DEFAULT_ATTRIBUTION_EXPIRES_DAYS)
        captured_at = datetime.now(timezone.utc)
        success, created = await self.directus.create_item(
            "referral_attributions",
            {
                "campaign_id": campaign.get("id"),
                "referral_profile_id": profile.get("id"),
                "referral_code": code,
                "referrer_user_id_hash": referrer_hash,
                "referred_user_id_hash": referred_hash,
                "status": REFERRAL_STATUS_PENDING,
                "captured_at": captured_at.isoformat(),
                "expires_at": (captured_at + timedelta(days=expires_days)).isoformat(),
                "created_at": captured_at.isoformat(),
            },
            admin_required=True,
        )
        if not success or not created:
            return {"accepted": False, "reason": "create_failed"}
        return {"accepted": True, "reason": "captured"}

    async def reward_after_purchase(
        self,
        referred_user_id: str,
        referred_current_credits: int,
        referred_vault_key_id: str,
        order_id: str,
        purchase_amount_cents: int,
        stripe_customer_id: Optional[str] = None,
        payment_method_fingerprint: Optional[str] = None,
    ) -> ReferralRewardResult:
        """Award referral credits after a successful eligible purchase."""
        if not referred_user_id or not order_id:
            return ReferralRewardResult(False, reason="missing_context")

        lock_key = f"referral_reward_lock:{order_id}"
        client = await self.cache.client
        lock_acquired = False
        if client:
            lock_acquired = bool(await client.set(lock_key, "1", nx=True, ex=120))
            if not lock_acquired:
                return ReferralRewardResult(False, reason="locked_or_duplicate")

        try:
            referred_hash = _sha256(referred_user_id)
            attributions = await self.directus.get_items(
                "referral_attributions",
                {
                    "filter": {
                        "referred_user_id_hash": {"_eq": referred_hash},
                        "status": {"_eq": REFERRAL_STATUS_PENDING},
                    },
                    "limit": 1,
                },
                admin_required=True,
            )
            if not attributions:
                return ReferralRewardResult(False, reason="no_pending_attribution")
            attribution = attributions[0]

            expires_at = _parse_datetime(attribution.get("expires_at"))
            if expires_at and expires_at < datetime.now(timezone.utc):
                await self._reject_attribution(attribution, REFERRAL_STATUS_EXPIRED, "expired")
                return ReferralRewardResult(False, reason="expired")

            campaign = await self._get_item_by_id("referral_campaigns", attribution.get("campaign_id"))
            profile = await self._get_item_by_id("referral_profiles", attribution.get("referral_profile_id"))
            if not campaign or not profile or not campaign.get("is_active"):
                await self._reject_attribution(attribution, REFERRAL_STATUS_REJECTED, "campaign_unavailable")
                return ReferralRewardResult(False, reason="campaign_unavailable")

            shared_lock_keys = [
                f"referral_campaign_lock:{campaign.get('id')}",
                f"referral_profile_lock:{profile.get('id')}",
            ]
            acquired_shared_locks: list[str] = []
            if client:
                for shared_lock_key in shared_lock_keys:
                    shared_lock_acquired = bool(await client.set(shared_lock_key, "1", nx=True, ex=120))
                    if not shared_lock_acquired:
                        for acquired_key in acquired_shared_locks:
                            await client.delete(acquired_key)
                        return ReferralRewardResult(False, reason="shared_lock_busy")
                    acquired_shared_locks.append(shared_lock_key)

            min_purchase = _safe_int(campaign.get("min_purchase_amount_cents"), DEFAULT_MIN_PURCHASE_AMOUNT_CENTS)
            if purchase_amount_cents < min_purchase:
                return ReferralRewardResult(False, reason="purchase_below_minimum")

            max_success = _safe_int(campaign.get("max_successful_referrals_per_user"), DEFAULT_MAX_SUCCESSFUL_REFERRALS)
            if _safe_int(profile.get("successful_referrals_count")) >= max_success:
                await self._reject_attribution(attribution, REFERRAL_STATUS_REJECTED, "referrer_limit_reached")
                return ReferralRewardResult(False, reason="referrer_limit_reached")

            referrer_user_id = profile.get("user_id") or await self._find_user_id_by_hash(attribution.get("referrer_user_id_hash"))
            if not referrer_user_id:
                await self._reject_attribution(attribution, REFERRAL_STATUS_REJECTED, "referrer_not_found")
                return ReferralRewardResult(False, reason="referrer_not_found")

            if await self._same_stripe_customer(referrer_user_id, stripe_customer_id):
                await self._reject_attribution(attribution, REFERRAL_STATUS_REJECTED, "same_payment_customer")
                return ReferralRewardResult(False, reason="same_payment_customer")

            if payment_method_fingerprint and await self._fingerprint_already_rewarded(attribution.get("referrer_user_id_hash"), payment_method_fingerprint):
                await self._reject_attribution(attribution, REFERRAL_STATUS_REJECTED, "same_payment_method")
                return ReferralRewardResult(False, reason="same_payment_method")

            referrer_bonus = _safe_int(campaign.get("credits_per_referrer"), DEFAULT_REFERRAL_CREDITS)
            referred_bonus = _safe_int(campaign.get("credits_per_referred_user"), DEFAULT_REFERRAL_CREDITS)
            total_bonus = referrer_bonus + referred_bonus
            if _safe_int(campaign.get("credits_awarded")) + total_bonus > _safe_int(campaign.get("max_total_credits")):
                await self._reject_attribution(attribution, REFERRAL_STATUS_REJECTED, "budget_exhausted")
                return ReferralRewardResult(False, reason="budget_exhausted")

            existing_reward = await self.directus.get_items(
                "referral_rewards",
                {"filter": {"idempotency_key": {"_eq": f"{order_id}:referred"}}, "limit": 1},
                admin_required=True,
            )
            if existing_reward:
                return ReferralRewardResult(False, reason="already_rewarded")

            referrer_fields = await self.directus.get_user_fields_direct(
                referrer_user_id,
                ["vault_key_id", "encrypted_credit_balance"],
            )
            if not referrer_fields or not referrer_fields.get("vault_key_id"):
                await self._reject_attribution(attribution, REFERRAL_STATUS_REJECTED, "referrer_credit_unavailable")
                return ReferralRewardResult(False, reason="referrer_credit_unavailable")

            referrer_current = await self._decrypt_credits(
                referrer_fields.get("encrypted_credit_balance"),
                referrer_fields.get("vault_key_id"),
            )
            referred_new_total = referred_current_credits + referred_bonus
            referrer_new_total = referrer_current + referrer_bonus

            referred_encrypted, _ = await self.encryption.encrypt_with_user_key(str(referred_new_total), referred_vault_key_id)
            referrer_encrypted, _ = await self.encryption.encrypt_with_user_key(str(referrer_new_total), referrer_fields.get("vault_key_id"))
            referred_ok = await self.directus.update_user(referred_user_id, {"encrypted_credit_balance": referred_encrypted})
            referrer_ok = await self.directus.update_user(referrer_user_id, {"encrypted_credit_balance": referrer_encrypted})
            if not referred_ok or not referrer_ok:
                await self._reject_attribution(attribution, REFERRAL_STATUS_REJECTED, "credit_update_failed")
                return ReferralRewardResult(False, reason="credit_update_failed")

            fingerprint_hash = _sha256(payment_method_fingerprint) if payment_method_fingerprint else None
            await self.directus.update_item(
                "referral_attributions",
                attribution.get("id"),
                {
                    "status": REFERRAL_STATUS_REWARDED,
                    "rewarded_at": _now_iso(),
                    "rewarded_order_id": order_id,
                    "referred_stripe_customer_id_hash": _sha256(stripe_customer_id) if stripe_customer_id else None,
                    "payment_method_fingerprint_hash": fingerprint_hash,
                    "updated_at": _now_iso(),
                },
                admin_required=True,
            )
            await self.directus.update_item(
                "referral_profiles",
                profile.get("id"),
                {
                    "successful_referrals_count": _safe_int(profile.get("successful_referrals_count")) + 1,
                    "updated_at": _now_iso(),
                },
                admin_required=True,
            )
            await self.directus.update_item(
                "referral_campaigns",
                campaign.get("id"),
                {"credits_awarded": _safe_int(campaign.get("credits_awarded")) + total_bonus},
                admin_required=True,
            )
            await self._record_reward(attribution, campaign, referred_hash, "referred", referred_bonus, order_id)
            await self._record_reward(attribution, campaign, attribution.get("referrer_user_id_hash"), "referrer", referrer_bonus, order_id)

            await self.cache.update_user(referred_user_id, {"credits": referred_new_total})
            await self.cache.update_user(referrer_user_id, {"credits": referrer_new_total})
            return ReferralRewardResult(
                True,
                referred_bonus=referred_bonus,
                referrer_bonus=referrer_bonus,
                referred_new_total=referred_new_total,
                referrer_user_id=referrer_user_id,
                referrer_new_total=referrer_new_total,
            )
        except Exception as exc:
            logger.error("Referral reward failed for order %s: %s", order_id, exc, exc_info=True)
            return ReferralRewardResult(False, reason="exception")
        finally:
            if client:
                for shared_lock_key in locals().get("acquired_shared_locks", []):
                    await client.delete(shared_lock_key)
            if client and lock_acquired:
                await client.delete(lock_key)

    async def _get_item_by_id(self, collection: str, item_id: Optional[str]) -> Optional[Dict[str, Any]]:
        if not item_id:
            return None
        items = await self.directus.get_items(collection, {"filter": {"id": {"_eq": item_id}}, "limit": 1}, admin_required=True)
        return items[0] if items else None

    async def _reject_attribution(self, attribution: Dict[str, Any], status: str, reason: str) -> None:
        await self.directus.update_item(
            "referral_attributions",
            attribution.get("id"),
            {"status": status, "rejection_reason": reason, "updated_at": _now_iso()},
            admin_required=True,
        )

    async def _find_user_id_by_hash(self, user_id_hash: Optional[str]) -> Optional[str]:
        if not user_id_hash:
            return None
        users = await self.directus.get_items(
            "users",
            {"filter": {"id": {"_nnull": True}}, "fields": "id", "limit": -1},
            admin_required=True,
        )
        for user in users or []:
            user_id = user.get("id")
            if user_id and _sha256(user_id) == user_id_hash:
                return user_id
        return None

    async def _same_stripe_customer(self, referrer_user_id: str, referred_customer_id: Optional[str]) -> bool:
        if not referred_customer_id:
            return False
        referrer = await self.directus.get_user_fields_direct(referrer_user_id, ["stripe_customer_id"])
        return bool(referrer and referrer.get("stripe_customer_id") and referrer.get("stripe_customer_id") == referred_customer_id)

    async def _fingerprint_already_rewarded(self, referrer_user_id_hash: Optional[str], fingerprint: str) -> bool:
        if not referrer_user_id_hash or not fingerprint:
            return False
        fingerprint_hash = _sha256(fingerprint)
        rows = await self.directus.get_items(
            "referral_attributions",
            {
                "filter": {
                    "referrer_user_id_hash": {"_eq": referrer_user_id_hash},
                    "payment_method_fingerprint_hash": {"_eq": fingerprint_hash},
                    "status": {"_eq": REFERRAL_STATUS_REWARDED},
                },
                "limit": 1,
            },
            admin_required=True,
        )
        return bool(rows)

    async def _decrypt_credits(self, encrypted_value: Optional[str], vault_key_id: str) -> int:
        if not encrypted_value:
            return 0
        decrypted = await self.encryption.decrypt_with_user_key(encrypted_value, vault_key_id)
        return _safe_int(decrypted)

    async def _record_reward(
        self,
        attribution: Dict[str, Any],
        campaign: Dict[str, Any],
        recipient_user_id_hash: str,
        role: str,
        credits: int,
        order_id: str,
    ) -> None:
        await self.directus.create_item(
            "referral_rewards",
            {
                "attribution_id": attribution.get("id"),
                "campaign_id": campaign.get("id"),
                "recipient_user_id_hash": recipient_user_id_hash,
                "role": role,
                "credits_awarded": credits,
                "order_id": order_id,
                "idempotency_key": f"{order_id}:{role}",
                "created_at": _now_iso(),
            },
            admin_required=True,
        )
