import logging
from app.services.directus import DirectusService
from app.services.cache import CacheService

logger = logging.getLogger(__name__)

async def validate_invite_code(invite_code: str, directus_service: DirectusService, cache_service: CacheService):
    """
    Validate the invite code.
    """
    cache_key = f"invite_code:{invite_code}"
    code_data = await cache_service.get(cache_key)
    
    if code_data is None:
        logger.info(f"Invite code {invite_code} not found in cache, fetching from Directus")
        code_data = await directus_service.get_invite_code(invite_code)
        
        if code_data:
            await cache_service.set(cache_key, code_data)
    
    if code_data is None:
        logger.warning(f"Invite code {invite_code} is invalid")
        return False, "Invalid invite code"
    
    logger.info(f"Invite code {invite_code} is valid")
    return True, "Invite code is valid"
