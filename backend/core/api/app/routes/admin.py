# backend/core/api/app/routes/admin.py
"""
REST API endpoints for server administration functionality.
"""

import logging
import random
import string
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel, Field, field_validator

from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.services.limiter import limiter
from backend.core.api.app.routes.auth_routes.auth_dependencies import get_current_user, get_cache_service
from backend.core.api.app.models.user import User
from backend.core.api.app.services.cache import CacheService

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/v1/admin",
    tags=["Admin"]
)

# --- Dependency to get services from app.state ---

def get_directus_service(request: Request) -> DirectusService:
    if not hasattr(request.app.state, 'directus_service'):
        logger.error("DirectusService not found in app.state")
        raise HTTPException(status_code=500, detail="Internal configuration error")
    return request.app.state.directus_service

async def require_admin(
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service)
) -> User:
    """Dependency to ensure user has admin privileges"""
    is_admin = await directus_service.admin.is_user_admin(current_user.id)
    if not is_admin:
        raise HTTPException(status_code=403, detail="Admin privileges required")
    return current_user

# --- Request/Response Models ---

class BecomeAdminRequest(BaseModel):
    """Request model for becoming admin using token"""
    token: str


class GenerateGiftCardsRequest(BaseModel):
    """Request model for admin gift card generation.
    
    Allows admins to generate one or more gift card codes with a specified
    credit value, optional custom prefix (replaces first segment of XXXX-XXXX-XXXX),
    and optional admin notes.
    """
    credits_value: int = Field(..., ge=1, le=50000, description="Credit value for each gift card (1-50,000)")
    count: int = Field(default=1, ge=1, le=100, description="Number of gift cards to generate (1-100)")
    prefix: Optional[str] = Field(default=None, max_length=4, description="Optional custom prefix (max 4 chars, replaces first segment)")
    notes: Optional[str] = Field(default=None, max_length=500, description="Optional admin notes for these gift cards")
    is_reusable: bool = Field(default=False, description="When true, generated cards survive redemption (for infrastructure/test cards only — OPE-76 prod smoke test). Never exposed in the admin UI; only settable via direct API call.")
    allowed_email_domain: Optional[str] = Field(default=None, max_length=255, description="Optional exact full-domain restriction (e.g. 'xyz9abc1.mailosaur.net'). When set, only users whose email domain matches exactly (case-insensitive) can redeem. Typically paired with is_reusable=true.")

    @field_validator('prefix')
    @classmethod
    def validate_prefix(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == '':
            return None
        v = v.upper().strip()
        # Charset must match the gift card generation charset:
        # Uppercase letters (excluding O, I) + digits (excluding 0, 1)
        valid_charset = set(
            string.ascii_uppercase.replace('O', '').replace('I', '')
            + string.digits.replace('0', '').replace('1', '')
        )
        if not all(c in valid_charset for c in v):
            raise ValueError(
                'Prefix must only contain uppercase letters (A-Z excluding O, I) '
                'and digits (2-9). Ambiguous characters (0, O, I, 1) are not allowed.'
            )
        if len(v) < 1 or len(v) > 4:
            raise ValueError('Prefix must be 1-4 characters long')
        return v

class GenerateGiftCardsResponse(BaseModel):
    """Response model for admin gift card generation."""
    success: bool
    gift_cards: List[Dict[str, Any]]  # List of {code, credits_value, created_at}
    count: int
    message: str

class AdminGiftCardItem(BaseModel):
    """A single gift card item returned in the admin list."""
    id: str
    code: str
    credits_value: int
    created_at: Optional[str] = None
    notes: Optional[str] = None
    purchased_at: Optional[str] = None  # None = admin-generated, set = user-purchased

class AdminGiftCardListResponse(BaseModel):
    """Response model for the admin gift card list endpoint."""
    success: bool
    gift_cards: List[AdminGiftCardItem]
    count: int

# --- Endpoints ---

@router.post("/become-admin")
@limiter.limit("5/minute")  # Strict rate limiting for admin creation
async def become_admin(
    request: Request,
    payload: BecomeAdminRequest,
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service)
) -> Dict[str, Any]:
    """
    Grant admin privileges using a temporary token.

    This endpoint is used by the /settings/server/become-admin route
    when a server admin uses the docker exec command to generate an admin token.
    """
    try:
        # Validate the admin token
        is_valid = await directus_service.admin.validate_admin_token(payload.token)
        if not is_valid:
            logger.warning(f"Invalid admin token used by user {current_user.id}")
            raise HTTPException(status_code=400, detail="Invalid or expired admin token")

        # Grant admin privileges
        success = await directus_service.admin.make_user_admin(current_user.id)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to grant admin privileges")

        logger.info(f"Granted admin privileges to user {current_user.id}")

        return {
            "success": True,
            "message": "Admin privileges granted successfully"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in become admin: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to process admin request")

    # Demo chat admin endpoints removed — example chats are now hardcoded in frontend.

@router.get("/server-stats")
@limiter.limit("30/minute")
async def get_server_stats(
    request: Request,
    admin_user: User = Depends(require_admin),
    directus_service: DirectusService = Depends(get_directus_service)
) -> Dict[str, Any]:
    """
    Get server statistics for the admin dashboard.
    Returns:
    - daily/monthly server stats (last 30 days / 12 months)
    - web analytics daily (last 30 days)
    - signup funnel daily (last 30 days)
    - app analytics daily (last 30 days)
    All collections fetched in parallel for performance.
    """
    try:
        import asyncio
        from datetime import datetime

        # Fetch all collections in parallel — avoids sequential round-trips to Directus
        (
            daily_stats,
            monthly_stats,
            web_analytics_daily,
            signup_funnel_daily,
            app_analytics_daily,
        ) = await asyncio.gather(
            # 1. Last 30 daily server stats records
            directus_service.get_items(
                "server_stats_global_daily",
                params={"sort": "-date", "limit": 30}
            ),
            # 2. Last 12 monthly server stats records
            directus_service.get_items(
                "server_stats_global_monthly",
                params={"sort": "-year_month", "limit": 12}
            ),
            # 3. Last 30 days of web traffic analytics
            directus_service.get_items(
                "web_analytics_daily",
                params={"sort": "-date", "limit": 30}
            ),
            # 4. Last 30 days of signup funnel data
            directus_service.get_items(
                "signup_funnel_daily",
                params={"sort": "-date", "limit": 30}
            ),
            # 5. Last 30 days of app analytics aggregates
            directus_service.get_items(
                "app_analytics_daily",
                params={"sort": "-date", "limit": 30}
            ),
        )

        # Current totals — prefer latest pre-aggregated daily record
        current_stats = daily_stats[0] if daily_stats else {}

        # Fetch newsletter subscriber count (confirmed subscribers only)
        newsletter_subscribers_count = 0
        try:
            from backend.core.api.app.routes.newsletter import get_total_newsletter_subscribers_count
            newsletter_subscribers_count = await get_total_newsletter_subscribers_count(directus_service)
        except Exception as e:
            logger.error(f"Error fetching newsletter subscribers count: {e}", exc_info=True)

        return {
            "current": current_stats,
            "daily_history": daily_stats,
            "monthly_history": monthly_stats,
            "web_analytics_daily": web_analytics_daily,
            "signup_funnel_daily": signup_funnel_daily,
            "app_analytics_daily": app_analytics_daily,
            "newsletter_subscribers_count": newsletter_subscribers_count,
            "timestamp": datetime.now().isoformat()
        }

    except Exception as e:
        logger.error(f"Error fetching server stats: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch server statistics")


# --- Gift Card Code Generation ---
# Charset: uppercase letters (excluding ambiguous O, I) + digits (excluding ambiguous 0, 1)
# This matches the canonical charset used in payments.py for consistency
GIFT_CARD_CHARSET = (
    string.ascii_uppercase.replace('O', '').replace('I', '')
    + string.digits.replace('0', '').replace('1', '')
)


def generate_gift_card_code(prefix: Optional[str] = None) -> str:
    """
    Generate a unique gift card code in the format XXXX-XXXX-XXXX.
    Uses uppercase letters and digits, excluding ambiguous characters (0, O, I, 1).
    
    If a prefix is provided (1-4 chars), it replaces the first segment.
    The prefix is right-padded with random chars to always produce a 4-char first segment.
    Example: prefix='XM' -> 'XMAB-XXXX-XXXX'
    
    Args:
        prefix: Optional custom prefix (1-4 chars, from the valid charset)
        
    Returns:
        A gift card code string in XXXX-XXXX-XXXX format
    """
    if prefix:
        # Prefix replaces start of first segment, pad remainder with random chars
        prefix = prefix.upper()
        remaining = 4 - len(prefix)
        part1 = prefix + ''.join(random.choices(GIFT_CARD_CHARSET, k=remaining))
    else:
        part1 = ''.join(random.choices(GIFT_CARD_CHARSET, k=4))
    
    part2 = ''.join(random.choices(GIFT_CARD_CHARSET, k=4))
    part3 = ''.join(random.choices(GIFT_CARD_CHARSET, k=4))
    
    return f"{part1}-{part2}-{part3}"


@router.post("/generate-gift-cards", response_model=GenerateGiftCardsResponse)
@limiter.limit("10/minute")
async def admin_generate_gift_cards(
    request: Request,
    payload: GenerateGiftCardsRequest,
    admin_user: User = Depends(require_admin),
    directus_service: DirectusService = Depends(get_directus_service)
) -> Dict[str, Any]:
    """
    Generate one or more gift card codes with a specified credit value.
    
    Admin-only endpoint. Creates gift cards in the database and returns
    the generated codes. Supports optional custom prefix for the first
    segment of the XXXX-XXXX-XXXX format and optional admin notes.
    
    Security: Protected by require_admin dependency which validates
    the user is in the server_admins collection with is_active=True.
    """
    try:
        generated_cards: List[Dict[str, Any]] = []
        max_retries = 3  # Max retries per code in case of collision
        
        logger.info(
            f"Admin {admin_user.id} generating {payload.count} gift card(s) "
            f"with {payload.credits_value} credits each"
            f"{f', prefix={payload.prefix}' if payload.prefix else ''}"
        )
        
        for i in range(payload.count):
            # Generate a unique code, retry on collision
            code = None
            for attempt in range(max_retries):
                candidate = generate_gift_card_code(prefix=payload.prefix)
                
                # Check for collision by looking up the code
                existing = await directus_service.get_gift_card_by_code(candidate)
                if existing is None:
                    code = candidate
                    break
                else:
                    logger.warning(
                        f"Gift card code collision on attempt {attempt + 1}: {candidate}. Retrying..."
                    )
            
            if code is None:
                logger.error(f"Failed to generate unique gift card code after {max_retries} retries")
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to generate unique code for card {i + 1}. Please try again."
                )
            
            # Create the gift card in Directus (no purchaser since admin-generated)
            created_card = await directus_service.create_gift_card(
                code=code,
                credits_value=payload.credits_value,
                purchaser_user_id_hash=None,  # Admin-generated, not purchased
                is_reusable=payload.is_reusable,
                allowed_email_domain=payload.allowed_email_domain,
            )
            
            if not created_card:
                logger.error(f"Failed to create gift card with code: {code}")
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to create gift card {i + 1} in database. Please try again."
                )
            
            # Add notes to the gift card if provided
            # Notes are stored directly in the gift_cards table
            if payload.notes:
                try:
                    await directus_service.update_item(
                        "gift_cards",
                        created_card["id"],
                        {"notes": payload.notes}
                    )
                except Exception as notes_err:
                    # Non-critical: log but don't fail the whole operation
                    logger.warning(f"Failed to add notes to gift card {code}: {notes_err}")
            
            generated_cards.append({
                "code": code,
                "credits_value": payload.credits_value,
                "created_at": created_card.get("created_at", "")
            })
        
        logger.info(
            f"Admin {admin_user.id} successfully generated {len(generated_cards)} gift card(s) "
            f"with {payload.credits_value} credits each"
        )
        
        return {
            "success": True,
            "gift_cards": generated_cards,
            "count": len(generated_cards),
            "message": f"Successfully generated {len(generated_cards)} gift card(s)"
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating gift cards: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to generate gift cards")


@router.get("/gift-cards", response_model=AdminGiftCardListResponse)
@limiter.limit("30/minute")
async def admin_list_gift_cards(
    request: Request,
    admin_user: User = Depends(require_admin),
    directus_service: DirectusService = Depends(get_directus_service)
) -> Dict[str, Any]:
    """
    List all active (unredeemed) gift cards on the server.

    Admin-only endpoint. Returns all gift cards currently in the database.
    Redeemed cards are deleted on redemption, so all returned cards are still valid.

    Security: Protected by require_admin dependency.
    """
    try:
        cards = await directus_service.get_all_gift_cards()

        # Normalise to the response model shape
        gift_cards = [
            {
                "id": str(card.get("id", "")),
                "code": card.get("code", ""),
                "credits_value": card.get("credits_value", 0),
                "created_at": card.get("created_at") or "",
                "notes": card.get("notes") or None,
                "purchased_at": card.get("purchased_at") or None,
            }
            for card in cards
        ]

        # Sort newest first so freshly generated cards appear at the top
        gift_cards.sort(key=lambda c: c.get("created_at", ""), reverse=True)

        logger.info(
            f"Admin {admin_user.id} listed {len(gift_cards)} active gift card(s)"
        )

        return {
            "success": True,
            "gift_cards": gift_cards,
            "count": len(gift_cards),
        }

    except Exception as e:
        logger.error(f"Error listing gift cards: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to list gift cards")



# --- Compression Threshold Admin Override ---
# Architecture: See docs/architecture/chat-compression.md
# Allows admins to set a custom compression trigger threshold (in tokens)
# that overrides the default 100k threshold for their own account only.
# This is stored in Redis and read by the AI worker during compression checks.

ADMIN_COMPRESSION_THRESHOLD_CACHE_KEY = "admin:compression_threshold_override"


class CompressionThresholdRequest(BaseModel):
    """Request body for setting the admin compression threshold override."""
    threshold: int = Field(
        ...,
        ge=1000,
        le=500000,
        description="Compression trigger threshold in estimated tokens (1000-500000)"
    )


class CompressionThresholdResponse(BaseModel):
    """Response for compression threshold operations."""
    success: bool = Field(default=True)
    threshold: Optional[int] = Field(
        None, description="Current threshold override (null if using default)"
    )
    default_threshold: int = Field(
        default=100000, description="Default compression threshold"
    )


@router.get("/compression-threshold", response_model=CompressionThresholdResponse)
@limiter.limit("30/minute")
async def get_compression_threshold(
    request: Request,
    admin_user: User = Depends(require_admin),
    cache_service: CacheService = Depends(get_cache_service),
):
    """Get the admin's current compression threshold override."""
    try:
        redis_client = await cache_service.client
        if redis_client is None:
            raise RuntimeError("cache client not connected")
        raw = await redis_client.hget(
            ADMIN_COMPRESSION_THRESHOLD_CACHE_KEY, admin_user.id
        )
        threshold = int(raw) if raw else None
        return CompressionThresholdResponse(
            success=True,
            threshold=threshold,
            default_threshold=100000,
        )
    except Exception as e:
        logger.error(f"Error getting compression threshold: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get compression threshold")


@router.post("/compression-threshold", response_model=CompressionThresholdResponse)
@limiter.limit("10/minute")
async def set_compression_threshold(
    request: Request,
    body: CompressionThresholdRequest,
    admin_user: User = Depends(require_admin),
    cache_service: CacheService = Depends(get_cache_service),
):
    """Set a custom compression threshold override for the admin's account."""
    try:
        redis_client = await cache_service.client
        if redis_client is None:
            raise RuntimeError("cache client not connected")
        await redis_client.hset(
            ADMIN_COMPRESSION_THRESHOLD_CACHE_KEY, admin_user.id, str(body.threshold)
        )
        logger.info(
            f"Admin {admin_user.id} set compression threshold to {body.threshold} tokens"
        )
        return CompressionThresholdResponse(
            success=True,
            threshold=body.threshold,
            default_threshold=100000,
        )
    except Exception as e:
        logger.error(f"Error setting compression threshold: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to set compression threshold")


@router.delete("/compression-threshold", response_model=CompressionThresholdResponse)
@limiter.limit("10/minute")
async def delete_compression_threshold(
    request: Request,
    admin_user: User = Depends(require_admin),
    cache_service: CacheService = Depends(get_cache_service),
):
    """Remove the admin's compression threshold override (revert to default)."""
    try:
        redis_client = await cache_service.client
        if redis_client is None:
            raise RuntimeError("cache client not connected")
        await redis_client.hdel(
            ADMIN_COMPRESSION_THRESHOLD_CACHE_KEY, admin_user.id
        )
        logger.info(f"Admin {admin_user.id} removed compression threshold override")
        return CompressionThresholdResponse(
            success=True,
            threshold=None,
            default_threshold=100000,
        )
    except Exception as e:
        logger.error(f"Error deleting compression threshold: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to delete compression threshold")


# =============================================================================
# Test Results API — Admin-only endpoints for viewing test results and
# triggering out-of-schedule test runs from the settings dashboard.
#
# Test results live as JSON files on disk (written by scripts/run-tests.sh and
# scripts/run-tests-daily.sh). No database model needed — this endpoint reads
# the existing files directly.
#
# Architecture: File-based test results, no DB persistence.
# See scripts/run-tests.sh and scripts/run-tests-daily.sh for the file format.
# =============================================================================

class TestResultsResponse(BaseModel):
    """Response model for GET /v1/admin/test-results."""
    has_results: bool = Field(description="Whether any test results are available")
    last_run: Optional[Dict[str, Any]] = Field(None, description="Full last-run.json data")
    last_run_timestamp: Optional[str] = Field(None, description="ISO timestamp of last run")
    next_scheduled_run_utc: str = Field(description="ISO timestamp of next scheduled daily run (03:00 UTC)")
    hours_until_next_run: float = Field(description="Hours until next scheduled daily run")


def _get_project_root():
    """Get the project root directory (works both on host and inside Docker)."""
    import pathlib
    # Walk up from this file to find the project root. Inside Docker the app
    # is mounted at /app, so we look for the test-results or scripts directory
    # as a project root indicator.
    candidate = pathlib.Path(__file__).resolve()
    for parent in candidate.parents:
        if (parent / "scripts").is_dir() or (parent / "test-results").is_dir():
            return parent
    # Fallback: inside Docker /app is always the project root
    return pathlib.Path("/app")


def _compute_next_daily_run_utc() -> tuple:
    """
    Compute the next daily test run time (03:00 UTC).
    Returns (iso_timestamp, hours_until).
    """
    from datetime import datetime, timezone, timedelta

    now = datetime.now(timezone.utc)
    # Next 03:00 UTC
    today_run = now.replace(hour=3, minute=0, second=0, microsecond=0)
    if now >= today_run:
        next_run = today_run + timedelta(days=1)
    else:
        next_run = today_run

    hours_until = (next_run - now).total_seconds() / 3600
    return next_run.isoformat(), round(hours_until, 1)


@router.get("/test-results", response_model=TestResultsResponse)
@limiter.limit("30/minute")
async def get_test_results(
    request: Request,
    admin_user: User = Depends(require_admin),
) -> TestResultsResponse:
    """
    Get the latest test run results and scheduling info.

    Reads test-results/last-run.json from disk and computes scheduling metadata.
    Daily tests are triggered by a system crontab (see `crontab -l` on the host).
    Manual runs can be started via: ./scripts/run-tests-daily.sh --force
    Admin-only endpoint.
    """
    import json
    project_root = _get_project_root()
    last_run_path = project_root / "test-results" / "last-run.json"

    next_run_utc, hours_until = _compute_next_daily_run_utc()

    if not last_run_path.exists():
        return TestResultsResponse(
            has_results=False,
            last_run=None,
            last_run_timestamp=None,
            next_scheduled_run_utc=next_run_utc,
            hours_until_next_run=hours_until,
        )

    try:
        with open(last_run_path, "r") as f:
            last_run = json.load(f)

        last_run_timestamp = last_run.get("run_id")

        return TestResultsResponse(
            has_results=True,
            last_run=last_run,
            last_run_timestamp=last_run_timestamp,
            next_scheduled_run_utc=next_run_utc,
            hours_until_next_run=hours_until,
        )
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse last-run.json: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to parse test results file")
    except Exception as e:
        logger.error(f"Failed to read test results: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to read test results")
