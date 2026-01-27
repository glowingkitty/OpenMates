import logging
from datetime import date
from typing import Dict, Any, Optional
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus import DirectusService

logger = logging.getLogger(__name__)

# Redis key patterns
STATS_DAILY_KEY_PREFIX = "stats:global:daily:" # e.g. stats:global:daily:2026-01-20
STATS_LIABILITY_KEY = "stats:global:total_liability"
STATS_TOTAL_USERS_KEY = "stats:global:total_regular_users"
STATS_ACTIVE_SUBS_KEY = "stats:global:active_subscriptions"

class ServerStatsService:
    """
    Service for tracking and persisting server-wide statistics.
    Follows an incremental update pattern: Hot cache (Redis) -> Periodic flush (Directus).
    """
    def __init__(self, cache_service: CacheService, directus_service: DirectusService):
        self.cache = cache_service
        self.directus = directus_service

    async def increment_stat(self, field: str, amount: int = 1, day: Optional[str] = None):
        """
        Increments a daily stat counter in Redis.
        Common fields: 'new_users_registered', 'new_users_finished_signup', 
        'income_eur_cents', 'credits_sold', 'credits_used', 'messages_sent', 
        'chats_created', 'embeds_created'.
        """
        if not day:
            day = date.today().isoformat()
        
        key = f"{STATS_DAILY_KEY_PREFIX}{day}"
        client = await self.cache.client
        if client:
            try:
                await client.hincrby(key, field, amount)
                # Ensure the hash has a TTL so it doesn't live forever in Redis
                # 2 days is enough since it will be flushed to Directus
                await client.expire(key, 172800) 
            except Exception as e:
                logger.error(f"Failed to increment stat {field} in Redis: {e}")

    async def update_liability(self, delta: int):
        """
        Updates the running total of user credit liability in Redis.
        delta: positive for purchases, negative for billing deductions.
        """
        client = await self.cache.client
        if client:
            try:
                await client.incrby(STATS_LIABILITY_KEY, delta)
            except Exception as e:
                logger.error(f"Failed to update liability in Redis: {e}")

    async def set_snapshot_stat(self, field: str, value: int):
        """
        Sets a snapshot stat (total users, active subs) in Redis.
        """
        client = await self.cache.client
        if client:
            try:
                key = f"stats:global:{field}" # e.g. stats:global:total_regular_users
                await client.set(key, value)
            except Exception as e:
                logger.error(f"Failed to set snapshot stat {field} in Redis: {e}")

    async def flush_to_directus(self, day: Optional[str] = None):
        """
        Flushes Redis counters for a specific day to the Directus daily model.
        Also aggregates into the monthly model.
        """
        if not day:
            day = date.today().isoformat()
        
        key = f"{STATS_DAILY_KEY_PREFIX}{day}"
        client = await self.cache.client
        if not client:
            return

        try:
            # 1. Get daily counters from Redis
            daily_data = await client.hgetall(key)
            if not daily_data:
                daily_data = {}
            
            # Convert bytes to int
            stats = {k.decode() if isinstance(k, bytes) else k: int(v) for k, v in daily_data.items()}
            
            # 2. Get snapshot values (Liability, Total Users, Subs)
            liability = await client.get(STATS_LIABILITY_KEY)
            total_users = await client.get(STATS_TOTAL_USERS_KEY)
            active_subs = await client.get(STATS_ACTIVE_SUBS_KEY)
            
            if liability:
                stats['liability_total'] = int(liability)
            if total_users:
                stats['total_regular_users'] = int(total_users)
            if active_subs:
                stats['active_subscriptions'] = int(active_subs)
            
            if not stats:
                logger.debug(f"No stats to flush for {day}")
                return

            # 3. Update Directus daily table
            await self._upsert_daily_stats(day, stats)
            
            # 4. Update Directus monthly table (aggregate)
            year_month = day[:7] # YYYY-MM
            await self._update_monthly_stats(year_month)
            
            logger.info(f"Successfully flushed server stats for {day} to Directus")
            
        except Exception as e:
            logger.error(f"Error flushing server stats to Directus: {e}", exc_info=True)

    async def _upsert_daily_stats(self, day: str, stats: Dict[str, Any]):
        """Upsert a record into server_stats_global_daily."""
        existing = await self.directus.get_items("server_stats_global_daily", params={
            "filter": {"date": {"_eq": day}},
            "limit": 1
        })
        
        if existing:
            await self.directus.update_item("server_stats_global_daily", existing[0]["id"], stats)
        else:
            stats["date"] = day
            await self.directus.create_item("server_stats_global_daily", stats)

    async def _update_monthly_stats(self, year_month: str):
        """Recalculate and update the monthly aggregate from daily records."""
        # 1. Sum all daily records for this month
        daily_records = await self.directus.get_items("server_stats_global_daily", params={
            "filter": {"date": {"_starts_with": year_month}},
            "limit": -1
        })
        
        if not daily_records:
            return

        monthly_totals = {
            "new_users_registered": 0,
            "new_users_finished_signup": 0,
            "income_eur_cents": 0,
            "credits_sold": 0,
            "credits_used": 0,
            "messages_sent": 0,
            "chats_created": 0,
            "embeds_created": 0
        }
        
        # Latest snapshots from the most recent day in the month
        latest_record = sorted(daily_records, key=lambda x: x["date"], reverse=True)[0]
        
        for record in daily_records:
            for field in monthly_totals.keys():
                monthly_totals[field] += record.get(field, 0)
        
        # Add snapshots from the latest day
        monthly_totals["liability_total"] = latest_record.get("liability_total")
        monthly_totals["active_subscriptions"] = latest_record.get("active_subscriptions")
        monthly_totals["total_regular_users"] = latest_record.get("total_regular_users")
        
        # 2. Upsert monthly record
        existing = await self.directus.get_items("server_stats_global_monthly", params={
            "filter": {"year_month": {"_eq": year_month}},
            "limit": 1
        })
        
        if existing:
            await self.directus.update_item("server_stats_global_monthly", existing[0]["id"], monthly_totals)
        else:
            monthly_totals["year_month"] = year_month
            await self.directus.create_item("server_stats_global_monthly", monthly_totals)
