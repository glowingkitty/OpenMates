# backend/core/api/app/routes/internal_api.py
#
# This module defines FastAPI routes for internal services (e.g., apps)
# to communicate with the main API. These endpoints are secured by an
# internal service token.

import logging
import os
import yaml
from fastapi import APIRouter, HTTPException, Request, Depends
from typing import Dict, Any, Optional
from pydantic import BaseModel # Ensure BaseModel is imported for Pydantic models
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
from typing import List

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
        # Determine source: "api_key" if api_key_hash is provided, otherwise "chat" if chat_id is provided, else "direct"
        if payload.api_key_hash:
            source = "api_key"
        elif payload.chat_id:
            source = "chat"
        else:
            source = "direct"
        
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
            user_input_tokens=payload.cost_details.get("user_input_tokens") if payload.cost_details else None,
            system_prompt_tokens=payload.cost_details.get("system_prompt_tokens") if payload.cost_details else None,
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

        logger.info("Successfully downloaded encrypted PDF from S3.")

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


# --- Issue Report Endpoints ---

class IssueResponse(BaseModel):
    """Response model for issue data"""
    id: str
    title: str
    description: Optional[str]
    chat_or_embed_url: Optional[str]  # Decrypted URL
    contact_email: Optional[str]  # Decrypted email
    timestamp: str
    estimated_location: Optional[str]  # Decrypted location
    device_info: Optional[str]  # Decrypted device info
    console_logs: Optional[str] = None  # Decrypted logs (only included if include_logs=true)
    created_at: str
    updated_at: str


@router.get("/issues", response_model=List[IssueResponse])
async def get_issues(
    search: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    directus_service: DirectusService = Depends(get_directus_service),
    encryption_service: EncryptionService = Depends(get_encryption_service)
) -> List[IssueResponse]:
    """
    Get issue reports with optional text search in title.
    
    This endpoint is only accessible from within the Docker network via internal service token.
    It allows searching for text in the issue title and returns issues with decrypted contact emails.
    
    Args:
        search: Optional text to search for in issue titles (case-insensitive partial match)
        limit: Maximum number of issues to return (default: 100, max: 1000)
        offset: Number of issues to skip for pagination (default: 0)
        
    Returns:
        List of issue reports with decrypted contact emails
    """
    logger.info(f"Internal API: Getting issues (search='{search}', limit={limit}, offset={offset})")
    
    try:
        # Build query parameters
        params = {
            "limit": min(limit, 1000),  # Cap at 1000 for performance
            "offset": offset,
            "sort": "-created_at"  # Sort by newest first
        }
        
        # Add search filter if provided
        if search:
            # Use Directus filter for case-insensitive partial match on title
            params["filter[title][_icontains]"] = search
        
        # Fetch issues from Directus
        issues = await directus_service.get_items("issues", params)
        
        # Decrypt encrypted fields and format response
        result = []
        for issue in issues:
            # Decrypt contact email if present
            decrypted_email = None
            if issue.get("encrypted_contact_email"):
                try:
                    decrypted_email = await encryption_service.decrypt_issue_report_email(
                        issue["encrypted_contact_email"]
                    )
                except Exception as e:
                    logger.warning(f"Failed to decrypt contact email for issue {issue.get('id')}: {str(e)}")
            
            # Decrypt chat or embed URL if present
            decrypted_url = None
            if issue.get("encrypted_chat_or_embed_url"):
                try:
                    decrypted_url = await encryption_service.decrypt_issue_report_data(
                        issue["encrypted_chat_or_embed_url"]
                    )
                except Exception as e:
                    logger.warning(f"Failed to decrypt chat or embed URL for issue {issue.get('id')}: {str(e)}")
            
            # Decrypt estimated location if present
            decrypted_location = None
            if issue.get("encrypted_estimated_location"):
                try:
                    decrypted_location = await encryption_service.decrypt_issue_report_data(
                        issue["encrypted_estimated_location"]
                    )
                except Exception as e:
                    logger.warning(f"Failed to decrypt estimated location for issue {issue.get('id')}: {str(e)}")
            
            # Decrypt device info if present
            decrypted_device_info = None
            if issue.get("encrypted_device_info"):
                try:
                    decrypted_device_info = await encryption_service.decrypt_issue_report_data(
                        issue["encrypted_device_info"]
                    )
                except Exception as e:
                    logger.warning(f"Failed to decrypt device info for issue {issue.get('id')}: {str(e)}")
            
            result.append(IssueResponse(
                id=issue["id"],
                title=issue["title"],
                description=issue.get("description"),
                chat_or_embed_url=decrypted_url,
                contact_email=decrypted_email,
                timestamp=issue.get("timestamp", ""),
                estimated_location=decrypted_location,
                device_info=decrypted_device_info,
                created_at=issue.get("created_at", ""),
                updated_at=issue.get("updated_at", "")
            ))
        
        logger.info(f"Internal API: Retrieved {len(result)} issues")
        return result
        
    except Exception as e:
        logger.error(f"Error retrieving issues: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to retrieve issues: {str(e)}")


@router.get("/issues/{issue_id}", response_model=IssueResponse)
async def get_issue(
    issue_id: str,
    include_logs: bool = False,
    directus_service: DirectusService = Depends(get_directus_service),
    encryption_service: EncryptionService = Depends(get_encryption_service),
    s3_service: S3UploadService = Depends(get_s3_service)
) -> IssueResponse:
    """
    Get a specific issue report by ID.
    
    This endpoint is only accessible from within the Docker network via internal service token.
    Returns the issue with decrypted fields. Console logs are only included if include_logs=true.
    
    Args:
        issue_id: UUID of the issue to retrieve
        include_logs: If True, fetch and decrypt console logs from S3 (default: False)
        
    Returns:
        Issue report with decrypted fields (and optionally console logs)
    """
    logger.info(f"Internal API: Getting issue {issue_id}")
    
    try:
        # Fetch issue from Directus using filter
        params = {
            "filter[id][_eq]": issue_id,
            "limit": 1
        }
        issues = await directus_service.get_items("issues", params)
        
        if not issues or len(issues) == 0:
            raise HTTPException(status_code=404, detail="Issue not found")
        
        issue = issues[0]
        
        # Decrypt contact email if present
        decrypted_email = None
        if issue.get("encrypted_contact_email"):
            try:
                decrypted_email = await encryption_service.decrypt_issue_report_email(
                    issue["encrypted_contact_email"]
                )
            except Exception as e:
                logger.warning(f"Failed to decrypt contact email for issue {issue_id}: {str(e)}")
        
        # Decrypt chat or embed URL if present
        decrypted_url = None
        if issue.get("encrypted_chat_or_embed_url"):
            try:
                decrypted_url = await encryption_service.decrypt_issue_report_data(
                    issue["encrypted_chat_or_embed_url"]
                )
            except Exception as e:
                logger.warning(f"Failed to decrypt chat or embed URL for issue {issue_id}: {str(e)}")
        
        # Decrypt estimated location if present
        decrypted_location = None
        if issue.get("encrypted_estimated_location"):
            try:
                decrypted_location = await encryption_service.decrypt_issue_report_data(
                    issue["encrypted_estimated_location"]
                )
            except Exception as e:
                logger.warning(f"Failed to decrypt estimated location for issue {issue_id}: {str(e)}")
        
        # Decrypt device info if present
        decrypted_device_info = None
        if issue.get("encrypted_device_info"):
            try:
                decrypted_device_info = await encryption_service.decrypt_issue_report_data(
                    issue["encrypted_device_info"]
                )
            except Exception as e:
                logger.warning(f"Failed to decrypt device info for issue {issue_id}: {str(e)}")
        
        # Optionally fetch and decrypt issue report YAML from S3
        decrypted_console_logs = None
        if include_logs and issue.get("encrypted_issue_report_yaml_s3_key"):
            try:
                # Decrypt the S3 object key
                s3_object_key = await encryption_service.decrypt_issue_report_data(
                    issue["encrypted_issue_report_yaml_s3_key"]
                )
                
                if s3_object_key:
                    # Get bucket name for issue_logs
                    from backend.core.api.app.services.s3.config import get_bucket_name
                    bucket_name = get_bucket_name('issue_logs', os.getenv('SERVER_ENVIRONMENT', 'development'))
                    
                    # Download encrypted YAML from S3
                    encrypted_yaml_bytes = await s3_service.get_file(
                        bucket_name=bucket_name,
                        object_key=s3_object_key
                    )
                    
                    if encrypted_yaml_bytes:
                        # Decrypt the YAML
                        encrypted_yaml_str = encrypted_yaml_bytes.decode('utf-8')
                        decrypted_yaml = await encryption_service.decrypt_issue_report_data(
                            encrypted_yaml_str
                        )
                        
                        # Parse YAML to extract console logs
                        yaml_data = yaml.safe_load(decrypted_yaml)
                        if yaml_data and 'issue_report' in yaml_data and 'logs' in yaml_data['issue_report']:
                            decrypted_console_logs = yaml_data['issue_report']['logs'].get('console_logs')
                        logger.info(f"Successfully fetched and decrypted issue report YAML for issue {issue_id}")
                    else:
                        logger.warning(f"Issue report YAML file not found in S3 for issue {issue_id}: {s3_object_key}")
            except Exception as e:
                logger.warning(f"Failed to fetch issue report YAML for issue {issue_id}: {str(e)}", exc_info=True)
        
        return IssueResponse(
            id=issue["id"],
            title=issue["title"],
            description=issue.get("description"),
            chat_or_embed_url=decrypted_url,
            contact_email=decrypted_email,
            timestamp=issue.get("timestamp", ""),
            estimated_location=decrypted_location,
            device_info=decrypted_device_info,
            console_logs=decrypted_console_logs,
            created_at=issue.get("created_at", ""),
            updated_at=issue.get("updated_at", "")
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving issue {issue_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to retrieve issue: {str(e)}")
