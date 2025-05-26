import httpx # Use httpx for async requests
import logging
from fastapi import HTTPException
import os
from backend.core.api.app.utils.secrets_manager import SecretsManager # Import SecretsManager

logger = logging.getLogger(__name__)

class ImageSafetyService:
    def __init__(self, secrets_manager: SecretsManager):
        self.secrets_manager = secrets_manager
        # Secrets will be fetched asynchronously in _check_image
        self.api_url = 'https://api.sightengine.com/1.0/check.json'

    async def _check_image(self, image_content: bytes, include_offensive: bool = False):
        # Fetch secrets asynchronously
        api_user = await self.secrets_manager.get_secret(secret_path="kv/data/providers/sightengine", secret_key="api_user")
        api_secret = await self.secrets_manager.get_secret(secret_path="kv/data/providers/sightengine", secret_key="api_secret")

        if not api_user or not api_secret:
            logger.error("Sightengine API user or secret not found in Secrets Manager.")
            raise HTTPException(status_code=500, detail="Image safety service configuration error.")

        try:
            files = {'media': ('image', image_content)} # Correct format for httpx files
            
            # Use basic nudity model for chat images, add offensive/gore for profile images
            models = 'nudity-2.0'
            if include_offensive:
                models += ',offensive,gore'
                
            data = { # Use data instead of params for POST with files
                'api_user': api_user,
                'api_secret': api_secret,
                'models': models
            }
            
            # Use httpx for async request
            async with httpx.AsyncClient() as client:
                response = await client.post(self.api_url, files=files, data=data)
                response.raise_for_status() # Raise exception for bad status codes
            result = response.json()
            
            response_data = {
                'nudity': result.get('nudity', {})
            }
            
            if include_offensive:
                response_data.update({
                    'offensive': result.get('offensive', {}),
                    'gore': result.get('gore', {})
                })
                
            return response_data
            
        except Exception as e:
            logger.error(f"Error in image safety check: {str(e)}")
            raise HTTPException(status_code=500, detail="Error checking image safety")

    async def check_profile_image(self, image_content: bytes) -> bool:
        results = await self._check_image(image_content, include_offensive=True)
        nudity = results['nudity']
        offensive = results.get('offensive', {})
        gore = results.get('gore', {})
        
        # Block if any explicit or suggestive content is detected
        should_block = (
            # Nudity checks
            nudity.get('sexual_activity', 0) > 0.3 or
            nudity.get('sexual_display', 0) > 0.3 or
            nudity.get('erotica', 0) > 0.4 or
            nudity.get('sextoy', 0) > 0.3 or
            nudity.get('suggestive', 0) > 0.6 or
            # Violence/Gore checks
            offensive.get('weapon', 0) > 0.5 or
            gore.get('gore', 0) > 0.3 or
            gore.get('blood', 0) > 0.4
        )
        
        return not should_block

    async def check_chat_image(self, image_content: bytes) -> bool:
        """Less strict check for chat images, only checking nudity"""
        results = await self._check_image(image_content, include_offensive=False)
        nudity = results['nudity']
        
        # Block only explicit sexual content
        should_block = (
            nudity.get('sexual_activity', 0) > 0.7 or
            nudity.get('sexual_display', 0) > 0.8 or
            nudity.get('erotica', 0) > 0.8
        )
        
        return not should_block
