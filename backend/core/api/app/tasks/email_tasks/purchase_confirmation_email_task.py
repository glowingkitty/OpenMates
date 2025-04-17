import logging
import os
import base64
import asyncio
from datetime import datetime, timezone
from typing import Dict, Any, Optional
import json

# Import the Celery app and Base Task
from app.tasks.celery_config import app
from app.tasks.base_task import BaseServiceTask # Import from new location

# Import necessary services and utilities (ensure all needed are here)
from app.services.cache import CacheService # Needed for user caching
# DirectusService, RevolutService, EncryptionService, S3Service, InvoiceTemplateService, EmailTemplateService
# are accessed via BaseServiceTask properties
from app.utils.log_filters import SensitiveDataFilter
from app.services.s3.config import get_bucket_name

# Setup loggers
logger = logging.getLogger(__name__)
sensitive_filter = SensitiveDataFilter()
logger.addFilter(sensitive_filter)
event_logger = logging.getLogger("app.events")
event_logger.addFilter(sensitive_filter)


@app.task(name='app.tasks.email_tasks.purchase_confirmation_email_task.process_invoice_and_send_email', base=BaseServiceTask, bind=True)
def process_invoice_and_send_email(
    self: BaseServiceTask, # Use the custom task class type hint
    order_id: str,
    user_id: str,
    credits_purchased: int
) -> bool:
    """
    Celery task to generate invoice, upload to S3, save to Directus, and send email.
    """
    logger.info(f"Starting invoice processing task for Order ID: {order_id}, User ID: {user_id}")
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(
            _async_process_invoice_and_send_email(self, order_id, user_id, credits_purchased)
        )
        logger.info(f"Invoice processing task completed for Order ID: {order_id}, User ID: {user_id}. Success: {result}")
        return result
    except Exception as e:
        logger.error(f"Failed to run invoice processing task for Order ID: {order_id}, User ID: {user_id}: {str(e)}", exc_info=True)
        # Consider retrying the task based on the exception type
        # self.retry(exc=e, countdown=60) # Example retry after 60 seconds
        return False
    finally:
        loop.close()

async def _async_process_invoice_and_send_email(
    task: BaseServiceTask, # Use the custom task class type hint
    order_id: str,
    user_id: str,
    credits_purchased: int
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
        user_profile = await cache_service.get_user_by_id(user_id)
        if user_profile:
            logger.info(f"User profile for {user_id} found in cache for invoice task {order_id}.")
        else:
            logger.info(f"User profile for {user_id} not in cache. Fetching from Directus for invoice task {order_id}.")
            user_profile = await task.directus_service.get_user_profile(user_id)
            if user_profile:
                # Cache the fetched profile
                await cache_service.set_user(user_data=user_profile, user_id=user_id)
                logger.info(f"User profile for {user_id} fetched from Directus and cached.")
            else:
                logger.error(f"Failed to fetch user profile for user {user_id} from Directus in invoice task {order_id}.")
                raise Exception("User profile not found")

        # --- Extract user details from profile (same as before) ---
        encrypted_email = user_profile.get("encrypted_email_address")
        vault_key_id = user_profile.get("vault_key_id")
        user_language = user_profile.get("language", "en")
        user_darkmode = user_profile.get("darkmode", False)

        if not encrypted_email or not vault_key_id:
            logger.error(f"Missing encrypted_email_address or vault_key_id for user {user_id} in invoice task {order_id}.")
            raise Exception("Missing user encryption details")
        logger.info(f"User profile details extracted for {user_id}")

        # 3. Fetch Full Order Details from Revolut (using service from BaseTask)
        revolut_order_details = await task.revolut_service.get_order(order_id)
        if not revolut_order_details:
            logger.error(f"Failed to fetch Revolut order details for {order_id} in invoice task.")
            raise Exception("Failed to fetch Revolut order details")
        logger.info(f"Revolut order details fetched for {order_id}")

        # 4. Extract Payment Details (same as before)
        payment_method_details = {}
        billing_address_dict = None
        # Accept both "COMPLETED" and "CAPTURED" as successful payment states
        successful_payment = next(
            (p for p in revolut_order_details.get('payments', [])
             if p.get('state', '').upper() in ('COMPLETED', 'CAPTURED')),
            None
        )

        if successful_payment:
            payment_method_details = successful_payment.get('payment_method', {})
            billing_address_data = payment_method_details.get('billing_address')
            if billing_address_data:
                 billing_address_dict = {
                     "street_line_1": billing_address_data.get("street_line_1"),
                     "street_line_2": billing_address_data.get("street_line_2"),
                     "region": billing_address_data.get("region"),
                     "city": billing_address_data.get("city"),
                     "country_code": billing_address_data.get("country_code"),
                     "postcode": billing_address_data.get("postcode"),
                 }
        else:
            logger.warning(f"Could not find a COMPLETED payment in Revolut order {order_id} details. Invoice may lack payment info.")

        cardholder_name = payment_method_details.get('cardholder_name')
        card_last_four = payment_method_details.get('card_last_four')
        card_brand = payment_method_details.get('card_brand')

        # Format card brand name for display
        formatted_card_brand = card_brand if card_brand else ""
        if card_brand:
            card_brand_lower = card_brand.lower()
            if card_brand_lower == 'visa':
                formatted_card_brand = 'VISA'
            elif card_brand_lower == 'mastercard':
                formatted_card_brand = 'MasterCard'
            elif card_brand_lower == 'american_express':
                formatted_card_brand = 'American Express'
            # Add more mappings if needed, otherwise keep original if not matched

        amount_paid = revolut_order_details.get('amount') # Smallest unit
        currency_paid = revolut_order_details.get('currency')

        if amount_paid is None or currency_paid is None:
            logger.error(f"Missing amount or currency in Revolut order details for {order_id}. Cannot generate invoice.")
            raise Exception("Missing amount/currency in Revolut order details")
        logger.info(f"Payment details extracted for {order_id}: Amount={amount_paid} {currency_paid}")

        # 5. Generate Invoice Number (using service from BaseTask)
        invoice_count = 0
        try:
            query_params = {"filter[user_id][_eq]": user_id, "meta": "total_count"}
            # Use task.directus_service here
            count_response = await task.directus_service.get_items("invoices", params=query_params)
            # Fix: count_response may be a Response object, not a dict
            if isinstance(count_response, dict):
                count_data = count_response
            elif hasattr(count_response, "json"):
                # If .json is a coroutine function, await it; else, call it
                if callable(count_response.json):
                    maybe_coro = count_response.json()
                    if asyncio.iscoroutine(maybe_coro):
                        count_data = await maybe_coro
                    else:
                        count_data = maybe_coro
                else:
                    count_data = count_response.json
            else:
                count_data = count_response
            invoice_count = count_data.get("meta", {}).get("total_count", 0)
        except Exception as count_err:
            logger.error(f"Failed to count existing invoices for user {user_id}: {count_err}", exc_info=True)
            logger.warning(f"Proceeding with invoice number generation assuming count is 0 due to error.")
            invoice_count = 0

        user_id_last_8 = user_id[-8:].upper()
        invoice_counter_str = str(invoice_count + 1).zfill(3)
        invoice_number = f"{user_id_last_8}-{invoice_counter_str}"
        logger.info(f"Generated invoice number for user {user_id}, order {order_id}: {invoice_number}")

        # Get date components for filenames and invoice data
        now_utc = datetime.now(timezone.utc)
        date_str_iso = now_utc.strftime('%Y-%m-%d')
        date_str_filename = now_utc.strftime('%Y_%m_%d')

        # 6. Prepare Invoice Data Dictionary (using service from BaseTask)
        # Decrypt email now for receiver_email field
        # Use task.encryption_service here
        decrypted_email = await task.encryption_service.decrypt_with_user_key(encrypted_email, vault_key_id)
        if not decrypted_email:
             logger.error(f"Failed to decrypt email for user {user_id} in invoice task {order_id}.")
             raise Exception("Failed to decrypt user email")

        invoice_data = {
            "invoice_number": invoice_number,
            "date_of_issue": date_str_iso, # Use formatted date
            "date_due": date_str_iso, # Same as issue date
            "receiver_name": cardholder_name, # Use fetched user name
            "receiver_email": decrypted_email, # Use decrypted email
            "credits": credits_purchased,
            "card_name": formatted_card_brand, # Use formatted brand name
            "card_last4": card_last_four, # Can be None
            "qr_code_url": "https://app.openmates.org"
        }

        logger.info('Invoice data:')
        logger.info(invoice_data.copy()) # Log the invoice data for debugging
        # Add billing address if available (cleaning up None values)
        if billing_address_dict:
            address_parts = {
                "receiver_address": billing_address_dict.get("street_line_1"),
                "receiver_address_l2": billing_address_dict.get("street_line_2"),
                "receiver_city": f"{billing_address_dict.get('postcode','')} {billing_address_dict.get('city','')}".strip(),
                "receiver_country": billing_address_dict.get("country_code"),
                "receiver_region": billing_address_dict.get("region")
            }
            # Add only non-empty parts to invoice_data
            invoice_data.update({k: v for k, v in address_parts.items() if v})

        logger.info(f"Prepared invoice data dictionary for {invoice_number}")

        # 7. Generate Invoice PDF(s)
        # Always generate English version first
        logger.info(f"Generating English invoice PDF for {invoice_number}")
        pdf_buffer_en = task.invoice_template_service.generate_invoice(
            invoice_data, lang='en', currency=currency_paid.lower()
        )
        pdf_bytes_en = pdf_buffer_en.getvalue()
        pdf_buffer_en.close()
        invoice_filename_en = f"openmates_invoice_{date_str_filename}_{invoice_number}.pdf"
        logger.info(f"Generated English PDF ({invoice_filename_en}) for invoice {invoice_number}")

        pdf_bytes_lang = None
        invoice_filename_lang = None
        # Generate translated version if language is not English
        if user_language != 'en':
            logger.info(f"Generating invoice PDF in user language '{user_language}' for {invoice_number}")
            try:
                # Fetch translation for "invoice"
                translations = await task.translation_service.get_translations(user_language, ["invoices_and_credit_notes"])
                # Safely get translation, default to "invoice"
                invoice_translation = translations.get("invoices_and_credit_notes", {}).get("invoice", {}).get("text", "invoice")
                invoice_translation_lower = invoice_translation.lower().replace(" ", "_") # Ensure lowercase and replace spaces

                pdf_buffer_lang = task.invoice_template_service.generate_invoice(
                    invoice_data, lang=user_language, currency=currency_paid.lower()
                )
                pdf_bytes_lang = pdf_buffer_lang.getvalue()
                pdf_buffer_lang.close()
                invoice_filename_lang = f"openmates_{invoice_translation_lower}_{date_str_filename}_{invoice_number}.pdf"
                logger.info(f"Generated PDF ({invoice_filename_lang}) for invoice {invoice_number} in language {user_language}")
            except Exception as lang_pdf_err:
                logger.error(f"Failed to generate or get translation for invoice PDF in language {user_language} for {invoice_number}: {lang_pdf_err}", exc_info=True)
                # Continue without the translated version if generation fails

        # 8. Upload ONLY English PDF to S3
        s3_object_key = invoice_filename_en # Use the English filename with date for S3 key
        logger.info(f"Uploading English invoice {s3_object_key} to S3")
        upload_result = await task.s3_service.upload_file(
            bucket_key='invoices',
            file_key=s3_object_key,
            content=pdf_bytes_en, # Upload English PDF bytes
            content_type='application/pdf'
        )
        s3_url = upload_result.get('url')
        upload_success = bool(s3_url)
        if not upload_success or not s3_url:
            logger.error(f"Failed to upload English invoice PDF to S3 for invoice {invoice_number}. URL: {s3_url}")
            raise Exception("Failed to upload English invoice PDF to S3")
        logger.info(f"Uploaded English invoice {s3_object_key} to S3: {s3_url}")

        # 9. Prepare Directus Invoice Record Data (with encryption using service from BaseTask)
        # Note: s3_url now always refers to the English PDF URL
        # Use task.encryption_service here
        encrypted_amount, _ = await task.encryption_service.encrypt_with_user_key(str(amount_paid), vault_key_id)
        encrypted_pdf_url, _ = await task.encryption_service.encrypt_with_user_key(s3_url, vault_key_id)
        encrypted_credits, _ = await task.encryption_service.encrypt_with_user_key(str(credits_purchased), vault_key_id)
        encrypted_payment_ref, _ = await task.encryption_service.encrypt_with_user_key(invoice_number, vault_key_id) # Using invoice_number as payment ref

        directus_invoice_payload = {
            "user_id": user_id,
            "date": datetime.now(timezone.utc).isoformat(),
            "encrypted_amount": encrypted_amount,
            "encrypted_pdf_url": encrypted_pdf_url,
            "encrypted_credits_purchased": encrypted_credits,
            "encrypted_payment_reference": encrypted_payment_ref,
            "vault_key_id": vault_key_id
        }
        logger.info(f"Prepared Directus payload for invoice {invoice_number}")

        # 10. Create Invoice Record in Directus (using service from BaseTask)
        # Use task.directus_service here
        create_success, created_item = await task.directus_service.create_item("invoices", directus_invoice_payload)
        if not create_success:
            logger.error(f"Failed to create invoice record in Directus for invoice {invoice_number}. Response: {created_item}")
            # Consider cleanup? Maybe delete S3 object? For now, just raise.
            raise Exception("Failed to create Directus invoice record")
        logger.info(f"Created Directus invoice record for invoice {invoice_number}")

        # 11. Prepare Email Context
        email_context = {
            "darkmode": user_darkmode
        }
        logger.info(f"Prepared email context for invoice {invoice_number}")

        # 12. Send Purchase Confirmation Email with Attachment(s)
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
        logger.info(f"Preparing to send email with {len(attachments)} attachment(s) for invoice {invoice_number}")

        # Use task.email_template_service here
        email_success = await task.email_template_service.send_email(
            template="purchase-confirmation",
            recipient_email=decrypted_email,
            context=email_context,
            lang=user_language,
            attachments=attachments # Pass the list of attachments
        )

        if not email_success:
            logger.error(f"Failed to send purchase confirmation email for invoice {invoice_number} to {decrypted_email[:2]}***")
            # Don't fail the whole task if email fails, but log it.
            # The invoice exists in S3 and Directus.
            return False # Indicate email sending failed

        logger.info(f"Successfully sent purchase confirmation email with invoice {invoice_number} attached.")
        return True

    except Exception as e:
        logger.error(f"Error in _async_process_invoice_and_send_email task for order {order_id}: {str(e)}", exc_info=True)
        # Re-raise the exception so Celery knows the task failed
        raise e