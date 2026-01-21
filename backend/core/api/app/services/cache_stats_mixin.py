import logging
from typing import Dict, Optional
from datetime import date

logger = logging.getLogger(__name__)

class CacheStatsMixin:
    """
    Mixin for CacheService to handle server-wide statistics counters in Redis.
    """
    
    def _get_daily_stats_key(self, date_str: Optional[str] = None) -> str:
        if not date_str:
            date_str = date.today().isoformat()
        return f"stats:global:daily:{date_str}"

    @property
    def liability_key(self) -> str:
        return "stats:global:liability_total"

    @property
    def total_users_key(self) -> str:
        return "stats:global:total_users"

    @property
    def active_subscriptions_key(self) -> str:
        return "stats:global:active_subscriptions"

    async def increment_stat(self, field: str, amount: int = 1, date_str: Optional[str] = None):
        """Increments a daily stat counter."""
        client = await self.client
        if not client:
            return
        
        key = self._get_daily_stats_key(date_str)
        try:
            await client.hincrby(key, field, amount)
            # Set expiry to 48 hours to ensure it lasts through the next day's flush
            await client.expire(key, 172800) 
        except Exception as e:
            logger.error(f"Error incrementing stat {field}: {e}")

    async def update_liability(self, delta: int):
        """Updates the running total of user liability (credits)."""
        client = await self.client
        if not client:
            return
        
        try:
            await client.incrby(self.liability_key, delta)
        except Exception as e:
            logger.error(f"Error updating liability: {e}")

    async def update_total_regular_users(self, delta: int):
        """Updates the running total of regular users."""
        client = await self.client
        if not client:
            return
        try:
            await client.incrby(self.total_users_key, delta)
        except Exception as e:
            logger.error(f"Error updating total regular users: {e}")

    async def update_active_subscriptions(self, delta: int):
        """Updates the running total of active subscriptions."""
        client = await self.client
        if not client:
            return
        try:
            await client.incrby(self.active_subscriptions_key, delta)
        except Exception as e:
            logger.error(f"Error updating active subscriptions: {e}")

    async def get_daily_stats(self, date_str: Optional[str] = None) -> Dict[str, int]:
        """Returns all stats for a specific day."""
        client = await self.client
        if not client:
            return {}
        
        key = self._get_daily_stats_key(date_str)
        try:
            data = await client.hgetall(key)
            return {k.decode(): int(v.decode()) for k, v in data.items()}
        except Exception as e:
            logger.error(f"Error getting daily stats: {e}")
            return {}

    async def get_total_liability(self) -> int:
        """Returns the current cached liability."""
        client = await self.client
        if not client:
            return 0
        
        try:
            val = await client.get(self.liability_key)
            return int(val.decode()) if val else 0
        except Exception as e:
            logger.error(f"Error getting liability: {e}")
            return 0

    async def set_total_liability(self, amount: int):
        """Force sets the liability (used during initialization)."""
        client = await self.client
        if not client:
            return
        
        try:
            await client.set(self.liability_key, amount)
        except Exception as e:
            logger.error(f"Error setting liability: {e}")

    async def get_total_regular_users(self) -> int:
        """Returns the current cached total regular users."""
        client = await self.client
        if not client:
            return 0
        try:
            val = await client.get(self.total_users_key)
            return int(val.decode()) if val else 0
        except Exception as e:
            logger.error(f"Error getting total regular users: {e}")
            return 0

    async def set_total_regular_users(self, amount: int):
        """Force sets the total regular users (used during initialization)."""
        client = await self.client
        if not client:
            return
        try:
            await client.set(self.total_users_key, amount)
        except Exception as e:
            logger.error(f"Error setting total regular users: {e}")

    async def get_active_subscriptions(self) -> int:
        """Returns the current cached active subscriptions."""
        client = await self.client
        if not client:
            return 0
        try:
            val = await client.get(self.active_subscriptions_key)
            return int(val.decode()) if val else 0
        except Exception as e:
            logger.error(f"Error getting active subscriptions: {e}")
            return 0

    async def set_active_subscriptions(self, amount: int):
        """Force sets the active subscriptions (used during initialization)."""
        client = await self.client
        if not client:
            return
        try:
            await client.set(self.active_subscriptions_key, amount)
        except Exception as e:
            logger.error(f"Error setting active subscriptions: {e}")
