# backend/core/api/app/routes/internal_api.py
#
# This module defines FastAPI routes for internal services (e.g., apps)
# to communicate with the main API. These endpoints are secured by an
# internal service token.

import logging
from fastapi import APIRouter, HTTPException, Request, Depends, Body
from typing import Dict, Any, Optional
from pydantic import BaseModel # Ensure BaseModel is imported for Pydantic models
import os # For os.urandom in simulated transaction ID
import base64
import hashlib
import httpx
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from datetime import datetime, timezone

from backend.core.api.app.utils.internal_auth import VerifiedInternalRequest
from backend.core.api.app.utils.config_manager import ConfigManager
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.services.billing_service import BillingService
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.s3.service import S3UploadService
from backend.core.api.app.services.email_template import EmailTemplateService
from backend.core.api.app.services.invoiceninja.invoiceninja import InvoiceNinjaService
from backend.core.api.app.services.payment.payment_service import PaymentService

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/internal",
    tags=["Internal Services"],
    dependencies=[VerifiedInternalRequest] # Apply token verification to all routes in this router
)

# --- Dependency to get services from app.state ---
# These are simplified versions. In a larger app, you might have a more robust
# dependency injection system or pass app.state around.

def get_config_manager(request: Request) -> ConfigManager:
    if not hasattr(request.app.state, 'config_manager'):
        logger.error("ConfigManager not found in app.state during internal API call.")
        raise HTTPException(status_code=500, detail="Internal configuration error: ConfigManager not available.")
    return request.app.state.config_manager

def get_directus_service(request: Request) -> DirectusService:
    if not hasattr(request.app.state, 'directus_service'):
        logger.error("DirectusService not found in app.state during internal API call.")
        raise HTTPException(status_code=500, detail="Internal configuration error: DirectusService not available.")
    return request.app.state.directus_service

def get_encryption_service(request: Request) -> EncryptionService:
    if not hasattr(request.app.state, 'encryption_service'):
        logger.error("EncryptionService not found in app.state during internal API call.")
        raise HTTPException(status_code=500, detail="Internal configuration error: EncryptionService not available.")
    return request.app.state.encryption_service

def get_cache_service(request: Request) -> CacheService:
    if not hasattr(request.app.state, 'cache_service'):
        logger.error("CacheService not found in app.state during internal API call.")
        raise HTTPException(status_code=500, detail="Internal configuration error: CacheService not available.")
    return request.app.state.cache_service

def get_billing_service(
    cache_service: CacheService = Depends(get_cache_service),
    directus_service: DirectusService = Depends(get_directus_service),
    encryption_service: EncryptionService = Depends(get_encryption_service)
) -> BillingService:
    return BillingService(cache_service, directus_service, encryption_service)

def get_s3_service(request: Request) -> S3UploadService:
    if not hasattr(request.app.state, 's3_service'):
        logger.error("S3UploadService not found in app.state during internal API call.")
        raise HTTPException(status_code=500, detail="Internal configuration error: S3UploadService not available.")
    return request.app.state.s3_service

def get_email_template_service(request: Request) -> EmailTemplateService:
    if not hasattr(request.app.state, 'email_template_service'):
        logger.error("EmailTemplateService not found in app.state during internal API call.")
        raise HTTPException(status_code=500, detail="Internal configuration error: EmailTemplateService not available.")
    return request.app.state.email_template_service

def get_invoice_ninja_service(request: Request) -> InvoiceNinjaService:
    if not hasattr(request.app.state, 'invoice_ninja_service'):
        logger.error("InvoiceNinjaService not found in app.state during internal API call.")
        raise HTTPException(status_code=500, detail="Internal configuration error: InvoiceNinjaService not available.")
    return request.app.state.invoice_ninja_service

def get_payment_service(request: Request) -> PaymentService:
    if not hasattr(request.app.state, 'payment_service'):
        logger.error("PaymentService not found in app.state during internal API call.")
        raise HTTPException(status_code=500, detail="Internal configuration error: PaymentService not available.")
    return request.app.state.payment_service


# --- Endpoint Implementations ---

@router.get("/config/provider_model_pricing/{provider_id}/{model_id_suffix}")
async def get_provider_model_pricing_route(
    provider_id: str,
    model_id_suffix: str, # Assuming model_id_suffix does not contain slashes
    config_manager: ConfigManager = Depends(get_config_manager)
) -> Dict[str, Any]:
    """
    Provides pricing configuration for a specific provider model.
    Called by app services (e.g., BaseSkill) to determine costs.
    """
    logger.info(f"Internal API: Requesting pricing for provider '{provider_id}', model suffix '{model_id_suffix}'.")
    try:
        provider_config = config_manager.get_provider_config(provider_id)
        if not provider_config:
            raise HTTPException(status_code=404, detail=f"Provider '{provider_id}' not found.")
        
        # Attempt to get pricing using model_id_suffix directly
        model_pricing = provider_config.get_model_pricing(model_id_suffix)
        
        if not model_pricing:
            # If not found, try constructing full model_id (provider_id/model_id_suffix)
            # This handles cases where model_id_suffix might be just the model name part
            full_model_id_from_suffix = f"{provider_id}/{model_id_suffix}"
            model_pricing = provider_config.get_model_pricing(full_model_id_from_suffix)

        if not model_pricing:
            # Final fallback: iterate through models if get_model_pricing is too strict
            # This is more robust if model IDs in YAML don't always match the exact lookup key.
            for model_conf in provider_config.models:
                if model_conf.id == model_id_suffix or model_conf.id == f"{provider_id}/{model_id_suffix}":
                    model_pricing = model_conf.pricing.model_dump(exclude_none=True) if model_conf.pricing else None
                    break
            if not model_pricing:
                 raise HTTPException(status_code=404, detail=f"Model pricing for '{model_id_suffix}' (provider '{provider_id}') not found after checking multiple forms.")

        return model_pricing
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching pricing for {provider_id}/{model_id_suffix}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error fetching pricing: {str(e)}")

@router.get("/config/provider_pricing/{provider_id}")
async def get_provider_pricing_route(
    provider_id: str,
    config_manager: ConfigManager = Depends(get_config_manager)
) -> Dict[str, Any]:
    """
    Provides pricing configuration for a provider (provider-level pricing, not model-specific).
    Called by app services (e.g., main_processor) to determine costs for skills that use provider-level pricing.
    
    Example: Brave Search has per_request_credits in brave.yml, not model-specific pricing.
    """
    logger.info(f"Internal API: Requesting provider-level pricing for provider '{provider_id}'.")
    try:
        provider_config = config_manager.get_provider_config(provider_id)
        if not provider_config:
            raise HTTPException(status_code=404, detail=f"Provider '{provider_id}' not found.")
        
        # Get provider-level pricing (not model-specific)
        provider_pricing = provider_config.get("pricing")
        if not provider_pricing:
            raise HTTPException(
                status_code=404, 
                detail=f"Provider-level pricing not found for provider '{provider_id}'. Provider may only have model-specific pricing."
            )
        
        return provider_pricing
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching provider pricing for {provider_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error fetching provider pricing: {str(e)}")

# Pydantic model for usage recording payload (mirroring BaseSkill.record_skill_usage)
class UsageRecordPayload(BaseModel):
    user_id: str  # Actual user ID (needed to look up vault_key_id for encryption)
    user_id_hash: str
    app_id: str
    skill_id: str
    type: str # e.g., "skill_execution"
    timestamp: int # Unix timestamp
    credits_charged: int
    model_used: Optional[str] = None
    chat_id: Optional[str] = None
    message_id: Optional[str] = None
    cost_details: Optional[Dict[str, Any]] = None # Raw, unencrypted data
    api_key_hash: Optional[str] = None  # SHA-256 hash of API key for tracking
    device_hash: Optional[str] = None  # SHA-256 hash of device for tracking

@router.post("/usage/record")
async def record_usage_route(
    payload: UsageRecordPayload,
    request: Request,
    directus_service: DirectusService = Depends(get_directus_service),
    encryption_service: EncryptionService = Depends(get_encryption_service),
    cache_service: CacheService = Depends(get_cache_service)
) -> Dict[str, Any]:
    """
    Records skill usage data. Called by app services (e.g., BaseSkill).
    
    Dual-write architecture:
    1. Writes encrypted user-specific data to 'usage' collection (blocking)
    2. Writes anonymous analytics data to 'app_analytics' collection (fire-and-forget)
    
    The main API handles encryption and persistence for usage entries.
    Analytics entries are written in cleartext (no user data, no encryption needed).
    """
    logger.info(f"Internal API: Recording usage for user '{payload.user_id_hash}', app '{payload.app_id}', skill '{payload.skill_id}'.")
    
    try:
        # Get user's vault_key_id for encryption (try cache first, then Directus)
        user_vault_key_id = await cache_service.get_user_vault_key_id(payload.user_id)
        
        if not user_vault_key_id:
            logger.debug(f"vault_key_id not in cache for user {payload.user_id}, fetching from Directus")
            try:
                user_profile_result = await directus_service.get_user_profile(payload.user_id)
                if not user_profile_result or not user_profile_result[0]:
                    logger.error(f"Failed to fetch user profile for encryption: {payload.user_id}")
                    raise HTTPException(status_code=404, detail="User profile not found")
                
                user_vault_key_id = user_profile_result[1].get("vault_key_id")
                if not user_vault_key_id:
                    logger.error(f"User {payload.user_id} missing vault_key_id in Directus profile")
                    raise HTTPException(status_code=500, detail="User encryption key not found")
                
                # Cache the vault_key_id for future use
                await cache_service.update_user(payload.user_id, {"vault_key_id": user_vault_key_id})
                logger.debug(f"Cached vault_key_id for user {payload.user_id}")
            except HTTPException:
                raise
            except Exception as e_profile:
                logger.error(f"Error fetching user profile for encryption: {e_profile}", exc_info=True)
                raise HTTPException(status_code=500, detail="Failed to retrieve user encryption key")
        
        # 1. Create usage entry (user-specific, private) - blocking
        # The directus_service.usage.create_usage_entry stores cleartext app_id/skill_id/chat_id/message_id
        # and encrypts sensitive fields (credits, tokens, model) using the user vault key
        # Determine source: "chat" if chat_id is provided, otherwise "api_key" or "direct"
        source = "chat" if payload.chat_id else "api_key"  # Default to "api_key" if no chat_id
        
        usage_entry_id = await directus_service.usage.create_usage_entry(
            user_id_hash=payload.user_id_hash,
            app_id=payload.app_id,
            skill_id=payload.skill_id,
            usage_type=payload.type,
            timestamp=payload.timestamp,
            credits_charged=payload.credits_charged,
            user_vault_key_id=user_vault_key_id,
            model_used=payload.model_used,
            chat_id=payload.chat_id,
            message_id=payload.message_id,
            source=source,
            cost_system_prompt_credits=payload.cost_details.get("system_prompt_credits") if payload.cost_details else None,
            cost_history_credits=payload.cost_details.get("history_credits") if payload.cost_details else None,
            cost_response_credits=payload.cost_details.get("response_credits") if payload.cost_details else None,
            actual_input_tokens=payload.cost_details.get("input_tokens") if payload.cost_details else None,
            actual_output_tokens=payload.cost_details.get("output_tokens") if payload.cost_details else None,
            api_key_hash=payload.api_key_hash,  # API key hash for tracking which API key created this usage
            device_hash=payload.device_hash,  # Device hash for tracking which device created this usage
        )
        
        # 2. Write anonymous analytics entry (fire-and-forget, non-blocking)
        # This doesn't block the response and failures are non-critical
        # Analytics are used for public statistics like "most used apps"
        import asyncio
        asyncio.create_task(
            directus_service.analytics.create_analytics_entry(
                app_id=payload.app_id,  # Cleartext for analytics
                skill_id=payload.skill_id,  # Cleartext for analytics
                model_used=payload.model_used,  # Cleartext for analytics
                focus_mode_id=None,  # TODO: Add focus_mode_id to payload when available
                settings_memory_type=None,  # TODO: Add settings_memory_type to payload when available
                timestamp=payload.timestamp
            )
        )
        
        logger.info(f"Usage recorded successfully. Entry ID: {usage_entry_id}")
        return {"status": "success", "usage_entry_id": usage_entry_id}
    except Exception as e:
        logger.error(f"Error recording usage for user {payload.user_id_hash}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error recording usage: {str(e)}")


# Pydantic model for credit charging payload (mirroring BaseApp.charge_user_credits)
class CreditChargePayload(BaseModel):
    user_id: str
    user_id_hash: str
    credits: int
    skill_id: str
    app_id: str
    idempotency_key: Optional[str] = None
    usage_details: Optional[Dict[str, Any]] = None
    api_key_hash: Optional[str] = None  # SHA-256 hash of API key for tracking
    device_hash: Optional[str] = None  # SHA-256 hash of device for tracking

@router.post("/billing/charge")
async def charge_credits_route(
    payload: CreditChargePayload,
    billing_service: BillingService = Depends(get_billing_service)
) -> Dict[str, Any]:
    """
    Charges credits from a user. Called by app services (e.g., BaseApp).
    """
    logger.info(f"Internal API: Charging {payload.credits} credits for user '{payload.user_id}', app '{payload.app_id}', skill '{payload.skill_id}'.")

    if payload.credits <= 0:
        logger.warning(f"Attempted to charge non-positive credits ({payload.credits}) for user {payload.user_id}. Skipping.")
        return {"status": "skipped", "reason": "Non-positive credits"}

    try:
        await billing_service.charge_user_credits(
            user_id=payload.user_id,
            credits_to_deduct=payload.credits,
            user_id_hash=payload.user_id_hash,
            app_id=payload.app_id,
            skill_id=payload.skill_id,
            usage_details=payload.usage_details,
            api_key_hash=payload.api_key_hash,  # API key hash for tracking which API key created this usage
            device_hash=payload.device_hash,  # Device hash for tracking which device created this usage
        )
        
        return {
            "status": "success",
            "charged_credits": payload.credits,
        }
    except HTTPException as e:
        # Forward HTTP exceptions from the service
        raise e
    except Exception as e:
        logger.error(f"Error charging credits for user {payload.user_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error charging credits: {str(e)}")


@router.post("/reprocess-invoice")
async def reprocess_invoice(
    user_id: str,
    order_id: str,
    directus_service: DirectusService = Depends(get_directus_service),
    encryption_service: EncryptionService = Depends(get_encryption_service),
    cache_service: CacheService = Depends(get_cache_service),
    s3_service: S3UploadService = Depends(get_s3_service),
    email_template_service: EmailTemplateService = Depends(get_email_template_service),
    invoice_ninja_service: InvoiceNinjaService = Depends(get_invoice_ninja_service),
    payment_service: PaymentService = Depends(get_payment_service),
) -> Dict[str, Any]:
    """
    Reprocesses a failed invoice.
    """
    logger.info(f"Internal API: Reprocessing invoice for user '{user_id}', order '{order_id}'.")
    try:
        # 1. Hash the user ID
        user_id_hash = hashlib.sha256(user_id.encode('utf-8')).hexdigest()
        logger.info(f"Hashed user ID {user_id} to {user_id_hash}")

        # 2. Search in Directus for the invoice entry
        params = {
            "filter[user_id_hash][_eq]": user_id_hash,
            "filter[order_id][_eq]": order_id,
            "limit": 1
        }
        invoices = await directus_service.get_items("invoices", params)
        if not invoices:
            logger.error(f"No invoice found for user_id_hash {user_id_hash} and order_id {order_id}")
            raise HTTPException(status_code=404, detail="Invoice not found")

        invoice = invoices[0]
        logger.info(f"Found invoice record: {invoice['id']}")

        # 3. Get user profile to retrieve vault_key_id
        user_profile = await cache_service.get_user_by_id(user_id)
        if not user_profile:
            logger.error(f"Could not retrieve user profile for user {user_id}")
            raise HTTPException(status_code=404, detail="User profile not found")

        vault_key_id = user_profile.get("vault_key_id")
        if not vault_key_id:
            logger.error(f"vault_key_id not found for user {user_id}")
            raise HTTPException(status_code=500, detail="vault_key_id not found for user")

        user_language = user_profile.get("language", "en")
        user_darkmode = user_profile.get("darkmode", False)

        # 4. Decrypt S3 object key and AES key
        encrypted_s3_object_key = invoice["encrypted_s3_object_key"]
        encrypted_aes_key = invoice["encrypted_aes_key"]
        aes_nonce_b64 = invoice["aes_nonce"]

        s3_object_key = await encryption_service.decrypt_with_user_key(encrypted_s3_object_key, vault_key_id)
        aes_key_b64 = await encryption_service.decrypt_with_user_key(encrypted_aes_key, vault_key_id)

        if not s3_object_key or not aes_key_b64:
            logger.error("Failed to decrypt S3 object key or AES key.")
            raise HTTPException(status_code=500, detail="Failed to decrypt S3 object key or AES key")

        aes_key = base64.b64decode(aes_key_b64)
        nonce = base64.b64decode(aes_nonce_b64)
        logger.info(f"Successfully decrypted S3 object key: {s3_object_key}")

        # 5. Download the PDF file from S3
        bucket_name = s3_service.get_bucket_name('invoices', os.getenv('SERVER_ENVIRONMENT', 'development'))
        presigned_url = s3_service.generate_presigned_url(bucket_name, s3_object_key)

        async with httpx.AsyncClient() as client:
            response = await client.get(presigned_url)
            response.raise_for_status()
            encrypted_pdf_payload = response.content

        logger.info(f"Successfully downloaded encrypted PDF from S3.")

        # 6. Decrypt the PDF file
        aesgcm = AESGCM(aes_key)
        pdf_bytes = aesgcm.decrypt(nonce, encrypted_pdf_payload, None)
        logger.info("Successfully decrypted PDF file.")

        # 7. Process the PDF file
        now_utc = datetime.now(timezone.utc)
        date_str_filename = now_utc.strftime('%Y_%m_%d')
        
        # Use account ID instead of user_id_last_8 for invoice numbering
        account_id = user_profile.get("account_id")
        if not account_id:
            logger.error(f"Missing account_id for user {user_id} in reprocess invoice.")
            raise HTTPException(status_code=500, detail="Missing account_id for user")

        payment_order_details = await payment_service.get_order(order_id)
        if not payment_order_details:
            logger.error(f"Failed to fetch payment order details for {order_id} in invoice task.")
            raise HTTPException(status_code=500, detail="Failed to fetch payment order details")

        invoice_number = f"{account_id}-MANUAL"  # Placeholder for reprocessed invoices

        invoice_filename_en = f"openmates_invoice_{date_str_filename}_{invoice_number}.pdf"

        # 8. Upload decrypted PDF to Invoice Ninja
        decrypted_email = await encryption_service.decrypt_with_user_key(user_profile["encrypted_email_address"], vault_key_id)

        cardholder_name = payment_order_details.get('metadata', {}).get('cardholder_name', '')
        customer_firstname = ""
        customer_lastname = ""
        if cardholder_name:
            if ' ' in cardholder_name:
                name_parts = cardholder_name.split(' ', 1)
                customer_firstname = name_parts[0]
                customer_lastname = name_parts[-1] if len(name_parts) > 1 else ""
            else:
                customer_firstname = cardholder_name

        amount_paid = payment_order_details.get('amount')
        currency_paid = payment_order_details.get('currency')

        credits_purchased_encrypted = invoice.get("encrypted_credits_purchased")
        credits_purchased = await encryption_service.decrypt_with_user_key(credits_purchased_encrypted, vault_key_id)

        invoice_ninja_service.process_income_transaction(
            user_hash=user_id_hash,
            external_order_id=order_id,
            customer_firstname=customer_firstname,
            customer_lastname=customer_lastname,
            customer_email=decrypted_email,
            customer_country_code=user_profile.get("country_code", ""),
            credits_value=int(credits_purchased),
            currency_code=currency_paid,
            purchase_price_value=float(amount_paid) / 100,
            invoice_date=datetime.now(timezone.utc).strftime('%Y-%m-%d'),
            due_date=datetime.now(timezone.utc).strftime('%Y-%m-%d'),
            payment_processor=payment_service.provider_name,
            card_brand_lower=payment_order_details.get('payment_method_details', {}).get('card', {}).get('brand', ''),
            custom_invoice_number=invoice_number,
            custom_pdf_data=pdf_bytes
        )
        logger.info("Successfully processed income transaction in Invoice Ninja.")

        # 9. Send email to user
        email_context = {
            "darkmode": user_darkmode,
            "account_id": account_id  # Add account ID for email template
        }
        attachments = [{
            "filename": invoice_filename_en,
            "content": base64.b64encode(pdf_bytes).decode('utf-8')
        }]

        email_success = await email_template_service.send_email(
            template="purchase-confirmation",
            recipient_email=decrypted_email,
            context=email_context,
            lang=user_language,
            attachments=attachments
        )

        if email_success:
            logger.info("Successfully sent purchase confirmation email.")
            return {"status": "success"}
        else:
            logger.error("Failed to send purchase confirmation email.")
            raise HTTPException(status_code=500, detail="Failed to send purchase confirmation email")

    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"An error occurred during invoice reprocessing: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
