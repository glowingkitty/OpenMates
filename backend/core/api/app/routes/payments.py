from fastapi import APIRouter, Depends, HTTPException, Request, Body
from pydantic import BaseModel
import logging
import os
import yaml
from typing import Dict, Any, Optional, List
from pathlib import Path

from backend.core.api.app.services.payment.payment_service import PaymentService
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.core.api.app.models.user import User
from backend.core.api.app.routes.auth_routes.auth_dependencies import get_current_user
from backend.core.api.app.tasks.celery_config import app # Import the Celery app
from backend.core.api.app.routes.websockets import manager
from backend.core.api.app.services.compliance import ComplianceService
from backend.core.api.app.services.s3.service import S3UploadService
from backend.core.api.app.services.s3.config import get_bucket_name
from backend.core.api.app.services.limiter import limiter
from fastapi.responses import StreamingResponse
import hashlib

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

def get_s3_service(request: Request) -> S3UploadService:
    return request.app.state.s3_service

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

class SavePaymentMethodRequest(BaseModel):
    payment_intent_id: str

class CreateSubscriptionRequest(BaseModel):
    credits_amount: int
    currency: str

class CreateSubscriptionResponse(BaseModel):
    subscription_id: str
    status: str
    next_billing_date: str

class RedeemGiftCardRequest(BaseModel):
    code: str

class RedeemGiftCardResponse(BaseModel):
    success: bool
    credits_added: int
    current_credits: int
    message: str

class InvoiceResponse(BaseModel):
    id: str
    date: str
    amount: str
    credits_purchased: int
    filename: str

class InvoicesListResponse(BaseModel):
    invoices: List[InvoiceResponse]

class GetSubscriptionResponse(BaseModel):
    subscription_id: str
    status: str
    credits_amount: int
    bonus_credits: int
    currency: str
    price: int
    next_billing_date: Optional[str] = None
    cancel_at_period_end: bool

class CancelSubscriptionResponse(BaseModel):
    subscription_id: str
    status: str
    cancel_at_period_end: bool

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
    """
    Get the price for a credit amount in the smallest currency unit (cents).
    
    Args:
        credits_amount: Number of credits
        currency: Currency code (EUR, USD, JPY)
        
    Returns:
        Price in cents/smallest unit, or None if not found
    """
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

def get_bonus_credits_for_tier(credits_amount: int) -> int:
    """
    Get bonus credits for a subscription tier.
    
    Args:
        credits_amount: Base credits amount
        
    Returns:
        Bonus credits amount (0 if no bonus)
    """
    for tier in PRICING_TIERS:
        if tier.get('credits') == credits_amount:
            return tier.get('monthly_auto_top_up_extra_credits', 0)
    return 0

def get_tier_info(credits_amount: int, currency: str) -> Optional[Dict[str, Any]]:
    """
    Get complete tier information including price and bonus credits.
    
    Args:
        credits_amount: Base credits amount
        currency: Currency code
        
    Returns:
        Dictionary with tier info or None if not found
    """
    price = get_price_for_credits(credits_amount, currency)
    if price is None:
        return None
    
    bonus_credits = get_bonus_credits_for_tier(credits_amount)
    
    return {
        'credits': credits_amount,
        'bonus_credits': bonus_credits,
        'price': price,
        'currency': currency.lower()
    }

@router.get("/config", response_model=PaymentConfigResponse)
@limiter.limit("60/minute")  # Public endpoint, allow higher rate
async def get_payment_config(
    request: Request,
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
@limiter.limit("10/minute")  # Sensitive endpoint - prevent abuse while allowing retries
async def create_payment_order(
    request: Request,
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

        # Cache the order - CRITICAL: Check if cache write succeeded
        # If cache write fails, webhook processing will fail because order won't be found
        cache_success = await cache_service.set_order(
            order_id=order_id,
            user_id=current_user.id,
            credits_amount=order_data.credits_amount,
            status="created",
            ttl=3600, # 1 hour TTL (increased from 5 minutes to handle webhook delays/retries)
            email_encryption_key=order_data.email_encryption_key  # Store the email encryption key
        )
        
        if not cache_success:
            logger.error(f"CRITICAL: Failed to cache order {order_id} for user {current_user.id}. Webhook processing will fail!")
            # Don't fail the request - payment was created successfully
            # But log the error so we can investigate cache issues

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
# Note: Webhook endpoint is called by payment providers (Stripe/Revolut)
# Rate limiting is handled by signature verification - providers have their own rate limits
# We don't apply strict rate limits here to avoid blocking legitimate webhook deliveries
# Security is ensured through signature verification in verify_and_parse_webhook
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
            elif event_type == "checkout.session.async_payment_failed":
                # For async payment failures, get PaymentIntent ID from checkout session
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
                        # First, publish to user_updates channel for the WebSocket listener
                        await cache_service.publish_event(
                            channel=f"user_updates::{user_id}",
                            event_data={
                                "event_for_client": "user_credits_updated",
                                "user_id_uuid": user_id,
                                "payload": {"credits": new_total_credits_calculated}
                            }
                        )
                        
                        # Also directly broadcast to the user via WebSocket manager for immediate update
                        
                        await manager.broadcast_to_user_specific_event(
                            user_id=user_id,
                            event_name="user_credits_updated",
                            payload={"credits": new_total_credits_calculated}
                        )
                        
                        logger.info(f"Published and broadcasted 'user_credits_updated' event for user {user_id}.")
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
                    
                    # Get the email encryption key from the cached order data
                    email_encryption_key = cached_order_data.get("email_encryption_key")
                    if not email_encryption_key:
                        logger.warning(f"Email encryption key not found in cached order data for order {webhook_order_id}. Email decryption may fail.")
                    
                    task_payload = {
                        "order_id": webhook_order_id,
                        "user_id": user_id,
                        "credits_purchased": credits_purchased,
                        "sender_addressline1": sender_addressline1,
                        "sender_addressline2": sender_addressline2,
                        "sender_addressline3": sender_addressline3,
                        "sender_country": sender_country,
                        "sender_email": sender_email if sender_email else "support@openmates.org",
                        "sender_vat": sender_vat,
                        "email_encryption_key": email_encryption_key  # Pass the email encryption key to the task
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
             (provider_name == "stripe" and event_type == "payment_intent.payment_failed") or \
             (provider_name == "stripe" and event_type == "checkout.session.async_payment_failed"):
            logger.warning(f"Payment for order {webhook_order_id} failed or was cancelled.")
            await cache_service.update_order_status(webhook_order_id, "failed")
            
            # Get user_id from cached order data to send notification
            cached_order_data = await cache_service.get_order(webhook_order_id)
            if cached_order_data:
                user_id = cached_order_data.get("user_id")
                if user_id:
                    # Send payment_failed notification via websocket
                    try:
                        # Publish payment_failed event to user_updates channel
                        await cache_service.publish_event(
                            channel=f"user_updates::{user_id}",
                            event_data={
                                "event_for_client": "payment_failed",
                                "user_id_uuid": user_id,
                                "payload": {
                                    "order_id": webhook_order_id,
                                    "message": "Payment failed. Please try again or use a different payment method."
                                }
                            }
                        )
                        
                        # Also directly broadcast to the user via WebSocket manager for immediate update
                        await manager.broadcast_to_user_specific_event(
                            user_id=user_id,
                            event_name="payment_failed",
                            payload={
                                "order_id": webhook_order_id,
                                "message": "Payment failed. Please try again or use a different payment method."
                            }
                        )
                        
                        logger.info(f"Published and broadcasted 'payment_failed' event for user {user_id}, order {webhook_order_id}.")
                    except Exception as pub_exc:
                        logger.error(f"Failed to publish 'payment_failed' event for user {user_id}: {pub_exc}", exc_info=True)
        
        # Handle subscription events
        elif provider_name == "stripe" and event_type == "invoice.payment_succeeded":
            # Process monthly subscription renewal
            invoice_data = event_payload.get("data", {}).get("object", {})
            subscription_id = invoice_data.get("subscription")
            
            if not subscription_id:
                logger.warning(f"Invoice payment succeeded but no subscription_id found")
                return {"status": "received_no_subscription"}
            
            # Get user by subscription_id
            user_data = await directus_service.get_user_by_subscription_id(subscription_id)
            
            if not user_data:
                logger.error(f"User not found for subscription {subscription_id}")
                return {"status": "user_not_found"}
            
            user_id = user_data.get("id")
            subscription_credits = user_data.get("subscription_credits", 0)
            subscription_currency = user_data.get("subscription_currency", "eur")
            
            # Get bonus credits from pricing.yml
            tier_info = get_tier_info(subscription_credits, subscription_currency)
            bonus_credits = tier_info['bonus_credits'] if tier_info else 0
            total_credits_to_add = subscription_credits + bonus_credits
            
            logger.info(f"Processing subscription renewal for user {user_id}: adding {total_credits_to_add} credits ({subscription_credits} + {bonus_credits} bonus)")
            
            # Get current credits and add subscription credits
            user_cache_data = await cache_service.get_user_by_id(user_id)
            if not user_cache_data:
                logger.error(f"User {user_id} not found in cache for subscription renewal")
                return {"status": "user_cache_miss"}
            
            current_credits = user_cache_data.get('credits', 0)
            new_total_credits = current_credits + total_credits_to_add
            
            # Encrypt new credit balance
            vault_key_id = user_cache_data.get("vault_key_id")
            if not vault_key_id:
                logger.error(f"Vault key ID missing for user {user_id}")
                return {"status": "vault_key_missing"}
            
            new_encrypted_credits, _ = await encryption_service.encrypt_with_user_key(
                str(new_total_credits),
                vault_key_id
            )
            
            # Update Directus
            update_success = await directus_service.update_user(
                user_id,
                {"encrypted_credit_balance": new_encrypted_credits}
            )
            
            if update_success:
                logger.info(f"Successfully added {total_credits_to_add} credits to user {user_id} (subscription renewal)")
                
                # Update cache
                user_cache_data["credits"] = new_total_credits
                await cache_service.set_user(user_cache_data, user_id=user_id)
                
                # Broadcast credit update
                try:
                    await cache_service.publish_event(
                        channel=f"user_updates::{user_id}",
                        event_data={
                            "event_for_client": "user_credits_updated",
                            "user_id_uuid": user_id,
                            "payload": {"credits": new_total_credits}
                        }
                    )
                    
                    await manager.broadcast_to_user_specific_event(
                        user_id=user_id,
                        event_name="user_credits_updated",
                        payload={"credits": new_total_credits}
                    )
                    
                    logger.info(f"Broadcasted credit update for subscription renewal to user {user_id}")
                except Exception as pub_exc:
                    logger.error(f"Failed to broadcast subscription renewal credits for user {user_id}: {pub_exc}", exc_info=True)
            else:
                logger.error(f"Failed to update credits for user {user_id} subscription renewal")
        
        elif provider_name == "stripe" and event_type == "customer.subscription.deleted":
            # Handle subscription cancellation
            subscription_data = event_payload.get("data", {}).get("object", {})
            subscription_id = subscription_data.get("id")
            
            if subscription_id:
                # Update user's subscription status to canceled
                user_data = await directus_service.get_user_by_subscription_id(subscription_id)
                if user_data:
                    user_id = user_data.get("id")
                    await directus_service.update_user(
                        user_id,
                        {"subscription_status": "canceled"}
                    )
                    logger.info(f"Updated subscription status to canceled for user {user_id}")
        
        elif provider_name == "stripe" and event_type == "invoice.payment_failed":
            # Handle failed subscription payment
            invoice_data = event_payload.get("data", {}).get("object", {})
            subscription_id = invoice_data.get("subscription")
            
            if subscription_id:
                logger.warning(f"Subscription payment failed for subscription {subscription_id}")
                user_data = await directus_service.get_user_by_subscription_id(subscription_id)
                if user_data:
                    user_id = user_data.get("id")
                    await directus_service.update_user(
                        user_id,
                        {"subscription_status": "past_due"}
                    )
                    logger.info(f"Updated subscription status to past_due for user {user_id}")
        
        elif provider_name == "stripe" and event_type == "customer.subscription.updated":
            # Handle subscription updates (e.g., status changes)
            subscription_data = event_payload.get("data", {}).get("object", {})
            subscription_id = subscription_data.get("id")
            new_status = subscription_data.get("status")
            current_period_end = subscription_data.get("current_period_end")
            
            if subscription_id:
                user_data = await directus_service.get_user_by_subscription_id(subscription_id)
                if user_data:
                    user_id = user_data.get("id")
                    from datetime import datetime
                    next_billing_date = datetime.fromtimestamp(current_period_end).isoformat() if current_period_end else None
                    
                    update_payload = {
                        "subscription_status": new_status
                    }
                    if next_billing_date:
                        update_payload["next_billing_date"] = next_billing_date
                    
                    await directus_service.update_user(user_id, update_payload)
                    logger.info(f"Updated subscription status to {new_status} for user {user_id}")
        
        else:
            logger.info(f"Ignoring webhook event type: {event_type} from {provider_name}")

    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Unexpected error processing webhook: {str(e)}", exc_info=True)
        return {"status": "internal_server_error"}

    return {"status": "received"}

@router.post("/order-status", response_model=OrderStatusResponse)
@limiter.limit("30/minute")  # Allow frequent polling for order status updates
async def get_order_status(
    request: Request,
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

@router.post("/save-payment-method")
@limiter.limit("5/minute")  # Very sensitive - prevent abuse of payment method storage
async def save_payment_method(
    request: Request,
    request_data: SavePaymentMethodRequest,
    current_user: User = Depends(get_current_user),
    payment_service: PaymentService = Depends(get_payment_service),
    encryption_service: EncryptionService = Depends(get_encryption_service),
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service)
):
    """
    Save the payment method ID from a successful payment for future subscription use.
    Creates a Stripe customer immediately and attaches the payment method to it.
    This must be done right after payment to avoid Stripe's restriction on reusing
    payment methods that were used without being attached to a customer.
    
    The payment_method ID is encrypted with the user's vault key.
    The customer_id is stored in cleartext (not sensitive).
    """
    logger.info(f"Saving payment method for user {current_user.id}")
    
    try:
        # Get payment method ID from the successful PaymentIntent
        if payment_service.provider_name != "stripe":
            raise HTTPException(status_code=400, detail="Subscriptions only supported with Stripe")
        
        payment_method_id = await payment_service.provider.get_payment_method(
            request_data.payment_intent_id
        )
        
        if not payment_method_id:
            raise HTTPException(status_code=404, detail="Payment method not found")
        
        # Get user email for customer creation
        user_cache_data = await cache_service.get_user_by_id(current_user.id)
        email = None
        
        if user_cache_data and user_cache_data.get('email'):
            email = user_cache_data.get('email')
        else:
            # Email not in cache - use placeholder that Stripe accepts
            logger.warning(f"Email not found in cache for user {current_user.id}, using placeholder")
            email = f"user-{current_user.id}@openmates.local"
        
        # Create customer and attach payment method immediately
        # This must be done right away to avoid Stripe's restriction on reusing
        # payment methods that were used without being attached to a customer
        customer_result = await payment_service.provider.create_customer(
            email=email,
            payment_method_id=payment_method_id
        )
        
        if not customer_result:
            logger.error(f"Failed to create customer for user {current_user.id}. Payment method may not be reusable for subscriptions.")
            # Still save the payment method - we'll handle subscription creation differently
            # (e.g., using SetupIntent to collect a new payment method)
            customer_id = None
        else:
            customer_id = customer_result['customer_id']
            logger.info(f"Created Stripe customer {customer_id} for user {current_user.id}")
        
        # Encrypt payment_method_id with user's vault key
        vault_key_id = current_user.vault_key_id
        if not vault_key_id:
            raise HTTPException(status_code=500, detail="User vault key not found")
        
        encrypted_payment_method_id, _ = await encryption_service.encrypt_with_user_key(
            payment_method_id,
            vault_key_id
        )
        
        # Prepare update payload
        update_payload = {"encrypted_payment_method_id": encrypted_payment_method_id}
        if customer_id:
            update_payload["stripe_customer_id"] = customer_id
        
        # Save to Directus
        update_success = await directus_service.update_user(
            current_user.id,
            update_payload
        )
        
        if not update_success:
            raise HTTPException(status_code=500, detail="Failed to save payment method")
        
        logger.info(f"Successfully saved payment method for user {current_user.id}" + 
                   (f" with customer {customer_id}" if customer_id else " (customer creation failed)"))
        return {"status": "success", "customer_created": customer_id is not None}
        
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error saving payment method for user {current_user.id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")

@router.post("/create-subscription", response_model=CreateSubscriptionResponse)
@limiter.limit("5/minute")  # Very sensitive - prevent abuse of subscription creation
async def create_subscription(
    request: Request,
    subscription_data: CreateSubscriptionRequest,
    current_user: User = Depends(get_current_user),
    payment_service: PaymentService = Depends(get_payment_service),
    encryption_service: EncryptionService = Depends(get_encryption_service),
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service)
):
    """
    Create a monthly subscription for auto top-up.
    Requires the user to have a saved payment method from a previous successful payment.
    """
    logger.info(f"Creating subscription for user {current_user.id}: {subscription_data.credits_amount} credits in {subscription_data.currency}")
    
    try:
        # Validate tier exists and has subscription bonus
        tier_info = get_tier_info(subscription_data.credits_amount, subscription_data.currency)
        if not tier_info:
            raise HTTPException(status_code=400, detail="Invalid credit amount or currency")
        
        if tier_info['bonus_credits'] == 0:
            raise HTTPException(status_code=400, detail="This tier does not support subscriptions")
        
        # Check if Stripe provider
        if payment_service.provider_name != "stripe":
            raise HTTPException(status_code=400, detail="Subscriptions only supported with Stripe")
        
        # Get encrypted payment method
        if not current_user.encrypted_payment_method_id:
            raise HTTPException(status_code=400, detail="No saved payment method found")
        
        # Decrypt payment method ID
        vault_key_id = current_user.vault_key_id
        if not vault_key_id:
            raise HTTPException(status_code=500, detail="User vault key not found")
        
        payment_method_id = await encryption_service.decrypt_with_user_key(
            current_user.encrypted_payment_method_id,
            vault_key_id
        )
        
        if not payment_method_id:
            raise HTTPException(status_code=500, detail="Failed to decrypt payment method")
        
        # Check if we already have a customer ID from when the payment method was saved
        customer_id = current_user.stripe_customer_id
        
        if not customer_id:
            # No existing customer - this shouldn't happen if save_payment_method was called
            # But we'll try to create one as a fallback
            logger.warning(f"No existing customer ID for user {current_user.id}, attempting to create one")
            
            # Get user email for customer creation
            user_cache_data = await cache_service.get_user_by_id(current_user.id)
            email = None
            
            if user_cache_data and user_cache_data.get('email'):
                email = user_cache_data.get('email')
            else:
                # Email not in cache - use placeholder
                logger.warning(f"Email not found in cache for user {current_user.id}, using placeholder")
                email = f"user-{current_user.id}@openmates.local"
            
            # Try to create customer and attach payment method
            customer_result = await payment_service.provider.create_customer(
                email=email,
                payment_method_id=payment_method_id
            )
            
            if not customer_result:
                raise HTTPException(
                    status_code=500, 
                    detail="Failed to create Stripe customer. Payment method may have been previously used and cannot be reused. Please use a different payment method for subscriptions."
                )
            
            customer_id = customer_result['customer_id']
            
            # Save the customer ID for future use
            await directus_service.update_user(
                current_user.id,
                {"stripe_customer_id": customer_id}
            )
            logger.info(f"Created and saved Stripe customer {customer_id} for user {current_user.id}")
        else:
            logger.info(f"Using existing Stripe customer {customer_id} for user {current_user.id}")
        
        # Find the Stripe price ID for this tier
        product_name = f"{subscription_data.credits_amount:,}".replace(",", ".") + " credits"
        price_id = await payment_service.provider._find_price_for_product(
            product_name,
            subscription_data.currency
        )
        
        if not price_id:
            logger.error(f"No Stripe price found for {subscription_data.credits_amount} credits in {subscription_data.currency}")
            raise HTTPException(status_code=500, detail="Subscription product not configured")
        
        # Create subscription
        subscription_result = await payment_service.provider.create_subscription(
            customer_id=customer_id,
            price_id=price_id,
            metadata={
                "user_id": current_user.id,
                "credits_amount": str(subscription_data.credits_amount),
                "bonus_credits": str(tier_info['bonus_credits'])
            }
        )
        
        if not subscription_result:
            raise HTTPException(status_code=500, detail="Failed to create subscription")
        
        # Save subscription details to Directus
        from datetime import datetime
        next_billing_date = datetime.fromtimestamp(
            subscription_result['current_period_end']
        ).isoformat()
        
        update_payload = {
            "stripe_subscription_id": subscription_result['subscription_id'],
            "subscription_status": subscription_result['status'],
            "subscription_credits": subscription_data.credits_amount,
            "subscription_currency": subscription_data.currency.lower(),
            "next_billing_date": next_billing_date
        }
        
        update_success = await directus_service.update_user(current_user.id, update_payload)
        
        if not update_success:
            # Subscription created but failed to save - log error but don't fail
            logger.error(f"Subscription {subscription_result['subscription_id']} created but failed to save to Directus for user {current_user.id}")
        
        logger.info(f"Successfully created subscription {subscription_result['subscription_id']} for user {current_user.id}")
        
        return CreateSubscriptionResponse(
            subscription_id=subscription_result['subscription_id'],
            status=subscription_result['status'],
            next_billing_date=next_billing_date
        )
        
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error creating subscription for user {current_user.id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")

@router.get("/subscription", response_model=GetSubscriptionResponse)
@limiter.limit("30/minute")  # Less sensitive read operation
async def get_subscription(
    request: Request,
    current_user: User = Depends(get_current_user),
    payment_service: PaymentService = Depends(get_payment_service)
):
    """
    Get the user's active subscription details.
    Bonus credits and price are calculated from pricing.yml based on the stored credits amount.
    """
    logger.info(f"Fetching subscription for user {current_user.id}")
    
    try:
        # Check if user has a subscription
        if not current_user.stripe_subscription_id:
            raise HTTPException(status_code=404, detail="No active subscription found")
        
        # Get subscription from Stripe
        if payment_service.provider_name != "stripe":
            raise HTTPException(status_code=400, detail="Subscriptions only supported with Stripe")
        
        subscription_result = await payment_service.provider.get_subscription(
            current_user.stripe_subscription_id
        )
        
        if not subscription_result:
            raise HTTPException(status_code=404, detail="Subscription not found")
        
        # Get tier info from pricing.yml
        tier_info = get_tier_info(
            current_user.subscription_credits,
            current_user.subscription_currency or 'eur'
        )
        
        if not tier_info:
            logger.error(f"Tier not found for {current_user.subscription_credits} credits")
            # Provide fallback values
            tier_info = {
                'credits': current_user.subscription_credits,
                'bonus_credits': 0,
                'price': 0,
                'currency': current_user.subscription_currency or 'eur'
            }
        
        # Format next billing date
        next_billing_date = None
        if subscription_result.get('current_period_end'):
            from datetime import datetime
            next_billing_date = datetime.fromtimestamp(
                subscription_result['current_period_end']
            ).isoformat()
        
        return GetSubscriptionResponse(
            subscription_id=current_user.stripe_subscription_id,
            status=subscription_result['status'],
            credits_amount=tier_info['credits'],
            bonus_credits=tier_info['bonus_credits'],
            currency=tier_info['currency'],
            price=tier_info['price'],
            next_billing_date=next_billing_date,
            cancel_at_period_end=subscription_result.get('cancel_at_period_end', False)
        )
        
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error fetching subscription for user {current_user.id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")

@router.post("/cancel-subscription", response_model=CancelSubscriptionResponse)
@limiter.limit("5/minute")  # Sensitive operation - prevent abuse
async def cancel_subscription(
    request: Request,
    current_user: User = Depends(get_current_user),
    payment_service: PaymentService = Depends(get_payment_service),
    directus_service: DirectusService = Depends(get_directus_service)
):
    """
    Cancel the user's active subscription at the end of the current billing period.
    """
    logger.info(f"Canceling subscription for user {current_user.id}")
    
    try:
        # Check if user has a subscription
        if not current_user.stripe_subscription_id:
            raise HTTPException(status_code=404, detail="No active subscription found")
        
        # Cancel subscription with Stripe
        if payment_service.provider_name != "stripe":
            raise HTTPException(status_code=400, detail="Subscriptions only supported with Stripe")
        
        cancel_result = await payment_service.provider.cancel_subscription(
            current_user.stripe_subscription_id
        )
        
        if not cancel_result:
            raise HTTPException(status_code=500, detail="Failed to cancel subscription")
        
        # Update status in Directus
        update_payload = {
            "subscription_status": cancel_result['status']
        }
        
        await directus_service.update_user(current_user.id, update_payload)
        
        logger.info(f"Successfully canceled subscription for user {current_user.id}")
        
        return CancelSubscriptionResponse(
            subscription_id=current_user.stripe_subscription_id,
            status=cancel_result['status'],
            cancel_at_period_end=cancel_result.get('cancel_at_period_end', True)
        )
        
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error canceling subscription for user {current_user.id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")

@router.post("/redeem-gift-card", response_model=RedeemGiftCardResponse)
@limiter.limit("10/minute")  # Sensitive - prevent brute force attacks on gift card codes
async def redeem_gift_card(
    request: Request,
    gift_card_request: RedeemGiftCardRequest,
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service),
    encryption_service: EncryptionService = Depends(get_encryption_service)
):
    """
    Redeem a gift card code and add credits to the user's account.
    Checks cache first, then Directus if not found in cache.
    Gift cards are single-use and are deleted after redemption.
    """
    user_id = current_user.id
    code = gift_card_request.code.strip().upper()  # Normalize the code (uppercase, trimmed)
    
    if not code:
        logger.warning(f"User {user_id} attempted to redeem empty gift card code")
        return RedeemGiftCardResponse(
            success=False,
            credits_added=0,
            current_credits=0,
            message="Gift card code cannot be empty"
        )
    
    logger.info(f"User {user_id} attempting to redeem gift card code: {code}")
    
    try:
        # 1. Check cache first for gift card
        gift_card = await directus_service.get_gift_card_by_code(code)
        
        if not gift_card:
            logger.warning(f"Gift card code {code} not found or already redeemed")
            # Get current credits for response
            user_cache_data = await cache_service.get_user_by_id(user_id)
            current_credits = user_cache_data.get('credits', 0) if user_cache_data else 0
            
            # Log failed redemption attempt for compliance
            ComplianceService.log_financial_transaction(
                user_id=user_id,
                transaction_type="gift_card_redemption",
                status="failed",
                details={"gift_card_code": code, "reason": "gift_card_not_found"}
            )
            
            return RedeemGiftCardResponse(
                success=False,
                credits_added=0,
                current_credits=current_credits,
                message="Invalid gift card code or code has already been redeemed"
            )
        
        # 2. Get credits value
        credits_value = gift_card.get("credits_value")
        if not credits_value or credits_value <= 0:
            logger.error(f"Invalid credits value {credits_value} for gift card {code}")
            user_cache_data = await cache_service.get_user_by_id(user_id)
            current_credits = user_cache_data.get('credits', 0) if user_cache_data else 0
            
            return RedeemGiftCardResponse(
                success=False,
                credits_added=0,
                current_credits=current_credits,
                message="Invalid gift card: credits value is invalid"
            )
        
        # 4. Get current user credits
        user_cache_data = await cache_service.get_user_by_id(user_id)
        if not user_cache_data:
            logger.error(f"User {user_id} not found in cache")
            raise HTTPException(status_code=404, detail="User not found")
        
        current_credits = user_cache_data.get('credits', 0)
        if not isinstance(current_credits, int):
            logger.warning(f"User credits for {user_id} were not an integer: {current_credits}. Converting to 0.")
            current_credits = 0
        
        # 5. Calculate new credit balance
        new_total_credits = current_credits + credits_value
        
        # 6. Encrypt new credit balance for Directus
        vault_key_id = user_cache_data.get("vault_key_id")
        if not vault_key_id:
            logger.error(f"Vault key ID missing for user {user_id}")
            raise HTTPException(status_code=500, detail="User encryption key not found")
        
        encrypted_new_credits_tuple = await encryption_service.encrypt_with_user_key(
            plaintext=str(new_total_credits),
            key_id=vault_key_id
        )
        encrypted_new_credits = encrypted_new_credits_tuple[0]
        
        # 7. Update Directus with new credit balance
        update_success = await directus_service.update_user(
            user_id,
            {"encrypted_credit_balance": encrypted_new_credits}
        )
        
        if not update_success:
            logger.error(f"Failed to update user {user_id} credits in Directus after gift card redemption")
            raise HTTPException(status_code=500, detail="Failed to update credits in database")
        
        # 8. Update cache with new credit balance
        user_cache_data["credits"] = new_total_credits
        await cache_service.set_user(user_cache_data, user_id=user_id)
        
        # 9. Redeem (delete) the gift card from Directus and cache
        redeem_success = await directus_service.redeem_gift_card(code, user_id)
        if not redeem_success:
            logger.error(f"Failed to delete gift card {code} after redemption. Credits were added but gift card may still exist.")
            # Don't fail the request - credits were already added
        
        # 10. Log gift card redemption for compliance
        ComplianceService.log_financial_transaction(
            user_id=user_id,
            transaction_type="gift_card_redemption",
            amount=credits_value,
            status="success",
            details={
                "gift_card_code": code,
                "credits_added": credits_value,
                "previous_credits": current_credits,
                "new_credits": new_total_credits
            }
        )
        
        # 11. Broadcast credit update via WebSocket
        try:
            await manager.broadcast_to_user(
                user_id=user_id,
                message={
                    "type": "user_credits_updated",
                    "payload": {"credits": new_total_credits}
                }
            )
            logger.info(f"Broadcasted credit update for gift card redemption to user {user_id}")
        except Exception as pub_exc:
            logger.error(f"Failed to broadcast gift card redemption credits for user {user_id}: {pub_exc}", exc_info=True)
            # Don't fail the request - credits were already added
        
        logger.info(f"Successfully redeemed gift card {code} for user {user_id}: added {credits_value} credits (new balance: {new_total_credits})")
        
        return RedeemGiftCardResponse(
            success=True,
            credits_added=credits_value,
            current_credits=new_total_credits,
            message=f"Gift card redeemed successfully! {credits_value:,} credits added to your account."
        )
        
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error redeeming gift card {code} for user {user_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="An error occurred while redeeming the gift card")

@router.get("/invoices", response_model=InvoicesListResponse)
@limiter.limit("30/minute")  # Less sensitive read operation
async def get_invoices(
    request: Request,
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
    encryption_service: EncryptionService = Depends(get_encryption_service)
):
    """
    Get all invoices for the current user.
    Returns a list of invoices with basic information.
    """
    logger.info(f"Fetching invoices for user {current_user.id}")

    try:
        # Create user ID hash for lookup (same method used during invoice creation)
        user_id_hash = hashlib.sha256(current_user.id.encode()).hexdigest()

        # Query invoices collection by user_id_hash
        # Note: Directus sort parameter should be a string, not a list
        # Using "-date" for descending order (most recent first)
        invoices_data = await directus_service.get_items(
            collection="invoices",
            params={
                "filter": {
                    "user_id_hash": {"_eq": user_id_hash}
                },
                "sort": "-date"  # Most recent first (string format, not list)
            }
        )

        if not invoices_data:
            logger.info(f"No invoices found for user {current_user.id}")
            return InvoicesListResponse(invoices=[])

        vault_key_id = current_user.vault_key_id
        if not vault_key_id:
            logger.error(f"Vault key ID missing for user {current_user.id}")
            raise HTTPException(status_code=500, detail="User encryption key not found")

        processed_invoices = []

        for invoice in invoices_data:
            try:
                # Decrypt invoice data
                # Check if required encrypted fields exist and are not empty before attempting decryption
                if "encrypted_amount" not in invoice or not invoice.get("encrypted_amount"):
                    logger.error(f"Invoice {invoice.get('id', 'unknown')} missing or empty encrypted_amount field")
                    continue
                if "encrypted_credits_purchased" not in invoice or not invoice.get("encrypted_credits_purchased"):
                    logger.error(f"Invoice {invoice.get('id', 'unknown')} missing or empty encrypted_credits_purchased field")
                    continue

                # Decrypt required fields
                amount = await encryption_service.decrypt_with_user_key(
                    invoice["encrypted_amount"],
                    vault_key_id
                )

                credits_purchased = await encryption_service.decrypt_with_user_key(
                    invoice["encrypted_credits_purchased"],
                    vault_key_id
                )

                # Check if critical fields decrypted successfully
                if not amount or not credits_purchased:
                    logger.warning(
                        f"Failed to decrypt critical invoice data for invoice {invoice.get('id', 'unknown')}. "
                        f"amount={bool(amount)}, credits={bool(credits_purchased)}"
                    )
                    continue

                # Format the date first (needed for both display and filename generation)
                # Date is stored as ISO format string from datetime.now(timezone.utc).isoformat()
                # Directus may return it as a string or datetime object
                invoice_date = invoice.get("date")
                formatted_date = None
                date_str_filename = None
                
                if invoice_date:
                    from datetime import datetime
                    try:
                        # Handle string format (ISO format from Directus)
                        if isinstance(invoice_date, str):
                            # Normalize timezone indicators (Z or +00:00)
                            date_str = invoice_date.replace('Z', '+00:00')
                            # Parse ISO format string
                            parsed_date = datetime.fromisoformat(date_str)
                        # Handle datetime object (if Directus returns it as object)
                        elif hasattr(invoice_date, 'isoformat'):
                            parsed_date = invoice_date
                        else:
                            # Try to convert to string and parse
                            date_str = str(invoice_date)
                            parsed_date = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                        
                        # Format for display (YYYY-MM-DD)
                        formatted_date = parsed_date.strftime("%Y-%m-%d")
                        # Format for filename (YYYY_MM_DD)
                        date_str_filename = parsed_date.strftime("%Y_%m_%d")
                    except Exception as date_parse_error:
                        logger.warning(
                            f"Failed to parse invoice date for invoice {invoice.get('id', 'unknown')}: {invoice_date}. "
                            f"Error: {date_parse_error}. Using fallback."
                        )
                        # Fallback: try to extract date from string
                        date_str = str(invoice_date)
                        if len(date_str) >= 10:
                            formatted_date = date_str[:10]  # Take first 10 chars (YYYY-MM-DD)
                            date_str_filename = formatted_date.replace('-', '_')
                        else:
                            formatted_date = None
                            date_str_filename = None
                
                # If date parsing failed completely, use a fallback
                if not formatted_date:
                    logger.error(f"Could not parse date for invoice {invoice.get('id', 'unknown')}. Date value: {invoice_date}")
                    formatted_date = "1970-01-01"  # Fallback date
                    date_str_filename = "1970_01_01"

                # Handle filename - use date-based generation for older invoices that don't have encrypted_filename
                filename = None
                if "encrypted_filename" in invoice and invoice.get("encrypted_filename"):
                    filename = await encryption_service.decrypt_with_user_key(
                        invoice["encrypted_filename"],
                        vault_key_id
                    )
                
                # If filename is missing or decryption failed, generate from date
                if not filename:
                    logger.info(
                        f"Invoice {invoice.get('id', 'unknown')} missing or failed to decrypt filename. "
                        f"Generating filename from date. This may be an older invoice created before the filename field was added."
                    )
                    filename = f"Invoice_{date_str_filename}.pdf"

                processed_invoices.append(InvoiceResponse(
                    id=invoice["id"],
                    date=formatted_date,
                    amount=amount,
                    credits_purchased=int(credits_purchased),
                    filename=filename
                ))

            except Exception as e:
                logger.error(
                    f"Error processing invoice {invoice.get('id', 'unknown')}: {str(e)}",
                    exc_info=True
                )
                continue

        logger.info(f"Successfully fetched {len(processed_invoices)} invoices for user {current_user.id}")
        return InvoicesListResponse(invoices=processed_invoices)

    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error fetching invoices for user {current_user.id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")

@router.get("/invoices/{invoice_id}/download")
@limiter.limit("30/minute")  # Prevent abuse of file downloads
async def download_invoice(
    request: Request,
    invoice_id: str,
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
    encryption_service: EncryptionService = Depends(get_encryption_service),
    s3_service: S3UploadService = Depends(get_s3_service)
):
    """
    Download a specific invoice PDF by ID.
    Returns the decrypted PDF file as a streaming response.
    """
    logger.info(f"Downloading invoice {invoice_id} for user {current_user.id}")

    try:
        # Create user ID hash for lookup
        user_id_hash = hashlib.sha256(current_user.id.encode()).hexdigest()

        # Get invoice by ID and verify ownership
        invoice_data = await directus_service.get_items(
            collection="invoices",
            params={
                "filter": {
                    "id": {"_eq": invoice_id},
                    "user_id_hash": {"_eq": user_id_hash}
                }
            }
        )

        if not invoice_data or len(invoice_data) == 0:
            logger.warning(f"Invoice {invoice_id} not found for user {current_user.id}")
            raise HTTPException(status_code=404, detail="Invoice not found")

        invoice = invoice_data[0]
        vault_key_id = current_user.vault_key_id
        if not vault_key_id:
            logger.error(f"Vault key ID missing for user {current_user.id}")
            raise HTTPException(status_code=500, detail="User encryption key not found")

        # Decrypt the S3 object key and AES key (required for download)
        s3_object_key = await encryption_service.decrypt_with_user_key(
            invoice["encrypted_s3_object_key"],
            vault_key_id
        )

        aes_key = await encryption_service.decrypt_with_user_key(
            invoice["encrypted_aes_key"],
            vault_key_id
        )

        # Check if critical fields decrypted successfully
        if not s3_object_key or not aes_key:
            logger.error(f"Failed to decrypt invoice access data for invoice {invoice_id}")
            raise HTTPException(status_code=500, detail="Failed to decrypt invoice data")

        # Format the date for filename generation (if needed)
        # Date is stored as ISO format string from datetime.now(timezone.utc).isoformat()
        # Directus may return it as a string or datetime object
        invoice_date = invoice.get("date")
        date_str_filename = None
        
        if invoice_date:
            from datetime import datetime
            try:
                # Handle string format (ISO format from Directus)
                if isinstance(invoice_date, str):
                    # Normalize timezone indicators (Z or +00:00)
                    date_str = invoice_date.replace('Z', '+00:00')
                    # Parse ISO format string
                    parsed_date = datetime.fromisoformat(date_str)
                # Handle datetime object (if Directus returns it as object)
                elif hasattr(invoice_date, 'isoformat'):
                    parsed_date = invoice_date
                else:
                    # Try to convert to string and parse
                    date_str = str(invoice_date)
                    parsed_date = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                
                # Format for filename (YYYY_MM_DD)
                date_str_filename = parsed_date.strftime("%Y_%m_%d")
            except Exception as date_parse_error:
                logger.warning(
                    f"Failed to parse invoice date for download {invoice_id}: {invoice_date}. "
                    f"Error: {date_parse_error}. Using fallback."
                )
                # Fallback: try to extract date from string
                date_str = str(invoice_date)
                if len(date_str) >= 10:
                    date_str_filename = date_str[:10].replace('-', '_')
                else:
                    date_str_filename = None

        # Handle filename - generate from date for older invoices that don't have encrypted_filename
        filename = None
        if "encrypted_filename" in invoice and invoice.get("encrypted_filename"):
            filename = await encryption_service.decrypt_with_user_key(
                invoice["encrypted_filename"],
                vault_key_id
            )
        
        # If filename is missing or decryption failed, generate from date
        if not filename:
            if date_str_filename:
                logger.info(
                    f"Invoice {invoice_id} missing or failed to decrypt filename. "
                    f"Generating filename from date: {date_str_filename}. This may be an older invoice created before the filename field was added."
                )
                filename = f"Invoice_{date_str_filename}.pdf"
            else:
                logger.warning(
                    f"Invoice {invoice_id} missing or failed to decrypt filename and date is invalid. "
                    f"Using fallback filename."
                )
                filename = "Invoice.pdf"

        aes_nonce = invoice["aes_nonce"]

        # Get the correct bucket name based on environment (dev vs production)
        # This ensures we use 'dev-openmates-invoices' in development and 'openmates-invoices' in production
        bucket_name = get_bucket_name('invoices', os.getenv('SERVER_ENVIRONMENT', 'development'))
        logger.debug(f"Using bucket '{bucket_name}' for invoice download (environment: {os.getenv('SERVER_ENVIRONMENT', 'development')})")

        # Download encrypted file from S3
        # Note: get_file will raise HTTPException on errors (not return None) to prevent silent failures
        try:
            encrypted_pdf_data = await s3_service.get_file(
                bucket_name=bucket_name,
                object_key=s3_object_key
            )
        except HTTPException as e:
            # Re-raise HTTPException from S3 service with more context
            logger.error(
                f"Failed to download invoice file from S3 for invoice {invoice_id}: "
                f"bucket={bucket_name}, key={s3_object_key}, error={e.detail}"
            )
            raise HTTPException(
                status_code=e.status_code,
                detail=f"Failed to retrieve invoice file: {e.detail}"
            )
        
        # Check if file was found (None is only returned for 404/NoSuchKey)
        if not encrypted_pdf_data:
            logger.error(
                f"Invoice file not found in S3 for invoice {invoice_id}: "
                f"bucket={bucket_name}, key={s3_object_key}"
            )
            raise HTTPException(
                status_code=404,
                detail=f"Invoice file not found in storage"
            )

        # Decrypt the PDF content using AES
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        from cryptography.hazmat.backends import default_backend
        import base64

        # Decode the base64 encoded AES key and nonce
        aes_key_bytes = base64.b64decode(aes_key)
        nonce_bytes = base64.b64decode(aes_nonce)

        # Create cipher and decrypt
        cipher = Cipher(
            algorithms.AES(aes_key_bytes),
            modes.GCM(nonce_bytes),
            backend=default_backend()
        )
        decryptor = cipher.decryptor()

        # The encrypted data includes the GCM tag at the end
        encrypted_content = encrypted_pdf_data[:-16]  # All but last 16 bytes
        tag = encrypted_pdf_data[-16:]  # Last 16 bytes is the tag

        decryptor.authenticate_additional_data(b"")
        decrypted_pdf_content = decryptor.update(encrypted_content) + decryptor.finalize_with_tag(tag)

        logger.info(f"Successfully decrypted invoice {invoice_id} for user {current_user.id}")

        # Return the PDF as a streaming response
        from io import BytesIO
        pdf_stream = BytesIO(decrypted_pdf_content)

        return StreamingResponse(
            pdf_stream,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f"attachment; filename={filename}"
            }
        )

    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error downloading invoice {invoice_id} for user {current_user.id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")
