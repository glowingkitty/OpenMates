# backend/core/api/app/tasks/email_tasks/credit_note_email_task.py
import logging
import os
import base64
import asyncio
from datetime import datetime, timezone
from typing import Optional
import hashlib
import uuid

# Imports for hybrid encryption
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# Import the Celery app and Base Task
from backend.core.api.app.tasks.celery_config import app
from backend.core.api.app.tasks.base_task import BaseServiceTask

# Import necessary services and utilities
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.utils.log_filters import SensitiveDataFilter

# Setup loggers
logger = logging.getLogger(__name__)
sensitive_filter = SensitiveDataFilter()
logger.addFilter(sensitive_filter)
event_logger = logging.getLogger("app.events")
event_logger.addFilter(sensitive_filter)


@app.task(name='app.tasks.email_tasks.credit_note_email_task.process_credit_note_and_send_email', base=BaseServiceTask, bind=True)
def process_credit_note_and_send_email(
    self: BaseServiceTask,
    invoice_id: str,
    user_id: str,
    order_id: str,
    refund_amount_cents: int,
    unused_credits: int,
    total_credits: int,
    currency: str,
    referenced_invoice_number: str,
    sender_addressline1: str,
    sender_addressline2: str,
    sender_addressline3: str,
    sender_country: str,
    sender_email: str,
    sender_vat: str,
    email_encryption_key: Optional[str] = None,
    provider: Optional[str] = None,  # Payment provider for MoR-aware document generation
) -> bool:
    """
    Celery task to generate credit note / refund confirmation PDF, upload to S3, save to Directus, and send email.

    For Polar refunds: generates a "Refund Confirmation" (not a credit note) because Polar as
    Merchant of Record issues the official credit note. Our document just confirms we deducted
    the credits on our side.
    For Stripe/Revolut refunds: generates a standard "Credit Note".
    """
    logger.info(f"Starting credit note processing task for Invoice ID: {invoice_id}, User ID: {user_id}, Provider: {provider}")
    try:
        # Use asyncio.run() which handles loop creation and cleanup
        result = asyncio.run(
            _async_process_credit_note_and_send_email(
                self, invoice_id, user_id, order_id, refund_amount_cents,
                unused_credits, total_credits, currency, referenced_invoice_number,
                sender_addressline1, sender_addressline2, sender_addressline3,
                sender_country, sender_email, sender_vat, email_encryption_key,
                provider
            )
        )
        logger.info(f"Credit note processing task completed for Invoice ID: {invoice_id}, User ID: {user_id}. Success: {result}")
        return result
    except Exception as e:
        logger.error(f"Failed to run credit note processing task for Invoice ID: {invoice_id}, User ID: {user_id}: {str(e)}", exc_info=True)
        return False


async def _async_process_credit_note_and_send_email(
    task: BaseServiceTask,
    invoice_id: str,
    user_id: str,
    order_id: str,
    refund_amount_cents: int,
    unused_credits: int,
    total_credits: int,
    currency: str,
    referenced_invoice_number: str,
    sender_addressline1: str,
    sender_addressline2: str,
    sender_addressline3: str,
    sender_country: str,
    sender_email: str,
    sender_vat: str,
    email_encryption_key: Optional[str] = None,
    provider: Optional[str] = None,  # Payment provider for MoR-aware document generation
) -> bool:
    """
    Async implementation for credit note / refund confirmation processing.
    Generates credit note PDF, uploads to S3, saves to Directus, sends email, and uploads to Invoice Ninja.
    """
    cache_service = None
    try:
        # 1. Initialize all necessary services using the base task class method
        await task.initialize_services()
        logger.info(f"Services initialized for credit note task {invoice_id}")

        # Initialize CacheService separately
        cache_service = CacheService()

        # 2. Fetch User Details (Email, Vault Key, Preferences) - Cache First
        user_profile = await cache_service.get_user_by_id(user_id)

        # Extract user details from profile
        encrypted_email = user_profile.get("encrypted_email_address")
        vault_key_id = user_profile.get("vault_key_id")
        user_language = user_profile.get("language", "en")
        country_code = user_profile.get("country_code")
        user_darkmode = user_profile.get("darkmode", False)
        account_id = user_profile.get("account_id")

        if not encrypted_email or not vault_key_id:
            logger.error(f"Missing encrypted_email_address or vault_key_id for user in credit note task {invoice_id}.")
            raise Exception("Missing user encryption details")
        logger.info(f"User profile details extracted for {user_id}")

        # 3. Decrypt email address
        # Credit note task requires email_encryption_key (same as invoice task)
        # The encrypted_email is encrypted with the email encryption key, not the user key
        if not email_encryption_key:
            logger.error(f"Missing email_encryption_key for credit note task {invoice_id}. Cannot decrypt user email.")
            raise Exception("Missing email encryption key")
            
        logger.info(f"Decrypting email using client-provided email encryption key for credit note task {invoice_id}")
        decrypted_email = await task.encryption_service.decrypt_with_email_key(encrypted_email, email_encryption_key)
            
        if not decrypted_email:
            logger.error(f"Failed to decrypt email with provided key for credit note task {invoice_id}.")
            raise Exception("Failed to decrypt user email")

        # 4. Get order details to extract payment method information
        payment_order_details = await task.payment_service.get_order(order_id)
        if not payment_order_details:
            logger.warning(f"Could not fetch order details for {order_id}, using defaults for credit note")
            card_brand_lower = "unknown"
            card_last_four = "****"
            formatted_card_brand = "Unknown"
        else:
            # Extract payment details using the same pattern as purchase confirmation task
            payment_method_details = {}
            # Accept both "COMPLETED" and "CAPTURED" as successful payment states
            successful_payment = next(
                (p for p in payment_order_details.get('payments', [])
                 if p.get('state', '').upper() in ('COMPLETED', 'CAPTURED', 'SUCCEEDED')),
                None
            )

            if successful_payment:
                payment_method_details = successful_payment.get('payment_method', {})
            else:
                logger.warning(f"Could not find a COMPLETED/CAPTURED/SUCCEEDED payment in order {order_id} details. Credit note may lack payment info.")

            # Extract card information from payment_method_details (same as invoice task)
            card_brand = payment_method_details.get('card_brand')
            card_last_four = payment_method_details.get('card_last_four')

            # Format card brand name for display (same as invoice task)
            formatted_card_brand = card_brand if card_brand else "Unknown"
            if card_brand:
                card_brand_lower = card_brand.lower()
                if card_brand_lower == 'visa':
                    formatted_card_brand = 'Visa'
                elif card_brand_lower == 'mastercard':
                    formatted_card_brand = 'MasterCard'
                elif card_brand_lower == 'american_express':
                    formatted_card_brand = 'American Express'
                # Add more mappings if needed, otherwise keep original if not matched
            else:
                card_brand_lower = "unknown"
                formatted_card_brand = "Unknown"
            
            # Ensure we have last4 digits
            if not card_last_four:
                card_last_four = "****"

        # 5. Generate credit note number (format: CN-{invoice_number})
        # Extract the invoice number part from referenced_invoice_number (format: {account_id}-{counter})
        credit_note_number = f"CN-{referenced_invoice_number}"

        # 6. Prepare credit note data
        now_utc = datetime.now(timezone.utc)
        date_str_iso = now_utc.strftime('%Y-%m-%d')
        date_str_filename = now_utc.strftime('%Y_%m_%d')

        # Calculate refund amount in decimal
        refund_amount_decimal = refund_amount_cents / 100.0 if currency.lower() in ['eur', 'usd', 'gbp'] else float(refund_amount_cents)

        credit_note_data = {
            "credit_note_number": credit_note_number,
            "date_of_issue": date_str_iso,
            "referenced_invoice": referenced_invoice_number,
            "receiver_account_id": account_id,
            "unused_credits": unused_credits,
            "total_credits": total_credits,
            "card_name": formatted_card_brand,
            "card_last4": card_last_four,
            # qr_code_url will be set in PDF service using domain from config
            "manual_refund_amount": refund_amount_decimal,  # Use the actual refund amount
            # Inject sender details from task payload
            "sender_addressline1": sender_addressline1,
            "sender_addressline2": sender_addressline2,
            "sender_addressline3": sender_addressline3,
            "sender_country": sender_country,
            "sender_email": sender_email,
            "sender_vat": sender_vat
        }

        logger.info("Prepared credit note data dictionary")

        # 7. Generate Credit Note / Refund Confirmation PDF(s)
        # For Polar: "Refund Confirmation" (Polar is MoR, issues official credit note)
        # For Stripe/Revolut: "Credit Note" (OpenMates is seller of record)
        pdf_document_type = "refund_confirmation" if provider == "polar" else "credit_note"
        logger.info(f"Generating English {pdf_document_type} PDF")
        pdf_buffer_en = task.credit_note_template_service.generate_credit_note(
            credit_note_data, lang='en', currency=currency.lower(), document_type=pdf_document_type
        )
        pdf_bytes_en = pdf_buffer_en.getvalue()
        pdf_buffer_en.close()
        # Filename reflects the document type:
        # Polar: openmates_refund_confirmation_{date}_{CN-invoice_number}.pdf
        # Stripe: openmates_credit_note_{date}_{CN-invoice_number}.pdf
        en_filename_prefix = "refund_confirmation" if provider == "polar" else "credit_note"
        credit_note_filename_en = f"openmates_{en_filename_prefix}_{date_str_filename}_{credit_note_number}.pdf"
        logger.info(f"Generated English PDF: {credit_note_filename_en}")

        pdf_bytes_lang = None
        credit_note_filename_lang = None
        # Generate translated version if language is not English
        if user_language != 'en':
            logger.info(f"Generating {pdf_document_type} PDF in user language '{user_language}'")
            try:
                # Fetch translation for the document type title
                translations = task.translation_service.get_translations(user_language, ["invoices_and_credit_notes"])
                if provider == "polar":
                    doc_type_translation = translations.get("invoices_and_credit_notes", {}).get(
                        "refund_confirmation_title", {}
                    ).get("text", "refund confirmation")
                else:
                    doc_type_translation = translations.get("invoices_and_credit_notes", {}).get(
                        "credit_note", {}
                    ).get("text", "credit note")
                doc_type_translation_lower = doc_type_translation.lower().replace(" ", "_")

                pdf_buffer_lang = task.credit_note_template_service.generate_credit_note(
                    credit_note_data, lang=user_language, currency=currency.lower(), document_type=pdf_document_type
                )
                pdf_bytes_lang = pdf_buffer_lang.getvalue()
                pdf_buffer_lang.close()
                credit_note_filename_lang = f"openmates_{doc_type_translation_lower}_{date_str_filename}_{credit_note_number}.pdf"
                logger.info(f"Generated PDF ({credit_note_filename_lang}) in language {user_language}")
            except Exception as lang_pdf_err:
                logger.error(f"Failed to generate or get translation for {pdf_document_type} PDF in language {user_language}: {lang_pdf_err}", exc_info=True)
                # Continue without the translated version if generation fails

        # 8. Encrypt English PDF and Upload to S3 with unique filename
        # --- Hybrid Encryption Start ---
        logger.info("Starting hybrid encryption for credit note PDF")

        # 8a. Generate local symmetric key and nonce
        aes_key = os.urandom(32)  # AES-256 key
        nonce = os.urandom(12)     # AES-GCM standard nonce size
        logger.debug("Generated local AES key and nonce")

        # 8b. Encrypt PDF locally using AES-GCM
        aesgcm = AESGCM(aes_key)
        encrypted_pdf_payload = aesgcm.encrypt(nonce, pdf_bytes_en, None)  # No associated data
        logger.debug("Locally encrypted PDF payload using AES-GCM")

        # 8c. Encrypt (wrap) the local AES key using Vault user key
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
        s3_object_key = f"{date_str_filename}_{random_unique_id}_credit_note.pdf"
        logger.info(f"Generated unique S3 filename: {s3_object_key}")

        logger.info(f"Uploading encrypted credit note {s3_object_key} to S3")
        upload_result = await task.s3_service.upload_file(
            bucket_key='invoices',  # Use same bucket as invoices
            file_key=s3_object_key,
            content=encrypted_pdf_payload,
            content_type='application/octet-stream'
        )
        s3_url = upload_result.get('url')
        upload_success = bool(s3_url)
        if not upload_success:
            logger.error(f"Failed to upload encrypted credit note PDF to S3. Upload result: {upload_result}")
            raise Exception("Failed to upload encrypted credit note PDF to S3")
        logger.info(f"Uploaded encrypted credit note {s3_object_key} to S3. URL (for reference): {s3_url}")

        # Publish websocket event to notify client that credit note PDF is ready for download
        # This allows the frontend to show the download button only when the PDF is actually available
        try:
            await cache_service.publish_event(
                channel=f"user_updates::{user_id}",
                event_data={
                    "event_for_client": "credit_note_ready",
                    "user_id_uuid": user_id,
                    "payload": {"invoice_id": invoice_id}
                }
            )
            logger.info(f"Published 'credit_note_ready' websocket event for invoice {invoice_id}, user {user_id}")
        except Exception as ws_pub_err:
            # Don't fail the task if websocket event publishing fails
            # The PDF is uploaded and available, just the notification failed
            logger.warning(f"Failed to publish 'credit_note_ready' websocket event for invoice {invoice_id}: {ws_pub_err}")

        # 9. Prepare Directus Credit Note Record Data (with encryption)
        encrypted_refund_amount, _ = await task.encryption_service.encrypt_with_user_key(
            str(refund_amount_cents), vault_key_id
        )
        encrypted_unused_credits, _ = await task.encryption_service.encrypt_with_user_key(
            str(unused_credits), vault_key_id
        )
        encrypted_s3_object_key, _ = await task.encryption_service.encrypt_with_user_key(s3_object_key, vault_key_id)

        if not encrypted_s3_object_key:
            logger.error(f"Failed to encrypt S3 object key {s3_object_key} for user credit note")
            raise Exception("Failed to encrypt S3 object key for Directus record")

        # Determine which filename to use (prefer language-specific if available, otherwise English)
        credit_note_filename_to_store = credit_note_filename_en

        # Encrypt the filename for storage
        encrypted_filename, _ = await task.encryption_service.encrypt_with_user_key(
            credit_note_filename_to_store, vault_key_id
        )
        if not encrypted_filename:
            logger.error(f"Failed to encrypt filename {credit_note_filename_to_store} for user credit note")
            raise Exception("Failed to encrypt filename for Directus record")

        # Base64 encode the nonce for JSON storage in Directus
        nonce_b64 = base64.b64encode(nonce).decode('utf-8')

        # Create user ID hash for lookup
        user_id_hash = hashlib.sha256(user_id.encode()).hexdigest()

        # Update payload with hybrid encryption details
        directus_credit_note_payload = {
            "invoice_id": invoice_id,  # Reference to the original invoice
            "order_id": order_id,
            "user_id_hash": user_id_hash,
            "date": now_utc.isoformat(),
            "credit_note_number": credit_note_number,
            "referenced_invoice_number": referenced_invoice_number,
            "encrypted_refund_amount": encrypted_refund_amount,
            "encrypted_unused_credits": encrypted_unused_credits,
            "encrypted_s3_object_key": encrypted_s3_object_key,
            "encrypted_aes_key": encrypted_aes_key_vault,
            "encrypted_filename": encrypted_filename,
            "aes_nonce": nonce_b64,
            "currency": currency.lower()
        }
        logger.info("Prepared Directus payload for credit note")

        # 10. Create Credit Note Record in Directus
        # Note: The 'credit_notes' collection needs to be created in Directus similar to 'invoices'
        # If the collection doesn't exist yet, we'll log a warning but continue with PDF generation and email
        try:
            create_success, created_item = await task.directus_service.create_item("credit_notes", directus_credit_note_payload)
            if not create_success:
                logger.warning(f"Failed to create credit note record in Directus for credit note {credit_note_number}. Response: {created_item}. Continuing with PDF and email...")
            else:
                logger.info(f"Created Directus credit note record for credit note {credit_note_number}")
        except Exception as directus_err:
            # Don't fail the whole task if Directus collection doesn't exist or creation fails
            # The PDF and email are more important
            logger.warning(f"Error creating credit note record in Directus (collection may not exist): {directus_err}. Continuing with PDF and email...")

        # 11. Prepare Email Context
        email_context = {
            "darkmode": user_darkmode,
            "credit_note_id": credit_note_number,
            "refund_amount": refund_amount_decimal,
            "currency": currency.upper()
        }
        logger.info("Prepared email context for credit note")

        # 12. Send Refund Confirmation Email with Attachment(s)
        attachments = []
        # Add English attachment
        attachments.append({
            "filename": credit_note_filename_en,
            "content": base64.b64encode(pdf_bytes_en).decode('utf-8')
        })

        # Add translated attachment if it was generated successfully
        if pdf_bytes_lang and credit_note_filename_lang:
            attachments.append({
                "filename": credit_note_filename_lang,
                "content": base64.b64encode(pdf_bytes_lang).decode('utf-8')
            })
        logger.info(f"Preparing to send email with {len(attachments)} attachment(s) for credit note")

        # Use task.email_template_service here
        email_success = await task.email_template_service.send_email(
            template="refund-confirmation",
            recipient_email=decrypted_email,
            context=email_context,
            lang=user_language,
            attachments=attachments
        )

        if not email_success:
            logger.error(f"Failed to send refund confirmation email for credit note to {decrypted_email[:2]}***")
            # Don't fail the whole task if email fails, but log it.
            # The credit note exists in S3 and Directus.
            return False

        logger.info("Successfully sent refund confirmation email with credit note attached.")

        # 13. Process Refund Transaction in Invoice Ninja
        # Skip for Polar: Polar is the Merchant of Record and handles all tax/accounting
        # documents including credit notes. We only need Invoice Ninja for Stripe/Revolut
        # where OpenMates is the seller of record.
        if provider == "polar":
            logger.info(
                f"Skipping Invoice Ninja refund recording for Polar refund (invoice {invoice_id}): "
                f"Polar is MoR, individual refund transactions are not recorded in our accounting."
            )
        else:
            logger.info(f"Processing refund transaction in Invoice Ninja for Invoice ID: {invoice_id}")
            try:
                # Access InvoiceNinjaService via the base task property
                invoice_ninja_service = task.invoice_ninja_service

                # Extract necessary details for Invoice Ninja
                customer_firstname = ""
                customer_lastname = ""
                # For credit notes, we don't have cardholder name, so use account ID
                if account_id:
                    customer_firstname = f"Account ID: {account_id}"
                    customer_lastname = ""

                # Ensure customer_country_code is a string
                customer_country_code = country_code if country_code is not None else ""

                # Convert refund amount from cents to decimal
                refund_amount_decimal = float(refund_amount_cents) / 100 if currency.lower() in ['eur', 'usd', 'gbp'] else float(refund_amount_cents)

                # Process refund transaction in Invoice Ninja
                invoice_ninja_service.process_refund_transaction(
                    user_hash=user_id_hash,
                    external_order_id=order_id,
                    invoice_id=invoice_id,
                    customer_firstname=customer_firstname,
                    customer_lastname=customer_lastname,
                    customer_account_id=account_id,
                    customer_country_code=customer_country_code,
                    refund_amount_value=refund_amount_decimal,
                    currency_code=currency.lower(),
                    refund_date=date_str_iso,
                    payment_processor=task.payment_service.provider_name,
                    custom_credit_note_number=credit_note_number,
                    custom_pdf_data=pdf_bytes_en,
                    referenced_invoice_number=referenced_invoice_number
                )

            except Exception as ninja_err:
                logger.error(f"Error processing refund transaction in Invoice Ninja: {str(ninja_err)}", exc_info=True)
                # Log the error but do not fail the main task

        return True  # Indicate overall success if email sent and credit note processed

    except Exception as e:
        logger.error(f"Error in _async_process_credit_note_and_send_email task for invoice: {str(e)}", exc_info=True)
        # Re-raise the exception so Celery knows the task failed
        raise e
    finally:
        # CRITICAL: Close async resources (like httpx clients) before the event loop closes
        # This prevents "Event loop is closed" errors during cleanup
        try:
            await task.cleanup_services()
            logger.debug("Task services cleaned up successfully for credit note task")
        except Exception as cleanup_error:
            logger.warning(f"Error during task cleanup: {str(cleanup_error)}")

