"""
Bank Transfer Duplicate Reference Email Task
===========================================

Sends a transactional notice when Revolut receives a new transfer that reuses
an already-completed OpenMates bank-transfer reference. The webhook must not
grant credits twice, so this email asks the account contact to choose a credits
gift card or refund. The recipient email stays zero-knowledge and is decrypted
only with the order's stored email key.
"""

from __future__ import annotations

import asyncio
import logging

from backend.core.api.app.tasks.celery_config import app
from backend.core.api.app.utils.log_filters import SensitiveDataFilter


logger = logging.getLogger(__name__)
logger.addFilter(SensitiveDataFilter())


@app.task(
    bind=True,
    name="app.tasks.email_tasks.bank_transfer_duplicate_reference_email_task.send_bank_transfer_duplicate_reference",
    queue="email",
    max_retries=2,
    default_retry_delay=60,
)
def send_bank_transfer_duplicate_reference(
    self,
    user_id: str,
    order_id: str,
    email_encryption_key: str,
    credits_amount: int,
    reference: str,
    expected_amount_eur: str,
    received_amount_eur: str,
    total_received_eur: str,
    overpaid_amount_eur: str,
    transaction_id: str,
    support_email: str = "support@openmates.org",
) -> bool:
    return asyncio.run(
        _async_send_bank_transfer_duplicate_reference(
            user_id=user_id,
            order_id=order_id,
            email_encryption_key=email_encryption_key,
            credits_amount=credits_amount,
            reference=reference,
            expected_amount_eur=expected_amount_eur,
            received_amount_eur=received_amount_eur,
            total_received_eur=total_received_eur,
            overpaid_amount_eur=overpaid_amount_eur,
            transaction_id=transaction_id,
            support_email=support_email,
        )
    )


async def _async_send_bank_transfer_duplicate_reference(
    *,
    user_id: str,
    order_id: str,
    email_encryption_key: str,
    credits_amount: int,
    reference: str,
    expected_amount_eur: str,
    received_amount_eur: str,
    total_received_eur: str,
    overpaid_amount_eur: str,
    transaction_id: str,
    support_email: str = "support@openmates.org",
) -> bool:
    from backend.core.api.app.services.cache import CacheService
    from backend.core.api.app.services.directus import DirectusService
    from backend.core.api.app.services.email_delivery_guard import send_email_once
    from backend.core.api.app.services.email_template import EmailTemplateService
    from backend.core.api.app.utils.encryption import EncryptionService
    from backend.core.api.app.utils.secrets_manager import SecretsManager

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
                logger.error("bank_transfer_duplicate_reference: user lookup failed for order %s: %s", order_id, message)
                return False

        encrypted_email = user_cache.get("encrypted_email_address")
        language = user_cache.get("language", "en")
        darkmode = bool(user_cache.get("darkmode", False))
        if not encrypted_email or not email_encryption_key:
            logger.error("bank_transfer_duplicate_reference: missing email material for order %s", order_id)
            return False

        email = await encryption_service.decrypt_with_email_key(encrypted_email, email_encryption_key)
        if not email:
            logger.error("bank_transfer_duplicate_reference: email decryption failed for order %s", order_id)
            return False

        context = {
            "darkmode": darkmode,
            "credits_amount": f"{credits_amount:,}".replace(",", "."),
            "reference": reference,
            "expected_amount_eur": expected_amount_eur,
            "received_amount_eur": received_amount_eur,
            "total_received_eur": total_received_eur,
            "overpaid_amount_eur": overpaid_amount_eur,
            "transaction_id": transaction_id,
            "support_email": support_email,
            "support_mailto": f"mailto:{support_email}",
        }

        success, delivery_status = await send_email_once(
            directus=directus_service,
            email_template_service=email_template_service,
            email_type="bank_transfer_duplicate_reference",
            campaign_key=transaction_id,
            recipient_kind="directus_user",
            recipient_id=user_id,
            stage=order_id,
            template="bank-transfer-duplicate-reference",
            recipient_email=email,
            context=context,
            lang=language,
            sender_email=sender_email,
            subject="Duplicate bank transfer reference received",
        )
        if success or delivery_status == "already_reserved":
            logger.info("bank_transfer_duplicate_reference: sent/reserved for order %s", order_id)
            return True
        logger.warning("bank_transfer_duplicate_reference: send failed for order %s", order_id)
        return False
    except Exception as exc:
        logger.error(
            "bank_transfer_duplicate_reference: unexpected error for order %s: %s",
            order_id,
            exc,
            exc_info=True,
        )
        return False
    finally:
        await cache_service.close()
        await directus_service.close()
