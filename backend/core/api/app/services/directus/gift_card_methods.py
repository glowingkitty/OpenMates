"""
Gift card methods for DirectusService.
Handles fetching, caching, and redeeming gift cards.
"""
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone

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

async def create_gift_card(
    self,
    code: str,
    credits_value: int,
    purchaser_user_id_hash: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """
    Creates a new gift card in Directus.
    
    Args:
        code: Unique gift card code
        credits_value: Number of credits the gift card provides
        purchaser_user_id_hash: Optional hash of the user ID who purchased this card
        
    Returns:
        Created gift card data dict if successful, None otherwise
    """
    try:
        logger.info(f"Creating gift card with code: {code}, credits: {credits_value}")
        collection_name = "gift_cards"
        
        # Prepare gift card data
        gift_card_data = {
            "code": code.upper(),  # Store codes in uppercase
            "credits_value": credits_value,
        }
        
        # Add purchaser info if provided
        if purchaser_user_id_hash:
            gift_card_data["purchaser_user_id_hash"] = purchaser_user_id_hash
            # Use ISO 8601 format for datetime fields (Directus/PostgreSQL requirement)
            gift_card_data["purchased_at"] = datetime.now(timezone.utc).isoformat()
        
        # Create the gift card using create_item (returns tuple: success, data)
        success, created_item = await self.create_item(collection_name, gift_card_data)
        
        if success and created_item:
            logger.info(f"Successfully created gift card with code: {code}")
            # Cache the newly created gift card
            cache_key = f"gift_card:{code.upper()}"
            await self.cache.set(cache_key, created_item, ttl=self.cache_ttl)
            return created_item
        else:
            logger.error(f"Failed to create gift card with code: {code}. Response: {created_item}")
            return None
            
    except Exception as e:
        logger.error(f"Error creating gift card with code {code}: {str(e)}", exc_info=True)
        return None

async def record_gift_card_redemption(
    self,
    gift_card_code: str,
    gift_card_id: Optional[str],
    user_id_hash: str,
    credits_value: int,
    encryption_service,
    vault_key_id: str
) -> bool:
    """
    Records a gift card redemption in the redeemed_gift_cards collection.
    This preserves redemption history even after the gift card is deleted.
    The gift card code is encrypted using the user's vault key for privacy.
    
    Args:
        gift_card_code: The gift card code that was redeemed
        gift_card_id: The ID of the gift card (may be None if already deleted)
        user_id_hash: Hash of the user ID who redeemed the card
        credits_value: Number of credits that were added
        encryption_service: EncryptionService instance for encrypting the code
        vault_key_id: User's vault key ID for encryption
        
    Returns:
        True if successfully recorded, False otherwise
    """
    try:
        logger.info(f"Recording gift card redemption: code={gift_card_code[:4]}***, user_hash={user_id_hash[:8]}...")
        collection_name = "redeemed_gift_cards"
        
        # Encrypt the gift card code using the user's vault key
        encrypted_code_tuple = await encryption_service.encrypt_with_user_key(
            plaintext=gift_card_code.upper(),
            key_id=vault_key_id
        )
        encrypted_gift_card_code = encrypted_code_tuple[0]
        
        # Use ISO 8601 format for datetime fields (Directus/PostgreSQL requirement)
        redemption_data = {
            "encrypted_gift_card_code": encrypted_gift_card_code,
            "user_id_hash": user_id_hash,
            "credits_value": credits_value,
            "gift_card_id": gift_card_id,  # May be None if card was already deleted
            "redeemed_at": datetime.now(timezone.utc).isoformat()
        }
        
        # Create the redemption record
        success, created_item = await self.create_item(collection_name, redemption_data)
        
        if success:
            logger.info(f"Successfully recorded gift card redemption for code: {gift_card_code[:4]}***")
            return True
        else:
            logger.error(f"Failed to record gift card redemption for code: {gift_card_code[:4]}***. Response: {created_item}")
            return False
            
    except Exception as e:
        logger.error(f"Error recording gift card redemption for code {gift_card_code[:4]}***: {str(e)}", exc_info=True)
        return False

async def get_user_redeemed_gift_cards(
    self,
    user_id_hash: str,
    encryption_service,
    vault_key_id: str
) -> List[Dict[str, Any]]:
    """
    Fetches all gift cards redeemed by a specific user.
    Decrypts the gift card codes using the user's vault key.
    
    Args:
        user_id_hash: Hash of the user ID
        encryption_service: EncryptionService instance for decrypting codes
        vault_key_id: User's vault key ID for decryption
        
    Returns:
        List of redeemed gift card records with decrypted codes, empty list if none found or error
    """
    try:
        logger.info(f"Fetching redeemed gift cards for user hash: {user_id_hash[:8]}...")
        collection_name = "redeemed_gift_cards"
        url = f"{self.base_url}/items/{collection_name}"
        
        # Filter by user_id_hash and sort by redeemed_at descending (most recent first)
        params = {
            "filter[user_id_hash][_eq]": user_id_hash,
            "sort[]": "-redeemed_at"  # Most recent first
        }
        
        response = await self._make_api_request("GET", url, params=params)
        
        if response.status_code == 200:
            response_data = response.json()
            items = response_data.get("data", [])
            
            if items:
                logger.info(f"Found {len(items)} redeemed gift cards for user")
                # Decrypt gift card codes for each item
                decrypted_items = []
                for item in items:
                    encrypted_code = item.get("encrypted_gift_card_code")
                    if encrypted_code:
                        try:
                            decrypted_code = await encryption_service.decrypt_with_user_key(
                                ciphertext=encrypted_code,
                                key_id=vault_key_id
                            )
                            # Add decrypted code to the item (keep encrypted version for reference)
                            item["gift_card_code"] = decrypted_code
                        except Exception as decrypt_err:
                            logger.error(f"Failed to decrypt gift card code for redemption record {item.get('id')}: {decrypt_err}")
                            # Still include the item but without the decrypted code
                            item["gift_card_code"] = None
                    else:
                        item["gift_card_code"] = None
                    decrypted_items.append(item)
                return decrypted_items
            else:
                logger.info("No redeemed gift cards found for user")
                return []
        else:
            logger.warning(f"Directus API error fetching redeemed gift cards: {response.status_code} - {response.text}")
            return []
            
    except Exception as e:
        logger.error(f"Error fetching redeemed gift cards for user: {str(e)}", exc_info=True)
        return []

async def get_user_purchased_gift_cards(self, user_id_hash: str) -> List[Dict[str, Any]]:
    """
    Fetches all gift cards purchased by a specific user (that haven't been redeemed yet).
    
    Args:
        user_id_hash: Hash of the user ID
        
    Returns:
        List of purchased gift card records, empty list if none found or error
    """
    try:
        logger.info(f"Fetching purchased gift cards for user hash: {user_id_hash[:8]}...")
        collection_name = "gift_cards"
        url = f"{self.base_url}/items/{collection_name}"
        
        # Filter by purchaser_user_id_hash and sort by purchased_at descending (most recent first)
        params = {
            "filter[purchaser_user_id_hash][_eq]": user_id_hash,
            "sort[]": "-purchased_at"  # Most recent first
        }
        
        response = await self._make_api_request("GET", url, params=params)
        
        if response.status_code == 200:
            response_data = response.json()
            items = response_data.get("data", [])
            
            if items:
                logger.info(f"Found {len(items)} purchased gift cards for user")
                return items
            else:
                logger.info("No purchased gift cards found for user")
                return []
        else:
            logger.warning(f"Directus API error fetching purchased gift cards: {response.status_code} - {response.text}")
            return []
            
    except Exception as e:
        logger.error(f"Error fetching purchased gift cards for user: {str(e)}", exc_info=True)
        return []

