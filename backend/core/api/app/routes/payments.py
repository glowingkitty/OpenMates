from fastapi import APIRouter, Depends, HTTPException, Request, Body
from pydantic import BaseModel
import logging
import os
import yaml # Import PyYAML
from typing import Dict, Any, Optional
from pathlib import Path # To construct path to pricing.yml

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
    # amount: int # REMOVED - Backend will determine amount based on credits and currency
    currency: str # e.g., "EUR"
    credits_amount: int # The number of credits being purchased

class CreateOrderResponse(BaseModel):
    order_token: str # The public token for the Revolut Checkout Widget
    order_id: str # The unique ID for the Revolut order

class OrderStatusRequest(BaseModel): # New model for the request body
    order_id: str

class OrderStatusResponse(BaseModel):
    order_id: str
    state: str # e.g., CREATED, PENDING, AUTHORISED, COMPLETED, FAILED, CANCELLED
    # Optionally include more details if needed from Revolut's get order response
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


# --- Pricing Config Loading ---
# Determine the path relative to this file's location
# Assumes this file is at backend/core/api/app/routes/payments.py
# and pricing.yml is at shared/config/pricing.yml
PRICING_CONFIG_PATH = Path(__file__).parent.parent.parent.parent.parent / "shared" / "config" / "pricing.yml"
PRICING_TIERS = []
try:
    with open(PRICING_CONFIG_PATH, 'r') as f:
        pricing_data = yaml.safe_load(f)
        PRICING_TIERS = pricing_data.get('pricingTiers', [])
        logger.info(f"Successfully loaded {len(PRICING_TIERS)} pricing tiers from {PRICING_CONFIG_PATH}")
except FileNotFoundError:
    logger.error(f"Pricing configuration file not found at {PRICING_CONFIG_PATH}")
except yaml.YAMLError as e:
     logger.error(f"Error parsing pricing configuration file {PRICING_CONFIG_PATH}: {e}")
except Exception as e:
     logger.error(f"Unexpected error loading pricing configuration: {e}")

def get_price_for_credits(credits_amount: int, currency: str) -> Optional[int]:
    """Finds the price in smallest unit for a given credit amount and currency."""
    currency_lower = currency.lower()
    for tier in PRICING_TIERS:
        if tier.get('credits') == credits_amount:
            price_in_currency = tier.get('price', {}).get(currency_lower)
            if price_in_currency is not None:
                # Assuming price is in major units (e.g., EUR), convert to smallest unit (cents)
                # TODO: Add more robust currency handling if needed (e.g., for JPY which has no subunits)
                if currency_lower in ['eur', 'usd', 'gbp']: # Add other currencies with 100 subunits
                     return int(price_in_currency * 100)
                else: # Assume currencies like JPY have 0 decimal places
                     return int(price_in_currency)
            else:
                logger.warning(f"Currency '{currency}' not found in price tier for {credits_amount} credits.")
                return None
    logger.warning(f"No pricing tier found for {credits_amount} credits.")
    return None
# --- End Pricing Config Loading ---


@router.post("/create-order", response_model=CreateOrderResponse)
async def create_payment_order(
    request: Request, # Needs to come before Depends for Pylance
    order_data: CreateOrderRequest,
    current_user: User = Depends(get_current_user),
    revolut_service: RevolutService = Depends(get_revolut_service), # Use the dependency
    encryption_service: EncryptionService = Depends(get_encryption_service),
    cache_service: CacheService = Depends(get_cache_service)
):
    """
    Looks up the price based on credits_amount and currency from pricing.yml,
    creates a payment order with Revolut, and returns the order token and ID.
    """
    logger.info(f"Received request to create payment order for user {current_user.id} - Currency: {order_data.currency}, Credits: {order_data.credits_amount}")

    # --- Determine Amount from Pricing Config ---
    calculated_amount = get_price_for_credits(order_data.credits_amount, order_data.currency)
    if calculated_amount is None:
         logger.error(f"Could not determine price for {order_data.credits_amount} credits in {order_data.currency} for user {current_user.id}.")
         raise HTTPException(status_code=400, detail=f"Invalid credit amount or currency combination.") # Bad request from client
    logger.info(f"Determined amount for {order_data.credits_amount} credits in {order_data.currency}: {calculated_amount} (smallest unit)")
    # --- End Determine Amount ---

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
            amount=calculated_amount, # Use the backend-determined amount
            currency=order_data.currency,
            email=decrypted_email,
            user_id=current_user.id, # Pass user ID for metadata/reference
            credits_amount=order_data.credits_amount # Pass credits for metadata
        )
        
        if not order_response or "token" not in order_response:
            logger.error(f"Failed to create Revolut order or missing token for user {current_user.id}.")
            raise HTTPException(status_code=502, detail="Failed to initiate payment with provider.")
            
        logger.info(f"Revolut order created successfully for user {current_user.id}. Order ID: {order_response.get('id')}")
        # Ensure order_id is present before returning
        order_id = order_response.get("id")
        if not order_id:
             logger.error(f"Revolut order response missing 'id' for user {current_user.id}.")
             raise HTTPException(status_code=502, detail="Failed to get order ID from payment provider.")

        # Cache the order metadata and status for 5 minutes
        cache_success = await cache_service.set_order(
            order_id=order_id,
            user_id=current_user.id,
            credits_amount=order_data.credits_amount,
            status="created",
            ttl=300  # 5 minutes
        )
        if not cache_success:
            logger.warning(f"Failed to cache order {order_id} for user {current_user.id} (non-blocking).")

        return CreateOrderResponse(
            order_token=order_response["token"],
            order_id=order_id
        )
        
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
    request_timestamp_header = request.headers.get("Revolut-Request-Timestamp")
    
    logger.info(f"Received Revolut webhook. Signature present: {bool(signature_header)}")
    
    if not signature_header:
        logger.warning("Missing Revolut-Signature header in webhook request.")
        raise HTTPException(status_code=400, detail="Missing signature")

    # --- Actual Implementation ---
    try:
        is_valid, event_payload = await revolut_service.verify_and_parse_webhook(
            payload_bytes, signature_header, request_timestamp_header
        )
        
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
        # Extract order_id directly from the top-level payload for events like ORDER_COMPLETED
        webhook_order_id = event_payload.get("order_id")
        if not webhook_order_id:
            logger.warning(f"Webhook event {event_type} received without an order_id in the payload.")
            return {"status": "received_missing_order_id"}

        logger.info(f"Processing verified webhook event: {event_type} for Order ID: {webhook_order_id}")

        # --- Process ORDER_COMPLETED ---
        if event_type == "ORDER_COMPLETED":
            # Fetch full order details to get metadata
            order_details = await revolut_service.get_order(webhook_order_id)
            if not order_details:
                logger.error(f"Failed to fetch order details for completed order {webhook_order_id}. Cannot process.")
                # Acknowledge webhook, but log error. Maybe set cache status to failed?
                await cache_service.update_order_status(webhook_order_id, "failed_details_fetch")
                return {"status": "order_fetch_failed"}

            metadata = order_details.get("metadata", {})
            user_id = metadata.get("user_id")
            credits_purchased_str = metadata.get("credits_purchased")
            order_id = order_details.get("id") # Use ID from fetched details for consistency

            if not user_id or not credits_purchased_str:
                 logger.error(f"Missing user_id or credits_purchased in metadata for completed order {order_id}. Metadata: {metadata}")
                 await cache_service.update_order_status(order_id, "failed_missing_metadata")
                 return {"status": "metadata_missing"}

            # Proceed with processing using fetched details - User-defined cache flag lock (Cache-first calculation)
            user_cache_data = None
            directus_update_success = False
            new_total_credits_calculated = 0 # Store calculated value for final cache update

            try:
                credits_purchased = int(credits_purchased_str)
                logger.info(f"Order {order_id} completed for user {user_id}. Attempting to process {credits_purchased} credits using cache-first method.")

                # 1. Check cache for user data and lock flag
                user_cache_data = await cache_service.get_user_by_id(user_id)

                if user_cache_data and user_cache_data.get("payment_in_progress") is True:
                    logger.warning(f"User {user_id} already has a payment in progress (Order ID: {order_id}). Skipping this webhook instance.")
                    return {"status": "skipped_payment_in_progress"}

                # 2. Set lock flag and save immediately
                if user_cache_data is None:
                    logger.warning(f"User {user_id} not found in cache when starting payment processing (Order ID: {order_id}). Initializing cache entry.")
                    user_cache_data = {} # Initialize if user not in cache yet

                user_cache_data["payment_in_progress"] = True
                # Use set_user which handles user_id key generation
                flag_set_success = await cache_service.set_user(user_cache_data, user_id=user_id)
                if not flag_set_success:
                    logger.error(f"Failed to set payment_in_progress flag for user {user_id} (Order ID: {order_id}). Aborting.")
                    # Let finally block clear the flag if possible, but return error status
                    return {"status": "cache_flag_set_failed"}
                logger.info(f"Set payment_in_progress flag for user {user_id} (Order ID: {order_id}).")

                # --- Start Protected Section ---
                # 3. Get current credits *from cache*
                current_credits = user_cache_data.get('credits')
                if current_credits is None:
                    logger.error(f"User {user_id} cache data missing 'credits' field (Order ID: {order_id}). Cannot process payment.")
                    raise Exception("Credits field missing from cache")

                # 4. Get vault_key_id *from cache*
                vault_key_id = user_cache_data.get("vault_key_id")
                if not vault_key_id:
                    logger.error(f"Vault key ID not found in CACHE for user {user_id} (Order ID: {order_id}). Cannot encrypt new credits.")
                    raise Exception("Vault key ID missing from cache") # Raise exception to trigger finally

                # 5. Calculate new total
                new_total_credits_calculated = current_credits + credits_purchased # Store for final cache update
                logger.info(f"Calculated new credit total for user {user_id}: {current_credits} (cached) + {credits_purchased} = {new_total_credits_calculated}")

                # 6. Update cached credits value immediately
                user_cache_data["credits"] = new_total_credits_calculated
                cache_update_success = await cache_service.set_user(user_cache_data, user_id=user_id)
                if not cache_update_success:
                    logger.error(f"Failed to update cached credits for user {user_id} (Order ID: {order_id}). Aborting payment processing.")
                    raise Exception("Failed to update cached credits")

                # 7. Encrypt new total using cached vault_key_id
                new_total_credits_str = str(new_total_credits_calculated)
                new_encrypted_credits, _ = await encryption_service.encrypt_with_user_key(new_total_credits_str, vault_key_id)

                # 8. Try to update Directus, with up to 3 attempts
                update_payload = {"encrypted_credit_balance": new_encrypted_credits}
                directus_update_success = False
                max_attempts = 3
                for attempt in range(1, max_attempts + 1):
                    directus_update_success = await directus_service.update_user(user_id, update_payload)
                    if directus_update_success:
                        logger.info(f"Successfully updated Directus credits for user {user_id} (Order ID: {order_id}) on attempt {attempt}.")
                        break
                    else:
                        logger.error(f"Attempt {attempt} to update Directus credits for user {user_id} (Order ID: {order_id}) failed.")
                # 9. If Directus update failed after 3 attempts, subtract the credits from cache again
                if not directus_update_success:
                    logger.error(f"Failed to update Directus credits for user {user_id} after {max_attempts} attempts (Order ID: {order_id}). Reverting cached credits.")
                    # Get latest cache, subtract credits, and update
                    latest_cache_data = await cache_service.get_user_by_id(user_id)
                    if latest_cache_data is None:
                        logger.error(f"Could not fetch latest cache for user {user_id} to revert credits (Order ID: {order_id}).")
                        latest_cache_data = {}
                    latest_credits = latest_cache_data.get("credits")
                    if latest_credits is None:
                        logger.error(f"Cannot revert cached credits for user {user_id} (Order ID: {order_id}) because 'credits' field is missing in cache.")
                    else:
                        reverted_credits = latest_credits - credits_purchased
                        latest_cache_data["credits"] = reverted_credits
                        revert_success = await cache_service.set_user(latest_cache_data, user_id=user_id)
                        if revert_success:
                            logger.info(f"Successfully reverted cached credits for user {user_id} to {reverted_credits} (Order ID: {order_id}).")
                        else:
                            logger.error(f"Failed to revert cached credits for user {user_id} (Order ID: {order_id}).")
                # --- End Protected Section ---

            except ValueError:
                logger.error(f"Could not parse credits_purchased '{credits_purchased_str}' to int for order {order_id}.")
                await cache_service.update_order_status(order_id, "failed_parsing_error")
                # Let finally block handle flag reset
            except Exception as processing_err:
                # Log errors from steps 3-7 or encryption
                logger.error(f"Error during protected processing for user {user_id}, order {order_id}: {processing_err}", exc_info=True)
                await cache_service.update_order_status(order_id, "failed_processing_error")
                # Let finally block handle flag reset
            finally:
                # 8. ALWAYS clear the flag and update cache status
                logger.debug(f"Entering finally block for user {user_id}, order {order_id}. Directus success: {directus_update_success}")
                final_cache_data = await cache_service.get_user_by_id(user_id) # Get latest cache data again
                if final_cache_data is None:
                    # If cache expired/cleared between setting flag and now, log warning but proceed to clear conceptually
                    logger.warning(f"Cache data for user {user_id} was missing when trying to clear payment_in_progress flag (Order ID: {order_id}).")
                    final_cache_data = {} # Initialize to avoid errors below

                final_cache_data["payment_in_progress"] = False # Clear the flag

                if directus_update_success:
                    # Update cache credits ONLY if Directus was successful
                    final_cache_data["credits"] = new_total_credits_calculated
                    logger.info(f"Updating final cache credits for user {user_id} to {new_total_credits_calculated} (Order ID: {order_id}).")
                    await cache_service.update_order_status(order_id, "completed") # Update order status cache
                else:
                    # Don't update credits field if Directus failed
                    logger.warning(f"Directus update failed for user {user_id}, order {order_id}. Cache 'credits' field NOT updated.")
                    # Order status should have been set to failed in except block if applicable

                # Save final cache state (with flag cleared and credits potentially updated)
                final_save_success = await cache_service.set_user(final_cache_data, user_id=user_id)
                if not final_save_success:
                     logger.error(f"Failed to save final cache state (clear flag) for user {user_id} (Order ID: {order_id}).")
                else:
                     logger.debug(f"Successfully saved final cache state (cleared flag) for user {user_id} (Order ID: {order_id}).")

        # --- Process ORDER_FAILED (or other terminal states from webhook if needed) ---
        elif event_type == "ORDER_FAILED":
            # Fetch order details to potentially get user_id if available in metadata
            order_details = await revolut_service.get_order(webhook_order_id)
            metadata = order_details.get("metadata", {}) if order_details else {}
            user_id_from_meta = metadata.get("user_id", "Unknown")
            error_message = order_details.get("error_message", "N/A") if order_details else "N/A"

            logger.warning(f"Received verified ORDER_FAILED event for order {webhook_order_id}. User (from metadata): {user_id_from_meta}. Reason: {error_message}")
            # Set order status in cache to "failed"
            await cache_service.update_order_status(webhook_order_id, "failed")
            # No action needed for credits, just log.

        # --- Ignore other events ---
        else:
            logger.info(f"Ignoring verified webhook event type: {event_type} for order {webhook_order_id}")

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


@router.post("/order-status", response_model=OrderStatusResponse) # Changed to POST
async def get_order_status(
    status_request: OrderStatusRequest, # Changed parameter to accept request body
    revolut_service: RevolutService = Depends(get_revolut_service),
    current_user: User = Depends(get_current_user) # Ensure user is authenticated
):
    """Retrieves the current status of a Revolut order."""
    order_id = status_request.order_id # Extract order_id from body
    logger.info(f"Fetching status for Revolut order {order_id} for user {current_user.id}")
    try:
        # We need to add a method to RevolutService to fetch order details
        order_details = await revolut_service.get_order(order_id)

        if not order_details:
            logger.warning(f"Order {order_id} not found or failed to fetch from Revolut for user {current_user.id}.")
            raise HTTPException(status_code=404, detail="Order not found")

        # Optional: Add check here to ensure the order belongs to the current_user
        # This might require storing user_id association with order_id or checking metadata if possible via GET /order
        # For now, we assume the frontend only polls for orders it created.

        order_state = order_details.get("state")
        if not order_state:
             logger.error(f"Revolut order details for {order_id} missing 'state'.")
             raise HTTPException(status_code=502, detail="Could not determine order status from payment provider.")

        logger.info(f"Status for order {order_id}: {order_state}")
        return OrderStatusResponse(order_id=order_id, state=order_state)

    except HTTPException as e:
        raise e # Re-raise HTTP exceptions
    except Exception as e:
        logger.error(f"Error fetching status for Revolut order {order_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error fetching order status.")