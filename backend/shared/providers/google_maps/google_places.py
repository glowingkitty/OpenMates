# backend/shared/providers/google_maps/google_places.py
#
# Google Places API (New) provider functions.
# Provides place search functionality using the Google Places API (New).
#
# Documentation: https://developers.google.com/maps/documentation/places/web-service
#
# Health Check:
# - No dedicated /health endpoint available
# - Health checks verify API key configuration and endpoint connectivity (HEAD request)
# - Does NOT perform actual search requests to avoid billing costs
# - Checked every 5 minutes via Celery Beat task

import json
import logging
import os
import httpx
from typing import Dict, Any, List, Optional

from backend.core.api.app.utils.secrets_manager import SecretsManager

logger = logging.getLogger(__name__)

# Vault path for Google Maps API key
GOOGLE_MAPS_SECRET_PATH = "kv/data/providers/google_maps"
GOOGLE_MAPS_API_KEY_NAME = "api_key"

# Google Places API (New) base URL
GOOGLE_PLACES_API_BASE_URL = "https://places.googleapis.com/v1"

# Default fields to request (Enterprise + Atmosphere SKU tier)
# 
# IMPORTANT: Google charges based on the HIGHEST tier field requested.
# Enterprise and Enterprise + Atmosphere both cost $0.032 per request.
# Since we're requesting Enterprise + Atmosphere fields (editorialSummary),
# we get all Enterprise fields included at no extra cost!
#
# NOTE: Reviews are NOT included by default as they significantly increase response size.
# Consider creating a separate skill for fetching reviews for a specific place.
#
# Fields included:
# - Basic info: name, address, location, types, place ID
# - Ratings: rating, user rating count
# - Contact: website URI, phone number (international preferred, national as fallback)
# - Business info: price level, price range, business status
# - Hours: current opening hours, regular opening hours (with text summaries)
# - Description: editorial summary (description of the place)
# - AI summaries: generative summary (AI-powered place summary, only if not empty)
DEFAULT_FIELD_MASK = [
    # Basic information (Pro/Enterprise tier)
    "places.displayName",
    "places.formattedAddress",  # Full address (shortFormattedAddress removed - not needed)
    "places.location",
    "places.types",
    "places.id",
    "places.businessStatus",  # OPERATIONAL, CLOSED_TEMPORARILY, etc.
    
    # Ratings (Enterprise tier)
    "places.rating",
    "places.userRatingCount",
    
    # Contact information (Enterprise tier)
    "places.websiteUri",
    "places.nationalPhoneNumber",  # Used as fallback if international not available
    "places.internationalPhoneNumber",  # Preferred phone number format
    
    # Pricing information (Enterprise tier)
    "places.priceLevel",  # 0-4 price level
    "places.priceRange",  # Price range details
    
    # Opening hours (Enterprise tier)
    "places.currentOpeningHours",  # Current/today's hours
    "places.regularOpeningHours",  # Regular weekly schedule
    
    # Descriptions and summaries (Enterprise + Atmosphere tier)
    "places.editorialSummary",  # Description of the place
    "places.generativeSummary",  # AI-powered place summary
    # Reviews excluded - too large for default response, consider separate skill
]


async def _get_google_maps_api_key(secrets_manager: SecretsManager) -> Optional[str]:
    """
    Retrieves the Google Maps Platform API key from Vault, with fallback to environment variables.
    
    Checks Vault first, then falls back to environment variables if Vault lookup fails.
    Uses SECRET__GOOGLE_MAPS__API_KEY environment variable format.
    
    Args:
        secrets_manager: The SecretsManager instance to use
        
    Returns:
        The API key if found, None otherwise
    """
    # First, try to get the API key from Vault
    try:
        api_key = await secrets_manager.get_secret(
            secret_path=GOOGLE_MAPS_SECRET_PATH,
            secret_key=GOOGLE_MAPS_API_KEY_NAME
        )
        
        if api_key:
            # Clean the API key (strip whitespace, remove quotes if present)
            api_key_clean = api_key.strip()
            if (api_key_clean.startswith('"') and api_key_clean.endswith('"')) or \
               (api_key_clean.startswith("'") and api_key_clean.endswith("'")):
                api_key_clean = api_key_clean[1:-1].strip()
            
            logger.debug(f"Successfully retrieved Google Maps API key from Vault (length: {len(api_key_clean)})")
            return api_key_clean
        
        logger.debug("Google Maps API key not found in Vault, checking environment variables")
    
    except Exception as e:
        logger.warning(f"Error retrieving Google Maps API key from Vault: {str(e)}, checking environment variables", exc_info=True)
    
    # Fallback to environment variables
    env_var_name = "SECRET__GOOGLE_MAPS__API_KEY"
    api_key = os.getenv(env_var_name)
    if api_key and api_key.strip():
        # Strip whitespace and ensure no hidden characters
        api_key_clean = api_key.strip()
        # Remove any potential quotes that might have been added
        if (api_key_clean.startswith('"') and api_key_clean.endswith('"')) or \
           (api_key_clean.startswith("'") and api_key_clean.endswith("'")):
            api_key_clean = api_key_clean[1:-1].strip()
        
        if api_key_clean:
            masked_key = f"{api_key_clean[:4]}****{api_key_clean[-4:]}" if len(api_key_clean) > 8 else "****"
            logger.info(f"Successfully retrieved Google Maps API key from environment variable '{env_var_name}': {masked_key} (length: {len(api_key_clean)})")
            return api_key_clean
    
    logger.error("Google Maps API key not found in Vault or environment variables. Please configure it in Vault or set SECRET__GOOGLE_MAPS__API_KEY environment variable.")
    return None


async def check_google_places_health(secrets_manager: SecretsManager) -> tuple[bool, Optional[str]]:
    """
    Check Google Places API health by verifying API key configuration and endpoint connectivity.
    
    This health check does NOT perform actual search requests to avoid billing costs.
    Instead, it:
    1. Verifies the API key is configured (in Vault or environment variables)
    2. Checks if the API base URL is reachable via HEAD request (no billing)
    
    Google Places API does not have a dedicated /health endpoint, and performing test searches
    would incur billing costs, so we use this lightweight connectivity check instead.
    
    Args:
        secrets_manager: SecretsManager instance for retrieving API key
    
    Returns:
        Tuple of (is_healthy, error_message)
        - is_healthy: True if API key is configured and endpoint is reachable
        - error_message: None if healthy, error description if unhealthy
    """
    try:
        # Step 1: Verify API key is configured
        api_key = await _get_google_maps_api_key(secrets_manager)
        if not api_key:
            return False, "API key not configured (not found in Vault or environment variables)"
        
        # Step 2: Check if API base URL is reachable via HEAD request (no billing)
        # HEAD request to base URL to verify connectivity without making a search request
        # We accept any HTTP response (even 404/405 errors) as proof the service is online
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                # Use HEAD request to check connectivity without triggering billing
                # Note: This may return 404, 405 (method not allowed), or other errors
                # Any response means the endpoint is reachable and the service is online
                response = await client.head(GOOGLE_PLACES_API_BASE_URL)
                logger.debug(f"Google Places API connectivity check: {response.status_code} - endpoint is reachable")
                return True, None
        except httpx.TimeoutException:
            return False, "API endpoint timeout (endpoint not reachable)"
        except httpx.ConnectError as e:
            return False, f"API endpoint connection error: {str(e)}"
        except httpx.HTTPStatusError as e:
            # Even if we get an error status (404, 405, etc.), the endpoint is reachable
            # This means the service is online - we got a response from their servers
            # This is much better than nothing and doesn't cost anything
            logger.debug(f"Google Places API returned status {e.response.status_code}, but endpoint is reachable (service is online)")
            return True, None
        except httpx.RequestError as e:
            return False, f"API request error: {str(e)}"
            
    except Exception as e:
        logger.error(f"Unexpected error in Google Places API health check: {str(e)}", exc_info=True)
        return False, f"Unexpected error: {str(e)}"


async def search_places(
    text_query: str,
    secrets_manager: SecretsManager,
    page_size: int = 20,  # Default to maximum results per request
    language_code: Optional[str] = None,
    location_bias: Optional[Dict[str, Any]] = None,
    included_type: Optional[str] = None,
    min_rating: Optional[float] = None,
    open_now: Optional[bool] = None,
    field_mask: Optional[List[str]] = None,
    include_reviews: bool = False  # If True, include reviews in response (significantly increases response size)
) -> Dict[str, Any]:
    """
    Performs a place search using the Google Places API (New) Text Search endpoint.
    
    Args:
        text_query: The text query string to search for places (e.g., "restaurants in Berlin")
        secrets_manager: SecretsManager instance for retrieving API key
        page_size: Number of results to return (1-20, default: 10)
        language_code: Language code for results (ISO 639-1, e.g., 'en', 'es', 'fr')
        location_bias: Optional location bias (circle or rectangle) to prioritize results near a specific area
        included_type: Optional place type filter (e.g., 'restaurant', 'museum')
        min_rating: Optional minimum rating filter (0.0 to 5.0)
        open_now: Optional filter to return only places currently open
        field_mask: Optional list of fields to return. If None, uses DEFAULT_FIELD_MASK (Enterprise + Atmosphere SKU)
        include_reviews: If True, include reviews in the response. Defaults to False to keep response size manageable.
    
    Returns:
        Dict containing search results with the following structure:
        {
            "query": str,
            "results": List[Dict],  # List of place objects
            "next_page_token": Optional[str],  # Token for pagination
            "error": Optional[str],  # Error message if request failed
        }
    
    Raises:
        ValueError: If API key is not available
        httpx.HTTPStatusError: If the API request fails
    """
    # Get API key from Vault or environment variables
    api_key = await _get_google_maps_api_key(secrets_manager)
    if not api_key:
        raise ValueError("Google Maps API key not available. Please configure it in Vault or set SECRET__GOOGLE_MAPS__API_KEY environment variable.")
    
    # Validate page_size
    page_size = max(1, min(page_size, 20))  # Clamp between 1 and 20
    
    # Use default field mask if not provided
    if field_mask is None:
        field_mask = DEFAULT_FIELD_MASK.copy()  # Make a copy to avoid modifying the default
    
    # Conditionally add reviews to field mask if requested
    if include_reviews and "places.reviews" not in field_mask:
        field_mask.append("places.reviews")
        logger.debug("Including reviews in field mask as requested")
    
    # Build request payload
    payload: Dict[str, Any] = {
        "textQuery": text_query,
        "pageSize": page_size
    }
    
    # Add optional parameters
    if language_code:
        payload["languageCode"] = language_code
    
    if location_bias:
        payload["locationBias"] = location_bias
    
    if included_type:
        payload["includedType"] = included_type
    
    if min_rating is not None:
        # Validate and round min_rating to nearest 0.5
        min_rating = max(0.0, min(5.0, min_rating))
        # Round to nearest 0.5
        min_rating = round(min_rating * 2) / 2
        payload["minRating"] = min_rating
    
    if open_now is not None:
        payload["openNow"] = open_now
    
    # Build full URL
    url = f"{GOOGLE_PLACES_API_BASE_URL}/places:searchText"
    
    # Set up headers
    # Google Places API (New) requires X-Goog-Api-Key header and X-Goog-FieldMask header
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": ",".join(field_mask)
    }
    
    # Log API key info for debugging (masked)
    masked_key = f"{api_key[:4]}****{api_key[-4:]}" if len(api_key) > 8 else "****"
    logger.debug(f"Performing Google Places search: query='{text_query}', page_size={page_size}, api_key_length={len(api_key)}, api_key_preview={masked_key}")
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            
            result_data = response.json()
            
            # Extract and format results
            places = result_data.get("places", [])
            
            # Format results for consistent structure
            formatted_results = []
            for place in places:
                # Extract display name
                display_name_obj = place.get("displayName", {})
                display_name = display_name_obj.get("text", "") if isinstance(display_name_obj, dict) else ""
                
                # Extract location
                location = place.get("location", {})
                latitude = location.get("latitude") if isinstance(location, dict) else None
                longitude = location.get("longitude") if isinstance(location, dict) else None
                
                # Extract rating
                rating = place.get("rating")
                user_rating_count = place.get("userRatingCount")
                
                # Extract types
                types = place.get("types", [])
                if not isinstance(types, list):
                    types = []
                
                # Extract place ID
                place_id = place.get("id", "")
                
                # Extract editorial summary (description) - Enterprise + Atmosphere tier
                editorial_summary_obj = place.get("editorialSummary", {})
                editorial_summary = editorial_summary_obj.get("text", "") if isinstance(editorial_summary_obj, dict) else None
                
                # Extract generative summary (AI-powered summary) - Enterprise + Atmosphere tier
                generative_summary_obj = place.get("generativeSummary", {})
                generative_summary = generative_summary_obj.get("text", "") if isinstance(generative_summary_obj, dict) else None
                
                # Extract phone numbers - Enterprise tier
                # Prefer international format, fallback to national if international not available
                international_phone = place.get("internationalPhoneNumber")
                national_phone = place.get("nationalPhoneNumber")
                phone_number = international_phone if international_phone else national_phone
                
                # Extract price information - Enterprise tier
                price_level = place.get("priceLevel")  # 0-4, where 0 is free and 4 is very expensive
                price_range = place.get("priceRange")  # Price range enum
                
                # Extract opening hours - Enterprise tier
                # Flatten to root level: extract weekdayDescriptions and nextCloseTime
                current_opening_hours_raw = place.get("currentOpeningHours")
                regular_opening_hours_raw = place.get("regularOpeningHours")
                
                # Extract openNow status - prefer current, fallback to regular
                open_now = None
                if current_opening_hours_raw and isinstance(current_opening_hours_raw, dict):
                    open_now = current_opening_hours_raw.get("openNow")
                elif regular_opening_hours_raw and isinstance(regular_opening_hours_raw, dict):
                    open_now = regular_opening_hours_raw.get("openNow")
                
                # Extract weekdayDescriptions from current_opening_hours (preferred) or regular_opening_hours
                opening_hours = None
                next_close_time = None
                
                if current_opening_hours_raw and isinstance(current_opening_hours_raw, dict):
                    # Extract weekdayDescriptions from current opening hours
                    opening_hours = current_opening_hours_raw.get("weekdayDescriptions")
                    # Extract nextCloseTime
                    next_close_time = current_opening_hours_raw.get("nextCloseTime")
                elif regular_opening_hours_raw and isinstance(regular_opening_hours_raw, dict):
                    # Fallback to regular opening hours if current not available
                    opening_hours = regular_opening_hours_raw.get("weekdayDescriptions")
                    next_close_time = regular_opening_hours_raw.get("nextCloseTime")
                
                # Ensure opening_hours is a list
                if opening_hours and not isinstance(opening_hours, list):
                    opening_hours = None
                
                # Extract business status - Pro tier
                business_status = place.get("businessStatus")
                
                # Extract reviews if requested - Enterprise + Atmosphere tier
                # Only include essential fields to keep response size manageable:
                # - rating: Review rating (1-5)
                # - text: Review text content (from text.text)
                # - publishTime: When the review was published (ISO timestamp)
                # - googleMapsUri: Link to the review on Google Maps
                # 
                # Future fields that could be added if needed:
                # - relativePublishTimeDescription: Human-readable time (e.g., "3 months ago")
                # - authorAttribution: Author name, photo, profile URI
                # - originalText: Original review text (if translated)
                # - flagContentUri: URI to report inappropriate content
                # - name: Review resource name
                reviews = None
                if include_reviews:
                    reviews_raw = place.get("reviews", [])
                    if isinstance(reviews_raw, list):
                        # Process reviews to only include essential fields
                        reviews = []
                        for review in reviews_raw:
                            if not isinstance(review, dict):
                                continue
                            
                            # Extract text from text.text
                            text_obj = review.get("text", {})
                            review_text = text_obj.get("text", "") if isinstance(text_obj, dict) else ""
                            
                            # Build minimal review object with only essential fields
                            minimal_review = {
                                "rating": review.get("rating"),
                                "text": review_text,
                                "publishTime": review.get("publishTime"),
                                "googleMapsUri": review.get("googleMapsUri")
                            }
                            
                            # Only add review if it has at least a rating or text
                            if minimal_review.get("rating") is not None or minimal_review.get("text"):
                                reviews.append(minimal_review)
                    else:
                        reviews = []
                
                # Build result dictionary
                formatted_result = {
                    "place_id": place_id,
                    "name": display_name,
                    "formatted_address": place.get("formattedAddress", ""),
                    "location": {
                        "latitude": latitude,
                        "longitude": longitude
                    } if latitude is not None and longitude is not None else None,
                    "types": types,
                    "rating": rating,
                    "user_rating_count": user_rating_count,
                    "website_uri": place.get("websiteUri"),
                    # Contact information - single phone number field (prefers international)
                    "phone_number": phone_number,
                    # Pricing information
                    "price_level": price_level,
                    "price_range": price_range,
                    # Opening hours - flattened to root level
                    "opening_hours": opening_hours,  # Array of weekday descriptions (e.g., "Monday: 11:30 AM – 10:00 PM")
                    "open_now": open_now,  # Boolean indicating if place is currently open
                    "next_close_time": next_close_time,  # ISO timestamp of next closing time
                    # Business status
                    "business_status": business_status,
                    # Descriptions and summaries
                    "description": editorial_summary,  # Editorial summary (description)
                    # Include raw place data for any additional fields
                    "_raw": place
                }
                
                # Only include generative_summary if it's not empty
                if generative_summary:
                    formatted_result["generative_summary"] = generative_summary
                
                # Only include reviews if requested (they significantly increase response size)
                if include_reviews and reviews:
                    formatted_result["reviews"] = reviews
                formatted_results.append(formatted_result)
            
            logger.info(f"Google Places search completed: found {len(formatted_results)} results for query '{text_query}'")
            
            return {
                "query": text_query,
                "results": formatted_results,
                "next_page_token": result_data.get("nextPageToken"),
                "error": None
            }
            
    except httpx.HTTPStatusError as e:
        error_msg = f"Google Places API error: {e.response.status_code} - {e.response.text}"
        logger.error(error_msg)
        return {
            "query": text_query,
            "results": [],
            "next_page_token": None,
            "error": error_msg
        }
    except httpx.RequestError as e:
        error_msg = f"Google Places API request error: {str(e)}"
        logger.error(error_msg)
        return {
            "query": text_query,
            "results": [],
            "next_page_token": None,
            "error": error_msg
        }
    except Exception as e:
        error_msg = f"Unexpected error in Google Places search: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return {
            "query": text_query,
            "results": [],
            "next_page_token": None,
            "error": error_msg
        }

