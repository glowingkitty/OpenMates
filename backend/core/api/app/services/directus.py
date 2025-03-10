import os
import httpx
from fastapi import Depends
from typing import Optional, Dict, Any

class DirectusService:
    def __init__(self):
        # Get configuration from environment variables
        self.cms_url = os.getenv("CMS_URL", "http://cms:8055")
        self.cms_token = os.getenv("CMS_TOKEN")
        
        if not self.cms_token:
            raise ValueError("CMS_TOKEN environment variable is not set")
            
    async def get_invite_code(self, code: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve an invite code from Directus CMS
        
        Args:
            code: The invite code to check
            
        Returns:
            Dictionary containing the invite code data if found, None otherwise
        """
        async with httpx.AsyncClient() as client:
            try:
                # Query the invite_codes collection with the given code
                response = await client.get(
                    f"{self.cms_url}/items/invite_codes",
                    params={
                        "filter[code][_eq]": code
                    },
                    headers={
                        "Authorization": f"Bearer {self.cms_token}"
                    }
                )
                
                response.raise_for_status()
                data = response.json()
                
                # Return the first item if any exist
                if data.get("data") and len(data["data"]) > 0:
                    return data["data"][0]
                    
                return None
                
            except httpx.HTTPError as e:
                print(f"Error connecting to CMS: {e}")
                return None
