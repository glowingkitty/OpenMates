# backend/core/api/app/services/cache_reminder_mixin.py
# 
# This mixin provides cache operations for the Reminder app.
# Reminders are stored vault-encrypted in Dragonfly cache with a sorted set index
# for efficient polling of due reminders. On graceful shutdown, pending reminders
# are dumped to disk and restored on startup.
#
# Architecture:
# - ZSET `reminders:schedule` - sorted by trigger_at timestamp for efficient polling
# - HASH `reminder:{reminder_id}` - individual reminder data (vault-encrypted fields)
# - SET `user:{user_id}:reminders` - user's reminder IDs for listing
#
# Reference: docs/architecture/apps/reminder.md

import logging
import time
import json
import os
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

# Path for persisting reminders during shutdown (shared volume mounted across containers)
REMINDER_BACKUP_PATH = "/shared/cache/pending_reminders_backup.json"

# Cache key patterns
REMINDER_SCHEDULE_KEY = "reminders:schedule"  # ZSET: score=trigger_at, member=reminder_id
REMINDER_KEY_PREFIX = "reminder:"  # Individual reminder data
USER_REMINDERS_KEY_PREFIX = "user_reminders:"  # User's reminder IDs set

# TTL for individual reminder entries (7 days - reminders older than this without firing are stale)
REMINDER_TTL = 604800  # 7 days in seconds


class ReminderCacheMixin:
    """
    Mixin for reminder-specific caching methods.
    
    Provides storage, retrieval, and management of scheduled reminders in cache.
    Reminders use vault encryption for sensitive data (prompt, chat history).
    """

    async def create_reminder(self, reminder_data: Dict[str, Any]) -> bool:
        """
        Store a new reminder in cache and add to schedule index.
        
        Args:
            reminder_data: Complete reminder data dict including:
                - reminder_id: UUID string (required)
                - user_id: User ID string (required)
                - trigger_at: Unix timestamp when reminder should fire (required)
                - encrypted_prompt: Vault-encrypted prompt text (required)
                - Other fields as defined in reminder schema
        
        Returns:
            True if reminder was successfully created, False otherwise
        """
        try:
            reminder_id = reminder_data.get("reminder_id")
            user_id = reminder_data.get("user_id")
            trigger_at = reminder_data.get("trigger_at")

            if not reminder_id or not user_id or not trigger_at:
                logger.error("Cannot create reminder: missing reminder_id, user_id, or trigger_at")
                return False

            client = await self.client
            if not client:
                logger.error("Cannot create reminder: cache client not available")
                return False

            # Ensure status is set
            if "status" not in reminder_data:
                reminder_data["status"] = "pending"

            # Store the reminder data as JSON
            reminder_key = f"{REMINDER_KEY_PREFIX}{reminder_id}"
            reminder_json = json.dumps(reminder_data)

            # Use pipeline for atomic operations
            async with client.pipeline(transaction=True) as pipe:
                # Store reminder data with TTL
                pipe.setex(reminder_key, REMINDER_TTL, reminder_json)
                
                # Add to schedule sorted set (score = trigger_at for efficient range queries)
                pipe.zadd(REMINDER_SCHEDULE_KEY, {reminder_id: trigger_at})
                
                # Add to user's reminders set
                user_reminders_key = f"{USER_REMINDERS_KEY_PREFIX}{user_id}"
                pipe.sadd(user_reminders_key, reminder_id)
                
                await pipe.execute()

            logger.info(f"Created reminder {reminder_id} for user {user_id}, trigger_at={trigger_at}")
            return True

        except Exception as e:
            logger.error(f"Error creating reminder: {str(e)}", exc_info=True)
            return False

    async def get_reminder(self, reminder_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a single reminder by ID.
        
        Args:
            reminder_id: The reminder UUID
            
        Returns:
            Reminder data dict or None if not found
        """
        try:
            if not reminder_id:
                return None

            client = await self.client
            if not client:
                return None

            reminder_key = f"{REMINDER_KEY_PREFIX}{reminder_id}"
            reminder_json = await client.get(reminder_key)

            if not reminder_json:
                return None

            # Handle bytes from Redis
            if isinstance(reminder_json, bytes):
                reminder_json = reminder_json.decode("utf-8")

            return json.loads(reminder_json)

        except Exception as e:
            logger.error(f"Error getting reminder {reminder_id}: {str(e)}", exc_info=True)
            return None

    async def get_user_reminders(
        self, 
        user_id: str, 
        status_filter: Optional[str] = "pending"
    ) -> List[Dict[str, Any]]:
        """
        Get all reminders for a user, optionally filtered by status.
        
        Args:
            user_id: The user ID
            status_filter: Filter by status ("pending", "fired", "cancelled", or None for all)
            
        Returns:
            List of reminder data dicts
        """
        try:
            if not user_id:
                return []

            client = await self.client
            if not client:
                return []

            # Get user's reminder IDs
            user_reminders_key = f"{USER_REMINDERS_KEY_PREFIX}{user_id}"
            reminder_ids = await client.smembers(user_reminders_key)

            if not reminder_ids:
                return []

            # Fetch each reminder
            reminders = []
            for reminder_id in reminder_ids:
                # Handle bytes
                if isinstance(reminder_id, bytes):
                    reminder_id = reminder_id.decode("utf-8")

                reminder = await self.get_reminder(reminder_id)
                if reminder:
                    # Apply status filter if specified
                    if status_filter is None or reminder.get("status") == status_filter:
                        reminders.append(reminder)

            # Sort by trigger_at ascending
            reminders.sort(key=lambda r: r.get("trigger_at", 0))

            return reminders

        except Exception as e:
            logger.error(f"Error getting reminders for user {user_id}: {str(e)}", exc_info=True)
            return []

    async def get_due_reminders(self, current_time: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Get all reminders that are due (trigger_at <= current_time).
        
        This method is called by the scheduled task to find reminders to process.
        
        Args:
            current_time: Unix timestamp to check against (defaults to now)
            
        Returns:
            List of due reminder data dicts
        """
        try:
            client = await self.client
            if not client:
                return []

            if current_time is None:
                current_time = int(time.time())

            # Get all reminder IDs with trigger_at <= current_time
            # ZRANGEBYSCORE returns members with scores in the given range
            due_reminder_ids = await client.zrangebyscore(
                REMINDER_SCHEDULE_KEY,
                min=0,
                max=current_time
            )

            if not due_reminder_ids:
                return []

            # Fetch each reminder
            due_reminders = []
            for reminder_id in due_reminder_ids:
                # Handle bytes
                if isinstance(reminder_id, bytes):
                    reminder_id = reminder_id.decode("utf-8")

                reminder = await self.get_reminder(reminder_id)
                if reminder and reminder.get("status") == "pending":
                    due_reminders.append(reminder)

            logger.debug(f"Found {len(due_reminders)} due reminders at time {current_time}")
            return due_reminders

        except Exception as e:
            logger.error(f"Error getting due reminders: {str(e)}", exc_info=True)
            return []

    async def update_reminder_status(self, reminder_id: str, status: str) -> bool:
        """
        Update the status of a reminder.
        
        Args:
            reminder_id: The reminder UUID
            status: New status ("pending", "fired", "cancelled")
            
        Returns:
            True if update succeeded, False otherwise
        """
        try:
            if not reminder_id or not status:
                return False

            reminder = await self.get_reminder(reminder_id)
            if not reminder:
                logger.warning(f"Cannot update status: reminder {reminder_id} not found")
                return False

            reminder["status"] = status
            
            client = await self.client
            if not client:
                return False

            reminder_key = f"{REMINDER_KEY_PREFIX}{reminder_id}"
            reminder_json = json.dumps(reminder)
            
            # Get remaining TTL and preserve it
            ttl = await client.ttl(reminder_key)
            if ttl <= 0:
                ttl = REMINDER_TTL

            await client.setex(reminder_key, ttl, reminder_json)
            logger.debug(f"Updated reminder {reminder_id} status to {status}")
            return True

        except Exception as e:
            logger.error(f"Error updating reminder {reminder_id} status: {str(e)}", exc_info=True)
            return False

    async def reschedule_reminder(
        self, 
        reminder_id: str, 
        new_trigger_at: int,
        increment_occurrence: bool = True
    ) -> bool:
        """
        Reschedule a reminder to a new trigger time (for repeating reminders).
        
        Args:
            reminder_id: The reminder UUID
            new_trigger_at: New Unix timestamp for next trigger
            increment_occurrence: Whether to increment occurrence_count
            
        Returns:
            True if reschedule succeeded, False otherwise
        """
        try:
            if not reminder_id or not new_trigger_at:
                return False

            reminder = await self.get_reminder(reminder_id)
            if not reminder:
                logger.warning(f"Cannot reschedule: reminder {reminder_id} not found")
                return False

            client = await self.client
            if not client:
                return False

            # Update reminder data
            reminder["trigger_at"] = new_trigger_at
            reminder["status"] = "pending"
            
            if increment_occurrence:
                reminder["occurrence_count"] = reminder.get("occurrence_count", 0) + 1

            reminder_key = f"{REMINDER_KEY_PREFIX}{reminder_id}"
            reminder_json = json.dumps(reminder)

            # Use pipeline for atomic update
            async with client.pipeline(transaction=True) as pipe:
                # Update reminder data with fresh TTL
                pipe.setex(reminder_key, REMINDER_TTL, reminder_json)
                
                # Update score in schedule sorted set
                pipe.zadd(REMINDER_SCHEDULE_KEY, {reminder_id: new_trigger_at})
                
                await pipe.execute()

            logger.info(f"Rescheduled reminder {reminder_id} to trigger_at={new_trigger_at}")
            return True

        except Exception as e:
            logger.error(f"Error rescheduling reminder {reminder_id}: {str(e)}", exc_info=True)
            return False

    async def delete_reminder(self, reminder_id: str, user_id: Optional[str] = None) -> bool:
        """
        Delete a reminder from all indexes.
        
        Args:
            reminder_id: The reminder UUID
            user_id: Optional user_id (will be fetched from reminder if not provided)
            
        Returns:
            True if deletion succeeded, False otherwise
        """
        try:
            if not reminder_id:
                return False

            client = await self.client
            if not client:
                return False

            # Get user_id from reminder if not provided
            if not user_id:
                reminder = await self.get_reminder(reminder_id)
                if reminder:
                    user_id = reminder.get("user_id")

            reminder_key = f"{REMINDER_KEY_PREFIX}{reminder_id}"

            # Use pipeline for atomic deletion
            async with client.pipeline(transaction=True) as pipe:
                # Delete reminder data
                pipe.delete(reminder_key)
                
                # Remove from schedule sorted set
                pipe.zrem(REMINDER_SCHEDULE_KEY, reminder_id)
                
                # Remove from user's reminders set if we have user_id
                if user_id:
                    user_reminders_key = f"{USER_REMINDERS_KEY_PREFIX}{user_id}"
                    pipe.srem(user_reminders_key, reminder_id)
                
                await pipe.execute()

            logger.info(f"Deleted reminder {reminder_id}")
            return True

        except Exception as e:
            logger.error(f"Error deleting reminder {reminder_id}: {str(e)}", exc_info=True)
            return False

    async def dump_reminders_to_disk(self) -> int:
        """
        Dump all pending reminders to disk for persistence across restarts.
        Called during graceful shutdown to prevent reminder data loss.
        
        Returns:
            Number of reminders saved to disk
        """
        try:
            client = await self.client
            if not client:
                logger.warning("Cannot dump reminders to disk: cache client not connected")
                return 0

            # Get all reminder IDs from schedule
            all_reminder_ids = await client.zrange(REMINDER_SCHEDULE_KEY, 0, -1)

            if not all_reminder_ids:
                logger.info("No reminders in cache to dump to disk")
                # Clean up any existing backup file
                if os.path.exists(REMINDER_BACKUP_PATH):
                    os.remove(REMINDER_BACKUP_PATH)
                return 0

            # Collect pending reminders
            pending_reminders: List[Dict[str, Any]] = []

            for reminder_id in all_reminder_ids:
                # Handle bytes
                if isinstance(reminder_id, bytes):
                    reminder_id = reminder_id.decode("utf-8")

                reminder = await self.get_reminder(reminder_id)
                if reminder and reminder.get("status") == "pending":
                    pending_reminders.append(reminder)
                    logger.debug(f"Including reminder {reminder_id} for backup")

            if not pending_reminders:
                logger.info("No pending reminders to dump to disk")
                if os.path.exists(REMINDER_BACKUP_PATH):
                    os.remove(REMINDER_BACKUP_PATH)
                return 0

            # Ensure directory exists
            backup_dir = os.path.dirname(REMINDER_BACKUP_PATH)
            os.makedirs(backup_dir, exist_ok=True)

            # Write to disk with timestamp and version
            backup_data = {
                "timestamp": int(time.time()),
                "version": 1,
                "reminders": pending_reminders
            }

            with open(REMINDER_BACKUP_PATH, 'w') as f:
                json.dump(backup_data, f, indent=2)

            logger.info(f"Successfully dumped {len(pending_reminders)} pending reminders to disk at {REMINDER_BACKUP_PATH}")
            return len(pending_reminders)

        except Exception as e:
            logger.error(f"Error dumping reminders to disk: {str(e)}", exc_info=True)
            return 0

    async def restore_reminders_from_disk(self) -> int:
        """
        Restore reminders from disk backup into cache.
        Called during startup to recover reminders after restart.
        
        Returns:
            Number of reminders restored to cache
        """
        try:
            if not os.path.exists(REMINDER_BACKUP_PATH):
                logger.info("No reminder backup file found at startup - nothing to restore")
                return 0

            with open(REMINDER_BACKUP_PATH, 'r') as f:
                backup_data = json.load(f)

            timestamp = backup_data.get("timestamp", 0)
            version = backup_data.get("version", 1)
            reminders = backup_data.get("reminders", [])

            if not reminders:
                logger.info("Reminder backup file is empty - nothing to restore")
                os.remove(REMINDER_BACKUP_PATH)
                return 0

            # Check backup age - reminders older than 7 days are stale
            current_time = int(time.time())
            backup_age_seconds = current_time - timestamp
            backup_age_hours = backup_age_seconds / 3600

            if backup_age_seconds > REMINDER_TTL:
                logger.warning(f"Reminder backup is {backup_age_hours:.1f} hours old (>{REMINDER_TTL/3600}h) - skipping stale restore")
                os.remove(REMINDER_BACKUP_PATH)
                return 0

            logger.info(f"Restoring {len(reminders)} reminders from backup (backup age: {backup_age_hours:.1f} hours, version: {version})")

            restored_count = 0

            for reminder_data in reminders:
                reminder_id = reminder_data.get("reminder_id")
                trigger_at = reminder_data.get("trigger_at", 0)

                if not reminder_id:
                    logger.warning("Skipping malformed reminder in backup: missing reminder_id")
                    continue

                # Check if reminder already exists in cache
                existing = await self.get_reminder(reminder_id)
                if existing:
                    logger.debug(f"Reminder {reminder_id} already exists in cache - skipping restore")
                    continue

                # For reminders that were due during downtime, we still restore them
                # so they can be processed immediately
                if trigger_at < current_time:
                    logger.info(f"Reminder {reminder_id} was due during downtime (trigger_at={trigger_at}) - will process immediately")

                # Restore to cache
                success = await self.create_reminder(reminder_data)
                if success:
                    restored_count += 1
                    logger.debug(f"Restored reminder {reminder_id} to cache")
                else:
                    logger.error(f"Failed to restore reminder {reminder_id} to cache")

            # Clean up backup file after successful restore
            os.remove(REMINDER_BACKUP_PATH)
            logger.info(f"Successfully restored {restored_count}/{len(reminders)} reminders from disk backup")

            return restored_count

        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in reminder backup file: {str(e)}")
            if os.path.exists(REMINDER_BACKUP_PATH):
                os.remove(REMINDER_BACKUP_PATH)
            return 0
        except Exception as e:
            logger.error(f"Error restoring reminders from disk: {str(e)}", exc_info=True)
            return 0

    async def get_reminder_stats(self) -> Dict[str, int]:
        """
        Get statistics about reminders in cache (for monitoring/admin).
        
        Returns:
            Dict with counts: total, pending, due_now
        """
        try:
            client = await self.client
            if not client:
                return {"total": 0, "pending": 0, "due_now": 0}

            current_time = int(time.time())

            # Total reminders in schedule
            total = await client.zcard(REMINDER_SCHEDULE_KEY)

            # Due now (trigger_at <= current_time)
            due_now = await client.zcount(REMINDER_SCHEDULE_KEY, 0, current_time)

            # For pending count, we'd need to scan all - approximate with total for now
            # In production, we might want a separate counter or accept this approximation
            pending = total  # Approximation: assumes most are pending

            return {
                "total": total,
                "pending": pending,
                "due_now": due_now
            }

        except Exception as e:
            logger.error(f"Error getting reminder stats: {str(e)}", exc_info=True)
            return {"total": 0, "pending": 0, "due_now": 0}
