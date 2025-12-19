"""
Newsletter subscription routes for GDPR-compliant newsletter signup.

This module handles:
- Newsletter subscription requests (with email confirmation)
- Newsletter confirmation (via email link)
- Newsletter unsubscribe/ignore requests
- Checking ignored emails during signup
"""

from fastapi import APIRouter, Depends, Request, Response
import logging
import os
import secrets
from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel, EmailStr

from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.limiter import limiter
from backend.core.api.app.utils.encryption import EncryptionService, NEWSLETTER_ENCRYPTION_KEY
from backend.core.api.app.routes.auth_routes.auth_dependencies import (
    get_directus_service, get_cache_service, get_encryption_service
)
from backend.core.api.app.routes.auth_routes.auth_utils import verify_allowed_origin
from backend.core.api.app.tasks.celery_config import app as celery_app
from backend.core.api.app.utils.newsletter_utils import hash_email, check_ignored_email

router = APIRouter(
    prefix="/v1",
    tags=["Newsletter"]
)
logger = logging.getLogger(__name__)


# Request/Response models
class NewsletterSubscribeRequest(BaseModel):
    email: EmailStr
    language: str = "en"


class NewsletterSubscribeResponse(BaseModel):
    success: bool
    message: str


class NewsletterConfirmRequest(BaseModel):
    token: str


class NewsletterConfirmResponse(BaseModel):
    success: bool
    message: str


class NewsletterUnsubscribeRequest(BaseModel):
    token: str


class NewsletterUnsubscribeResponse(BaseModel):
    success: bool
    message: str


@router.post("/newsletter/subscribe", response_model=NewsletterSubscribeResponse, dependencies=[Depends(verify_allowed_origin)])
@limiter.limit("5/minute")
async def newsletter_subscribe(
    request: Request,
    subscribe_request: NewsletterSubscribeRequest,
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service),
    encryption_service: EncryptionService = Depends(get_encryption_service),
):
    """
    Subscribe to newsletter - sends confirmation email.
    Email is stored in cache for 30 minutes until confirmed.
    """
    try:
        email = subscribe_request.email.lower().strip()
        language = subscribe_request.language or "en"
        
        # Hash email for lookup
        hashed_email = hash_email(email)
        
        # Check if email is in ignored list
        is_ignored = await check_ignored_email(hashed_email, directus_service)
        if is_ignored:
            logger.info(f"Newsletter subscription attempt from ignored email: {hashed_email[:16]}...")
            # Return success to avoid revealing that email is ignored
            return NewsletterSubscribeResponse(
                success=True,
                message="If this email is not in our ignore list, you will receive a confirmation email."
            )
        
        # Check if already subscribed (if entry exists in Directus, they're confirmed)
        try:
            collection_name = "newsletter_subscribers"
            url = f"{directus_service.base_url}/items/{collection_name}"
            params = {"filter[hashed_email][_eq]": hashed_email}
            
            response = await directus_service._make_api_request("GET", url, params=params)
            
            if response.status_code == 200:
                response_data = response.json()
                items = response_data.get("data", [])
                if items:
                    logger.info(f"Newsletter subscription attempt for already confirmed email: {hashed_email[:16]}...")
                    return NewsletterSubscribeResponse(
                        success=True,
                        message="You are already subscribed to our newsletter."
                    )
        except Exception as e:
            logger.warning(f"Error checking existing subscription: {str(e)}")
        
        # Generate confirmation token
        confirmation_token = secrets.token_urlsafe(32)
        
        # Store email and token in cache for 30 minutes (1800 seconds)
        cache_key = f"newsletter_subscribe:{confirmation_token}"
        cache_data = {
            "email": email,
            "hashed_email": hashed_email,
            "language": language,
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        await cache_service.set(cache_key, cache_data, ttl=1800)  # 30 minutes
        
        # Send confirmation email via Celery task
        logger.info(f"Submitting newsletter confirmation email task for {email[:2]}***")
        task = celery_app.send_task(
            name='app.tasks.email_tasks.newsletter_email_task.send_newsletter_confirmation_email',
            kwargs={
                'email': email,
                'confirmation_token': confirmation_token,
                'language': language,
            },
            queue='email'
        )
        
        logger.info(f"Newsletter subscription task {task.id} submitted to Celery")
        
        return NewsletterSubscribeResponse(
            success=True,
            message="Please check your email to confirm your subscription."
        )
        
    except Exception as e:
        logger.error(f"Error processing newsletter subscription: {str(e)}", exc_info=True)
        return NewsletterSubscribeResponse(
            success=False,
            message="An error occurred while processing your subscription request."
        )


@router.get("/newsletter/confirm/{token}", response_model=NewsletterConfirmResponse)
@limiter.limit("10/minute")
async def newsletter_confirm(
    request: Request,
    token: str,
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service),
    encryption_service: EncryptionService = Depends(get_encryption_service),
):
    """
    Confirm newsletter subscription via email link.
    Moves subscriber from cache to Directus with confirmed status.
    """
    try:
        # Get subscription data from cache
        cache_key = f"newsletter_subscribe:{token}"
        cache_data = await cache_service.get(cache_key)
        
        if not cache_data:
            logger.warning(f"Newsletter confirmation attempted with invalid or expired token")
            return NewsletterConfirmResponse(
                success=False,
                message="Invalid or expired confirmation link. Please subscribe again."
            )
        
        email = cache_data.get("email")
        hashed_email = cache_data.get("hashed_email")
        language = cache_data.get("language", "en")
        
        if not email or not hashed_email:
            logger.error(f"Invalid cache data for newsletter confirmation token")
            return NewsletterConfirmResponse(
                success=False,
                message="Invalid confirmation data. Please subscribe again."
            )
        
        # Check if email is in ignored list
        is_ignored = await check_ignored_email(hashed_email, directus_service)
        if is_ignored:
            logger.info(f"Newsletter confirmation attempt from ignored email: {hashed_email[:16]}...")
            # Delete from cache and return success to avoid revealing
            await cache_service.delete(cache_key)
            return NewsletterConfirmResponse(
                success=True,
                message="Subscription confirmed."
            )
        
        # Encrypt email for storage
        encrypted_email = await encryption_service.encrypt_newsletter_email(email)
        
        # Check if already exists
        collection_name = "newsletter_subscribers"
        url = f"{directus_service.base_url}/items/{collection_name}"
        params = {"filter[hashed_email][_eq]": hashed_email}
        
        response = await directus_service._make_api_request("GET", url, params=params)
        
        now = datetime.now(timezone.utc).isoformat()
        
        if response.status_code == 200:
            response_data = response.json()
            items = response_data.get("data", [])
            
            if items:
                # Update existing subscriber (re-confirmation)
                subscriber_id = items[0].get("id")
                update_url = f"{directus_service.base_url}/items/{collection_name}/{subscriber_id}"
                
                # Generate and encrypt unsubscribe token if not already present
                existing_encrypted_token = items[0].get("encrypted_unsubscribe_token")
                if not existing_encrypted_token:
                    # Generate new token and encrypt it
                    new_token = secrets.token_urlsafe(32)
                    existing_encrypted_token = await encryption_service.encrypt_newsletter_token(new_token)
                
                update_payload = {
                    "encrypted_email_address": encrypted_email,
                    "confirmed_at": now,
                    "language": language,
                    "encrypted_unsubscribe_token": existing_encrypted_token,
                    "date_updated": now
                }
                await directus_service._make_api_request("PATCH", update_url, json=update_payload)
                logger.info(f"Updated existing newsletter subscriber: {hashed_email[:16]}...")
            else:
                # Create new subscriber (only created after confirmation)
                # Generate and encrypt unsubscribe token for persistent unsubscribe link
                unsubscribe_token = secrets.token_urlsafe(32)
                encrypted_unsubscribe_token = await encryption_service.encrypt_newsletter_token(unsubscribe_token)
                create_payload = {
                    "encrypted_email_address": encrypted_email,
                    "hashed_email": hashed_email,
                    "confirmed_at": now,
                    "subscribed_at": now,
                    "language": language,
                    "encrypted_unsubscribe_token": encrypted_unsubscribe_token
                }
                await directus_service.create_item(collection_name, create_payload)
                logger.info(f"Created new newsletter subscriber: {hashed_email[:16]}...")
        
        # Delete from cache
        await cache_service.delete(cache_key)
        
        # Send confirmation success email
        logger.info(f"Submitting newsletter confirmed email task for {email[:2]}***")
        task = celery_app.send_task(
            name='app.tasks.email_tasks.newsletter_email_task.send_newsletter_confirmed_email',
            kwargs={
                'email': email,
                'language': language,
            },
            queue='email'
        )
        
        return NewsletterConfirmResponse(
            success=True,
            message="You have been successfully subscribed to our newsletter!"
        )
        
    except Exception as e:
        logger.error(f"Error confirming newsletter subscription: {str(e)}", exc_info=True)
        return NewsletterConfirmResponse(
            success=False,
            message="An error occurred while confirming your subscription."
        )


@router.get("/newsletter/unsubscribe/{token}", response_model=NewsletterUnsubscribeResponse)
@limiter.limit("10/minute")
async def newsletter_unsubscribe(
    request: Request,
    token: str,
    directus_service: DirectusService = Depends(get_directus_service),
    encryption_service: EncryptionService = Depends(get_encryption_service),
):
    """
    Unsubscribe from newsletter using persistent encrypted token stored in Directus.
    
    The token is encrypted server-side and stored in the newsletter_subscribers collection
    as encrypted_unsubscribe_token, persisting indefinitely and allowing users to unsubscribe
    even weeks or months after subscribing.
    
    This endpoint:
    1. Encrypts the incoming plaintext token
    2. Looks up subscriber by encrypted_unsubscribe_token in Directus
    3. Deletes the newsletter subscription
    4. Does NOT add to block list (only unsubscribes from newsletter)
    """
    try:
        # Encrypt the incoming plaintext token to compare with stored encrypted tokens
        encrypted_token = await encryption_service.encrypt_newsletter_token(token)
        
        # Look up subscriber by encrypted_unsubscribe_token in Directus
        collection_name = "newsletter_subscribers"
        url = f"{directus_service.base_url}/items/{collection_name}"
        params = {"filter[encrypted_unsubscribe_token][_eq]": encrypted_token}
        
        response = await directus_service._make_api_request("GET", url, params=params)
        
        if response.status_code != 200:
            logger.warning(f"Newsletter unsubscribe attempted with invalid token")
            return NewsletterUnsubscribeResponse(
                success=False,
                message="Invalid or expired unsubscribe link."
            )
        
        response_data = response.json()
        items = response_data.get("data", [])
        
        if not items:
            logger.warning(f"Newsletter unsubscribe attempted with token not found in Directus")
            return NewsletterUnsubscribeResponse(
                success=False,
                message="Invalid or expired unsubscribe link."
            )
        
        subscriber = items[0]
        subscriber_id = subscriber.get("id")
        hashed_email = subscriber.get("hashed_email")
        
        if not subscriber_id or not hashed_email:
            logger.error(f"Invalid subscriber data for unsubscribe token")
            return NewsletterUnsubscribeResponse(
                success=False,
                message="Invalid unsubscribe data."
            )
        
        # Delete newsletter subscriber entry
        delete_url = f"{directus_service.base_url}/items/{collection_name}/{subscriber_id}"
        delete_response = await directus_service._make_api_request("DELETE", delete_url)
        
        if delete_response.status_code in [200, 204]:
            logger.info(f"Deleted newsletter subscriber entry: {hashed_email[:16]}...")
            return NewsletterUnsubscribeResponse(
                success=True,
                message="You have been unsubscribed from our newsletter. You will not receive any further newsletter emails."
            )
        else:
            logger.error(f"Failed to delete newsletter subscriber: {hashed_email[:16]}...")
            return NewsletterUnsubscribeResponse(
                success=False,
                message="An error occurred while processing your unsubscribe request."
            )
        
    except Exception as e:
        logger.error(f"Error processing newsletter unsubscribe: {str(e)}", exc_info=True)
        return NewsletterUnsubscribeResponse(
            success=False,
            message="An error occurred while processing your unsubscribe request."
        )
