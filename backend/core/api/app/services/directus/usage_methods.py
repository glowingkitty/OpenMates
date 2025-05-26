# backend/core/api/app/services/directus/usage_methods.py
# This module contains methods for interacting with the 'usage' collection in Directus.

import logging
from typing import Dict, Any, Optional
from httpx import AsyncClient, HTTPStatusError

logger = logging.getLogger(__name__)

USAGE_COLLECTION = "usage"

class UsageMethods:
    """
    Provides methods for creating and managing usage records in Directus.
    """
    def __init__(self, client: AsyncClient, base_url: str, static_token: str):
        self._client = client
        self._base_url = base_url
        self._static_token = static_token
        self._headers = {"Authorization": f"Bearer {self._static_token}"}

    async def create_usage_entry(self, usage_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Creates a new usage entry in the Directus 'usage' collection.

        Args:
            usage_data: A dictionary containing the data for the new usage entry.
                        Required fields depend on the 'usage' collection schema.
                        Example:
                        {
                            "user_id_hash": "some_hash",
                            "app_id": "ai",
                            "skill_id": "ask",
                            "timestamp": 1678886400, # Unix timestamp
                            "credits_charged": 5,
                            "model_used": "google/gemini-2.5-pro",
                            "input_tokens": 100,
                            "output_tokens": 200,
                            # ... other fields from usage.yml ...
                            # Ensure 'created_at' and 'updated_at' are also Unix timestamps if manually set,
                            # or let Directus handle them if its default behavior is preferred.
                            # The current usage.yml has created_at and updated_at as integer timestamps.
                        }
        
        Returns:
            A dictionary representing the created usage entry, or None if an error occurred.
        """
        url = f"{self._base_url}/items/{USAGE_COLLECTION}"
        try:
            response = await self._client.post(url, json=usage_data, headers=self._headers)
            response.raise_for_status()  # Raise an exception for HTTP 4xx/5xx errors
            created_entry = response.json().get("data")
            logger.info(f"Successfully created usage entry: {created_entry.get('id') if created_entry else 'N/A'}")
            return created_entry
        except HTTPStatusError as e:
            logger.error(f"HTTP error creating usage entry. Status: {e.response.status_code}, Response: {e.response.text}, Payload: {usage_data}")
            # Consider specific error handling or re-raising
            return None
        except Exception as e:
            logger.error(f"Unexpected error creating usage entry: {e}, Payload: {usage_data}", exc_info=True)
            return None