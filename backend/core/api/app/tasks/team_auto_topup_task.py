"""Background Team top-up. Webhook settles the Team ledger after payment succeeds."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from backend.core.api.app.services.billing_profile_service import BillingProfileService
from backend.core.api.app.services.directus.team_methods import hash_id
from backend.core.api.app.tasks.base_task import BaseServiceTask
from backend.core.api.app.tasks.celery_config import app

logger = logging.getLogger(__name__)


@app.task(name="billing.team_auto_topup", base=BaseServiceTask, bind=True)
def team_auto_topup(self: BaseServiceTask, *, team_id: str, charge_event_id: str) -> dict[str, str]:
    async def run() -> dict[str, str]:
        try:
            await self.initialize_services()
            profiles = BillingProfileService(self.directus_service, self.encryption_service)
            client = await self.cache_service.client
            if not client:
                raise RuntimeError("Auto top-up lock unavailable")
            admitted = await client.set(f"billing:team-auto-topup:{hash_id(team_id)}", charge_event_id, nx=True, ex=300)
            if not admitted:
                return {"status": "already_running"}
            profile = await profiles.get_profile("team", team_id)
            if not profile.get("auto_topup_enabled"):
                return {"status": "disabled"}
            accounts = await self.directus_service.get_items(
                "team_credit_accounts",
                params={"filter": {"hashed_team_id": {"_eq": hash_id(team_id)}}, "limit": 1},
                no_cache=True, admin_required=True,
            )
            if not accounts or int(accounts[0].get("balance_credits") or 0) > 100:
                return {"status": "balance_above_threshold"}
            last = profile.get("auto_topup_last_triggered_at")
            if last:
                try:
                    if (datetime.now(timezone.utc) - datetime.fromisoformat(str(last).replace("Z", "+00:00"))).total_seconds() < 300:
                        return {"status": "cooldown"}
                except ValueError:
                    pass
            key_id = profile.get("auto_topup_vault_key_id")
            if not key_id or not profile.get("encrypted_auto_topup_email") or not profile.get("encrypted_auto_topup_payment_method"):
                raise RuntimeError("Team auto top-up credentials unavailable")
            email = await self.encryption_service.decrypt_with_user_key(profile["encrypted_auto_topup_email"], key_id)
            method_id = await self.encryption_service.decrypt_with_user_key(profile["encrypted_auto_topup_payment_method"], key_id)
            customer_id = profile.get("stripe_customer_id")
            payer_id = profile.get("auto_topup_payer_user_id")
            amount_credits = int(profile.get("auto_topup_amount") or 0)
            currency = str(profile.get("auto_topup_currency") or "eur").lower()
            if not email or not method_id or not customer_id or not payer_id:
                raise RuntimeError("Team auto top-up profile incomplete")
            try:
                await self.directus_service.team.require_team_role(team_id, payer_id, {"owner", "admin"})
            except Exception:
                logger.warning("Disabled Team auto top-up after payer lost billing permission")
                await profiles.update_profile("team", team_id, {"auto_topup_enabled": False})
                return {"status": "payer_no_longer_admin"}
            from backend.core.api.app.routes.teams import get_price_for_credits
            amount = get_price_for_credits(amount_credits, currency)
            if amount is None:
                raise RuntimeError("Invalid Team auto top-up tier")
            import stripe
            method = await asyncio.to_thread(stripe.PaymentMethod.retrieve, method_id)
            if method.customer != customer_id:
                raise RuntimeError("Team payment method customer mismatch")
            from backend.core.api.app.utils.geo_utils import is_eu_vat_country
            if method.card and method.card.country and not is_eu_vat_country(method.card.country):
                raise RuntimeError("Team auto top-up requires EU card")
            await profiles.update_profile("team", team_id, {"auto_topup_last_triggered_at": datetime.now(timezone.utc).isoformat()})
            order = await self.payment_service.create_order(
                amount=amount, currency=currency, email=email, credits_amount=amount_credits,
                customer_id=customer_id, is_eu=True,
            )
            if not order or not order.get("id"):
                raise RuntimeError("Team auto top-up payment creation failed")
            order_id = order["id"]
            await profiles.save_order_context(
                order_id=order_id, owner_kind="team", owner_id=team_id, actor_user_id=payer_id,
                credits_amount=amount_credits, currency=currency, provider="team_auto_topup",
                vault_key_id=key_id, email_encryption_key=None, buyer_address=None,
            )
            cached = await self.cache_service.set_order(
                order_id=order_id, user_id=payer_id, credits_amount=amount_credits,
                status="auto_topup_pending", ttl=86400, currency=currency,
                provider="team_auto_topup", is_auto_topup=True,
            )
            if not cached:
                raise RuntimeError("Team auto top-up order cache unavailable")
            confirmed = await asyncio.to_thread(
                stripe.PaymentIntent.confirm, order_id, payment_method=method_id,
                return_url="https://app.openmates.com/billing/return",
            )
            if confirmed.status != "succeeded":
                await self.cache_service.update_order_status(order_id, "auto_topup_failed")
                return {"status": "payment_requires_action"}
            return {"status": "payment_confirmed", "order_id": order_id}
        finally:
            await self.cleanup_services()

    return asyncio.run(run())
