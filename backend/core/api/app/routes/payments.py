from fastapi import APIRouter, Depends, HTTPException, Request, Body
from pydantic import BaseModel
import logging
import os
import yaml
from typing import Dict, Any, Optional
from pathlib import Path

from backend.core.api.app.services.payment.payment_service import PaymentService
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.core.api.app.models.user import User
from backend.core.api.app.routes.auth_routes.auth_dependencies import get_current_user
from backend.core.api.app.tasks.celery_config import app # Import the Celery app

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/payments", tags=["Payments"])

def get_secrets_manager(request: Request) -> SecretsManager:
    return request.app.state.secrets_manager

def get_payment_service(request: Request) -> PaymentService:
    if not hasattr(request.app.state, 'payment_service'):
        logger.error("PaymentService not found in application state.")
        raise HTTPException(status_code=503, detail="Payment service unavailable")
    return request.app.state.payment_service

def get_directus_service(request: Request) -> DirectusService:
    return request.app.state.directus_service

def get_cache_service(request: Request) -> CacheService:
    return request.app.state.cache_service

def get_encryption_service(request: Request) -> EncryptionService:
    return request.app.state.encryption_service

def is_production() -> bool:
    return os.getenv("SERVER_ENVIRONMENT", "development") == "production"

class PaymentConfigResponse(BaseModel):
    provider: str
    public_key: str
    environment: str

class CreateOrderRequest(BaseModel):
    currency: str
    credits_amount: int
    email_encryption_key: Optional[str] = None

class CreateOrderResponse(BaseModel):
    provider: str
    order_token: Optional[str] = None # For Revolut
    client_secret: Optional[str] = None # For Stripe
    order_id: str

class OrderStatusRequest(BaseModel):
    order_id: str

class OrderStatusResponse(BaseModel):
    order_id: str
    state: str
    current_credits: Optional[int] = None

PRICING_CONFIG_PATH = Path("/shared/config/pricing.yml")
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
    currency_lower = currency.lower()
    for tier in PRICING_TIERS:
        if tier.get('credits') == credits_amount:
            price_in_currency = tier.get('price', {}).get(currency_lower)
            if price_in_currency is not None:
                if currency_lower in ['eur', 'usd', 'gbp']:
                    return int(price_in_currency * 100)
                else:
                    return int(price_in_currency)
            else:
                logger.warning(f"Currency '{currency}' not found in price tier for {credits_amount} credits.")
                return None
    logger.warning(f"No pricing tier found for {credits_amount} credits.")
    return None

@router.get("/config", response_model=PaymentConfigResponse)
async def get_payment_config(
    secrets_manager: SecretsManager = Depends(get_secrets_manager),
    payment_service: PaymentService = Depends(get_payment_service)
):
    """Provides the necessary public configuration for the frontend payment widget."""
    try:
        provider_name = payment_service.provider_name
        environment = "production" if is_production() else "sandbox"
        
        public_key = None
        if provider_name == "revolut":
            secret_key_name = f"merchant_{environment}_public_key"
            secret_path = "kv/data/providers/revolut_business"
            public_key = await secrets_manager.get_secret(secret_path=secret_path, secret_key=secret_key_name)
        elif provider_name == "stripe":
            secret_key_name = f"{environment}_public_key"
            secret_path = "kv/data/providers/stripe"
            public_key = await secrets_manager.get_secret(secret_path=secret_path, secret_key=secret_key_name)
        else:
            raise HTTPException(status_code=503, detail="Payment provider not configured.")

        if not public_key:
            logger.error(f"Public Key '{secret_key_name}' not found for provider '{provider_name}'.")
            raise HTTPException(status_code=503, detail="Payment configuration unavailable.")

        logger.info(f"Payment config fetched for provider: {provider_name}, environment: {environment}")
        return PaymentConfigResponse(provider=provider_name, public_key=public_key, environment=environment)
    except Exception as e:
        logger.error(f"Error fetching payment config: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error fetching payment config.")

@router.post("/create-order", response_model=CreateOrderResponse)
async def create_payment_order(
    order_data: CreateOrderRequest,
    current_user: User = Depends(get_current_user),
    payment_service: PaymentService = Depends(get_payment_service),
    encryption_service: EncryptionService = Depends(get_encryption_service),
    cache_service: CacheService = Depends(get_cache_service)
):
    logger.info(f"Received request to create payment order for user {current_user.id} - Provider: {payment_service.provider_name}, Currency: {order_data.currency}, Credits: {order_data.credits_amount}")

    calculated_amount = get_price_for_credits(order_data.credits_amount, order_data.currency)
    if calculated_amount is None:
        logger.error(f"Could not determine price for {order_data.credits_amount} credits in {order_data.currency} for user {current_user.id}.")
        raise HTTPException(status_code=400, detail=f"Invalid credit amount or currency combination.")
    
    try:
        if not current_user.encrypted_email_address:
            logger.error(f"Missing encrypted_email_address for user {current_user.id}")
            raise HTTPException(status_code=500, detail="User email information unavailable.")
        
        if not order_data.email_encryption_key:
            logger.error(f"Missing email_encryption_key in request for user {current_user.id}")
            raise HTTPException(status_code=400, detail="Email encryption key is required")
            
        try:
            logger.info(f"Using client-provided email encryption key for user {current_user.id}")
            decrypted_email = await encryption_service.decrypt_with_email_key(
                current_user.encrypted_email_address,
                order_data.email_encryption_key
            )
            
            if not decrypted_email:
                logger.error(f"Failed to decrypt email with provided key for user {current_user.id}")
                raise HTTPException(status_code=400, detail="Invalid email encryption key")
                
        except Exception as e:
            logger.error(f"Error decrypting email for user {current_user.id}: {str(e)}")
            raise HTTPException(status_code=500, detail="Failed to decrypt user email")

        order_response = await payment_service.create_order(
            amount=calculated_amount,
            currency=order_data.currency,
            email=decrypted_email,
            credits_amount=order_data.credits_amount
        )

        if not order_response:
            logger.error(f"Failed to create order with {payment_service.provider_name} for user {current_user.id}.")
            raise HTTPException(status_code=502, detail="Failed to initiate payment with provider.")

        order_id = order_response.get("id")
        if not order_id:
            logger.error(f"Order response from {payment_service.provider_name} missing 'id' for user {current_user.id}.")
            raise HTTPException(status_code=502, detail="Failed to get order ID from payment provider.")

        await cache_service.set_order(
            order_id=order_id,
            user_id=current_user.id,
            credits_amount=order_data.credits_amount,
            status="created",
            ttl=3600 # 1 hour
        )

        response_data = {
            "provider": payment_service.provider_name,
            "order_id": order_id,
            "order_token": order_response.get("token"), # For Revolut
            "client_secret": order_response.get("client_secret") # For Stripe
        }
        
        return CreateOrderResponse(**response_data)

    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error creating payment order for user {current_user.id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error during payment initiation.")

@router.post("/webhook", status_code=200)
async def payment_webhook(
    request: Request,
    payment_service: PaymentService = Depends(get_payment_service),
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service),
    encryption_service: EncryptionService = Depends(get_encryption_service),
    secrets_manager: SecretsManager = Depends(get_secrets_manager)
):
    payload_bytes = await request.body()
    
    # Differentiate webhooks by headers
    provider_name = None
    sig_header = None
    request_timestamp_header = None # For Revolut

    if "Revolut-Signature" in request.headers:
        provider_name = "revolut"
        sig_header = request.headers.get("Revolut-Signature")
        request_timestamp_header = request.headers.get("Revolut-Request-Timestamp")
    elif "Stripe-Signature" in request.headers:
        provider_name = "stripe"
        sig_header = request.headers.get("Stripe-Signature")
    else:
        logger.warning("Webhook received without a recognizable signature header.")
        raise HTTPException(status_code=400, detail="Missing or unsupported signature header")

    logger.info(f"Received {provider_name} webhook.")

    if not sig_header:
        logger.warning(f"Missing {provider_name.capitalize()}-Signature header in webhook request.")
        raise HTTPException(status_code=400, detail="Missing signature")

    try:
        # For Revolut, pass timestamp header; for Stripe, it's handled internally by construct_event
        if provider_name == "revolut":
            event_payload = await payment_service.verify_and_parse_webhook(
                payload_bytes, sig_header, request_timestamp_header
            )
        elif provider_name == "stripe":
            event_payload = await payment_service.verify_and_parse_webhook(
                payload_bytes, sig_header
            )
        else:
            event_payload = None

        if event_payload is None: # If verification or parsing failed
            raise HTTPException(status_code=400, detail="Invalid signature or unparseable payload")

        event_type = event_payload.get("type") if provider_name == "stripe" else event_payload.get("event")
        
        # Normalize event type and get order ID
        webhook_order_id = None
        if provider_name == "revolut":
            webhook_order_id = event_payload.get("order_id")
        elif provider_name == "stripe":
            # For Stripe, the PaymentIntent ID is in event.data.object.id
            if event_type.startswith("payment_intent."):
                webhook_order_id = event_payload.get("data", {}).get("object", {}).get("id")
            elif event_type == "checkout.session.completed":
                # If using Checkout Sessions, the PaymentIntent ID is linked
                webhook_order_id = event_payload.get("data", {}).get("object", {}).get("payment_intent")

        if not webhook_order_id:
            logger.warning(f"Webhook event {event_type} received without an order_id for provider {provider_name}.")
            return {"status": "received_missing_order_id"}

        logger.info(f"Processing verified webhook event: {event_type} for Order ID: {webhook_order_id} from {provider_name}")

        if (provider_name == "revolut" and event_type == "ORDER_COMPLETED") or \
           (provider_name == "stripe" and event_type == "payment_intent.succeeded"):
            
            cached_order_data = await cache_service.get_order(webhook_order_id)
            if not cached_order_data:
                logger.error(f"Order {webhook_order_id} not found in cache. Cannot process.")
                await cache_service.update_order_status(webhook_order_id, "failed_missing_cache_data")
                return {"status": "order_cache_miss"}

            user_id = cached_order_data.get("user_id")
            credits_purchased = cached_order_data.get("credits_amount")

            if not user_id or credits_purchased is None:
                logger.error(f"Missing user_id or credits_amount in cached data for order {webhook_order_id}.")
                await cache_service.update_order_status(webhook_order_id, "failed_invalid_cache_data")
                return {"status": "cache_data_invalid"}

            user_cache_data = await cache_service.get_user_by_id(user_id)
            if user_cache_data and user_cache_data.get("payment_in_progress"):
                logger.warning(f"User {user_id} already has a payment in progress. Skipping webhook.")
                return {"status": "skipped_payment_in_progress"}

            if user_cache_data is None:
                user_cache_data = {}
            
            user_cache_data["payment_in_progress"] = True
            await cache_service.set_user(user_cache_data, user_id=user_id)

            directus_update_success = False
            new_total_credits_calculated = 0

            try:
                current_credits = user_cache_data.get('credits')
                if current_credits is None:
                    raise Exception("Credits field missing from cache")

                vault_key_id = user_cache_data.get("vault_key_id")
                if not vault_key_id:
                    raise Exception("Vault key ID missing from cache")

                new_total_credits_calculated = current_credits + credits_purchased
                new_encrypted_credits, _ = await encryption_service.encrypt_with_user_key(str(new_total_credits_calculated), vault_key_id)

                update_payload = {"encrypted_credit_balance": new_encrypted_credits, "last_opened": "/chat/new"}
                directus_update_success = await directus_service.update_user(user_id, update_payload)

                if directus_update_success:
                    logger.info(f"Successfully updated Directus credits for user {user_id}.")

                    # Publish an event to notify websockets about the credit update
                    try:
                        await cache_service.publish_event(
                            channel=f"user_updates::{user_id}",
                            event_data={
                                "event_for_client": "user_credits_updated",
                                "user_id_uuid": user_id,
                                "payload": {"credits": new_total_credits_calculated}
                            }
                        )
                        logger.info(f"Published 'user_credits_updated' event for user {user_id}.")
                    except Exception as pub_exc:
                        logger.error(f"Failed to publish 'user_credits_updated' event for user {user_id}: {pub_exc}", exc_info=True)

                    # Dispatch invoice task
                    # Fetch sender details for invoice via SecretsManager
                    invoice_sender_path = f"kv/data/providers/invoice_sender"

                    sender_addressline1 = await secrets_manager.get_secret(secret_path=invoice_sender_path, secret_key="addressline1")
                    sender_addressline2 = await secrets_manager.get_secret(secret_path=invoice_sender_path, secret_key="addressline2")
                    sender_addressline3 = await secrets_manager.get_secret(secret_path=invoice_sender_path, secret_key="addressline3")
                    sender_country = await secrets_manager.get_secret(secret_path=invoice_sender_path, secret_key="country")
                    sender_email = await secrets_manager.get_secret(secret_path=invoice_sender_path, secret_key="email")
                    sender_vat = await secrets_manager.get_secret(secret_path=invoice_sender_path, secret_key="vat")
                    
                    task_payload = {
                        "order_id": webhook_order_id,
                        "user_id": user_id,
                        "credits_purchased": credits_purchased,
                        "sender_addressline1": sender_addressline1,
                        "sender_addressline2": sender_addressline2,
                        "sender_addressline3": sender_addressline3,
                        "sender_country": sender_country,
                        "sender_email": sender_email if sender_email else "support@openmates.org",
                        "sender_vat": sender_vat
                    }
                    app.send_task(
                        name='app.tasks.email_tasks.purchase_confirmation_email_task.process_invoice_and_send_email',
                        kwargs=task_payload,
                        queue='email'
                    )
                    logger.info(f"Dispatched invoice processing task for user {user_id}, order {webhook_order_id} to queue 'email'.")
                else:
                    logger.error(f"Failed to update Directus credits for user {user_id}.")

            except Exception as processing_err:
                logger.error(f"Error during payment processing for user {user_id}: {processing_err}", exc_info=True)
                await cache_service.update_order_status(webhook_order_id, "failed_processing_error")
            finally:
                final_cache_data = await cache_service.get_user_by_id(user_id) or {}
                final_cache_data["payment_in_progress"] = False
                final_order_status = "unknown"
                if directus_update_success:
                    final_cache_data["credits"] = new_total_credits_calculated
                    final_cache_data["last_opened"] = "/chat/new"
                    final_order_status = "completed"
                else:
                    final_order_status = "failed_directus_update"
                
                await cache_service.set_user(final_cache_data, user_id=user_id)
                await cache_service.update_order_status(webhook_order_id, final_order_status)

        elif (provider_name == "revolut" and event_type == "ORDER_CANCELLED") or \
             (provider_name == "stripe" and event_type == "payment_intent.payment_failed"):
            logger.warning(f"Payment for order {webhook_order_id} failed or was cancelled.")
            await cache_service.update_order_status(webhook_order_id, "failed")
        else:
            logger.info(f"Ignoring webhook event type: {event_type} from {provider_name}")

    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Unexpected error processing webhook: {str(e)}", exc_info=True)
        return {"status": "internal_server_error"}

    return {"status": "received"}

@router.post("/order-status", response_model=OrderStatusResponse)
async def get_order_status(
    status_request: OrderStatusRequest,
    payment_service: PaymentService = Depends(get_payment_service),
    cache_service: CacheService = Depends(get_cache_service),
    current_user: User = Depends(get_current_user)
):
    order_id = status_request.order_id
    logger.info(f"Fetching status for order {order_id} for user {current_user.id}")
    try:
        cached_order_data = await cache_service.get_order(order_id)
        if not cached_order_data or cached_order_data.get("user_id") != current_user.id:
            raise HTTPException(status_code=404, detail="Order not found")

        order_details = await payment_service.get_order(order_id)
        if not order_details:
            raise HTTPException(status_code=404, detail="Order not found")

        order_state = order_details.get("status") # Stripe uses 'status', Revolut uses 'state'
        internal_status = cached_order_data.get("status")

        if not order_state:
            raise HTTPException(status_code=502, detail="Could not determine order status.")

        user_credits: Optional[int] = None
        final_state = order_state

        # Normalize status for frontend display
        if order_state.upper() == "SUCCEEDED": # Stripe status
            final_state = "COMPLETED"
        elif order_state.upper() == "COMPLETED": # Revolut status
            final_state = "COMPLETED"
        elif order_state.upper() == "REQUIRES_PAYMENT_METHOD" or \
             order_state.upper() == "REQUIRES_CONFIRMATION" or \
             order_state.upper() == "REQUIRES_ACTION": # Stripe statuses
            final_state = "PENDING"
        elif order_state.upper() == "PENDING": # Revolut status
            final_state = "PENDING"
        elif order_state.upper() == "CANCELED" or \
             order_state.upper() == "FAILED": # Stripe/Revolut statuses
            final_state = "FAILED"

        if final_state == "COMPLETED":
            if internal_status == "completed":
                user_cache_data = await cache_service.get_user_by_id(current_user.id)
                if user_cache_data:
                    user_credits = user_cache_data.get('credits')
            else:
                final_state = "PENDING_CONFIRMATION" # Still waiting for backend processing

        return OrderStatusResponse(order_id=order_id, state=final_state, current_credits=user_credits)

    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error fetching order status for {order_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error.")
