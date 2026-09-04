# backend/core/api/app/tasks/email_tasks/purchase_confirmation_email_task.py
import logging
import os
import base64
import asyncio
import re
from datetime import datetime, timezone
from html import escape
from typing import Any, Optional
import hashlib
import uuid

# Imports for hybrid encryption
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# Import the Celery app and Base Task
from backend.core.api.app.tasks.celery_config import app
from backend.core.api.app.tasks.base_task import BaseServiceTask # Import from new location

# Import necessary services and utilities (ensure all needed are here)
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.s3.config import get_bucket_name
from backend.core.api.app.services.s3.service import HetznerObjectStorageError
from backend.core.api.app.utils.log_filters import SensitiveDataFilter
from backend.shared.python_utils.invoice_ciphertext_versions import (
    append_verified_invoice_ciphertext_version,
)

# Setup loggers
logger = logging.getLogger(__name__)
sensitive_filter = SensitiveDataFilter()
logger.addFilter(sensitive_filter)
event_logger = logging.getLogger("app.events")
event_logger.addFilter(sensitive_filter)

BILLING_ADMIN_ERROR_TEMPLATE = "billing-processing-error"
BILLING_ADMIN_ERROR_MESSAGE_LIMIT = 2000
BILLING_ADMIN_FIELD_LIMIT = 300
INVOICE_RECORD_CREATE_ERROR_MESSAGE = "Failed to create Directus invoice record"
INVOICE_RECORD_CREATE_RETRY_DELAY_SECONDS = 60
INVOICE_RECORD_CREATE_MAX_RETRIES = 3
INVOICE_STORAGE_RETRY_DELAY_SECONDS = 10 * 60
INVOICE_STORAGE_MAX_RETRIES = 24 * 60 // 10
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_BEARER_TOKEN_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_API_SECRET_RE = re.compile(
    r"(?i)\b(api[_-]?key|token|secret|password)\s*[:=]\s*[^,\s;]+"
)
_STRIPE_SECRET_RE = re.compile(r"\b(?:sk|rk|pk)_(?:live|test)_[A-Za-z0-9_]+\b")


class InvoiceRecordCreationError(RuntimeError):
    """Raised when the paid order was processed but its Directus document row was not created."""


def _is_retryable_invoice_record_creation_error(error: BaseException) -> bool:
    return isinstance(error, InvoiceRecordCreationError) or str(error) == INVOICE_RECORD_CREATE_ERROR_MESSAGE


def _task_retry_count(task: BaseServiceTask) -> int:
    request = getattr(task, "request", None)
    retries = getattr(request, "retries", 0)
    return retries if isinstance(retries, int) and retries >= 0 else 0


def _retry_kwargs(task: BaseServiceTask, **updates: int) -> dict[str, Any]:
    request = getattr(task, "request", None)
    request_kwargs = getattr(request, "kwargs", None)
    kwargs = dict(request_kwargs) if isinstance(request_kwargs, dict) else {}
    kwargs.update(updates)
    return kwargs


def _should_notify_storage_failure(*, retryable: bool, storage_retry_count: int) -> bool:
    return not retryable or storage_retry_count in {0, INVOICE_STORAGE_MAX_RETRIES}


def _coerce_invoice_datetime(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, (int, float)):
        parsed = datetime.fromtimestamp(value, tz=timezone.utc)
    else:
        text = str(value).strip()
        if not text:
            return None
        try:
            if text.isdigit():
                parsed = datetime.fromtimestamp(int(text), tz=timezone.utc)
            else:
                parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _resolve_invoice_datetime(
    explicit_invoice_date: Optional[str],
    payment_order_details: dict[str, Any],
) -> datetime:
    for candidate in (
        explicit_invoice_date,
        payment_order_details.get("payment_created"),
        payment_order_details.get("created"),
        payment_order_details.get("created_at"),
    ):
        resolved = _coerce_invoice_datetime(candidate)
        if resolved:
            return resolved
    return datetime.now(timezone.utc)


_PURCHASE_CONFIRMATION_USER_FIELDS = [
    "account_id",
    "vault_key_id",
    "encrypted_email_address",
    "encrypted_email_auto_topup",
    "encrypted_invoice_counter",
    "encrypted_credit_balance",
    "language",
    "country_code",
    "darkmode",
]


def _has_purchase_confirmation_profile_fields(user_profile: Any) -> bool:
    return (
        isinstance(user_profile, dict)
        and bool(user_profile.get("account_id"))
        and bool(user_profile.get("vault_key_id"))
        and bool(user_profile.get("encrypted_email_address"))
    )


async def _decrypt_optional_profile_int(
    *,
    task: BaseServiceTask,
    encrypted_value: Any,
    vault_key_id: str,
    field_name: str,
    order_id: str,
) -> Optional[int]:
    if not encrypted_value:
        return None
    try:
        decrypted_value = await task.encryption_service.decrypt_with_user_key(
            encrypted_value,
            vault_key_id,
        )
        if decrypted_value in (None, ""):
            return None
        return int(float(decrypted_value))
    except Exception as err:
        logger.warning(
            "Could not decrypt %s while preparing invoice task %s: %s",
            field_name,
            order_id,
            err,
        )
        return None


async def _get_purchase_confirmation_user_profile(
    *,
    task: BaseServiceTask,
    cache_service: CacheService,
    user_id: str,
    order_id: str,
) -> dict[str, Any]:
    user_profile = await cache_service.get_user_by_id(user_id)
    if _has_purchase_confirmation_profile_fields(user_profile):
        return user_profile

    logger.info(
        "User profile cache miss or partial profile for invoice task %s; fetching direct fields for user %s.",
        order_id,
        user_id,
    )
    direct_fields = await task.directus_service.get_user_fields_direct(
        user_id,
        _PURCHASE_CONFIRMATION_USER_FIELDS,
    )
    if not _has_purchase_confirmation_profile_fields(direct_fields):
        logger.error("Failed to fetch invoice-ready user profile for invoice task %s", order_id)
        raise Exception("Failed to fetch user profile")

    vault_key_id = direct_fields["vault_key_id"]
    refreshed_profile = dict(user_profile or {})
    for field in (
        "account_id",
        "vault_key_id",
        "encrypted_email_address",
        "encrypted_email_auto_topup",
        "language",
        "country_code",
        "darkmode",
    ):
        if direct_fields.get(field) is not None:
            refreshed_profile[field] = direct_fields[field]

    invoice_counter = await _decrypt_optional_profile_int(
        task=task,
        encrypted_value=direct_fields.get("encrypted_invoice_counter"),
        vault_key_id=vault_key_id,
        field_name="invoice_counter",
        order_id=order_id,
    )
    refreshed_profile["invoice_counter"] = invoice_counter if invoice_counter is not None else 0

    credits = await _decrypt_optional_profile_int(
        task=task,
        encrypted_value=direct_fields.get("encrypted_credit_balance"),
        vault_key_id=vault_key_id,
        field_name="credits",
        order_id=order_id,
    )
    if credits is not None:
        refreshed_profile["credits"] = credits

    if direct_fields.get("encrypted_credit_balance") is not None:
        refreshed_profile["encrypted_credit_balance"] = direct_fields["encrypted_credit_balance"]

    cache_success = await cache_service.set_user(refreshed_profile, user_id=user_id)
    if not cache_success:
        logger.warning("Could not refresh user profile cache for invoice task %s", order_id)
    return refreshed_profile


def _billing_admin_recipient() -> Optional[str]:
    return os.getenv("ADMIN_NOTIFY_EMAIL") or os.getenv("SERVER_OWNER_EMAIL")


def _sanitize_billing_admin_text(value: Any, limit: int = BILLING_ADMIN_FIELD_LIMIT) -> str:
    if value is None:
        return "unknown"

    text = str(value)
    text = _CONTROL_CHAR_RE.sub("", text)
    text = _EMAIL_RE.sub("<redacted-email>", text)
    text = _BEARER_TOKEN_RE.sub("Bearer <redacted>", text)
    text = _API_SECRET_RE.sub(r"\1=<redacted>", text)
    text = _STRIPE_SECRET_RE.sub("<redacted-stripe-key>", text)
    if len(text) > limit:
        text = f"{text[:limit]}... [truncated]"
    return escape(text)


def _hash_admin_user_id(user_id: str) -> str:
    return hashlib.sha256(user_id.encode("utf-8")).hexdigest()[:16]


async def _notify_billing_processing_error(
    *,
    task: BaseServiceTask,
    stage: str,
    order_id: str,
    user_id: str,
    credits_purchased: int,
    provider: Optional[str],
    provider_order_id: Optional[str],
    send_email: bool,
    error: BaseException | str,
    failure_provider: Optional[str] = None,
    failure_classification: Optional[str] = None,
    retryable: Optional[bool] = None,
    retry_delay_seconds: Optional[int] = None,
    retry_attempt: Optional[int] = None,
    max_retries: Optional[int] = None,
    max_attempts: Optional[int] = None,
    retries_exhausted: Optional[bool] = None,
) -> bool:
    admin_email = _billing_admin_recipient()
    if not admin_email:
        logger.error("Billing processing error notification skipped: ADMIN_NOTIFY_EMAIL/SERVER_OWNER_EMAIL is not configured")
        return False

    email_service = getattr(task, "email_template_service", None)
    if email_service is None:
        try:
            await task.initialize_services()
        except Exception as init_err:
            logger.error(
                "Billing processing error notification skipped: could not initialize email services: %s",
                init_err,
                exc_info=True,
            )
            return False
        email_service = getattr(task, "email_template_service", None)

    if email_service is None:
        logger.error("Billing processing error notification skipped: email_template_service is unavailable")
        return False

    if isinstance(error, BaseException):
        error_type = type(error).__name__
        error_message = str(error)
    else:
        error_type = "BillingProcessingError"
        error_message = str(error)

    alert_title = "Billing processing error"
    alert_summary = (
        "A billing invoice-processing task reported an error. Review the worker logs "
        "and accounting state before running any backfill."
    )
    if failure_provider and failure_classification == "external_provider_degraded":
        if retries_exhausted:
            alert_title = f"{failure_provider} retries exhausted"
            alert_summary = (
                "Payment and credits remain completed, but invoice storage retries are exhausted. "
                "Review the external provider and run the invoice recovery workflow after service restoration."
            )
        else:
            alert_title = f"{failure_provider} degraded"
            alert_summary = (
                "Payment and credits remain completed. Invoice storage is delayed by an external provider "
                "failure and will retry automatically."
            )
    elif failure_provider:
        alert_title = "Billing storage configuration error"
        alert_summary = (
            "Payment and credits remain completed, but invoice storage failed because of an internal "
            "storage configuration error. Automatic degradation retries are not scheduled."
        )

    context = {
        "darkmode": True,
        "alert_title": _sanitize_billing_admin_text(alert_title),
        "alert_summary": _sanitize_billing_admin_text(alert_summary, BILLING_ADMIN_ERROR_MESSAGE_LIMIT),
        "environment": _sanitize_billing_admin_text(
            os.getenv("SERVER_ENVIRONMENT") or os.getenv("ENVIRONMENT") or "unknown"
        ),
        "stage": _sanitize_billing_admin_text(stage),
        "order_id": _sanitize_billing_admin_text(order_id),
        "provider": _sanitize_billing_admin_text(provider or "unknown"),
        "provider_order_id": _sanitize_billing_admin_text(provider_order_id or "none"),
        "user_id_hash": _hash_admin_user_id(user_id),
        "credits_purchased": _sanitize_billing_admin_text(credits_purchased),
        "send_email": _sanitize_billing_admin_text(send_email),
        "error_type": _sanitize_billing_admin_text(error_type),
        "error_message": _sanitize_billing_admin_text(error_message, BILLING_ADMIN_ERROR_MESSAGE_LIMIT),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if failure_provider:
        context.update(
            {
                "failure_provider": _sanitize_billing_admin_text(failure_provider),
                "failure_classification": _sanitize_billing_admin_text(failure_classification),
                "retryable": _sanitize_billing_admin_text(retryable),
                "retry_delay_seconds": _sanitize_billing_admin_text(retry_delay_seconds),
                "retry_attempt": _sanitize_billing_admin_text(retry_attempt),
                "max_retries": _sanitize_billing_admin_text(max_retries),
                "max_attempts": _sanitize_billing_admin_text(max_attempts),
                "retries_exhausted": _sanitize_billing_admin_text(retries_exhausted),
            }
        )

    try:
        sent = await email_service.send_email(
            template=BILLING_ADMIN_ERROR_TEMPLATE,
            recipient_email=admin_email,
            subject=f"[OpenMates] {context['alert_title']}: {context['stage']} order {context['order_id']}",
            context=context,
            lang="en",
        )
    except Exception as notify_err:
        logger.error("Failed to send billing processing error notification: %s", notify_err, exc_info=True)
        return False

    if not sent:
        logger.error("Billing processing error notification send_email() returned False")
        return False

    logger.info(
        "Sent billing processing error notification for order %s at stage %s",
        order_id,
        stage,
    )
    return True


async def _notify_billing_processing_error_safely(**kwargs: Any) -> bool:
    try:
        return await _notify_billing_processing_error(**kwargs)
    except Exception as notify_err:
        logger.error(
            "Billing processing error notification failed and will not mask the original error: %s",
            notify_err,
            exc_info=True,
        )
        return False


@app.task(name='app.tasks.email_tasks.purchase_confirmation_email_task.process_invoice_and_send_email', base=BaseServiceTask, bind=True)
def process_invoice_and_send_email(
    self: BaseServiceTask,  # Use the custom task class type hint
    order_id: str,
    user_id: str,
    credits_purchased: int,
    sender_addressline1: str,
    sender_addressline2: str,
    sender_addressline3: str,
    sender_country: str,
    sender_email: str,
    sender_vat: str,
    email_encryption_key: Optional[str] = None,  # Add email encryption key parameter
    is_gift_card: bool = False,  # Flag to indicate if this is a gift card purchase
    is_auto_topup: bool = False,  # Flag to indicate if this is auto top-up (use server-side email decryption)
    provider: Optional[str] = None,  # Payment provider/mode — controls PDF document type
    provider_order_id: Optional[str] = None,  # Provider-specific refundable payment ID
    send_email: bool = True,  # Backfills can generate records/PDFs without notifying users
    gift_card_code: Optional[str] = None,  # Generated code for gift-card purchase confirmation emails
    invoice_date: Optional[str] = None,  # Original provider payment date for historical backfills
    storage_retry_count: int = 0,
    invoice_record_retry_count: int = 0,
) -> bool:
    """
    Celery task to generate invoice/payment confirmation, upload to S3, save to Directus, and send email.

    For Stripe Managed Payments the PDF title is "Payment Confirmation" (not "Invoice") because
    Stripe/Link as Merchant of Record issues the real tax invoice.
    For direct Stripe orders the PDF title remains "Invoice".
    """
    logger.info(f"Starting invoice processing task for Order ID: {order_id}, User ID: {user_id}, Provider: {provider}")
    try:
        # Use asyncio.run() which handles loop creation and cleanup
        result = asyncio.run(
            _async_process_invoice_and_send_email(
                self, order_id, user_id, credits_purchased,
                sender_addressline1, sender_addressline2, sender_addressline3,
                sender_country, sender_email, sender_vat,
                email_encryption_key, is_gift_card, is_auto_topup, provider,
                provider_order_id,
                send_email,
                gift_card_code,
                invoice_date,
                storage_retry_count,
            )
        )
        logger.info(f"Invoice processing task completed for Order ID: {order_id}, User ID: {user_id}. Success: {result}")
        return result
    except Exception as e:
        logger.error(f"Failed to run invoice processing task for Order ID: {order_id}, User ID: {user_id}: {str(e)}", exc_info=True)
        if isinstance(e, HetznerObjectStorageError) and e.retryable:
            if storage_retry_count >= INVOICE_STORAGE_MAX_RETRIES:
                logger.error(
                    "Hetzner Object Storage invoice retries exhausted for order %s after %s retries",
                    order_id,
                    storage_retry_count,
                )
                raise
            celery_retry_count = _task_retry_count(self)
            remaining_storage_retries = INVOICE_STORAGE_MAX_RETRIES - storage_retry_count
            logger.warning(
                "Retrying invoice processing for order %s in %s seconds because "
                "Hetzner Object Storage is degraded (retry %s/%s)",
                order_id,
                INVOICE_STORAGE_RETRY_DELAY_SECONDS,
                storage_retry_count + 1,
                INVOICE_STORAGE_MAX_RETRIES,
            )
            raise self.retry(
                exc=e,
                countdown=INVOICE_STORAGE_RETRY_DELAY_SECONDS,
                max_retries=celery_retry_count + remaining_storage_retries,
                kwargs=_retry_kwargs(
                    self,
                    storage_retry_count=storage_retry_count + 1,
                    invoice_record_retry_count=invoice_record_retry_count,
                ),
            )
        if _is_retryable_invoice_record_creation_error(e):
            if invoice_record_retry_count >= INVOICE_RECORD_CREATE_MAX_RETRIES:
                raise
            celery_retry_count = _task_retry_count(self)
            remaining_record_retries = (
                INVOICE_RECORD_CREATE_MAX_RETRIES - invoice_record_retry_count
            )
            logger.warning(
                "Retrying invoice processing for order %s after Directus invoice row creation failed",
                order_id,
            )
            raise self.retry(
                exc=e,
                countdown=INVOICE_RECORD_CREATE_RETRY_DELAY_SECONDS,
                max_retries=celery_retry_count + remaining_record_retries,
                kwargs=_retry_kwargs(
                    self,
                    storage_retry_count=storage_retry_count,
                    invoice_record_retry_count=invoice_record_retry_count + 1,
                ),
            )
        raise

async def _async_process_invoice_and_send_email(
    task: BaseServiceTask,  # Use the custom task class type hint
    order_id: str,
    user_id: str,
    credits_purchased: int,
    sender_addressline1: str,
    sender_addressline2: str,
    sender_addressline3: str,
    sender_country: str,
    sender_email: str,
    sender_vat: str,
    email_encryption_key: Optional[str] = None,  # Add email encryption key parameter
    is_gift_card: bool = False,  # Flag to indicate if this is a gift card purchase
    is_auto_topup: bool = False,  # Flag to indicate if this is auto top-up (use server-side email decryption)
    provider: Optional[str] = None,  # Payment provider/mode
    provider_order_id: Optional[str] = None,  # Provider-specific refundable payment ID
    send_email: bool = True,
    gift_card_code: Optional[str] = None,
    invoice_date: Optional[str] = None,
    storage_retry_count: int = 0,
) -> bool:
    """
    Async implementation for invoice processing.
    """
    cache_service = None # Initialize cache_service variable
    try:
        # 1. Initialize all necessary services using the base task class method
        await task.initialize_services()
        logger.info(f"Services initialized for invoice task {order_id}")

        # Initialize CacheService separately (as it's not part of BaseServiceTask init)
        cache_service = CacheService()

        # 2. Fetch User Details (Email, Vault Key, Preferences) - Cache First
        user_profile = await _get_purchase_confirmation_user_profile(
            task=task,
            cache_service=cache_service,
            user_id=user_id,
            order_id=order_id,
        )

        # --- Extract user details from profile (same as before) ---
        encrypted_email = user_profile.get("encrypted_email_address")
        vault_key_id = user_profile.get("vault_key_id")
        user_language = user_profile.get("language")
        country_code = user_profile.get("country_code")
        user_darkmode = user_profile.get("darkmode")
        current_invoice_counter = user_profile.get("invoice_counter")

        if not encrypted_email or not vault_key_id:
            logger.error(f"Missing encrypted_email_address or vault_key_id for user in invoice task {order_id}.")
            raise Exception("Missing user encryption details")
        logger.info(f"User profile details extracted for {user_id}")

        # 3. Fetch Full Order Details from PaymentService
        # Bank transfer orders (provider="bank_transfer") are not stored in Stripe.
        # Supply synthetic order details directly instead of calling payment_service.get_order().
        if provider == "bank_transfer":
            payment_order_details = {
                "amount": credits_purchased,  # not cents — used only for reference; actual amount below
                "currency": "eur",
                "payments": [],  # no card payment
            }
            # Retrieve the actual amount from the pending_bank_transfers Directus record
            try:
                bt_records = await task.directus_service.get_items(
                    "pending_bank_transfers",
                    params={"filter[order_id][_eq]": order_id, "fields": "amount_expected_cents,currency", "limit": 1}
                )
                if bt_records:
                    payment_order_details["amount"] = bt_records[0].get("amount_expected_cents", credits_purchased * 100)
                    payment_order_details["currency"] = bt_records[0].get("currency", "eur")
            except Exception as bt_err:
                logger.warning(f"Could not fetch bank transfer amount for {order_id}: {bt_err}")
            logger.info(f"Bank transfer order details synthesised for {order_id}")
        else:
            order_lookup_id = provider_order_id if provider == "stripe_managed" and provider_order_id else order_id
            payment_order_details = await task.payment_service.get_order(order_lookup_id)
            if not payment_order_details:
                logger.error(f"Failed to fetch payment order details for {order_lookup_id} in invoice task.")
                raise Exception("Failed to fetch payment order details")
            logger.info(f"Payment order details fetched for {order_lookup_id}")

        # 4. Extract Payment Details (same as before)
        payment_method_details = {}
        # Accept both "COMPLETED" and "CAPTURED" as successful payment states
        # This logic might need adjustment based on the specific payment provider's response structure
        # PaymentService's get_order should normalize the response to some extent.
        # Assuming 'payments' key still exists and 'state' is consistent.
        successful_payment = next(
            (p for p in payment_order_details.get('payments', [])
             if p.get('state', '').upper() in ('COMPLETED', 'CAPTURED', 'SUCCEEDED')), # Added SUCCEEDED for Stripe
            None
        )

        if successful_payment:
            payment_method_details = successful_payment.get('payment_method', {})
        elif provider != "bank_transfer":
            logger.warning(f"Could not find a COMPLETED/CAPTURED/SUCCEEDED payment in order {order_id} details. Invoice may lack payment info.")

        cardholder_name = payment_method_details.get('cardholder_name')
        card_last_four = payment_method_details.get('card_last_four')
        card_brand = payment_method_details.get('card_brand')
        # For bank transfers: show "SEPA Bank Transfer" as the payment method
        if provider == "bank_transfer" and not card_brand:
            card_brand = "SEPA Bank Transfer"

        # Format card brand name for display
        formatted_card_brand = card_brand if card_brand else ""
        if card_brand and provider != "bank_transfer":
            card_brand_lower = card_brand.lower()
            if card_brand_lower == 'visa':
                formatted_card_brand = 'VISA'
            elif card_brand_lower == 'mastercard':
                formatted_card_brand = 'MasterCard'
            elif card_brand_lower == 'american_express':
                formatted_card_brand = 'American Express'
            # Add more mappings if needed, otherwise keep original if not matched

        amount_paid = payment_order_details.get('amount') # Smallest unit
        currency_paid = payment_order_details.get('currency')
        stripe_customer_id = payment_order_details.get('customer')

        if amount_paid is None or currency_paid is None:
            logger.error(f"Missing amount or currency in payment order details for {order_id}. Cannot generate invoice.")
            raise Exception("Missing amount/currency in payment order details")
        logger.info(f"Payment details extracted for {order_id}: Amount={amount_paid} {currency_paid}")

        # Determine the effective provider for this order.
        # The `provider` argument is passed from the webhook handler via the task payload.
        # Fall back to the active provider name on the payment service for backwards compatibility
        # with orders created before this field existed.
        effective_provider = provider or task.payment_service.provider_name

        # Determine PDF document type:
        # - Stripe Managed Payments: "payment_confirmation" (Stripe/Link is MoR)
        # - Direct Stripe / unknown: "invoice"
        document_type = "payment_confirmation" if effective_provider == "stripe_managed" else "invoice"
        logger.info(f"Invoice task for order {order_id}: provider={effective_provider}, document_type={document_type}")

        # Create customer portal link for subscription management — Stripe only.
        customer_portal_url = None
        if effective_provider == "stripe" and stripe_customer_id and is_auto_topup:
            try:
                customer_portal_url = await task.payment_service.get_customer_portal_url(
                    customer_id=stripe_customer_id,
                    return_url="https://openmates.org/settings/billing"
                )
                logger.info(f"Generated customer portal URL for auto top-up order {order_id}")
            except Exception as portal_err:
                logger.warning(f"Failed to generate customer portal URL for order {order_id}: {portal_err}")

        # 5. Generate Invoice Number using counter from user profile
        # Generate user_id_hash (deterministic)
        user_id_hash = hashlib.sha256(user_id.encode('utf-8')).hexdigest()
        logger.info("Generated user_id_hash for user")

        # Increment the counter for the new invoice, defaulting to 0 if None
        base_counter = current_invoice_counter if current_invoice_counter is not None else 0
        new_invoice_counter = base_counter + 1

        # Cache update will happen *after* successful Directus update below.

        # Use account ID instead of user_id_last_8 for invoice numbering
        account_id = user_profile.get("account_id")
        if not account_id:
            logger.error(f"Missing account_id for user in invoice task {order_id}.")
            raise Exception("Missing account_id for user")
        
        invoice_counter_str = str(new_invoice_counter) # Use the incremented counter
        invoice_number = f"{account_id}-{invoice_counter_str}"
        logger.info(f"Generated invoice number: {invoice_number}")

        # Get date components for filenames and invoice data. Historical
        # backfills must preserve the original provider payment date.
        invoice_datetime = _resolve_invoice_datetime(invoice_date, payment_order_details)
        date_str_iso = invoice_datetime.date().isoformat()
        date_str_filename = date_str_iso.replace('-', '_')
        directus_invoice_date = invoice_datetime.isoformat()

        # 6. Prepare Invoice Data Dictionary (using service from BaseTask)
        # Decrypt email - different approach for auto top-up vs manual purchases
        decrypted_email = None

        invoice_data = {
            'invoice_number': invoice_number,
            'date_of_issue': date_str_iso,
            'date_due': date_str_iso,
            'receiver_account_id': account_id,
            'credits': credits_purchased,
            'card_name': formatted_card_brand,
            'card_last4': card_last_four if card_last_four else "xxxx",
            'is_gift_card': is_gift_card,
            'customer_portal_url': customer_portal_url  # Add management link to PDF
        }

        if is_auto_topup:
            # Auto top-up: use server-side vault decryption
            logger.info(f"Auto top-up invoice task {order_id} - using server-side email decryption")

            # Try auto top-up specific email first
            encrypted_email_auto_topup = user_profile.get("encrypted_email_auto_topup")
            if encrypted_email_auto_topup:
                try:
                    decrypted_email = await task.encryption_service.decrypt_with_user_key(
                        ciphertext=encrypted_email_auto_topup,
                        key_id=vault_key_id
                    )
                    if decrypted_email:
                        logger.info(f"Successfully decrypted auto top-up email for invoice task {order_id}")
                    else:
                        logger.warning(f"Vault decryption returned empty for auto top-up email in invoice task {order_id}")
                except Exception as auto_email_error:
                    logger.warning(f"Failed to decrypt auto top-up email for invoice task {order_id}: {auto_email_error}")

            # No fallback to `encrypted_email_address` here:
            # `encrypted_email_address` is client-side encrypted (TweetNaCl secretbox) and requires the
            # client-provided `email_encryption_key`, which is not available for background auto top-ups.
            if not decrypted_email:
                logger.error(
                    f"Missing/undecryptable encrypted_email_auto_topup for auto top-up invoice task {order_id}; "
                    f"cannot decrypt encrypted_email_address server-side without client key."
                )

        else:
            # Manual purchase: use client-provided email key
            if email_encryption_key:
                logger.info(f"Decrypting email using client-provided email encryption key for invoice task {order_id}")
                decrypted_email = await task.encryption_service.decrypt_with_email_key(encrypted_email, email_encryption_key)
            elif send_email and provider != "bank_transfer":
                # Non-bank-transfer email sends require the client key. No-email
                # backfills can still create the Directus row/PDF without it.
                logger.error(f"Missing email_encryption_key for invoice task {order_id}. Cannot decrypt user email.")
                raise Exception("Missing email encryption key")

            # Bank transfer fallback: if client key missing or decryption failed,
            # try server-side Vault decryption via encrypted_email_auto_topup.
            # This covers users who enabled auto-topup (key stored server-side)
            # and edge cases where the client key was unavailable at order creation.
            if not decrypted_email and provider == "bank_transfer":
                logger.info(f"Bank transfer invoice {order_id}: trying server-side email fallback")
                encrypted_email_auto_topup = user_profile.get("encrypted_email_auto_topup")
                if encrypted_email_auto_topup:
                    try:
                        decrypted_email = await task.encryption_service.decrypt_with_user_key(
                            ciphertext=encrypted_email_auto_topup, key_id=vault_key_id
                        )
                        if decrypted_email:
                            logger.info(f"Bank transfer invoice {order_id}: server-side fallback succeeded")
                    except Exception as fallback_err:
                        logger.warning(f"Bank transfer invoice {order_id}: server-side fallback failed: {fallback_err}")

        if not decrypted_email and send_email:
            logger.error(f"Failed to decrypt email for invoice task {order_id}. Auto top-up: {is_auto_topup}")
            raise Exception("Failed to decrypt user email")
        if not decrypted_email:
            logger.info("Continuing invoice backfill for %s without decrypted email", order_id)
            decrypted_email = ""

        # TODO For consumers, we only show the email address of the receiver.
        # For future "teams" functionality, we would show full name, address, and VAT.
        receiver_name_display = "" # Set to empty string to avoid duplication with receiver_email
        # receiver_name_display = ""
        # if cardholder_name:
        #     receiver_name_display = cardholder_name
        # elif country_code:
        #     # Attempt to get full country name from translation service
        #     translated_country_name = task.translation_service.get_nested_translation(
        #         f"countries.{country_code.upper()}", lang=user_language
        #     )
        #     # If translation service returns the key itself (meaning not found), use the code
        #     if translated_country_name and translated_country_name != f"countries.{country_code.upper()}":
        #         receiver_name_display = translated_country_name
        #     else:
        #         receiver_name_display = country_code # Fallback to code if translation not found
        # else:
        #     receiver_name_display = decrypted_email # Fallback to email if no name or country

        # Determine receiver_country (full name) - only needed for full address display
        # receiver_country_display = ""
        # if country_code:
        #     translated_country_name = task.translation_service.get_nested_translation(
        #         f"countries.{country_code.upper()}", lang=user_language
        #     )
        #     if translated_country_name and translated_country_name != f"countries.{country_code.upper()}":
        #         receiver_country_display = translated_country_name
        #     else:
        #         receiver_country_display = country_code # Fallback to code if translation not found
        
        # For Merchant-of-Record orders, pass the actual amount charged (in smallest
        # currency unit) so the PDF displays what the buyer paid, regardless of currency.
        # For direct Stripe orders this is not set; the PDF looks up the EU price.
        actual_amount_paid: Optional[float] = None
        # Tax/net amounts for MoR payment confirmations when the provider exposes them.
        actual_tax_amount: Optional[float] = None
        # Net amount (before tax, in display units) — subtotal for the PDF.
        actual_net_amount: Optional[float] = None

        if effective_provider == "stripe_managed" and amount_paid is not None and currency_paid is not None:
            # Convert from smallest unit to display unit.
            # Zero-decimal currencies (e.g. JPY, KRW) use the amount as-is; all others divide by 100.
            # We use a known list of zero-decimal currencies to handle this correctly.
            ZERO_DECIMAL_CURRENCIES = {"jpy", "krw", "vnd", "clp", "gnf", "mga", "pyg", "rwf", "ugx", "xaf", "xof"}
            is_zero_decimal = currency_paid.lower() in ZERO_DECIMAL_CURRENCIES

            if is_zero_decimal:
                actual_amount_paid = float(amount_paid)
            else:
                actual_amount_paid = float(amount_paid) / 100.0

            # Extract tax_amount from providers that expose it (nullable int, in cents).
            raw_tax_amount = payment_order_details.get("tax_amount")
            if raw_tax_amount is not None:
                if is_zero_decimal:
                    actual_tax_amount = float(raw_tax_amount)
                else:
                    actual_tax_amount = float(raw_tax_amount) / 100.0
                # Derive net amount: total - tax
                actual_net_amount = actual_amount_paid - actual_tax_amount
            else:
                # No tax data available — treat as 0% tax (net = total)
                actual_tax_amount = 0.0
                actual_net_amount = actual_amount_paid

            logger.info(
                f"MoR order {order_id}: actual_amount_paid={actual_amount_paid} "
                f"actual_tax_amount={actual_tax_amount} actual_net_amount={actual_net_amount} "
                f"{currency_paid.upper()} (from provider amount={amount_paid}, tax_amount={raw_tax_amount})"
            )

        invoice_data = {
            "invoice_number": invoice_number,
            "date_of_issue": date_str_iso,  # Use formatted date
            "date_due": date_str_iso,       # Same as issue date
            "receiver_name": receiver_name_display, # Now an empty string
            "receiver_account_id": user_profile.get("account_id"),  # Use account ID instead of email
            "credits": credits_purchased,
            "card_name": formatted_card_brand,
            "card_last4": card_last_four,
            # qr_code_url will be set in PDF service using domain from config
            # Inject sender details from task payload
            "sender_addressline1": sender_addressline1,
            "sender_addressline2": sender_addressline2,
            "sender_addressline3": sender_addressline3,
            "sender_country": sender_country,
            "sender_email": sender_email,
            "sender_vat": sender_vat,
            "is_gift_card": is_gift_card,  # Flag to indicate if this is a gift card purchase
            # For MoR payments: the exact amount the buyer was charged.
            # When set, overrides the pricing.yml lookup in the PDF generator.
            "actual_amount_paid": actual_amount_paid,
            # For MoR payments: actual tax amount (display units), if available.
            # When set, the PDF shows the real tax instead of "VAT (0%) *".
            "actual_tax_amount": actual_tax_amount,
            # For MoR payments: net amount before tax (display units), if available.
            # When set, the PDF uses this as the subtotal line.
            "actual_net_amount": actual_net_amount,
            # Note: refund_link will be added after invoice is created and we have the UUID
        }

        # Add billing address if available (cleaning up None values) - only for future business/teams functionality
        # if billing_address_dict:
        #     address_parts = {
        #         "receiver_address": billing_address_dict.get("street_line_1"),
        #         "receiver_address_l2": billing_address_dict.get("street_line_2"),
        #         "receiver_city": f"{billing_address_dict.get('postcode','')} {billing_address_dict.get('city','')}".strip(),
        #         "receiver_country": receiver_country_display, # Use the translated country name
        #         "receiver_region": billing_address_dict.get("region")
        #     }
        #     # Add only non-empty parts to invoice_data
        #     invoice_data.update({k: v for k, v in address_parts.items() if v})

        logger.info("Prepared invoice data dictionary")

        # 7. Generate Invoice/Payment Confirmation PDF(s)
        # Always generate English version first.
        logger.info(f"Generating English PDF ({document_type})")
        pdf_buffer_en = task.invoice_template_service.generate_invoice(
            invoice_data, lang='en', currency=currency_paid.lower(), document_type=document_type
        )
        pdf_bytes_en = pdf_buffer_en.getvalue()
        pdf_buffer_en.close()

        # Use the correct prefix in the filename to match document type
        file_prefix = "payment_confirmation" if document_type == "payment_confirmation" else "invoice"
        invoice_filename_en = f"openmates_{file_prefix}_{date_str_filename}_{invoice_number}.pdf"
        logger.info(f"Generated English PDF ({invoice_filename_en})")

        pdf_bytes_lang = None
        invoice_filename_lang = None
        # Generate translated version if language is not English
        if user_language != 'en':
            logger.info(f"Generating PDF in user language '{user_language}' ({document_type})")
            try:
                # Fetch translation key based on document_type
                translations = task.translation_service.get_translations(user_language, ["invoices_and_credit_notes"])
                if document_type == "payment_confirmation":
                    doc_translation = translations.get("invoices_and_credit_notes", {}).get("payment_confirmation", {}).get("text", "payment_confirmation")
                else:
                    doc_translation = translations.get("invoices_and_credit_notes", {}).get("invoice", {}).get("text", "invoice")
                doc_translation_lower = doc_translation.lower().replace(" ", "_")

                pdf_buffer_lang = task.invoice_template_service.generate_invoice(
                    invoice_data, lang=user_language, currency=currency_paid.lower(), document_type=document_type
                )
                pdf_bytes_lang = pdf_buffer_lang.getvalue()
                pdf_buffer_lang.close()
                invoice_filename_lang = f"openmates_{doc_translation_lower}_{date_str_filename}_{invoice_number}.pdf"
                logger.info(f"Generated PDF ({invoice_filename_lang}) in language {user_language}")
            except Exception as lang_pdf_err:
                logger.error(f"Failed to generate PDF in language {user_language}: {lang_pdf_err}", exc_info=True)
                # Continue without the translated version if generation fails

        # 8. Encrypt English PDF and Upload to S3 with unique filename
        # --- Hybrid Encryption Start ---
        logger.info("Starting hybrid encryption for PDF")

        # 8a. Generate local symmetric key and nonce
        aes_key = os.urandom(32) # AES-256 key
        nonce = os.urandom(12)   # AES-GCM standard nonce size
        logger.debug("Generated local AES key and nonce")

        # 8b. Encrypt PDF locally using AES-GCM
        aesgcm = AESGCM(aes_key)
        encrypted_pdf_payload = aesgcm.encrypt(nonce, pdf_bytes_en, None) # No associated data
        logger.debug("Locally encrypted PDF payload using AES-GCM")

        # 8c. Encrypt (wrap) the local AES key using Vault user key
        # Base64 encode the raw AES key bytes before passing to Vault string encryption
        aes_key_b64 = base64.b64encode(aes_key).decode('utf-8')
        encrypted_aes_key_vault, _ = await task.encryption_service.encrypt_with_user_key(
            aes_key_b64, vault_key_id
        )
        if not encrypted_aes_key_vault:
            logger.error("Failed to encrypt (wrap) local AES key using Vault for user")
            raise Exception("Failed to wrap symmetric encryption key")
        logger.debug(f"Wrapped local AES key using Vault user key {vault_key_id}")
        # --- Hybrid Encryption End ---

        # Generate unique filename for S3
        random_unique_id = uuid.uuid4().hex
        s3_object_key = f"{date_str_filename}_{random_unique_id}.pdf" # Keep .pdf extension for clarity if needed, though content is encrypted
        logger.info(f"Generated unique S3 filename: {s3_object_key}")

        logger.info(f"Uploading encrypted invoice {s3_object_key} to S3")
        upload_result = await task.s3_service.upload_file(
            bucket_key='invoices',
            file_key=s3_object_key,
            content=encrypted_pdf_payload, # Upload locally encrypted PDF payload (raw bytes)
            content_type='application/octet-stream' # Content type is now generic encrypted bytes
        )
        # Note: The S3 URL might not be directly usable for viewing the encrypted file without decryption.
        # We store the encrypted filename in Directus instead of the URL.
        s3_url = upload_result.get('url') # Keep for logging/potential future use, but don't rely on it for direct access
        upload_success = bool(s3_url) # Check if the upload call returned a URL structure, indicating success from the service perspective
        if not upload_success:
             # Log the raw result if available for debugging
            logger.error(f"Failed to upload encrypted invoice PDF to S3 for invoice. Upload result: {upload_result}")
            raise Exception("Failed to upload encrypted invoice PDF to S3")
        logger.info(f"Uploaded encrypted invoice {s3_object_key} to S3. URL (for reference): {s3_url}")

        # 9. Prepare Directus Invoice Record Data (with encryption using service from BaseTask)
        # Use task.encryption_service here
        # Encrypt other sensitive fields as before
        encrypted_amount, _ = await task.encryption_service.encrypt_with_user_key(str(amount_paid), vault_key_id)
        encrypted_credits, _ = await task.encryption_service.encrypt_with_user_key(str(credits_purchased), vault_key_id)
        # Encrypt the S3 object key itself
        encrypted_s3_object_key, _ = await task.encryption_service.encrypt_with_user_key(s3_object_key, vault_key_id)

        if not encrypted_s3_object_key:
             logger.error(f"Failed to encrypt S3 object key {s3_object_key} for user invoice")
             raise Exception("Failed to encrypt S3 object key for Directus record")

        # Determine which filename to use (prefer language-specific if available, otherwise English)
        # The filename is used for the download, so we use the English filename as the primary one
        # since it's always generated and provides a consistent download name
        invoice_filename_to_store = invoice_filename_en
        
        # Encrypt the filename for storage
        encrypted_filename, _ = await task.encryption_service.encrypt_with_user_key(invoice_filename_to_store, vault_key_id)
        if not encrypted_filename:
            logger.error(f"Failed to encrypt filename {invoice_filename_to_store} for user invoice")
            raise Exception("Failed to encrypt filename for Directus record")

        # Base64 encode the nonce for JSON storage in Directus
        nonce_b64 = base64.b64encode(nonce).decode('utf-8')

        # Update payload with hybrid encryption details
        directus_invoice_payload = {
            "order_id": order_id,
            "user_id_hash": user_id_hash, # Store the hash instead of the raw user_id
            "date": directus_invoice_date,
            "encrypted_amount": encrypted_amount,
            "encrypted_credits_purchased": encrypted_credits,
            "encrypted_s3_object_key": encrypted_s3_object_key, # Store encrypted S3 object key
            "encrypted_aes_key": encrypted_aes_key_vault, # Store the Vault-wrapped AES key
            "encrypted_filename": encrypted_filename, # Store encrypted filename for download
            "aes_nonce": nonce_b64, # Store the base64 encoded nonce
            "is_gift_card": is_gift_card,  # Store gift card flag for invoice display
            "provider": effective_provider,  # Payment provider/mode for routing refunds correctly
            "provider_order_id": provider_order_id,  # PaymentIntent for managed Stripe refunds
        }

        # Encrypt and store the currency code so the frontend can display amounts
        # in the correct currency (instead of hardcoding "EUR").
        if currency_paid:
            try:
                encrypted_currency, _ = await task.encryption_service.encrypt_with_user_key(
                    currency_paid.lower(), vault_key_id
                )
                if encrypted_currency:
                    directus_invoice_payload["encrypted_currency"] = encrypted_currency
                    logger.info(f"Encrypted currency '{currency_paid.lower()}' for invoice {invoice_number}")
                else:
                    logger.warning(f"Failed to encrypt currency for invoice {invoice_number} — field will be null")
            except Exception as currency_enc_err:
                logger.warning(f"Error encrypting currency for invoice {invoice_number}: {currency_enc_err}")
                # Non-blocking — frontend will fall back to "EUR" for this invoice
        logger.info("Prepared Directus payload for invoice")

        # 10. Create Invoice Record in Directus (using service from BaseTask)
        # Use task.directus_service here
        create_success, created_item = await task.directus_service.create_item("invoices", directus_invoice_payload)
        if not create_success:
            logger.error(f"Failed to create invoice record in Directus for invoice {invoice_number}. Response: {created_item}")
            # Consider cleanup? Maybe delete S3 object? For now, just raise.
            raise InvoiceRecordCreationError(INVOICE_RECORD_CREATE_ERROR_MESSAGE)
        logger.info(f"Created Directus invoice record for invoice {invoice_number}")
        
        # Extract invoice UUID from created item for deep link
        invoice_uuid = None
        if isinstance(created_item, dict):
            invoice_uuid = created_item.get('id')
        elif hasattr(created_item, 'id'):
            invoice_uuid = created_item.id
        
        if not invoice_uuid:
            logger.warning(f"Could not extract invoice UUID from created_item for invoice {invoice_number}. Deep link will not be generated.")
        else:
            logger.info(f"Extracted invoice UUID: {invoice_uuid} for invoice {invoice_number}")

        # 10b. Update the invoice counter in Directus and Cache
        try:
            logger.info(f"Attempting to encrypt new invoice counter {new_invoice_counter} for user")
            # Encrypt the new counter value
            encrypted_new_counter, _ = await task.encryption_service.encrypt_with_user_key(
                str(new_invoice_counter), vault_key_id
            )
            if encrypted_new_counter:
                logger.info("Successfully encrypted new invoice counter for user.")
                # Update Directus
                update_payload = {"encrypted_invoice_counter": encrypted_new_counter}
                logger.info("Attempting to update encrypted_invoice_counter in Directus for user with new encrypted value.")
                directus_update_success = await task.directus_service.update_user(user_id, update_payload)

                if directus_update_success:
                    logger.info(f"Successfully updated encrypted_invoice_counter in Directus for user to {new_invoice_counter} (encrypted).")
                    # Now, update the cache with the new *decrypted* value
                    if cache_service:
                        try:
                            cache_update_payload = {"invoice_counter": new_invoice_counter} # Store the decrypted int
                            cache_update_success = await cache_service.update_user(user_id, cache_update_payload)
                            if cache_update_success:
                                logger.info(f"Successfully updated cache for invoice_counter for user with value {new_invoice_counter}.")
                            else:
                                logger.warning("Failed to update cache for invoice_counter for user after Directus update.")
                        except Exception as cache_err:
                            logger.error(f"Error updating cache for invoice_counter for user after Directus update: {cache_err}", exc_info=True)
                    else:
                         logger.warning("Cache service not available, skipping cache update for invoice_counter for user after Directus update.")
                else:
                    logger.error("Failed to update encrypted_invoice_counter in Directus for user. Directus update call returned failure. Cache will not be updated.")
            else:
                 logger.error(f"Failed to encrypt new invoice counter {new_invoice_counter} for user. Encryption returned None. Directus and cache will not be updated.")
        except Exception as counter_update_err:
            logger.error(f"Exception occurred during invoice counter update process for user: {counter_update_err}", exc_info=True)
            # Continue with email sending even if counter update fails, but log the error

        # 11. Now that we have the invoice UUID, regenerate the PDFs with the refund link
        # Generate refund deep link URL if invoice UUID is available
        refund_deep_link_url = None
        if invoice_uuid:
            try:
                # Load shared URLs configuration to get webapp URL
                from backend.core.api.app.services.email.config_loader import load_shared_urls
                shared_urls = load_shared_urls()

                # Determine environment (development or production)
                # Check if we're in development mode (common patterns: localhost, dev, test)
                is_dev = os.getenv("ENVIRONMENT", "production").lower() in ("development", "dev", "test") or \
                         "localhost" in os.getenv("WEBAPP_URL", "").lower()
                env_name = "development" if is_dev else "production"

                # Get webapp URL from shared config
                webapp_url = shared_urls.get('urls', {}).get('base', {}).get('webapp', {}).get(env_name)

                # Fallback to environment variable or default
                if not webapp_url:
                    webapp_url = os.getenv("WEBAPP_URL", "https://openmates.org" if not is_dev else "http://localhost:5173")

                # Generate deep link URL: {webapp_url}#settings/billing/invoices/{invoice_uuid}/refund
                refund_deep_link_url = f"{webapp_url}#settings/billing/invoices/{invoice_uuid}/refund"
                logger.info(f"Generated refund deep link URL for invoice {invoice_number}: {refund_deep_link_url[:50]}...")

                # Update invoice_data with the refund link
                invoice_data['refund_link'] = refund_deep_link_url

                # Regenerate the PDFs with the refund link
                logger.info(f"Regenerating PDFs with refund link for invoice {invoice_number}")

                # Regenerate English version (with refund link and correct document_type)
                pdf_buffer_en = task.invoice_template_service.generate_invoice(
                    invoice_data, lang='en', currency=currency_paid.lower(), document_type=document_type
                )
                pdf_bytes_en = pdf_buffer_en.getvalue()
                pdf_buffer_en.close()
                logger.info(f"Regenerated English PDF with refund link ({document_type})")

                # Regenerate translated version if language is not English
                if user_language != 'en':
                    try:
                        pdf_buffer_lang = task.invoice_template_service.generate_invoice(
                            invoice_data, lang=user_language, currency=currency_paid.lower(), document_type=document_type
                        )
                        pdf_bytes_lang = pdf_buffer_lang.getvalue()
                        pdf_buffer_lang.close()
                        logger.info(f"Regenerated PDF with refund link for invoice in language {user_language}")
                    except Exception as lang_pdf_err:
                        logger.error(f"Failed to regenerate invoice PDF in language {user_language} with refund link: {lang_pdf_err}", exc_info=True)
                        # Continue with the English version only

                # Publish only after a fresh candidate decrypts successfully from storage.
                try:
                    await append_verified_invoice_ciphertext_version(
                        task=task,
                        invoice_id=invoice_uuid,
                        user_id_hash=user_id_hash,
                        vault_key_id=vault_key_id,
                        bucket_name=get_bucket_name(
                            "invoices",
                            task.s3_service.environment,
                        ),
                        filename=invoice_filename_en,
                        pdf_bytes=pdf_bytes_en,
                    )
                    logger.info("Published verified regenerated invoice ciphertext version")
                except Exception as version_error:
                    logger.error(
                        "Failed to publish regenerated invoice ciphertext version: %s",
                        version_error,
                        exc_info=True,
                    )
                    logger.warning("The immutable original invoice remains available for download")

            except Exception as url_err:
                logger.error(f"Failed to generate refund deep link URL for invoice {invoice_number}: {url_err}", exc_info=True)
                # Continue without deep link - email will still be sent with PDFs without refund link

        email_context = {
            "darkmode": user_darkmode,
            "invoice_id": invoice_number,  # Use invoice_id instead of account_id for email template
            "document_type": document_type,
            "refund_deep_link_url": refund_deep_link_url,  # Deep link URL for refund button (for variable processor)
            "refund_link": refund_deep_link_url,  # Set refund_link directly to ensure it's used in email template
            "customer_portal_url": customer_portal_url  # Pass management link to email
        }
        if is_gift_card and gift_card_code:
            email_context["gift_card_code"] = gift_card_code
            email_context["gift_card_credits"] = credits_purchased
        logger.info("Prepared email context for invoice")

        # 12. Optionally send Purchase Confirmation Email with Attachment(s)
        attachments = []
        # Add English attachment (using the filename with date)
        attachments.append({
            "filename": invoice_filename_en,
            "content": base64.b64encode(pdf_bytes_en).decode('utf-8')
        })

        # Add translated attachment if it was generated successfully
        if pdf_bytes_lang and invoice_filename_lang:
            attachments.append({
                "filename": invoice_filename_lang,
                "content": base64.b64encode(pdf_bytes_lang).decode('utf-8')
            })
        logger.info(f"Preparing to send email with {len(attachments)} attachment(s) for invoice")

        if send_email:
            # Use task.email_template_service here
            email_success = await task.email_template_service.send_email(
                template="purchase-confirmation",
                recipient_email=decrypted_email,
                context=email_context,
                lang=user_language,
                attachments=attachments # Pass the list of attachments
            )

            if not email_success:
                logger.error(f"Failed to send purchase confirmation email for invoice to {decrypted_email[:2]}***")
                await _notify_billing_processing_error_safely(
                    task=task,
                    stage="purchase_confirmation_email",
                    order_id=order_id,
                    user_id=user_id,
                    credits_purchased=credits_purchased,
                    provider=effective_provider,
                    provider_order_id=provider_order_id,
                    send_email=send_email,
                    error="Purchase confirmation email delivery failed",
                )
                # Don't fail the whole task if email fails, but log it.
                # The invoice exists in S3 and Directus.
                return False # Indicate email sending failed

            logger.info("Successfully sent purchase confirmation email with invoice attached.")
        else:
            logger.info("Skipping purchase confirmation email for backfilled invoice %s", invoice_number)

        # 13. Notify user via WebSocket that payment is completed (credits updated and invoice sent)
        # This notification is ONLY sent for regular credit purchases, NOT for gift card purchases
        # Gift card purchases already have their own 'gift_card_created' event sent from the webhook handler
        if not is_gift_card and effective_provider != "stripe_managed":
            try:
                # Get current credits from cache to include in notification
                current_credits = user_profile.get('credits', 0)
                
                # Publish payment_completed event to user_updates channel
                # The websocket listener will pick this up and broadcast it to the client
                await cache_service.publish_event(
                    channel=f"user_updates::{user_id}",
                    event_data={
                        "event_for_client": "payment_completed",
                        "user_id_uuid": user_id,
                        "payload": {
                            "order_id": order_id,
                            "credits_purchased": credits_purchased,
                            "current_credits": current_credits
                        }
                    }
                )
                logger.info(f"Published 'payment_completed' event for user {user_id}, order {order_id} (regular credit purchase).")
            except Exception as notification_err:
                logger.error(f"Failed to publish 'payment_completed' event for user {user_id}: {notification_err}", exc_info=True)
                # Don't fail the task if notification fails - invoice was sent successfully
        else:
            logger.info(f"Skipping 'payment_completed' event for gift card purchase (order {order_id}). Gift card notification already sent via webhook.")

        # 14. Process Income Transaction in Invoice Ninja
        # Skip for managed payments: Stripe/Link is the Merchant of Record and handles
        # the official tax/accounting documents. Invoice Ninja recording is only needed
        # for direct Stripe where OpenMates is the seller of record.
        if effective_provider == "stripe_managed":
            logger.info(
                f"Skipping Invoice Ninja recording for managed Stripe order {order_id}: "
                f"Stripe/Link is MoR, individual transactions are not recorded in our accounting."
            )
        else:
            logger.info(f"Processing income transaction in Invoice Ninja for Order ID: {order_id}, provider={effective_provider}")
            try:
                # Access InvoiceNinjaService via the base task property
                invoice_ninja_service = task.invoice_ninja_service

                # Extract necessary details for Invoice Ninja
                customer_firstname = ""
                customer_lastname = ""
                if cardholder_name:  # Check if cardholder_name is not None or empty
                    if ' ' in cardholder_name:
                        name_parts = cardholder_name.split(' ', 1)
                        customer_firstname = name_parts[0]
                        customer_lastname = name_parts[-1] if len(name_parts) > 1 else ""
                    else:
                        customer_firstname = cardholder_name

                # Ensure customer_country_code is a string, even if country_code is None
                customer_country_code = country_code if country_code is not None else ""

                # Amount is in smallest unit (cents), convert to currency units
                purchase_price_value = float(amount_paid) / 100 if amount_paid is not None else 0.0

                # card_brand_lower may be unbound if no successful_payment was found above;
                # default to empty string so Invoice Ninja call doesn't fail
                card_brand_lower_safe = card_brand.lower() if card_brand else ""

                # Pass the English PDF bytes as custom_pdf_data and other required fields
                await invoice_ninja_service.process_income_transaction(
                    user_hash=user_id_hash,  # Using user_id_hash as user_hash
                    external_order_id=order_id,
                    customer_firstname=customer_firstname,
                    customer_lastname=customer_lastname,
                    customer_account_id=account_id,  # Use account_id instead of email
                    customer_country_code=customer_country_code,  # Use the sanitized country code
                    credits_value=credits_purchased,
                    currency_code=currency_paid,
                    purchase_price_value=purchase_price_value,
                    invoice_date=date_str_iso,
                    due_date=date_str_iso,
                    payment_processor=effective_provider,  # Use the resolved provider name
                    card_brand_lower=card_brand_lower_safe,
                    custom_invoice_number=invoice_number,  # Pass generated invoice number
                    custom_pdf_data=pdf_bytes_en,  # Pass the English PDF bytes
                    is_gift_card=is_gift_card  # Pass gift card flag
                )

            except Exception as ninja_err:
                logger.error(f"Error processing income transaction in Invoice Ninja: {str(ninja_err)}", exc_info=True)
                await _notify_billing_processing_error_safely(
                    task=task,
                    stage="invoice_ninja_income_transaction",
                    order_id=order_id,
                    user_id=user_id,
                    credits_purchased=credits_purchased,
                    provider=effective_provider,
                    provider_order_id=provider_order_id,
                    send_email=send_email,
                    error=ninja_err,
                )
                # Log the error but do not fail the main task

        return True # Indicate overall success if email sent and invoice processed (even if Ninja failed)

    except Exception as e:
        logger.error(f"Error in _async_process_invoice_and_send_email task for order: {str(e)}", exc_info=True)
        if isinstance(e, HetznerObjectStorageError):
            retries_exhausted = (
                e.retryable and storage_retry_count >= INVOICE_STORAGE_MAX_RETRIES
            )
            if _should_notify_storage_failure(
                retryable=e.retryable,
                storage_retry_count=storage_retry_count,
            ):
                await _notify_billing_processing_error_safely(
                    task=task,
                    stage="invoice_storage_upload",
                    order_id=order_id,
                    user_id=user_id,
                    credits_purchased=credits_purchased,
                    provider=provider,
                    provider_order_id=provider_order_id,
                    send_email=send_email,
                    error=e,
                    failure_provider=e.provider,
                    failure_classification=e.classification,
                    retryable=e.retryable,
                    retry_delay_seconds=(
                        INVOICE_STORAGE_RETRY_DELAY_SECONDS
                        if e.retryable and not retries_exhausted
                        else None
                    ),
                    retry_attempt=storage_retry_count + 1,
                    max_retries=INVOICE_STORAGE_MAX_RETRIES,
                    max_attempts=INVOICE_STORAGE_MAX_RETRIES + 1,
                    retries_exhausted=retries_exhausted,
                )
            else:
                logger.warning(
                    "Hetzner Object Storage remains degraded for invoice order %s "
                    "(attempt %s/%s); retry remains scheduled",
                    order_id,
                    storage_retry_count + 1,
                    INVOICE_STORAGE_MAX_RETRIES + 1,
                )
        else:
            await _notify_billing_processing_error_safely(
                task=task,
                stage="invoice_processing",
                order_id=order_id,
                user_id=user_id,
                credits_purchased=credits_purchased,
                provider=provider,
                provider_order_id=provider_order_id,
                send_email=send_email,
                error=e,
            )
        # Re-raise the exception so Celery knows the task failed
        raise e
    finally:
        # CRITICAL: Close async resources (like httpx clients) before the event loop closes
        # This prevents "Event loop is closed" errors and Redis connection leaks
        try:
            if cache_service:
                await cache_service.close()
            await task.cleanup_services()
            logger.debug("Task services cleaned up successfully for invoice task")
        except Exception as cleanup_error:
            logger.warning(f"Error during task cleanup: {str(cleanup_error)}")
