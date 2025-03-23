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

    async def check_image_safety(self, image_content: bytes) -> bool:
        try:
            files = {'media': image_content}
            params = {
                'api_user': self.api_user,
                'api_secret': self.api_secret,
                'models': 'nudity-2.0,offensive,gore'
            }
            
            response = requests.post(self.api_url, files=files, params=params)
            result = response.json()
            
            # Log all results for analysis
            logger.info(f"Sightengine API response: {result}")
            
            # Extract relevant scores
            nudity = result.get('nudity', {})
            offensive = result.get('offensive', {})
            gore = result.get('gore', {})
            
            # Block only if explicit adult content or illegal content is detected
            should_block = (
                nudity.get('sexual_activity', 0) > 0.8 or  # Explicit sexual activity
                nudity.get('pornography', 0) > 0.8 or      # Pornographic content
                offensive.get('weapon', 0) > 0.8 or        # Weapons
                gore.get('gore', 0) > 0.8                  # Gore content
            )
            
            return not should_block
            
        except Exception as e:
            logger.error(f"Error in image safety check: {str(e)}")
            raise HTTPException(status_code=500, detail="Error checking image safety")
