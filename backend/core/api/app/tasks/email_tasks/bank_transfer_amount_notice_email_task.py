"""
Bank Transfer Amount Notice Email Task

Sends transactional notices when Revolut Business receives a bank transfer that
does not exactly match the selected credit pack price. The settlement logic may
still complete an overpaid order, but the surplus must be resolved by support.
Underpaid orders stay pending until later transfers with the same reference
cover the selected pack price.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from backend.core.api.app.tasks.celery_config import app
from backend.core.api.app.utils.log_filters import SensitiveDataFilter


logger = logging.getLogger(__name__)
logger.addFilter(SensitiveDataFilter())


@app.task(
    bind=True,
    name="app.tasks.email_tasks.bank_transfer_amount_notice_email_task.send_bank_transfer_amount_notice",
    queue="email",
    max_retries=2,
    default_retry_delay=60,
)
def send_bank_transfer_amount_notice(
    self,
    notice_type: str,
    user_id: str,
    order_id: str,
    email_encryption_key: str,
    credits_amount: int,
    reference: str,
    expected_amount_eur: str,
    received_amount_eur: str,
    remaining_amount_eur: str,
    overpaid_amount_eur: str,
    expires_at: str = "",
    support_email: str = "support@openmates.org",
) -> bool:
    return asyncio.run(
        _async_send_bank_transfer_amount_notice(
            notice_type=notice_type,
            user_id=user_id,
            order_id=order_id,
            email_encryption_key=email_encryption_key,
            credits_amount=credits_amount,
            reference=reference,
            expected_amount_eur=expected_amount_eur,
            received_amount_eur=received_amount_eur,
            remaining_amount_eur=remaining_amount_eur,
            overpaid_amount_eur=overpaid_amount_eur,
            expires_at=expires_at,
            support_email=support_email,
        )
    )


async def _async_send_bank_transfer_amount_notice(
    *,
    notice_type: str,
    user_id: str,
    order_id: str,
    email_encryption_key: str,
    credits_amount: int,
    reference: str,
    expected_amount_eur: str,
    received_amount_eur: str,
    remaining_amount_eur: str,
    overpaid_amount_eur: str,
    expires_at: str = "",
    support_email: str = "support@openmates.org",
) -> bool:
    from backend.core.api.app.services.cache import CacheService
    from backend.core.api.app.services.directus import DirectusService
    from backend.core.api.app.services.email_delivery_guard import send_email_once
    from backend.core.api.app.services.email_template import EmailTemplateService
    from backend.core.api.app.utils.encryption import EncryptionService
    from backend.core.api.app.utils.secrets_manager import SecretsManager

    if notice_type not in {"overpaid", "underpaid"}:
        logger.error("bank_transfer_amount_notice: unsupported notice_type=%s order=%s", notice_type, order_id)
        return False

    secrets_manager = SecretsManager()
    await secrets_manager.initialize()
    cache_service = CacheService()
    directus_service = DirectusService()
    encryption_service = EncryptionService(secrets_manager)
    email_template_service = EmailTemplateService(secrets_manager)

    invoice_sender_path = "kv/data/providers/invoice_sender"
    sender_email = await secrets_manager.get_secret(
        secret_path=invoice_sender_path,
        secret_key="email",
    ) or support_email

    try:
        user_cache = await cache_service.get_user_by_id(user_id)
        if not user_cache:
            success, user_cache, message = await directus_service.get_user_profile(user_id)
            if not success or not user_cache:
                logger.error("bank_transfer_amount_notice: user lookup failed for order %s: %s", order_id, message)
                return False

        encrypted_email = user_cache.get("encrypted_email_address")
        language = user_cache.get("language", "en")
        darkmode = bool(user_cache.get("darkmode", False))
        if not encrypted_email or not email_encryption_key:
            logger.error("bank_transfer_amount_notice: missing email material for order %s", order_id)
            return False

        email = await encryption_service.decrypt_with_email_key(encrypted_email, email_encryption_key)
        if not email:
            logger.error("bank_transfer_amount_notice: email decryption failed for order %s", order_id)
            return False

        expires_at_formatted = ""
        if expires_at:
            try:
                expires_dt = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
                expires_at_formatted = expires_dt.strftime("%B %d, %Y")
            except Exception:
                expires_at_formatted = expires_at[:10]

        context = {
            "darkmode": darkmode,
            "notice_type": notice_type,
            "credits_amount": f"{credits_amount:,}".replace(",", "."),
            "reference": reference,
            "expected_amount_eur": expected_amount_eur,
            "received_amount_eur": received_amount_eur,
            "remaining_amount_eur": remaining_amount_eur,
            "overpaid_amount_eur": overpaid_amount_eur,
            "expires_at_formatted": expires_at_formatted,
            "support_email": support_email,
            "support_mailto": f"mailto:{support_email}",
        }
        subject = (
            "Your OpenMates bank transfer needs an additional payment"
            if notice_type == "underpaid"
            else "Your OpenMates bank transfer was received with an extra amount"
        )

        success, delivery_status = await send_email_once(
            directus=directus_service,
            email_template_service=email_template_service,
            email_type="bank_transfer_amount_notice",
            campaign_key=order_id,
            recipient_kind="directus_user",
            recipient_id=user_id,
            stage=f"{notice_type}:{received_amount_eur}",
            template="bank-transfer-amount-notice",
            recipient_email=email,
            context=context,
            lang=language,
            sender_email=sender_email,
            subject=subject,
        )
        if success or delivery_status == "already_reserved":
            logger.info("bank_transfer_amount_notice: %s notice sent/reserved for order %s", notice_type, order_id)
            return True
        logger.warning("bank_transfer_amount_notice: send failed for order %s", order_id)
        return False
    except Exception as exc:
        logger.error("bank_transfer_amount_notice: unexpected error for order %s: %s", order_id, exc, exc_info=True)
        return False
    finally:
        await cache_service.close()
        await directus_service.close()
