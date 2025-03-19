import logging
import time
import asyncio
from datetime import datetime, timedelta
from app.services.directus import DirectusService
from app.services.metrics import MetricsService
from app.services.cache import CacheService

logger = logging.getLogger(__name__)

async def update_active_users_metrics():
    """
    Calculate and update active user metrics based on login data.
    This should be called periodically (e.g., every 5 minutes).
    """
    try:
        from main import directus_service, metrics_service, cache_service
        
        logger.info("Updating active users metrics")
        
        # 1. Get count of all users (total registered)
        total_users = await get_total_users(directus_service)
        
        # 2. Calculate daily active users (users who logged in today)
        daily_active = await get_daily_active_users(directus_service)
        
        # 3. Calculate monthly active users (users who logged in this month)
        monthly_active = await get_monthly_active_users(directus_service)
        
        # 4. Update metrics - don't subtract admin here, we'll do it in Grafana
        metrics_service.update_active_users(daily_active, monthly_active)
        
        logger.info(f"Updated metrics: total_users={total_users}, daily_active={daily_active}, monthly_active={monthly_active}")
        
    except Exception as e:
        logger.error(f"Error updating active users metrics: {str(e)}", exc_info=True)

async def get_total_users(directus_service: DirectusService) -> int:
    """Get the total count of registered users"""
    try:
        total = await directus_service.get_total_users_count()
        return total
    except Exception as e:
        logger.error(f"Error getting total users: {str(e)}", exc_info=True)
        return 0

async def get_daily_active_users(directus_service: DirectusService) -> int:
    """Get the count of users who have logged in today"""
    try:
        # Get users who have logged in since midnight today
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        today_timestamp = int(today.timestamp())
        
        count = await directus_service.get_active_users_since(today_timestamp)
        return count
    except Exception as e:
        logger.error(f"Error getting daily active users: {str(e)}", exc_info=True)
        return 0

async def get_monthly_active_users(directus_service: DirectusService) -> int:
    """Get the count of users who have logged in this month"""
    try:
        # Get users who have logged in since the 1st of the current month
        today = datetime.now()
        month_start = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        month_start_timestamp = int(month_start.timestamp())
        
        count = await directus_service.get_active_users_since(month_start_timestamp)
        return count
    except Exception as e:
        logger.error(f"Error getting monthly active users: {str(e)}", exc_info=True)
        return 0

async def periodic_metrics_update():
    """Run a periodic task to update user metrics more frequently"""
    while True:
        await update_active_users_metrics()
        # Wait 15 seconds before updating again (instead of 60)
        await asyncio.sleep(15)
