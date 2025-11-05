# backend/core/api/app/tasks/email_tasks/purchase_confirmation_email_task.py
import logging
import os
import base64
import asyncio
from datetime import datetime, timezone
from typing import Dict, Any, Optional
import json
import hashlib
import uuid

# Imports for hybrid encryption
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# Import the Celery app and Base Task
from backend.core.api.app.tasks.celery_config import app
from backend.core.api.app.tasks.base_task import BaseServiceTask # Import from new location

# Import necessary services and utilities (ensure all needed are here)
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.utils.log_filters import SensitiveDataFilter

# Setup loggers
logger = logging.getLogger(__name__)
sensitive_filter = SensitiveDataFilter()
logger.addFilter(sensitive_filter)
event_logger = logging.getLogger("app.events")
event_logger.addFilter(sensitive_filter)


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
    email_encryption_key: Optional[str] = None  # Add email encryption key parameter
) -> bool:
    """
    Celery task to generate invoice, upload to S3, save to Directus, and send email.
    """
    logger.info(f"Starting invoice processing task for Order ID: {order_id}, User ID: {user_id}")
    try:
        # Use asyncio.run() which handles loop creation and cleanup
        result = asyncio.run(
            _async_process_invoice_and_send_email(
                self, order_id, user_id, credits_purchased,
                sender_addressline1, sender_addressline2, sender_addressline3,
                sender_country, sender_email, sender_vat,
                email_encryption_key
            )
        )
        logger.info(f"Invoice processing task completed for Order ID: {order_id}, User ID: {user_id}. Success: {result}")
        return result
    except Exception as e:
        logger.error(f"Failed to run invoice processing task for Order ID: {order_id}, User ID: {user_id}: {str(e)}", exc_info=True)
        # Consider retrying the task based on the exception type
        # self.retry(exc=e, countdown=60) # Example retry after 60 seconds
        return False

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
    email_encryption_key: Optional[str] = None  # Add email encryption key parameter
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
        payment_order_details = await task.payment_service.get_order(order_id)
        if not payment_order_details:
            logger.error(f"Failed to fetch payment order details for {order_id} in invoice task.")
            raise Exception("Failed to fetch payment order details")
        logger.info(f"Payment order details fetched for {order_id}")

        # 4. Extract Payment Details (same as before)
        payment_method_details = {}
        billing_address_dict = None
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
            logger.warning(f"Could not find a COMPLETED/CAPTURED/SUCCEEDED payment in order {order_id} details. Invoice may lack payment info.")

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

        amount_paid = payment_order_details.get('amount') # Smallest unit
        currency_paid = payment_order_details.get('currency')

        if amount_paid is None or currency_paid is None:
            logger.error(f"Missing amount or currency in payment order details for {order_id}. Cannot generate invoice.")
            raise Exception("Missing amount/currency in payment order details")
        logger.info(f"Payment details extracted for {order_id}: Amount={amount_paid} {currency_paid}")

        # 5. Generate Invoice Number using counter from user profile
        # Generate user_id_hash (deterministic)
        user_id_hash = hashlib.sha256(user_id.encode('utf-8')).hexdigest()
        logger.info(f"Generated user_id_hash for user")

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

        # Get date components for filenames and invoice data
        now_utc = datetime.now(timezone.utc)
        date_str_iso = now_utc.strftime('%Y-%m-%d')
        date_str_filename = now_utc.strftime('%Y_%m_%d')

        # 6. Prepare Invoice Data Dictionary (using service from BaseTask)
        # Decrypt email now for receiver_email field using the client-provided email encryption key
        if not email_encryption_key:
            logger.error(f"Missing email_encryption_key for invoice task {order_id}. Cannot decrypt user email.")
            raise Exception("Missing email encryption key")
            
        logger.info(f"Decrypting email using client-provided email encryption key for invoice task {order_id}")
        decrypted_email = await task.encryption_service.decrypt_with_email_key(encrypted_email, email_encryption_key)
            
        if not decrypted_email:
            logger.error(f"Failed to decrypt email with provided key for invoice task {order_id}.")
            raise Exception("Failed to decrypt user email")

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
        
        invoice_data = {
            "invoice_number": invoice_number,
            "date_of_issue": date_str_iso,  # Use formatted date
            "date_due": date_str_iso,       # Same as issue date
            "receiver_name": receiver_name_display, # Now an empty string
            "receiver_account_id": user_profile.get("account_id"),  # Use account ID instead of email
            "credits": credits_purchased,
            "card_name": formatted_card_brand,
            "card_last4": card_last_four,
            "qr_code_url": "https://openmates.org",
            # Inject sender details from task payload
            "sender_addressline1": sender_addressline1,
            "sender_addressline2": sender_addressline2,
            "sender_addressline3": sender_addressline3,
            "sender_country": sender_country,
            "sender_email": sender_email,
            "sender_vat": sender_vat
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

        logger.info(f"Prepared invoice data dictionary")

        # 7. Generate Invoice PDF(s)
        # Always generate English version first
        logger.info(f"Generating English invoice PDF")
        pdf_buffer_en = task.invoice_template_service.generate_invoice(
            invoice_data, lang='en', currency=currency_paid.lower()
        )
        pdf_bytes_en = pdf_buffer_en.getvalue()
        pdf_buffer_en.close()
        invoice_filename_en = f"openmates_invoice_{date_str_filename}_{invoice_number}.pdf"
        logger.info(f"Generated English PDF for invoice")

        pdf_bytes_lang = None
        invoice_filename_lang = None
        # Generate translated version if language is not English
        if user_language != 'en':
            logger.info(f"Generating invoice PDF in user language '{user_language}' for invoice")
            try:
                # Fetch translation for "invoice"
                translations = task.translation_service.get_translations(user_language, ["invoices_and_credit_notes"])
                # Safely get translation, default to "invoice"
                invoice_translation = translations.get("invoices_and_credit_notes", {}).get("invoice", {}).get("text", "invoice")
                invoice_translation_lower = invoice_translation.lower().replace(" ", "_") # Ensure lowercase and replace spaces

                pdf_buffer_lang = task.invoice_template_service.generate_invoice(
                    invoice_data, lang=user_language, currency=currency_paid.lower()
                )
                pdf_bytes_lang = pdf_buffer_lang.getvalue()
                pdf_buffer_lang.close()
                invoice_filename_lang = f"openmates_{invoice_translation_lower}_{date_str_filename}_{invoice_number}.pdf"
                logger.info(f"Generated PDF ({invoice_filename_lang}) for invoice in language {user_language}")
            except Exception as lang_pdf_err:
                logger.error(f"Failed to generate or get translation for invoice PDF in language {user_language} for invoice: {lang_pdf_err}", exc_info=True)
                # Continue without the translated version if generation fails

        # 8. Encrypt English PDF and Upload to S3 with unique filename
        # --- Hybrid Encryption Start ---
        logger.info(f"Starting hybrid encryption for PDF")

        # 8a. Generate local symmetric key and nonce
        aes_key = os.urandom(32) # AES-256 key
        nonce = os.urandom(12)   # AES-GCM standard nonce size
        logger.debug(f"Generated local AES key and nonce")

        # 8b. Encrypt PDF locally using AES-GCM
        aesgcm = AESGCM(aes_key)
        encrypted_pdf_payload = aesgcm.encrypt(nonce, pdf_bytes_en, None) # No associated data
        logger.debug(f"Locally encrypted PDF payload using AES-GCM")

        # 8c. Encrypt (wrap) the local AES key using Vault user key
        # Base64 encode the raw AES key bytes before passing to Vault string encryption
        aes_key_b64 = base64.b64encode(aes_key).decode('utf-8')
        encrypted_aes_key_vault, _ = await task.encryption_service.encrypt_with_user_key(
            aes_key_b64, vault_key_id
        )
        if not encrypted_aes_key_vault:
            logger.error(f"Failed to encrypt (wrap) local AES key using Vault for user")
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

        # Base64 encode the nonce for JSON storage in Directus
        nonce_b64 = base64.b64encode(nonce).decode('utf-8')

        # Update payload with hybrid encryption details
        directus_invoice_payload = {
            "order_id": order_id,
            "user_id_hash": user_id_hash, # Store the hash instead of the raw user_id
            "date": datetime.now(timezone.utc).isoformat(),
            "encrypted_amount": encrypted_amount,
            "encrypted_credits_purchased": encrypted_credits,
            "encrypted_s3_object_key": encrypted_s3_object_key, # Store encrypted S3 object key
            "encrypted_aes_key": encrypted_aes_key_vault, # Store the Vault-wrapped AES key
            "aes_nonce": nonce_b64 # Store the base64 encoded nonce
        }
        logger.info(f"Prepared Directus payload for invoice")

        # 10. Create Invoice Record in Directus (using service from BaseTask)
        # Use task.directus_service here
        create_success, created_item = await task.directus_service.create_item("invoices", directus_invoice_payload)
        if not create_success:
            logger.error(f"Failed to create invoice record in Directus for invoice {invoice_number}. Response: {created_item}")
            # Consider cleanup? Maybe delete S3 object? For now, just raise.
            raise Exception("Failed to create Directus invoice record")
        logger.info(f"Created Directus invoice record for invoice {invoice_number}")

        # 10b. Update the invoice counter in Directus and Cache
        try:
            logger.info(f"Attempting to encrypt new invoice counter {new_invoice_counter} for user")
            # Encrypt the new counter value
            encrypted_new_counter, _ = await task.encryption_service.encrypt_with_user_key(
                str(new_invoice_counter), vault_key_id
            )
            if encrypted_new_counter:
                logger.info(f"Successfully encrypted new invoice counter for user.")
                # Update Directus
                update_payload = {"encrypted_invoice_counter": encrypted_new_counter}
                logger.info(f"Attempting to update encrypted_invoice_counter in Directus for user with new encrypted value.")
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
                                logger.warning(f"Failed to update cache for invoice_counter for user after Directus update.")
                        except Exception as cache_err:
                            logger.error(f"Error updating cache for invoice_counter for user after Directus update: {cache_err}", exc_info=True)
                    else:
                         logger.warning(f"Cache service not available, skipping cache update for invoice_counter for user after Directus update.")
                else:
                    logger.error(f"Failed to update encrypted_invoice_counter in Directus for user. Directus update call returned failure. Cache will not be updated.")
            else:
                 logger.error(f"Failed to encrypt new invoice counter {new_invoice_counter} for user. Encryption returned None. Directus and cache will not be updated.")
        except Exception as counter_update_err:
            logger.error(f"Exception occurred during invoice counter update process for user: {counter_update_err}", exc_info=True)
            # Continue with email sending even if counter update fails, but log the error

        # 11. Prepare Email Context
        email_context = {
            "darkmode": user_darkmode,
            "invoice_id": invoice_number  # Use invoice_id instead of account_id for email template
        }
        logger.info(f"Prepared email context for invoice")

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
        logger.info(f"Preparing to send email with {len(attachments)} attachment(s) for invoice")

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
            # Don't fail the whole task if email fails, but log it.
            # The invoice exists in S3 and Directus.
            return False # Indicate email sending failed

        logger.info(f"Successfully sent purchase confirmation email with invoice attached.")

        # 13. Process Income Transaction in Invoice Ninja
        logger.info(f"Processing income transaction in Invoice Ninja for Order ID: {order_id}")
        try:
            # Access InvoiceNinjaService via the base task property
            invoice_ninja_service = task.invoice_ninja_service

            # Extract necessary details for Invoice Ninja
            customer_firstname = ""
            customer_lastname = ""
            if cardholder_name: # Check if cardholder_name is not None or empty
                if ' ' in cardholder_name:
                    name_parts = cardholder_name.split(' ', 1)
                    customer_firstname = name_parts[0]
                    customer_lastname = name_parts[-1] if len(name_parts) > 1 else ""
                else:
                    customer_firstname = cardholder_name

            # Ensure customer_country_code is a string, even if country_code is None
            customer_country_code = country_code if country_code is not None else ""

            # Assuming payment_order_details has 'amount' and 'currency'
            # Amount is in smallest unit, need to convert to float for price
            purchase_price_value = float(amount_paid) / 100 if amount_paid is not None else 0.0

            # Pass the English PDF bytes as custom_pdf_data and other required fields
            invoice_ninja_service.process_income_transaction(
                user_hash=user_id_hash, # Using user_id_hash as user_hash
                external_order_id=order_id,
                customer_firstname=customer_firstname,
                customer_lastname=customer_lastname,
                customer_account_id=account_id,  # Use account_id instead of email
                customer_country_code=customer_country_code, # Use the sanitized country code
                credits_value=credits_purchased,
                currency_code=currency_paid,
                purchase_price_value=purchase_price_value,
                invoice_date=date_str_iso, # Pass generated invoice date
                due_date=date_str_iso, # Pass generated due date (same as invoice date)
                payment_processor=task.payment_service.provider_name, # Use the active payment provider name
                card_brand_lower=card_brand_lower,
                custom_invoice_number=invoice_number, # Pass generated invoice number
                custom_pdf_data=pdf_bytes_en # Pass the English PDF bytes
            )

        except Exception as ninja_err:
            logger.error(f"Error processing income transaction in Invoice Ninja: {str(ninja_err)}", exc_info=True)
            # Log the error but do not fail the main task

        return True # Indicate overall success if email sent and invoice processed (even if Ninja failed)

    except Exception as e:
        logger.error(f"Error in _async_process_invoice_and_send_email task for order: {str(e)}", exc_info=True)
        # Re-raise the exception so Celery knows the task failed
        raise e
