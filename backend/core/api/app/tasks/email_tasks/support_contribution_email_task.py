# backend/core/api/app/tasks/email_tasks/support_contribution_email_task.py
import logging
import os
import base64
import asyncio
from datetime import datetime, timezone
from typing import Optional, Any
import hashlib
import uuid

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from backend.core.api.app.tasks.celery_config import app
from backend.core.api.app.tasks.base_task import BaseServiceTask
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.pdf.support_contribution_receipt import (
    SupportContributionReceiptTemplateService,
)
from backend.core.api.app.utils.log_filters import SensitiveDataFilter
from backend.core.api.app.utils.encryption import SUPPORT_PAYMENTS_ENCRYPTION_KEY

logger = logging.getLogger(__name__)
logger.addFilter(SensitiveDataFilter())


def _format_amount_display(amount_smallest_unit: int, currency: str) -> str:
    currency_upper = (currency or "").upper()
    if currency_upper in ("EUR", "USD", "GBP"):
        return f"{amount_smallest_unit / 100:.2f} {currency_upper}"
    return f"{amount_smallest_unit} {currency_upper}"


@app.task(
    name="app.tasks.email_tasks.support_contribution_email_task.process_support_contribution_receipt_and_send_email",
    base=BaseServiceTask,
    bind=True,
)
def process_support_contribution_receipt_and_send_email(
    self: BaseServiceTask,
    order_id: str,
    user_id: str,
    sender_addressline1: str,
    sender_addressline2: str,
    sender_addressline3: str,
    sender_country: str,
    sender_email: str,
    sender_vat: str,
    email_encryption_key: Optional[str] = None,
) -> bool:
    logger.info(f"Starting support contribution receipt task for Order ID: {order_id}, User ID: {user_id}")
    try:
        return asyncio.run(
            _async_process_support_contribution_receipt_and_send_email(
                self,
                order_id=order_id,
                user_id=user_id,
                sender_addressline1=sender_addressline1,
                sender_addressline2=sender_addressline2,
                sender_addressline3=sender_addressline3,
                sender_country=sender_country,
                sender_email=sender_email,
                sender_vat=sender_vat,
                email_encryption_key=email_encryption_key,
            )
        )
    except Exception as e:
        logger.error(
            f"Failed to run support contribution receipt task for Order ID: {order_id}, User ID: {user_id}: {str(e)}",
            exc_info=True,
        )
        return False


async def _async_process_support_contribution_receipt_and_send_email(
    task: BaseServiceTask,
    order_id: str,
    user_id: str,
    sender_addressline1: str,
    sender_addressline2: str,
    sender_addressline3: str,
    sender_country: str,
    sender_email: str,
    sender_vat: str,
    email_encryption_key: Optional[str] = None,
) -> bool:
    cache_service: Optional[CacheService] = None
    try:
        await task.initialize_services()
        cache_service = CacheService()

        user_profile = await cache_service.get_user_by_id(user_id)
        if not user_profile:
            raise Exception("User not found in cache")

        encrypted_email = user_profile.get("encrypted_email_address")
        vault_key_id = user_profile.get("vault_key_id")
        user_language = user_profile.get("language") or "en"
        user_darkmode = bool(user_profile.get("darkmode"))
        current_invoice_counter = user_profile.get("invoice_counter")
        account_id = user_profile.get("account_id")

        if not vault_key_id or not account_id:
            raise Exception("Missing user encryption details (vault_key_id/account_id)")

        if not encrypted_email:
            raise Exception("Missing encrypted_email_address for user")
        if not email_encryption_key:
            raise Exception("Missing email_encryption_key for support contribution receipt task")

        decrypted_email = await task.encryption_service.decrypt_with_email_key(encrypted_email, email_encryption_key)
        if not decrypted_email:
            raise Exception("Failed to decrypt user email")

        payment_order_details = await task.payment_service.get_order(order_id)
        if not payment_order_details:
            raise Exception("Failed to fetch payment order details")

        amount_paid = payment_order_details.get("amount")
        currency_paid = payment_order_details.get("currency")
        stripe_customer_id = payment_order_details.get("customer")
        if amount_paid is None or not currency_paid:
            raise Exception("Missing amount/currency in payment order details")

        # Check if this is a recurring payment by checking the cached order
        # Only create customer portal link for recurring subscriptions (monthly support)
        customer_portal_url = None
        is_recurring = False
        if task.cache_service:
            cached_order = await task.cache_service.get_order(order_id)
            if cached_order:
                cached_is_recurring = cached_order.get("is_recurring")
                if cached_is_recurring is not None:
                    is_recurring = bool(cached_is_recurring)
        
        # Only create customer portal link for recurring Stripe subscriptions
        if is_recurring and task.payment_service.provider_name == "stripe" and stripe_customer_id:
            try:
                customer_portal_url = await task.payment_service.get_customer_portal_url(
                    customer_id=stripe_customer_id,
                    return_url="https://openmates.org/settings/support"
                )
                logger.info(f"Generated customer portal URL for recurring support subscription order {order_id}")
            except Exception as portal_err:
                logger.warning(f"Failed to generate customer portal URL for order {order_id}: {portal_err}")

        # Invoice / receipt numbering: reuse the existing per-account invoice counter scheme.
        user_id_hash = hashlib.sha256(user_id.encode("utf-8")).hexdigest()
        base_counter = current_invoice_counter if current_invoice_counter is not None else 0
        new_invoice_counter = base_counter + 1
        receipt_number = f"{account_id}-{new_invoice_counter}"

        now_utc = datetime.now(timezone.utc)
        date_str_iso = now_utc.strftime("%Y-%m-%d")
        date_str_filename = now_utc.strftime("%Y_%m_%d")

        receipt_service = await SupportContributionReceiptTemplateService.create(task.secrets_manager)
        pdf_bytes = receipt_service.generate_receipt(
            {
                "receipt_number": receipt_number,
                "date_of_issue": date_str_iso,
                "receiver_account_id": account_id,
                "description": "Supporter contribution",
                "amount_display": _format_amount_display(int(amount_paid), str(currency_paid)),
                "sender_addressline1": sender_addressline1,
                "sender_addressline2": sender_addressline2,
                "sender_addressline3": sender_addressline3,
                "sender_country": sender_country,
                "sender_email": sender_email,
                "sender_vat": sender_vat,
                "customer_portal_url": customer_portal_url,  # Pass management link to PDF
            },
            lang=user_language,
        )

        # Encrypt the PDF locally (AES-GCM) and wrap the AES key using the user's Vault key.
        # Keep the same storage format as credit purchase invoices:
        # - S3 payload: ciphertext only (no nonce prefix)
        # - Directus: store base64(nonce) + Vault-wrapped base64(aes_key)
        aes_key = os.urandom(32)  # AES-256
        nonce = os.urandom(12)  # AES-GCM standard nonce size
        aesgcm = AESGCM(aes_key)
        encrypted_pdf_payload = aesgcm.encrypt(nonce, pdf_bytes, None)

        aes_key_b64 = base64.b64encode(aes_key).decode("utf-8")
        encrypted_aes_key_vault, _ = await task.encryption_service.encrypt_with_user_key(aes_key_b64, vault_key_id)
        if not encrypted_aes_key_vault:
            raise Exception("Failed to wrap symmetric encryption key")

        random_unique_id = uuid.uuid4().hex
        s3_object_key = f"support_receipts/{date_str_filename}_{random_unique_id}.pdf"

        upload_result = await task.s3_service.upload_file(
            bucket_key="invoices",
            file_key=s3_object_key,
            content=encrypted_pdf_payload,
            content_type="application/octet-stream",
        )
        s3_url = upload_result.get("url")
        if not s3_url:
            raise Exception("Failed to upload encrypted receipt PDF to S3")

        encrypted_amount, _ = await task.encryption_service.encrypt_with_user_key(str(amount_paid), vault_key_id)
        encrypted_credits, _ = await task.encryption_service.encrypt_with_user_key("0", vault_key_id)
        encrypted_s3_object_key, _ = await task.encryption_service.encrypt_with_user_key(s3_object_key, vault_key_id)
        encrypted_filename, _ = await task.encryption_service.encrypt_with_user_key(
            f"openmates_support_receipt_{date_str_iso}_{receipt_number}.pdf", vault_key_id
        )

        if not encrypted_s3_object_key or not encrypted_filename:
            raise Exception("Failed to encrypt S3 object key/filename for Directus record")

        nonce_b64 = base64.b64encode(nonce).decode("utf-8")

        directus_invoice_payload = {
            "order_id": order_id,
            "user_id_hash": user_id_hash,
            "date": now_utc.isoformat(),
            "encrypted_amount": encrypted_amount,
            "encrypted_credits_purchased": encrypted_credits,
            "encrypted_s3_object_key": encrypted_s3_object_key,
            "encrypted_aes_key": encrypted_aes_key_vault,
            "encrypted_filename": encrypted_filename,
            "aes_nonce": nonce_b64,
            "is_gift_card": False,
        }

        create_success, created_item = await task.directus_service.create_item("invoices", directus_invoice_payload)
        if not create_success:
            raise Exception("Failed to create Directus invoice record for support contribution")

        # Update invoice counter in Directus + cache (best-effort, same approach as purchase invoice task)
        try:
            encrypted_new_counter, _ = await task.encryption_service.encrypt_with_user_key(str(new_invoice_counter), vault_key_id)
            if encrypted_new_counter:
                directus_update_success = await task.directus_service.update_user(
                    user_id, {"encrypted_invoice_counter": encrypted_new_counter}
                )
                if directus_update_success and cache_service:
                    await cache_service.update_user(user_id, {"invoice_counter": new_invoice_counter})
        except Exception as counter_update_err:
            logger.error(f"Failed to update invoice counter for support receipt {order_id}: {counter_update_err}", exc_info=True)

        email_context = {
            "darkmode": user_darkmode,
            "receipt_id": receipt_number,
            "support_amount": _format_amount_display(int(amount_paid), str(currency_paid)),
            "customer_portal_url": customer_portal_url,  # Pass management link to email
        }

        attachments = [
            {
                "filename": f"openmates_support_receipt_{date_str_iso}_{receipt_number}.pdf",
                "content": base64.b64encode(pdf_bytes).decode("utf-8"),
            }
        ]

        email_success = await task.email_template_service.send_email(
            template="support-contribution-confirmation",
            recipient_email=decrypted_email,
            context=email_context,
            lang=user_language,
            attachments=attachments,
        )
        if not email_success:
            logger.error(f"Failed to send support contribution email for receipt {receipt_number} to {decrypted_email[:2]}***")
            return False

        return True
    except Exception as e:
        logger.error(f"Error in support contribution receipt task for order {order_id}: {str(e)}", exc_info=True)
        return False


@app.task(
    name="app.tasks.email_tasks.support_contribution_email_task.process_guest_support_contribution_receipt_and_send_email",
    base=BaseServiceTask,
    bind=True,
)
def process_guest_support_contribution_receipt_and_send_email(
    self: BaseServiceTask,
    order_id: str,
    support_email: str,
    sender_addressline1: str,
    sender_addressline2: str,
    sender_addressline3: str,
    sender_country: str,
    sender_email: str,
    sender_vat: str,
) -> bool:
    logger.info(f"Starting guest support contribution receipt task for Order ID: {order_id}")
    try:
        return asyncio.run(
            _async_process_guest_support_contribution_receipt_and_send_email(
                self,
                order_id=order_id,
                support_email=support_email,
                sender_addressline1=sender_addressline1,
                sender_addressline2=sender_addressline2,
                sender_addressline3=sender_addressline3,
                sender_country=sender_country,
                sender_email=sender_email,
                sender_vat=sender_vat,
            )
        )
    except Exception as e:
        logger.error(f"Failed to run guest support contribution receipt task for Order ID: {order_id}: {str(e)}", exc_info=True)
        return False


async def _async_process_guest_support_contribution_receipt_and_send_email(
    task: BaseServiceTask,
    order_id: str,
    support_email: str,
    sender_addressline1: str,
    sender_addressline2: str,
    sender_addressline3: str,
    sender_country: str,
    sender_email: str,
    sender_vat: str,
) -> bool:
    try:
        await task.initialize_services()

        payment_order_details = await task.payment_service.get_order(order_id)
        if not payment_order_details:
            raise Exception("Failed to fetch payment order details")

        amount_paid = payment_order_details.get("amount")
        currency_paid = payment_order_details.get("currency")
        stripe_customer_id = payment_order_details.get("customer")
        if amount_paid is None or not currency_paid:
            raise Exception("Missing amount/currency in payment order details")

        # Check if this is a recurring payment by checking the cached order
        # Only create customer portal link for recurring subscriptions (monthly support)
        customer_portal_url = None
        is_recurring = False
        if task.cache_service:
            cached_order = await task.cache_service.get_order(order_id)
            if cached_order:
                cached_is_recurring = cached_order.get("is_recurring")
                if cached_is_recurring is not None:
                    is_recurring = bool(cached_is_recurring)
        
        # Only create customer portal link for recurring Stripe subscriptions
        if is_recurring and task.payment_service.provider_name == "stripe" and stripe_customer_id:
            try:
                # For guest support, use the generic support page as return URL
                customer_portal_url = await task.payment_service.get_customer_portal_url(
                    customer_id=stripe_customer_id,
                    return_url="https://openmates.org/support"
                )
                logger.info(f"Generated customer portal URL for recurring guest support subscription order {order_id}")
            except Exception as portal_err:
                logger.warning(f"Failed to generate customer portal URL for guest order {order_id}: {portal_err}")

        now_utc = datetime.now(timezone.utc)
        date_str_iso = now_utc.strftime("%Y-%m-%d")
        date_str_filename = now_utc.strftime("%Y_%m_%d")

        receipt_number = f"SUP-{order_id[-8:]}" if order_id else f"SUP-{uuid.uuid4().hex[:8]}"

        receipt_service = await SupportContributionReceiptTemplateService.create(task.secrets_manager)
        pdf_bytes = receipt_service.generate_receipt(
            {
                "receipt_number": receipt_number,
                "date_of_issue": date_str_iso,
                "receiver_email": support_email,
                "description": "Supporter contribution",
                "amount_display": _format_amount_display(int(amount_paid), str(currency_paid)),
                "sender_addressline1": sender_addressline1,
                "sender_addressline2": sender_addressline2,
                "sender_addressline3": sender_addressline3,
                "sender_country": sender_country,
                "sender_email": sender_email,
                "sender_vat": sender_vat,
                "customer_portal_url": customer_portal_url,  # Pass management link to PDF
            },
            lang="en",
        )

        # Encrypt the receipt for archival in S3 (invoices bucket only allows application/octet-stream).
        # Use a system-level Vault key to wrap the AES key so this remains independent of user accounts.
        aes_key = os.urandom(32)  # AES-256
        nonce = os.urandom(12)  # AES-GCM standard nonce size
        aesgcm = AESGCM(aes_key)
        encrypted_pdf_payload = aesgcm.encrypt(nonce, pdf_bytes, None)

        aes_key_b64 = base64.b64encode(aes_key).decode("utf-8")
        encrypted_aes_key_vault, _ = await task.encryption_service.encrypt(
            aes_key_b64,
            key_name=SUPPORT_PAYMENTS_ENCRYPTION_KEY,
        )
        if not encrypted_aes_key_vault:
            raise Exception("Failed to wrap support receipt AES key with server-side key")

        nonce_b64 = base64.b64encode(nonce).decode("utf-8")

        random_unique_id = uuid.uuid4().hex
        s3_object_key = f"support_payments/{date_str_filename}_{random_unique_id}.bin"
        upload_result = await task.s3_service.upload_file(
            bucket_key="invoices",
            file_key=s3_object_key,
            content=encrypted_pdf_payload,
            content_type="application/octet-stream",
            metadata={
                # Store decryption metadata for future administrative retrieval.
                # Note: S3 metadata values must be strings.
                "enc_key": encrypted_aes_key_vault,
                "nonce_b64": nonce_b64,
                "format": "aes-gcm+vault-transit",
            },
        )
        if not upload_result.get("url"):
            logger.warning(f"Guest support receipt upload returned no URL (order {order_id}). Continuing to email anyway.")

        email_context = {
            "darkmode": False,
            "receipt_id": receipt_number,
            "support_amount": _format_amount_display(int(amount_paid), str(currency_paid)),
            "customer_portal_url": customer_portal_url,  # Pass management link to email
        }

        attachments = [
            {
                "filename": f"openmates_support_receipt_{date_str_iso}_{receipt_number}.pdf",
                "content": base64.b64encode(pdf_bytes).decode("utf-8"),
            }
        ]

        email_success = await task.email_template_service.send_email(
            template="support-contribution-confirmation",
            recipient_email=support_email,
            context=email_context,
            lang="en",
            attachments=attachments,
        )
        if not email_success:
            logger.error(f"Failed to send guest support contribution email for receipt {receipt_number} to {support_email[:2]}***")
            return False

        return True
    except Exception as e:
        logger.error(f"Error in guest support contribution receipt task for order {order_id}: {str(e)}", exc_info=True)
        return False
