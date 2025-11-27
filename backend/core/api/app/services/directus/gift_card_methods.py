"""
Gift card methods for DirectusService.
Handles fetching, caching, and redeeming gift cards.
"""
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

async def get_gift_card_by_code(self, code: str) -> Optional[Dict[str, Any]]:
    """
    Fetches a gift card by code from cache first, then Directus if not found.
    Gift cards are deleted after redemption, so if found, it's available.
    
    Args:
        code: The gift card code to look up
        
    Returns:
        Gift card data dict if found, None otherwise
    """
    cache_key = f"gift_card:{code}"
    cached_data = await self.cache.get(cache_key)
    
    if cached_data:
        logger.debug(f"Using cached gift card data for code: {code}")
        return cached_data
        
    try:
        logger.info(f"Checking gift card code: {code}")
        collection_name = "gift_cards"
        url = f"{self.base_url}/items/{collection_name}"
        # Filter for cards with matching code (redeemed cards are deleted, so all found cards are available)
        params = {
            "filter[code][_eq]": code
        }
        
        response = await self._make_api_request(
            "GET", 
            url, 
            params=params
        )
        
        if response.status_code == 200:
            response_data = response.json()
            items = response_data.get("data", [])
            
            if items:
                gift_card = items[0]
                logger.info(f"Found gift card in collection {collection_name} with code: {code}")
                # Cache the gift card for faster future lookups
                await self.cache.set(cache_key, gift_card, ttl=self.cache_ttl)
                return gift_card
        else:
            logger.warning(f"Directus API error for {collection_name}: {response.status_code} - {response.text}")
    
    except Exception as e:
        logger.exception(f"Error connecting to CMS while fetching gift card: {str(e)}")
        return None
    
    logger.info(f"Gift card not found or already redeemed: {code}")
    return None

async def get_all_gift_cards(self) -> list:
    """
    Fetches all gift cards from Directus.
    Used for preloading into cache on server startup.
    Redeemed cards are deleted, so all cards in the collection are available.
    
    Returns:
        List of gift card dictionaries, empty list if none found or error
    """
    try:
        logger.info("Fetching all gift cards from Directus")
        collection_name = "gift_cards"
        url = f"{self.base_url}/items/{collection_name}"
        # Fetch all cards (redeemed cards are deleted, so all found cards are available)
        params = {}
        
        response = await self._make_api_request("GET", url, params=params)
        
        if response.status_code == 200:
            response_data = response.json()
            items = response_data.get("data", [])
            
            if items:
                logger.info(f"Found {len(items)} unredeemed gift cards")
                return items
            else:
                logger.info("No unredeemed gift cards found")
                return []
        else:
            logger.warning(f"Directus API error fetching gift cards: {response.status_code} - {response.text}")
            return []
            
    except Exception as e:
        logger.error(f"Error fetching all gift cards: {str(e)}", exc_info=True)
        return []

async def redeem_gift_card(self, code: str, user_id: str) -> bool:
    """
    Redeems a gift card by deleting it from Directus and cache.
    Gift cards are single-use only, so we delete them upon redemption.
    
    Args:
        code: The gift card code to redeem
        user_id: The ID of the user redeeming the card
        
    Returns:
        True if successfully redeemed and deleted, False otherwise
    """
    # First, get the gift card to verify it exists and get its ID
    gift_card = await self.get_gift_card_by_code(code)
    
    if not gift_card or 'id' not in gift_card:
        logger.error(f"Cannot redeem gift card {code}: Gift card not found or invalid.")
        return False
    
    gift_card_id = gift_card.get('id')
    collection_name = "gift_cards"
    url = f"{self.base_url}/items/{collection_name}/{gift_card_id}"
    
    try:
        # Delete the gift card (single-use, so we delete it)
        logger.info(f"Deleting gift card {code} (ID: {gift_card_id}) after redemption by user {user_id}.")
        response = await self._make_api_request("DELETE", url)
        
        # DELETE often returns 204 No Content on success
        if response.status_code == 204 or response.status_code == 200:
            logger.info(f"Successfully deleted gift card {code} after redemption")
            # Clear cache for this specific code
            cache_key = f"gift_card:{code}"
            await self.cache.delete(cache_key)
            return True
        else:
            logger.error(f"Failed to delete gift card {code}. Status: {response.status_code} - {response.text}")
            return False
                
    except Exception as e:
        logger.error(f"Error redeeming gift card {code}: {str(e)}", exc_info=True)
        return False

