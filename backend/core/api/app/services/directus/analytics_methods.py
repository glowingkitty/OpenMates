# backend/core/api/app/services/directus/analytics_methods.py
#
# This module contains the DirectusService methods for interacting with the
# 'app_analytics' collection in Directus.
#
# The app_analytics collection stores anonymous usage statistics for public analytics.
# No user data, no encryption needed - purely for aggregate statistics.

import logging
import time
import json
from typing import Dict, Any, Optional, List, TYPE_CHECKING

if TYPE_CHECKING:
    from backend.core.api.app.services.directus.directus import DirectusService

logger = logging.getLogger(__name__)

class AnalyticsMethods:
    """
    Methods for managing anonymous app analytics data.
    
    This collection is used for public statistics like "most used apps"
    and does not contain any user-specific or encrypted data.
    """
    def __init__(self, directus_service_instance: 'DirectusService'):
        self.directus_service = directus_service_instance
        self.collection = "app_analytics"

    async def create_analytics_entry(
        self,
        app_id: str,
        skill_id: str,
        model_used: Optional[str] = None,
        focus_mode_id: Optional[str] = None,
        settings_memory_type: Optional[str] = None,
        timestamp: Optional[int] = None
    ) -> Optional[str]:
        """
        Creates an anonymous analytics entry.
        
        No user data, no encryption needed - purely for aggregate statistics.
        This is called asynchronously (fire-and-forget) when usage is recorded.
        
        Args:
            app_id: App identifier (cleartext)
            skill_id: Skill identifier (cleartext)
            model_used: Optional model identifier (cleartext)
            focus_mode_id: Optional focus mode ID (cleartext)
            settings_memory_type: Optional settings/memory type (cleartext)
            timestamp: Unix timestamp (defaults to current time)
        
        Returns:
            Entry ID if successful, None otherwise
        """
        log_prefix = f"DirectusService ({self.collection}):"
        
        if timestamp is None:
            timestamp = int(time.time())
        
        payload = {
            "app_id": app_id,
            "skill_id": skill_id,
            "timestamp": timestamp,
        }
        
        # Add optional fields
        if model_used:
            payload["model_used"] = model_used
        if focus_mode_id:
            payload["focus_mode_id"] = focus_mode_id
        if settings_memory_type:
            payload["settings_memory_type"] = settings_memory_type
        
        try:
            success, response_data = await self.directus_service.create_item(self.collection, payload)
            
            if success and response_data and response_data.get("id"):
                entry_id = response_data["id"]
                logger.debug(f"{log_prefix} Successfully created analytics entry for app '{app_id}', skill '{skill_id}'")
                return entry_id
            else:
                logger.warning(f"{log_prefix} Failed to create analytics entry. Response: {response_data}")
                return None
        except Exception as e:
            # Don't log errors for analytics - it's fire-and-forget
            # We don't want analytics failures to affect usage recording
            logger.debug(f"{log_prefix} Error creating analytics entry (non-critical): {e}")
            return None

    async def get_most_used_apps_last_30_days(
        self,
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        """
        Get most used apps in the last 30 days from analytics collection.
        
        Fast query - no decryption needed since all data is cleartext.
        Aggregates by app_id and returns top N apps by usage count.
        
        Args:
            limit: Maximum number of apps to return (default 20)
        
        Returns:
            List of dicts with app_id and usage_count, sorted by count descending
        """
        log_prefix = f"DirectusService ({self.collection}):"
        
        try:
            # Calculate 30 days ago timestamp
            thirty_days_ago = int(time.time()) - (30 * 24 * 60 * 60)
            
            # Query Directus with filter for last 30 days
            # Only fetch app_id field to minimize data transfer
            params = {
                "filter": json.dumps({
                    "timestamp": {
                        "_gte": thirty_days_ago
                    }
                }),
                "fields": "app_id",
                "limit": -1  # Get all matching records
            }
            
            items = await self.directus_service.get_items(self.collection, params=params)
            
            if not items:
                logger.debug(f"{log_prefix} No analytics entries found in last 30 days")
                return []
            
            # Aggregate by app_id
            app_counts = {}
            for item in items:
                app_id = item.get("app_id")
                if app_id and isinstance(app_id, str) and len(app_id) > 0:
                    app_counts[app_id] = app_counts.get(app_id, 0) + 1
            
            if not app_counts:
                logger.debug(f"{log_prefix} No valid app_ids found in analytics entries")
                return []
            
            # Sort by count descending and return top N
            sorted_apps = sorted(
                app_counts.items(),
                key=lambda x: x[1],
                reverse=True
            )[:limit]
            
            result = [
                {"app_id": app_id, "usage_count": count}
                for app_id, count in sorted_apps
            ]
            
            logger.info(f"{log_prefix} Found {len(result)} most used apps in last 30 days")
            return result
            
        except Exception as e:
            logger.error(f"{log_prefix} Error getting most used apps: {e}", exc_info=True)
            return []

    async def get_server_stats_daily(self, date_str: str) -> Optional[Dict[str, Any]]:
        """Fetch daily stats for a specific date."""
        params = {
            "filter": {"date": {"_eq": date_str}},
            "limit": 1
        }
        items = await self.directus_service.get_items("server_stats_global_daily", params=params)
        return items[0] if items else None

    async def update_server_stats_daily(self, item_id: str, data: Dict[str, Any]) -> bool:
        """Update a daily stats record."""
        url = f"{self.directus_service.base_url}/items/server_stats_global_daily/{item_id}"
        resp = await self.directus_service._make_api_request("PATCH", url, json=data)
        return resp is not None and 200 <= resp.status_code < 300

    async def create_server_stats_daily(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Create a new daily stats record."""
        success, result = await self.directus_service.create_item("server_stats_global_daily", data)
        return result if success else None

    async def get_server_stats_monthly(self, year_month: str) -> Optional[Dict[str, Any]]:
        """Fetch monthly stats for a specific month."""
        params = {
            "filter": {"year_month": {"_eq": year_month}},
            "limit": 1
        }
        items = await self.directus_service.get_items("server_stats_global_monthly", params=params)
        return items[0] if items else None

    async def update_server_stats_monthly(self, item_id: str, data: Dict[str, Any]) -> bool:
        """Update a monthly stats record."""
        url = f"{self.directus_service.base_url}/items/server_stats_global_monthly/{item_id}"
        resp = await self.directus_service._make_api_request("PATCH", url, json=data)
        return resp is not None and 200 <= resp.status_code < 300

    async def create_server_stats_monthly(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Create a new monthly stats record."""
        success, result = await self.directus_service.create_item("server_stats_global_monthly", data)
        return result if success else None


