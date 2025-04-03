import logging

logger = logging.getLogger(__name__)

async def get_invite_code(self, code: str) -> dict:
    cache_key = f"invite_code:{code}"
    cached_data = await self.cache.get(cache_key)
    
    if cached_data:
        logger.info(f"Using cached invite code data for code: {code}")
        return cached_data
        
    try:
        logger.info(f"Checking invite code: {code}")
        collection_name = "invite_codes"
        url = f"{self.base_url}/items/{collection_name}"
        params = {"filter[code][_eq]": code}
        
        response = await self._make_api_request(
            "GET", 
            url, 
            params=params
        )
        
        if response.status_code == 200:
            response_data = response.json()
            items = response_data.get("data", [])
            
            if items:
                logger.info(f"Found invite code in collection {collection_name}")
                await self.cache.set(cache_key, items[0], ttl=self.cache_ttl)
                return items[0]
        else:
            logger.warning(f"Directus API error for {collection_name}: {response.status_code} - {response.text}")
    
        logger.info(f"Invite code not found: {code}")
        return None
            
    except Exception as e:
        logger.exception(f"Error connecting to CMS: {str(e)}")
        return None

async def consume_invite_code(self, invite_code: str, code_data: dict) -> bool:
    """
    Consumes an invite code by either deleting it or decrementing remaining_uses.
    """
    if not code_data or 'id' not in code_data:
        logger.error(f"Cannot consume invite code {invite_code}: Invalid code_data provided.")
        return False

    code_id = code_data.get('id')
    # Default to 1 use if remaining_uses is not specified or invalid
    try:
        remaining_uses = int(code_data.get('remaining_uses', 1))
    except (ValueError, TypeError):
        remaining_uses = 1
        
    collection_name = "invite_codes"
    url = f"{self.base_url}/items/{collection_name}/{code_id}"

    try:
        if remaining_uses <= 1:
            logger.info(f"Deleting invite code {invite_code} (ID: {code_id}) as remaining uses <= 1.")
            response = await self._make_api_request("DELETE", url)
            # DELETE often returns 204 No Content on success
            if response.status_code == 204 or response.status_code == 200:
                logger.info(f"Successfully deleted invite code {invite_code}")
                # Clear cache for this specific code
                await self.cache.delete(f"invite_code:{invite_code}")
                return True
            else:
                logger.error(f"Failed to delete invite code {invite_code}. Status: {response.status_code} - {response.text}")
                return False
        else:
            new_uses = remaining_uses - 1
            logger.info(f"Decrementing remaining uses for invite code {invite_code} (ID: {code_id}) from {remaining_uses} to {new_uses}.")
            payload = {"remaining_uses": new_uses}
            response = await self._make_api_request("PATCH", url, json=payload)
            
            if response.status_code == 200:
                logger.info(f"Successfully decremented remaining uses for invite code {invite_code}")
                # Update cache with new data (or simply delete to force refresh)
                await self.cache.delete(f"invite_code:{invite_code}") 
                return True
            else:
                logger.error(f"Failed to decrement remaining uses for invite code {invite_code}. Status: {response.status_code} - {response.text}")
                return False
                
    except Exception as e:
        logger.error(f"Error consuming invite code {invite_code}: {str(e)}", exc_info=True)
        return False

async def get_all_invite_codes(self):
    try:
        logger.info("Fetching all invite codes from Directus")
        collection_name = "invite_codes"
        url = f"{self.base_url}/items/{collection_name}"
        
        response = await self._make_api_request("GET", url)
        
        if response.status_code == 200:
            response_data = response.json()
            items = response_data.get("data", [])
            
            if items:
                logger.info(f"Found {len(items)} invite codes")
                return items
            else:
                logger.info("No invite codes found")
                return []
        else:
            logger.warning(f"Directus API error: {response.status_code} - {response.text}")
            return []
            
    except Exception as e:
        logger.error(f"Error fetching all invite codes: {str(e)}", exc_info=True)
        return []
