from fastapi import APIRouter, Depends, HTTPException, Request, Body
from pydantic import BaseModel
import logging
import os
from typing import Dict, Any

# Import necessary services and dependencies (adjust paths as needed)
from app.services.directus import DirectusService
from app.services.cache import CacheService
from app.utils.encryption import EncryptionService
from app.utils.secrets_manager import SecretsManager
from app.models.user import User
from app.routes.auth_routes.auth_dependencies import get_current_user # Assuming this provides the User model

# Import the actual Revolut Service
from app.services.revolut_service import RevolutService
logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/payments", tags=["Payments"])

# --- Helper to get services from app state ---
def get_secrets_manager(request: Request) -> SecretsManager:
    return request.app.state.secrets_manager

# Dependency function to get RevolutService instance from app state
def get_revolut_service(request: Request) -> RevolutService:
    # Service is already initialized and stored in app.state by lifespan manager
    if not hasattr(request.app.state, 'revolut_service'):
         logger.error("RevolutService not found in application state.")
         # Raise HTTPException here so FastAPI handles the error response
         raise HTTPException(status_code=503, detail="Payment service unavailable")
    return request.app.state.revolut_service

def get_directus_service(request: Request) -> DirectusService:
    return request.app.state.directus_service

def get_cache_service(request: Request) -> CacheService:
    return request.app.state.cache_service

def get_encryption_service(request: Request) -> EncryptionService:
    return request.app.state.encryption_service

# --- Environment Check ---
def is_production() -> bool:
    return os.getenv("SERVER_ENVIRONMENT", "development") == "production"

# --- Response Models ---
class PaymentConfigResponse(BaseModel):
    revolut_public_key: str
    environment: str # 'production' or 'sandbox'

class CreateOrderRequest(BaseModel):
    amount: int # Amount in smallest currency unit (e.g., cents)
    currency: str # e.g., "EUR"
    credits_amount: int # The number of credits being purchased

class CreateOrderResponse(BaseModel):
    order_token: str # The public token for the Revolut Checkout Widget

# --- Endpoints ---

@router.get("/config", response_model=PaymentConfigResponse)
async def get_payment_config(
    secrets_manager: SecretsManager = Depends(get_secrets_manager)
):
    """Provides the necessary public configuration for the frontend payment widget."""
    logger.info("Fetching payment configuration...")
    try:
        if is_production():
            public_key = await secrets_manager.get_secret("API_SECRET__REVOLUT_BUSINESS_MERCHANT_PRODUCTION_PUBLIC_KEY")
            environment = "production"
        else:
            public_key = await secrets_manager.get_secret("API_SECRET__REVOLUT_BUSINESS_MERCHANT_SANDBOX_PUBLIC_KEY")
            environment = "sandbox"

        if not public_key:
            logger.error("Revolut Public Key not found in Secrets Manager.")
            raise HTTPException(status_code=503, detail="Payment configuration unavailable.")

        logger.info(f"Payment config fetched for environment: {environment}")
        return PaymentConfigResponse(revolut_public_key=public_key, environment=environment)
    except Exception as e:
        logger.error(f"Error fetching payment config: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error fetching payment config.")


@router.post("/create-order", response_model=CreateOrderResponse)
async def create_payment_order(
    request: Request, # Needs to come before Depends for Pylance
    order_data: CreateOrderRequest,
    current_user: User = Depends(get_current_user),
    revolut_service: RevolutService = Depends(get_revolut_service), # Use the dependency
    encryption_service: EncryptionService = Depends(get_encryption_service)
):
    """Creates a payment order with Revolut and returns the order token."""
    logger.info(f"Received request to create payment order for user {current_user.id} - Amount: {order_data.amount} {order_data.currency}, Credits: {order_data.credits_amount}")
    
    # --- Actual Implementation ---
    try:
        # Decrypt the user's email address
        if not current_user.encrypted_email_address or not current_user.vault_key_id:
            logger.error(f"Missing encrypted_email_address or vault_key_id for user {current_user.id}")
            raise HTTPException(status_code=500, detail="User email information unavailable.")
        decrypted_email = await encryption_service.decrypt_with_user_key(
            current_user.encrypted_email_address,
            current_user.vault_key_id
        )

        order_response = await revolut_service.create_order(
            amount=order_data.amount,
            currency=order_data.currency,
            email=decrypted_email,
            user_id=current_user.id, # Pass user ID for metadata/reference
            credits_amount=order_data.credits_amount # Pass credits for metadata
        )
        
        if not order_response or "token" not in order_response:
            logger.error(f"Failed to create Revolut order or missing token for user {current_user.id}.")
            raise HTTPException(status_code=502, detail="Failed to initiate payment with provider.")
            
        logger.info(f"Revolut order created successfully for user {current_user.id}. Order ID: {order_response.get('id')}")
        return CreateOrderResponse(order_token=order_response["token"])
        
    except HTTPException as e:
        raise e # Re-raise HTTP exceptions
    except Exception as e:
        logger.error(f"Error creating Revolut payment order for user {current_user.id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error during payment initiation.")
    # --- End Actual Implementation ---


@router.post("/webhook", status_code=200) # Explicitly return 200 on success
async def revolut_webhook(
    request: Request,
    revolut_service: RevolutService = Depends(get_revolut_service), # Use the dependency
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service),
    encryption_service: EncryptionService = Depends(get_encryption_service)
):
    """Handles incoming webhook events from Revolut."""
    payload_bytes = await request.body()
    signature_header = request.headers.get("Revolut-Signature")
    
    logger.info(f"Received Revolut webhook. Signature present: {bool(signature_header)}")
    
    if not signature_header:
        logger.warning("Missing Revolut-Signature header in webhook request.")
        raise HTTPException(status_code=400, detail="Missing signature")

    # --- Actual Implementation ---
    try:
        is_valid, event_payload = await revolut_service.verify_and_parse_webhook(payload_bytes, signature_header)
        
        if not is_valid:
            # Error is logged within the service method
            # Return 400 Bad Request as the signature is invalid
            raise HTTPException(status_code=400, detail="Invalid signature")
            
        # If signature is valid, but payload parsing failed
        if is_valid and event_payload is None:
             # Error logged in service, return 200 to Revolut as signature was ok, but we can't process
             logger.warning("Webhook signature valid, but payload parsing failed. Acknowledging receipt.")
             return {"status": "received_parsing_error"}

        # Proceed if signature is valid and payload parsed
        event_type = event_payload.get("event")
        event_data = event_payload.get("data", {})
        order_id = event_data.get("id")
        order_state = event_data.get("state")
        metadata = event_data.get("metadata", {})
        user_id = metadata.get("user_id")
        credits_purchased_str = metadata.get("credits_purchased")
        
        logger.info(f"Processing verified webhook event: {event_type}, Order ID: {order_id}, State: {order_state}, User ID: {user_id}")
        
        # --- Process ORDER_COMPLETED ---
        if event_type == "ORDER_COMPLETED" and user_id and credits_purchased_str:
            try:
                credits_purchased = int(credits_purchased_str)
                logger.info(f"Order {order_id} completed for user {user_id}. Awarding {credits_purchased} credits.")
                
                # Get current encrypted credits and vault key DIRECTLY from Directus
                fields_to_fetch = ["encrypted_credit_balance", "vault_key_id"] # Adjust field name if needed
                user_data = await directus_service.get_user_fields_direct(user_id, fields=fields_to_fetch)
                
                if not user_data:
                    logger.error(f"User {user_id} not found or failed to fetch direct fields for webhook processing (Order ID: {order_id}).")
                    return {"status": "user_data_fetch_failed"} # Acknowledge Revolut, log error

                current_encrypted_credits = user_data.get("encrypted_credit_balance") # Use correct field name
                vault_key_id = user_data.get("vault_key_id")
                
                if not vault_key_id:
                    logger.error(f"Vault key ID not found for user {user_id} (Order ID: {order_id}). Cannot update credits.")
                    return {"status": "user_key_error"} # Acknowledge Revolut, log critical error

                # Decrypt current credits
                current_credits = 0
                if current_encrypted_credits:
                    try:
                        decrypted_credits_str = await encryption_service.decrypt_with_user_key(current_encrypted_credits, vault_key_id)
                        current_credits = int(decrypted_credits_str)
                    except Exception as decrypt_err:
                        logger.error(f"Failed to decrypt current credits for user {user_id} (Order ID: {order_id}): {decrypt_err}", exc_info=True)
                        return {"status": "decryption_error"} # Acknowledge Revolut, log critical error
                
                # Calculate and encrypt new total
                new_total_credits = current_credits + credits_purchased
                new_total_credits_str = str(new_total_credits)
                new_encrypted_credits, _ = await encryption_service.encrypt_with_user_key(new_total_credits_str, vault_key_id)
                
                # Update Directus - use the correct field name
                update_payload = {"encrypted_credit_balance": new_encrypted_credits}
                update_success = await directus_service.update_user(user_id, update_payload)
                
                if not update_success:
                    logger.error(f"Failed to update Directus credits for user {user_id} after successful payment (Order ID: {order_id}).")
                    # Acknowledge Revolut, but log data inconsistency error
                    return {"status": "directus_update_failed"}
                else:
                    logger.info(f"Successfully updated Directus credits for user {user_id} (Order ID: {order_id}).")

                # Update Cache
                cache_update_success = await cache_service.update_user(user_id, {"credits": new_total_credits}) # Update with decrypted value
                if not cache_update_success:
                     logger.warning(f"Failed to update cache credits for user {user_id} after successful payment (Order ID: {order_id}), but Directus was updated.")
                else:
                    logger.info(f"Successfully updated cache credits for user {user_id} to {new_total_credits} (Order ID: {order_id}).")

            except ValueError:
                 logger.error(f"Could not parse credits_purchased '{credits_purchased_str}' to int for order {order_id}.")
                 return {"status": "metadata_error"} # Acknowledge Revolut, log error
            except Exception as processing_err:
                 logger.error(f"Error processing ORDER_COMPLETED for user {user_id}, order {order_id}: {processing_err}", exc_info=True)
                 # Acknowledge Revolut, log internal processing error
                 return {"status": "processing_error"}

        # --- Process ORDER_FAILED ---
        elif event_type == "ORDER_FAILED":
            logger.warning(f"Received verified ORDER_FAILED event for order {order_id}. User: {user_id}. Reason: {event_data.get('error_message', 'N/A')}")
            # No action needed for credits, just log.
            
        # --- Ignore other events ---
        else:
             logger.info(f"Ignoring verified webhook event type: {event_type} for order {order_id}")
             
    except HTTPException as e:
        # Re-raise HTTP exceptions (like the 400 from invalid signature)
        raise e
    except Exception as e:
        # Catch any other unexpected errors during webhook processing
        logger.error(f"Unexpected error processing verified Revolut webhook: {str(e)}", exc_info=True)
        # Return 500 but acknowledge receipt to Revolut if possible (depends on where error occurred)
        # For safety, return 500 to indicate server error, but Revolut might retry.
        # A simple {"status": "received"} might be safer to prevent retries for non-transient errors.
        # Let's return 200 with an error status for now to stop retries but indicate failure.
        return {"status": "internal_server_error"}
        # raise HTTPException(status_code=500, detail="Webhook processing error") # Alternative: raise 500

    # If we reach here, processing was successful or the event was ignored
    return {"status": "received"} # Acknowledge receipt to Revolut
# --- End Actual Implementation ---