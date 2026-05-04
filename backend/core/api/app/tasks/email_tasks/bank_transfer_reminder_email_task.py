"""
Bank Transfer Reminder Email Task

Sends an email with bank transfer details to the user immediately after they
initiate a SEPA bank transfer during signup. This ensures they have the IBAN,
BIC, reference, and amount saved even if they navigate away from the details screen.

Only dispatched when is_signup=True on the create-bank-transfer-order endpoint.
"""

import asyncio
import logging
from datetime import datetime

from backend.core.api.app.tasks.celery_config import app
from backend.core.api.app.utils.log_filters import SensitiveDataFilter

logger = logging.getLogger(__name__)
sensitive_filter = SensitiveDataFilter()
logger.addFilter(sensitive_filter)


@app.task(
    bind=True,
    name="app.tasks.email_tasks.bank_transfer_reminder_email_task.send_bank_transfer_reminder",
    queue="email",
    max_retries=2,
    default_retry_delay=60,
)
def send_bank_transfer_reminder(
    self,
    user_id: str,
    order_id: str,
    email_encryption_key: str,
    iban: str,
    bic: str,
    account_holder_name: str,
    bank_name: str,
    amount_eur: str,
    credits_amount: int,
    reference: str,
    expires_at: str,
) -> bool:
    return asyncio.run(
        _async_send_bank_transfer_reminder(
            user_id=user_id,
            order_id=order_id,
            email_encryption_key=email_encryption_key,
            iban=iban,
            bic=bic,
            account_holder_name=account_holder_name,
            bank_name=bank_name,
            amount_eur=amount_eur,
            credits_amount=credits_amount,
            reference=reference,
            expires_at=expires_at,
        )
    )


async def _async_send_bank_transfer_reminder(
    user_id: str,
    order_id: str,
    email_encryption_key: str,
    iban: str,
    bic: str,
    account_holder_name: str,
    bank_name: str,
    amount_eur: str,
    credits_amount: int,
    reference: str,
    expires_at: str,
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

    # Look up sender email from Vault
    invoice_sender_path = "kv/data/providers/invoice_sender"
    sender_email = await secrets_manager.get_secret(
        secret_path=invoice_sender_path, secret_key="email"
    ) or "support@openmates.org"

    try:
        # Decrypt user email using the client-provided key (same pattern as purchase_confirmation_email_task)
        user_cache = await cache_service.get_user_by_id(user_id)
        if not user_cache:
            logger.error("bank_transfer_reminder: user not found in cache for order %s", order_id)
            return False

        encrypted_email = user_cache.get("encrypted_email_address")
        language = user_cache.get("language", "en")
        darkmode = bool(user_cache.get("darkmode", False))

        if not encrypted_email or not email_encryption_key:
            logger.error("bank_transfer_reminder: missing email or key for order %s", order_id)
            return False

        email = await encryption_service.decrypt_with_email_key(encrypted_email, email_encryption_key)
        if not email:
            logger.error("bank_transfer_reminder: email decryption failed for order %s", order_id)
            return False

        # Format expiry date for display
        try:
            expires_dt = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            expires_at_formatted = expires_dt.strftime("%B %d, %Y")
        except Exception:
            expires_at_formatted = expires_at[:10]

        credits_formatted = f"{credits_amount:,}".replace(",", ".")

        context = {
            "iban": iban,
            "bic": bic,
            "account_holder_name": account_holder_name,
            "bank_name": bank_name,
            "amount_eur": amount_eur,
            "credits_amount": credits_formatted,
            "reference": reference,
            "expires_at_formatted": expires_at_formatted,
            "darkmode": darkmode,
        }

        success, delivery_status = await send_email_once(
            directus=directus_service,
            email_template_service=email_template_service,
            email_type="bank_transfer_reminder",
            campaign_key=order_id,
            recipient_kind="directus_user",
            recipient_id=user_id,
            stage="created",
            template="bank-transfer-reminder",
            recipient_email=email,
            context=context,
            lang=language,
            sender_email=sender_email,
        )

        if success:
            logger.info("bank_transfer_reminder: sent for order %s", order_id)
        elif delivery_status == "already_reserved":
            logger.info("bank_transfer_reminder: already reserved for order %s", order_id)
            return True
        else:
            logger.warning("bank_transfer_reminder: send failed for order %s", order_id)

        return success

    except Exception as exc:
        logger.error("bank_transfer_reminder: unexpected error for order %s: %s", order_id, exc, exc_info=True)
        return False
    finally:
        await cache_service.close()
        await directus_service.close()
