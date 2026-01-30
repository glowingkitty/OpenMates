# backend/core/api/app/services/directus/health_event_methods.py
# Methods for recording and querying health events for historical tracking.

import logging
import uuid
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)


class HealthEventMethods:
    """
    Methods for recording and querying health status change events.
    
    Health events are recorded when a service transitions between health states
    (e.g., healthy → unhealthy). This enables historical tracking and analysis
    of service availability and incident frequency.
    """
    
    def __init__(self, directus_service):
        """
        Initialize HealthEventMethods.
        
        Args:
            directus_service: The parent DirectusService instance
        """
        self.ds = directus_service
    
    async def record_health_event(
        self,
        service_type: str,
        service_id: str,
        previous_status: Optional[str],
        new_status: str,
        error_message: Optional[str] = None,
        response_time_ms: Optional[float] = None,
        duration_seconds: Optional[int] = None
    ) -> bool:
        """
        Record a health status change event.
        
        This should be called when a service's health status changes (e.g., healthy → unhealthy).
        Only status changes are recorded, not every health check - this keeps the event log efficient.
        
        Args:
            service_type: Type of service ('provider', 'app', 'external')
            service_id: Service identifier (e.g., 'openrouter', 'ai', 'stripe')
            previous_status: Previous status ('healthy', 'unhealthy', 'degraded') or None for first check
            new_status: New status ('healthy', 'unhealthy', 'degraded')
            error_message: Sanitized error message if new_status is unhealthy
            response_time_ms: Response time in milliseconds at time of status change
            duration_seconds: Duration of previous status in seconds (if known)
        
        Returns:
            True if event was recorded successfully, False otherwise
        """
        try:
            event_id = str(uuid.uuid4())
            created_at = datetime.now(timezone.utc).isoformat()
            
            payload = {
                "id": event_id,
                "service_type": service_type,
                "service_id": service_id,
                "previous_status": previous_status,
                "new_status": new_status,
                "error_message": error_message[:255] if error_message else None,  # Truncate to field length
                "response_time_ms": round(response_time_ms, 2) if response_time_ms else None,
                "duration_seconds": duration_seconds,
                "created_at": created_at
            }
            
            success, result = await self.ds.create_item("health_events", payload)
            
            if success:
                logger.info(
                    f"[HEALTH_EVENT] Recorded status change for {service_type}/{service_id}: "
                    f"{previous_status or 'initial'} → {new_status}"
                )
            else:
                logger.error(
                    f"[HEALTH_EVENT] Failed to record status change for {service_type}/{service_id}: {result}"
                )
            
            return success
            
        except Exception as e:
            logger.error(
                f"[HEALTH_EVENT] Error recording status change for {service_type}/{service_id}: {e}",
                exc_info=True
            )
            return False
    
    async def get_health_history(
        self,
        service_type: Optional[str] = None,
        service_id: Optional[str] = None,
        since_timestamp: Optional[int] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Get health event history, optionally filtered by service type/id and time range.
        
        Args:
            service_type: Filter by service type ('provider', 'app', 'external')
            service_id: Filter by service identifier
            since_timestamp: Only include events after this Unix timestamp
            limit: Maximum number of events to return (default 100, max 1000)
        
        Returns:
            List of health events, sorted by created_at descending (newest first)
        """
        try:
            # Build filter
            filters = []
            if service_type:
                filters.append(f'filter[service_type][_eq]={service_type}')
            if service_id:
                filters.append(f'filter[service_id][_eq]={service_id}')
            if since_timestamp:
                # Convert Unix timestamp to ISO format for Directus
                since_dt = datetime.fromtimestamp(since_timestamp, tz=timezone.utc)
                filters.append(f'filter[created_at][_gte]={since_dt.isoformat()}')
            
            # Clamp limit
            limit = min(max(1, limit), 1000)
            
            # Build query string
            query_parts = [
                f'limit={limit}',
                'sort=-created_at',  # Newest first
                'fields=id,service_type,service_id,previous_status,new_status,error_message,response_time_ms,duration_seconds,created_at'
            ]
            query_parts.extend(filters)
            query_string = '&'.join(query_parts)
            
            url = f"{self.ds.base_url}/items/health_events?{query_string}"
            
            response = await self.ds._make_api_request("GET", url)
            
            if response.status_code == 200:
                data = response.json()
                events = data.get("data", [])
                logger.debug(f"[HEALTH_EVENT] Retrieved {len(events)} health events")
                return events
            else:
                logger.error(f"[HEALTH_EVENT] Failed to get health history: {response.status_code}")
                return []
                
        except Exception as e:
            logger.error(f"[HEALTH_EVENT] Error getting health history: {e}", exc_info=True)
            return []
    
    async def get_incident_summary(
        self,
        since_timestamp: Optional[int] = None,
        service_type: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get a summary of incidents (unhealthy events) for all services.
        
        Args:
            since_timestamp: Only include events after this Unix timestamp
            service_type: Filter by service type ('provider', 'app', 'external')
        
        Returns:
            Dict with incident counts per service and overall statistics
        """
        try:
            # Get all events where new_status is unhealthy
            filters = ['filter[new_status][_eq]=unhealthy']
            if service_type:
                filters.append(f'filter[service_type][_eq]={service_type}')
            if since_timestamp:
                since_dt = datetime.fromtimestamp(since_timestamp, tz=timezone.utc)
                filters.append(f'filter[created_at][_gte]={since_dt.isoformat()}')
            
            query_parts = [
                'limit=1000',
                'sort=-created_at',
                'fields=service_type,service_id,created_at,duration_seconds'
            ]
            query_parts.extend(filters)
            query_string = '&'.join(query_parts)
            
            url = f"{self.ds.base_url}/items/health_events?{query_string}"
            
            response = await self.ds._make_api_request("GET", url)
            
            if response.status_code != 200:
                logger.error(f"[HEALTH_EVENT] Failed to get incident summary: {response.status_code}")
                return {"error": "Failed to retrieve data"}
            
            data = response.json()
            events = data.get("data", [])
            
            # Aggregate by service
            services: Dict[str, Dict[str, Any]] = {}
            total_incidents = 0
            total_downtime_seconds = 0
            
            for event in events:
                service_key = f"{event['service_type']}/{event['service_id']}"
                
                if service_key not in services:
                    services[service_key] = {
                        "service_type": event['service_type'],
                        "service_id": event['service_id'],
                        "incident_count": 0,
                        "total_downtime_seconds": 0,
                        "last_incident": None
                    }
                
                services[service_key]["incident_count"] += 1
                total_incidents += 1
                
                if event.get("duration_seconds"):
                    services[service_key]["total_downtime_seconds"] += event["duration_seconds"]
                    total_downtime_seconds += event["duration_seconds"]
                
                # Track last incident (events are sorted newest first)
                if services[service_key]["last_incident"] is None:
                    services[service_key]["last_incident"] = event["created_at"]
            
            return {
                "total_incidents": total_incidents,
                "total_downtime_seconds": total_downtime_seconds,
                "services": list(services.values()),
                "since_timestamp": since_timestamp
            }
            
        except Exception as e:
            logger.error(f"[HEALTH_EVENT] Error getting incident summary: {e}", exc_info=True)
            return {"error": str(e)}
    
    async def cleanup_old_events(self, retention_days: int = 90) -> int:
        """
        Delete health events older than the retention period.
        
        Args:
            retention_days: Number of days to retain events (default 90)
        
        Returns:
            Number of events deleted, or -1 on error
        """
        try:
            from datetime import timedelta
            
            cutoff_dt = datetime.now(timezone.utc) - timedelta(days=retention_days)
            cutoff_iso = cutoff_dt.isoformat()
            
            # First, get the IDs of events to delete
            url = f"{self.ds.base_url}/items/health_events?filter[created_at][_lt]={cutoff_iso}&limit=1000&fields=id"
            
            response = await self.ds._make_api_request("GET", url)
            
            if response.status_code != 200:
                logger.error(f"[HEALTH_EVENT] Failed to query old events for cleanup: {response.status_code}")
                return -1
            
            data = response.json()
            events = data.get("data", [])
            
            if not events:
                logger.info(f"[HEALTH_EVENT] No events older than {retention_days} days to clean up")
                return 0
            
            # Delete in batch
            event_ids = [event["id"] for event in events]
            success, result = await self.ds.delete_items("health_events", event_ids)
            
            if success:
                logger.info(f"[HEALTH_EVENT] Cleaned up {len(event_ids)} events older than {retention_days} days")
                return len(event_ids)
            else:
                logger.error(f"[HEALTH_EVENT] Failed to delete old events: {result}")
                return -1
                
        except Exception as e:
            logger.error(f"[HEALTH_EVENT] Error cleaning up old events: {e}", exc_info=True)
            return -1
