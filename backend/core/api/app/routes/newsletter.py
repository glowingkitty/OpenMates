"""
Newsletter subscription routes for GDPR-compliant newsletter signup.

This module handles:
- Newsletter subscription requests (with email confirmation)
- Newsletter confirmation (via email link)
- Newsletter unsubscribe/ignore requests
- Checking ignored emails during signup
"""

from fastapi import APIRouter, Depends, Request
import logging
import secrets
from datetime import datetime, timezone
from pydantic import BaseModel, EmailStr

from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.limiter import limiter
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.routes.auth_routes.auth_dependencies import (
    get_directus_service, get_cache_service, get_encryption_service
)
from backend.core.api.app.routes.auth_routes.auth_utils import verify_allowed_origin
from backend.core.api.app.tasks.celery_config import app as celery_app
from backend.core.api.app.utils.newsletter_utils import (
    hash_email,
    check_ignored_email,
    update_newsletter_registration_status,
    NEWSLETTER_CATEGORIES,
    DEFAULT_NEWSLETTER_CATEGORIES,
    normalize_newsletter_categories,
)
from backend.core.api.app.routes.auth_routes.auth_dependencies import get_current_user
from backend.core.api.app.models.user import User
from typing import Dict, Optional

router = APIRouter(
    prefix="/v1",
    tags=["Newsletter"]
)
logger = logging.getLogger(__name__)


async def _get_registration_status_for_hashed_email(
    hashed_email: str,
    directus_service: DirectusService,
) -> "NewsletterUserStatusType":
    """
    Cross-reference a newsletter subscriber's hashed_email against directus_users.hashed_email
    (same SHA-256/base64 algorithm — no decryption needed) and return the appropriate status:
      - "not_signed_up"      — no matching user record found
      - "signup_incomplete"  — user record exists but signup_completed=False
      - "signup_complete"    — user record exists and signup_completed=True
    """
    users_url = f"{directus_service.base_url}/users"
    resp = await directus_service._make_api_request(
        "GET",
        users_url,
        params={
            "filter[hashed_email][_eq]": hashed_email,
            "fields": "id,signup_completed",
            "limit": 1,
        },
    )
    if resp.status_code != 200:
        logger.warning(
            f"_get_registration_status: user lookup failed (HTTP {resp.status_code}) "
            f"for hash {hashed_email[:16]}... — defaulting to not_signed_up"
        )
        return "not_signed_up"

    users = resp.json().get("data", [])
    if not users:
        return "not_signed_up"

    signup_completed = users[0].get("signup_completed", False)
    return "signup_complete" if signup_completed else "signup_incomplete"


# Re-export the type alias for callers in this module
NewsletterUserStatusType = str  # "not_signed_up" | "signup_incomplete" | "signup_complete"


async def get_total_newsletter_subscribers_count(directus_service: DirectusService) -> int:
    """
    Get the total count of confirmed newsletter subscribers
    Returns the count as an integer
    """
    try:
        collection_name = "newsletter_subscribers"
        url = f"{directus_service.base_url}/items/{collection_name}"
        params = {
            "limit": 1,
            "meta": "filter_count",
            "filter[confirmed_at][_nnull]": "true"  # Only count confirmed subscribers
        }

        response = await directus_service._make_api_request("GET", url, params=params)

        if response.status_code == 200:
            data = response.json()
            meta = data.get("meta", {})
            filter_count = meta.get("filter_count")
            logger.debug(f"Total newsletter subscribers count: {filter_count}")

            if filter_count is not None:
                return int(filter_count)
            else:
                logger.warning("filter_count not found in meta response for newsletter subscribers")
                return 0
        else:
            logger.error(f"Failed to get newsletter subscribers count: {response.status_code} - {response.text}")
            return 0

    except Exception as e:
        logger.error(f"Error getting newsletter subscribers count: {str(e)}")
        return 0


async def get_newsletter_subscriber_breakdown(directus_service: DirectusService) -> dict:
    """
    Cross-reference newsletter subscribers with user registration and payment data.
    Returns a breakdown: total, never_registered, signup_incomplete,
    completed_not_paying, paying_customers, and non-subscriber paying count.
    Uses hashed_email (SHA-256/base64) for matching — no decryption needed.
    """
    try:
        # Fetch all confirmed subscriber hashed emails
        nl_url = f"{directus_service.base_url}/items/newsletter_subscribers"
        nl_resp = await directus_service._make_api_request("GET", nl_url, params={
            "fields": "hashed_email",
            "limit": -1,
            "filter[confirmed_at][_nnull]": "true",
        })
        nl_hashes = set()
        if nl_resp.status_code == 200:
            nl_hashes = {
                s["hashed_email"] for s in nl_resp.json().get("data", [])
                if s.get("hashed_email")
            }

        # Fetch all users with registration + payment fields
        users_url = f"{directus_service.base_url}/users"
        users_resp = await directus_service._make_api_request("GET", users_url, params={
            "fields": "hashed_email,signup_completed,last_successful_payment_date",
            "limit": -1,
        })
        users = users_resp.json().get("data", []) if users_resp.status_code == 200 else []

        all_user_hashes = set()
        completed_hashes = set()
        paying_hashes = set()
        for u in users:
            h = u.get("hashed_email")
            if not h:
                continue
            all_user_hashes.add(h)
            if u.get("signup_completed"):
                completed_hashes.add(h)
            if u.get("last_successful_payment_date"):
                paying_hashes.add(h)

        total = len(nl_hashes)
        nl_not_registered = len(nl_hashes - all_user_hashes)
        nl_registered = nl_hashes & all_user_hashes
        nl_incomplete = len(nl_registered - completed_hashes)
        nl_paying = len(nl_hashes & paying_hashes)
        nl_completed_not_paying = len((nl_hashes & completed_hashes) - paying_hashes)

        return {
            "confirmed_subscribers": total,
            "never_registered": nl_not_registered,
            "signup_incomplete": nl_incomplete,
            "completed_not_paying": nl_completed_not_paying,
            "paying_customers": nl_paying,
            "total_paying_users": len(paying_hashes),
            "paying_not_subscribed": len(paying_hashes - nl_hashes),
        }
    except Exception as e:
        logger.error(f"Error getting newsletter subscriber breakdown: {e}", exc_info=True)
        # Fall back to just the count
        count = await get_total_newsletter_subscribers_count(directus_service)
        return {"confirmed_subscribers": count, "error": str(e)}


# Request/Response models
class NewsletterSubscribeRequest(BaseModel):
    email: EmailStr
    language: str = "en"
    darkmode: bool = False  # Default to light mode if not provided


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
@limiter.limit("2/minute")
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
        darkmode = subscribe_request.darkmode if hasattr(subscribe_request, 'darkmode') else False
        
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
            "darkmode": darkmode,
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
                'darkmode': darkmode,
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
@limiter.limit("5/minute")
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
            logger.warning("Newsletter confirmation attempted with invalid or expired token")
            return NewsletterConfirmResponse(
                success=False,
                message="Invalid or expired confirmation link. Please subscribe again."
            )
        
        email = cache_data.get("email")
        hashed_email = cache_data.get("hashed_email")
        language = cache_data.get("language", "en")
        darkmode = cache_data.get("darkmode", False)
        
        if not email or not hashed_email:
            logger.error("Invalid cache data for newsletter confirmation token")
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
                
                # Generate unsubscribe token if not already present (store plaintext for direct lookup)
                existing_token = items[0].get("unsubscribe_token")
                if not existing_token:
                    # Generate new plaintext token
                    existing_token = secrets.token_urlsafe(32)
                
                update_payload = {
                    "encrypted_email_address": encrypted_email,
                    "confirmed_at": now,
                    "language": language,
                    "darkmode": darkmode,
                    "unsubscribe_token": existing_token
                }
                await directus_service._make_api_request("PATCH", update_url, json=update_payload)
                logger.info(f"Updated existing newsletter subscriber: {hashed_email[:16]}...")
            else:
                # Create new subscriber (only created after confirmation)
                # Generate plaintext unsubscribe token for persistent unsubscribe link (stored in cleartext for direct lookup)
                unsubscribe_token = secrets.token_urlsafe(32)
                create_payload = {
                    "encrypted_email_address": encrypted_email,
                    "hashed_email": hashed_email,
                    "confirmed_at": now,
                    "subscribed_at": now,
                    "language": language,
                    "darkmode": darkmode,
                    "unsubscribe_token": unsubscribe_token
                }
                await directus_service.create_item(collection_name, create_payload)
                logger.info(f"Created new newsletter subscriber: {hashed_email[:16]}...")

        # Determine and persist user_registration_status by cross-referencing directus_users.
        # Uses hashed_email (same SHA-256/base64 algorithm) so no decryption is needed.
        try:
            user_status = await _get_registration_status_for_hashed_email(hashed_email, directus_service)
            await update_newsletter_registration_status(hashed_email, user_status, directus_service)
        except Exception as status_err:
            # Non-critical — log but do not block confirmation
            logger.error(
                f"Failed to set registration status on newsletter confirm for {hashed_email[:16]}...: {status_err}",
                exc_info=True,
            )

        # Delete from cache
        await cache_service.delete(cache_key)
        
        # Send confirmation success email
        logger.info(f"Submitting newsletter confirmed email task for {email[:2]}***")
        celery_app.send_task(
            name='app.tasks.email_tasks.newsletter_email_task.send_newsletter_confirmed_email',
            kwargs={
                'email': email,
                'language': language,
                'darkmode': darkmode,
            },
            queue='email'
        )

        # Check if we've reached a newsletter signup milestone
        try:
            # Get the total newsletter subscriber count after confirmation
            total_subscribers = await get_total_newsletter_subscribers_count(directus_service)

            # Dispatch milestone check task asynchronously
            celery_app.send_task(
                name='app.tasks.email_tasks.milestone_checker_task.check_and_notify_newsletter_milestone',
                kwargs={"total_subscribers": total_subscribers},
                queue='email'
            )
            logger.info(f"Dispatched newsletter milestone check task for {total_subscribers} subscribers")
        except Exception as milestone_err:
            logger.error(f"Error dispatching newsletter milestone check task: {milestone_err}", exc_info=True)
            # Continue with confirmation even if milestone task dispatch fails

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
@limiter.limit("5/minute")
async def newsletter_unsubscribe(
    request: Request,
    token: str,
    directus_service: DirectusService = Depends(get_directus_service),
):
    """
    Unsubscribe from newsletter using persistent plaintext token stored in Directus.
    
    The token is stored in plaintext in the newsletter_subscribers collection
    as unsubscribe_token, persisting indefinitely and allowing users to unsubscribe
    even weeks or months after subscribing.
    
    This endpoint:
    1. Looks up subscriber by unsubscribe_token in Directus (direct plaintext search)
    2. Deletes the newsletter subscription
    3. Does NOT add to block list (only unsubscribes from newsletter)
    """
    try:
        # Look up subscriber by plaintext unsubscribe_token in Directus
        collection_name = "newsletter_subscribers"
        url = f"{directus_service.base_url}/items/{collection_name}"
        params = {"filter[unsubscribe_token][_eq]": token}
        
        response = await directus_service._make_api_request("GET", url, params=params)
        
        if response.status_code != 200:
            logger.warning("Newsletter unsubscribe attempted with invalid token")
            return NewsletterUnsubscribeResponse(
                success=False,
                message="Invalid or expired unsubscribe link."
            )
        
        response_data = response.json()
        items = response_data.get("data", [])
        
        if not items:
            logger.warning("Newsletter unsubscribe attempted with token not found in Directus")
            return NewsletterUnsubscribeResponse(
                success=False,
                message="Invalid or expired unsubscribe link."
            )
        
        subscriber = items[0]
        subscriber_id = subscriber.get("id")
        hashed_email = subscriber.get("hashed_email")
        
        if not subscriber_id or not hashed_email:
            logger.error("Invalid subscriber data for unsubscribe token")
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


# ─── Category preferences ─────────────────────────────────────────────────
# Auth-based routes let a signed-in user manage their own per-category
# opt-outs (Settings → Newsletter). We match the newsletter subscriber row by
# the user's ``hashed_email`` — the same hash stored on both tables, so no
# email decryption is needed on the backend.

class NewsletterCategoriesResponse(BaseModel):
    success: bool
    subscribed: bool  # False when the authenticated user never subscribed
    categories: Dict[str, bool]  # Always keyed by every NEWSLETTER_CATEGORIES entry


class NewsletterCategoriesUpdateRequest(BaseModel):
    # Partial update: only keys present are applied; unknown keys are ignored.
    categories: Dict[str, bool]


async def _find_subscriber_by_hashed_email(
    hashed_email: str,
    directus_service: DirectusService,
) -> Optional[Dict]:
    """Return the subscriber row (or None) for a confirmed opt-in subscriber."""
    url = f"{directus_service.base_url}/items/newsletter_subscribers"
    params = {
        "filter[hashed_email][_eq]": hashed_email,
        "filter[confirmed_at][_nnull]": "true",
        "fields": "id,categories",
        "limit": 1,
    }
    resp = await directus_service._make_api_request("GET", url, params=params)
    if resp.status_code != 200:
        logger.warning(f"Subscriber lookup failed: HTTP {resp.status_code}")
        return None
    rows = resp.json().get("data", [])
    return rows[0] if rows else None


@router.get("/newsletter/categories", response_model=NewsletterCategoriesResponse)
async def get_newsletter_categories(
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
):
    """Return the authenticated user's per-category newsletter preferences.

    If the user has never subscribed (no newsletter_subscribers row), we still
    return the defaults with ``subscribed=false`` so the frontend can render
    the UI in a disabled/subscribe-first state without a second round-trip.
    """
    hashed_email = getattr(current_user, "hashed_email", None)
    if not hashed_email:
        # Treat as not-subscribed rather than 500 — matches the UX for users
        # whose accounts predate hashed_email backfill.
        return NewsletterCategoriesResponse(
            success=True,
            subscribed=False,
            categories=dict(DEFAULT_NEWSLETTER_CATEGORIES),
        )

    row = await _find_subscriber_by_hashed_email(hashed_email, directus_service)
    if not row:
        return NewsletterCategoriesResponse(
            success=True,
            subscribed=False,
            categories=dict(DEFAULT_NEWSLETTER_CATEGORIES),
        )

    return NewsletterCategoriesResponse(
        success=True,
        subscribed=True,
        categories=normalize_newsletter_categories(row.get("categories")),
    )


@router.patch("/newsletter/categories", response_model=NewsletterCategoriesResponse)
@limiter.limit("20/minute")
async def update_newsletter_categories(
    request: Request,
    payload: NewsletterCategoriesUpdateRequest,
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
):
    """Patch the authenticated user's category preferences.

    Only keys in ``NEWSLETTER_CATEGORIES`` are applied; unknown keys are
    silently dropped. Missing keys keep their previous value. A 404 is
    returned if the user is not a confirmed subscriber — the UI should
    prompt them to subscribe first.
    """
    hashed_email = getattr(current_user, "hashed_email", None)
    if not hashed_email:
        return NewsletterCategoriesResponse(
            success=False,
            subscribed=False,
            categories=dict(DEFAULT_NEWSLETTER_CATEGORIES),
        )

    row = await _find_subscriber_by_hashed_email(hashed_email, directus_service)
    if not row:
        return NewsletterCategoriesResponse(
            success=False,
            subscribed=False,
            categories=dict(DEFAULT_NEWSLETTER_CATEGORIES),
        )

    current = normalize_newsletter_categories(row.get("categories"))
    for key, value in payload.categories.items():
        if key in NEWSLETTER_CATEGORIES and isinstance(value, bool):
            current[key] = value

    patch_url = f"{directus_service.base_url}/items/newsletter_subscribers/{row['id']}"
    resp = await directus_service._make_api_request(
        "PATCH", patch_url, json={"categories": current}
    )
    if resp.status_code not in (200, 204):
        logger.error(
            f"Failed to update newsletter categories for subscriber {row['id']}: "
            f"HTTP {resp.status_code}"
        )
        return NewsletterCategoriesResponse(
            success=False,
            subscribed=True,
            categories=current,
        )

    return NewsletterCategoriesResponse(success=True, subscribed=True, categories=current)
