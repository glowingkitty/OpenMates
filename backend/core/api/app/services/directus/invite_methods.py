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
