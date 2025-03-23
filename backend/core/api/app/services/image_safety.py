import requests
import logging
from fastapi import HTTPException
import os

logger = logging.getLogger(__name__)

class ImageSafetyService:
    def __init__(self):
        self.api_user = os.getenv('SIGHTENGINE_API_USER')
        self.api_secret = os.getenv('SIGHTENGINE_API_SECRET')
        self.api_url = 'https://api.sightengine.com/1.0/check.json'

    async def _check_image(self, image_content: bytes, include_offensive: bool = False):
        try:
            files = {'media': image_content}
            
            # Use basic nudity model for chat images, add offensive/gore for profile images
            models = 'nudity-2.0'
            if include_offensive:
                models += ',offensive,gore'
                
            params = {
                'api_user': self.api_user,
                'api_secret': self.api_secret,
                'models': models
            }
            
            response = requests.post(self.api_url, files=files, params=params)
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
