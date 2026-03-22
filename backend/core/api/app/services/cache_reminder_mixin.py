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
# Pending delivery: stores fired reminders waiting for client WebSocket delivery
# LIST per user: each entry is a JSON-encoded reminder delivery payload
PENDING_DELIVERY_KEY_PREFIX = "reminder_pending_delivery:"  # Per-user pending delivery list

# TTL for individual reminder entries (7 days - reminders older than this without firing are stale)
REMINDER_TTL = 604800  # 7 days in seconds

# TTL for pending delivery entries (60 days). If a user doesn't come online within 60 days,
# entries are cleaned up by the periodic cleanup task (with logging).
# Email notifications serve as reminders that undelivered messages exist.
PENDING_DELIVERY_TTL = 5184000  # 60 days in seconds

# Path for persisting pending deliveries during shutdown
PENDING_DELIVERY_BACKUP_PATH = "/shared/cache/pending_deliveries_backup.json"

# Pending embed encryption tracking constants
# Tracks embeds finalized on server but not yet confirmed as client-encrypted via store_embed
PENDING_EMBED_KEY_PREFIX = "pending_embed_encryption:"
PENDING_EMBED_TTL = 2592000  # 30 days (seconds)
EMBED_CACHE_EXTENDED_TTL = 2592000  # 30 days for embeds in the pending set


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

    # =========================================================================
    # PENDING DELIVERY METHODS
    # 
    # When a reminder fires but the user has no active WebSocket connections,
    # the reminder delivery payload is queued here. When the user reconnects,
    # the WebSocket endpoint delivers these pending reminders to the client.
    # The client then encrypts with the chat key and persists normally.
    #
    # Architecture:
    # - LIST `reminder_pending_delivery:{user_id}` - FIFO queue of delivery payloads
    # - Each entry is a JSON-encoded dict with the same fields as the
    #   reminder_fired WebSocket event payload (content in plaintext)
    # - TTL of 48h per key - after that, email notification is the fallback
    # =========================================================================

    async def add_pending_reminder_delivery(
        self, user_id: str, delivery_payload: Dict[str, Any]
    ) -> bool:
        """
        Queue a fired reminder for delivery when the user comes back online.
        
        Args:
            user_id: The user ID (UUID, not hashed)
            delivery_payload: The reminder_fired payload dict (plaintext content)
            
        Returns:
            True if queued successfully
        """
        try:
            if not user_id or not delivery_payload:
                return False

            client = await self.client
            if not client:
                logger.error("Cannot queue pending reminder delivery: cache client not available")
                return False

            key = f"{PENDING_DELIVERY_KEY_PREFIX}{user_id}"
            payload_json = json.dumps(delivery_payload)

            # Push to list and set/refresh TTL
            async with client.pipeline(transaction=True) as pipe:
                pipe.rpush(key, payload_json)
                pipe.expire(key, PENDING_DELIVERY_TTL)
                await pipe.execute()

            logger.info(
                f"Queued pending reminder delivery for user {user_id[:8]}... "
                f"(reminder_id={delivery_payload.get('reminder_id')})"
            )
            return True

        except Exception as e:
            logger.error(f"Error queuing pending reminder delivery: {e}", exc_info=True)
            return False

    async def get_and_clear_pending_reminder_deliveries(
        self, user_id: str
    ) -> List[Dict[str, Any]]:
        """
        Atomically retrieve and remove all pending reminder deliveries for a user.
        Called when the user reconnects via WebSocket.
        
        Args:
            user_id: The user ID (UUID, not hashed)
            
        Returns:
            List of delivery payload dicts (may be empty)
        """
        try:
            if not user_id:
                return []

            client = await self.client
            if not client:
                return []

            key = f"{PENDING_DELIVERY_KEY_PREFIX}{user_id}"

            # Atomically get all entries and delete the key
            async with client.pipeline(transaction=True) as pipe:
                pipe.lrange(key, 0, -1)
                pipe.delete(key)
                results = await pipe.execute()

            raw_entries = results[0] if results else []
            if not raw_entries:
                return []

            deliveries = []
            for entry in raw_entries:
                if isinstance(entry, bytes):
                    entry = entry.decode("utf-8")
                try:
                    deliveries.append(json.loads(entry))
                except json.JSONDecodeError:
                    logger.warning(f"Skipping malformed pending delivery entry for user {user_id[:8]}...")

            if deliveries:
                logger.info(
                    f"Retrieved {len(deliveries)} pending reminder deliveries for user {user_id[:8]}..."
                )
            return deliveries

        except Exception as e:
            logger.error(f"Error retrieving pending reminder deliveries: {e}", exc_info=True)
            return []

    async def has_pending_reminder_deliveries(self, user_id: str) -> bool:
        """
        Check if a user has any pending reminder deliveries without consuming them.
        
        Args:
            user_id: The user ID (UUID, not hashed)
            
        Returns:
            True if there are pending deliveries
        """
        try:
            if not user_id:
                return False

            client = await self.client
            if not client:
                return False

            key = f"{PENDING_DELIVERY_KEY_PREFIX}{user_id}"
            count = await client.llen(key)
            return count > 0

        except Exception as e:
            logger.error(f"Error checking pending reminder deliveries: {e}", exc_info=True)
            return False

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

    # =========================================================================
    # PENDING DELIVERY DISK BACKUP / RESTORE
    # 
    # On graceful shutdown, pending deliveries are written to disk so they
    # survive cache restarts. On startup, they are restored and the disk
    # file is deleted. Same pattern as reminder backup.
    # =========================================================================

    async def dump_pending_deliveries_to_disk(self) -> int:
        """
        Dump all pending delivery lists to disk for persistence across restarts.
        Called during graceful shutdown alongside dump_reminders_to_disk.
        
        Returns:
            Number of delivery entries saved to disk
        """
        try:
            client = await self.client
            if not client:
                logger.warning("Cannot dump pending deliveries: cache client not connected")
                return 0

            # Scan for all pending delivery keys
            all_keys = []
            async for key in client.scan_iter(match=f"{PENDING_DELIVERY_KEY_PREFIX}*"):
                if isinstance(key, bytes):
                    key = key.decode("utf-8")
                all_keys.append(key)

            if not all_keys:
                logger.debug("No pending deliveries to dump to disk")
                if os.path.exists(PENDING_DELIVERY_BACKUP_PATH):
                    os.remove(PENDING_DELIVERY_BACKUP_PATH)
                return 0

            all_deliveries = {}
            total_count = 0
            for key in all_keys:
                user_id = key.replace(PENDING_DELIVERY_KEY_PREFIX, "")
                entries = await client.lrange(key, 0, -1)
                parsed = []
                for entry in entries:
                    if isinstance(entry, bytes):
                        entry = entry.decode("utf-8")
                    try:
                        parsed.append(json.loads(entry))
                    except json.JSONDecodeError:
                        continue
                if parsed:
                    all_deliveries[user_id] = parsed
                    total_count += len(parsed)

            if not all_deliveries:
                logger.debug("No valid pending deliveries to dump")
                if os.path.exists(PENDING_DELIVERY_BACKUP_PATH):
                    os.remove(PENDING_DELIVERY_BACKUP_PATH)
                return 0

            backup_dir = os.path.dirname(PENDING_DELIVERY_BACKUP_PATH)
            os.makedirs(backup_dir, exist_ok=True)

            backup_data = {
                "timestamp": int(time.time()),
                "version": 1,
                "deliveries_by_user": all_deliveries
            }

            with open(PENDING_DELIVERY_BACKUP_PATH, 'w') as f:
                json.dump(backup_data, f, indent=2)

            logger.info(
                f"Dumped {total_count} pending delivery entries for "
                f"{len(all_deliveries)} users to disk"
            )
            return total_count

        except Exception as e:
            logger.error(f"Error dumping pending deliveries to disk: {e}", exc_info=True)
            return 0

    async def restore_pending_deliveries_from_disk(self) -> int:
        """
        Restore pending deliveries from disk backup into cache.
        Called during startup alongside restore_reminders_from_disk.
        
        Returns:
            Number of delivery entries restored
        """
        try:
            if not os.path.exists(PENDING_DELIVERY_BACKUP_PATH):
                logger.info("No pending deliveries backup found at startup")
                return 0

            with open(PENDING_DELIVERY_BACKUP_PATH, 'r') as f:
                backup_data = json.load(f)

            timestamp = backup_data.get("timestamp", 0)
            deliveries_by_user = backup_data.get("deliveries_by_user", {})

            if not deliveries_by_user:
                logger.info("Pending deliveries backup is empty")
                os.remove(PENDING_DELIVERY_BACKUP_PATH)
                return 0

            # Check backup age - don't restore entries older than 60 days
            current_time = int(time.time())
            backup_age_seconds = current_time - timestamp
            if backup_age_seconds > PENDING_DELIVERY_TTL:
                logger.warning(
                    f"Pending deliveries backup is {backup_age_seconds / 86400:.1f} days old "
                    f"(>60 days) - discarding stale backup"
                )
                os.remove(PENDING_DELIVERY_BACKUP_PATH)
                return 0

            restored_count = 0
            client = await self.client
            if not client:
                logger.error("Cannot restore pending deliveries: cache client not connected")
                return 0

            for user_id, entries in deliveries_by_user.items():
                key = f"{PENDING_DELIVERY_KEY_PREFIX}{user_id}"
                for entry in entries:
                    try:
                        await client.rpush(key, json.dumps(entry))
                        restored_count += 1
                    except Exception as e:
                        logger.warning(f"Failed to restore delivery entry for user {user_id[:8]}...: {e}")
                # Set TTL on the list
                await client.expire(key, PENDING_DELIVERY_TTL)

            # Clean up backup file
            os.remove(PENDING_DELIVERY_BACKUP_PATH)
            logger.info(
                f"Restored {restored_count} pending delivery entries for "
                f"{len(deliveries_by_user)} users from disk"
            )
            return restored_count

        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in pending deliveries backup: {e}")
            if os.path.exists(PENDING_DELIVERY_BACKUP_PATH):
                os.remove(PENDING_DELIVERY_BACKUP_PATH)
            return 0
        except Exception as e:
            logger.error(f"Error restoring pending deliveries: {e}", exc_info=True)
            return 0

    async def cleanup_expired_pending_deliveries(self) -> int:
        """
        Clean up expired pending delivery entries and log the event.
        Called periodically by a Celery beat task.
        
        Since Redis handles TTL-based expiry automatically, this method
        primarily serves to log the cleanup events for audit purposes
        and send reminder emails to users who still have pending deliveries.
        
        Returns:
            Number of users with pending deliveries
        """
        try:
            client = await self.client
            if not client:
                return 0

            users_with_pending = 0
            async for key in client.scan_iter(match=f"{PENDING_DELIVERY_KEY_PREFIX}*"):
                if isinstance(key, bytes):
                    key = key.decode("utf-8")
                user_id = key.replace(PENDING_DELIVERY_KEY_PREFIX, "")
                count = await client.llen(key)
                ttl = await client.ttl(key)

                if count > 0:
                    users_with_pending += 1
                    days_remaining = ttl / 86400 if ttl > 0 else 0
                    logger.info(
                        f"[PENDING_DELIVERY_AUDIT] User {user_id[:8]}... has "
                        f"{count} pending deliveries, {days_remaining:.1f} days remaining"
                    )

            return users_with_pending

        except Exception as e:
            logger.error(f"Error auditing pending deliveries: {e}", exc_info=True)
            return 0

    # ===================================================================
    # PENDING EMBED ENCRYPTION TRACKING
    # ===================================================================
    # Tracks embeds that have been finalized on the server but not yet
    # confirmed as client-encrypted via store_embed. Uses a sorted set
    # (score = creation timestamp) for efficient age-based cleanup.
    #
    # Key: pending_embed_encryption:{user_id}
    # Members: embed_id strings
    # Score: Unix timestamp when the embed was finalized
    #
    # Lifecycle:
    # 1. Embed finalized → add_pending_embed()
    # 2. Client sends store_embed → remove_pending_embed()
    # 3. On reconnect → get_pending_embeds() → re-send to client
    # 4. Safety net task → get_all_users_with_pending_embeds() → re-send
    # ===================================================================

    async def add_pending_embed(self, user_id: str, embed_id: str) -> bool:
        """
        Track a finalized embed as pending client encryption.

        Adds the embed_id to a per-user sorted set with the current unix
        timestamp as score. Sets/refreshes the key TTL to 30 days.

        Args:
            user_id: User ID (UUID string)
            embed_id: Embed ID to track

        Returns:
            True if successfully added, False otherwise
        """
        try:
            client = await self.client
            if not client:
                logger.warning(f"Cannot add pending embed {embed_id}: cache client not available")
                return False

            key = f"{PENDING_EMBED_KEY_PREFIX}{user_id}"
            score = time.time()

            await client.zadd(key, {embed_id: score})
            await client.expire(key, PENDING_EMBED_TTL)

            logger.debug(
                f"[PENDING_EMBED] Added embed {embed_id} to pending set for "
                f"user {user_id[:8]}... (score={score:.0f})"
            )
            return True

        except Exception as e:
            logger.error(
                f"[PENDING_EMBED] Error adding embed {embed_id} to pending set "
                f"for user {user_id[:8]}...: {e}",
                exc_info=True
            )
            return False

    async def remove_pending_embed(self, user_id: str, embed_id: str) -> bool:
        """
        Remove an embed from the pending encryption tracking set.

        Called when the client confirms encryption via store_embed.
        Deletes the key entirely if the set becomes empty.

        Args:
            user_id: User ID (UUID string)
            embed_id: Embed ID to remove

        Returns:
            True if the embed was removed (was in the set), False otherwise
        """
        try:
            client = await self.client
            if not client:
                logger.warning(f"Cannot remove pending embed {embed_id}: cache client not available")
                return False

            key = f"{PENDING_EMBED_KEY_PREFIX}{user_id}"
            removed = await client.zrem(key, embed_id)

            if removed:
                # Check if the set is now empty and clean up the key
                remaining = await client.zcard(key)
                if remaining == 0:
                    await client.delete(key)

                logger.info(
                    f"[PENDING_EMBED] Removed embed {embed_id} from pending set for "
                    f"user {user_id[:8]}... (confirmed client encryption)"
                )
                return True
            else:
                logger.debug(
                    f"[PENDING_EMBED] Embed {embed_id} was not in pending set for "
                    f"user {user_id[:8]}... (already removed or never tracked)"
                )
                return False

        except Exception as e:
            logger.error(
                f"[PENDING_EMBED] Error removing embed {embed_id} from pending set "
                f"for user {user_id[:8]}...: {e}",
                exc_info=True
            )
            return False

    async def get_pending_embed_ids(self, user_id: str) -> List[str]:
        """
        Get all pending embed IDs for a user.

        Returns all members of the sorted set (embed_ids waiting for client encryption).

        Args:
            user_id: User ID (UUID string)

        Returns:
            List of embed_id strings, empty list if none or on error
        """
        try:
            client = await self.client
            if not client:
                return []

            key = f"{PENDING_EMBED_KEY_PREFIX}{user_id}"
            members = await client.zrange(key, 0, -1)

            return [
                m.decode("utf-8") if isinstance(m, bytes) else m
                for m in members
            ]

        except Exception as e:
            logger.error(
                f"[PENDING_EMBED] Error getting pending embeds for "
                f"user {user_id[:8]}...: {e}",
                exc_info=True
            )
            return []

    async def get_all_users_with_pending_embeds(self) -> List[str]:
        """
        Find all users who have pending embed encryptions.

        Uses SCAN to find all keys matching the pending embed prefix
        and extracts the user_id from each key.

        Returns:
            List of user_id strings
        """
        try:
            client = await self.client
            if not client:
                return []

            user_ids = []
            async for key in client.scan_iter(match=f"{PENDING_EMBED_KEY_PREFIX}*"):
                if isinstance(key, bytes):
                    key = key.decode("utf-8")
                user_id = key.replace(PENDING_EMBED_KEY_PREFIX, "")
                user_ids.append(user_id)

            return user_ids

        except Exception as e:
            logger.error(
                f"[PENDING_EMBED] Error scanning for users with pending embeds: {e}",
                exc_info=True
            )
            return []

    async def refresh_pending_embed_cache_ttls(self, user_id: str) -> int:
        """
        Refresh cache TTLs for all pending embeds of a user.

        Extends the TTL of each embed:{embed_id} cache key to 30 days
        to prevent cache entries from expiring while still pending
        client encryption.

        Args:
            user_id: User ID (UUID string)

        Returns:
            Number of cache entries whose TTL was refreshed
        """
        try:
            client = await self.client
            if not client:
                return 0

            pending_ids = await self.get_pending_embed_ids(user_id)
            if not pending_ids:
                return 0

            refreshed = 0
            for embed_id in pending_ids:
                try:
                    cache_key = f"embed:{embed_id}"
                    existing = await client.get(cache_key)
                    if existing:
                        await client.expire(cache_key, EMBED_CACHE_EXTENDED_TTL)
                        refreshed += 1
                    else:
                        logger.debug(
                            f"[PENDING_EMBED] Cache key {cache_key} not found "
                            f"(already expired?) for user {user_id[:8]}..."
                        )
                except Exception as e:
                    logger.warning(
                        f"[PENDING_EMBED] Error refreshing TTL for embed {embed_id}: {e}"
                    )

            if refreshed > 0:
                logger.debug(
                    f"[PENDING_EMBED] Refreshed {refreshed} cache TTLs for "
                    f"user {user_id[:8]}..."
                )
            return refreshed

        except Exception as e:
            logger.error(
                f"[PENDING_EMBED] Error refreshing cache TTLs for "
                f"user {user_id[:8]}...: {e}",
                exc_info=True
            )
            return 0

    async def cleanup_expired_pending_embeds(self, max_age_seconds: int = 2592000) -> int:
        """
        Remove stale entries from pending embed sets across all users.

        Finds entries older than max_age_seconds (default 30 days) and removes them.
        Deletes the sorted set key entirely if it becomes empty after cleanup.

        Args:
            max_age_seconds: Maximum age in seconds before an entry is considered expired.
                           Default: 2592000 (30 days).

        Returns:
            Total number of expired entries removed across all users
        """
        try:
            client = await self.client
            if not client:
                return 0

            cutoff = time.time() - max_age_seconds
            total_removed = 0

            user_ids = await self.get_all_users_with_pending_embeds()
            for user_id in user_ids:
                try:
                    key = f"{PENDING_EMBED_KEY_PREFIX}{user_id}"

                    # Find entries older than cutoff
                    expired = await client.zrangebyscore(key, "-inf", cutoff)
                    if expired:
                        removed = await client.zremrangebyscore(key, "-inf", cutoff)
                        total_removed += removed
                        logger.info(
                            f"[PENDING_EMBED] Cleaned up {removed} expired pending embed(s) "
                            f"for user {user_id[:8]}... (older than {max_age_seconds / 86400:.0f} days)"
                        )

                    # Delete the key if the set is now empty
                    remaining = await client.zcard(key)
                    if remaining == 0:
                        await client.delete(key)

                except Exception as e:
                    logger.warning(
                        f"[PENDING_EMBED] Error cleaning up pending embeds for "
                        f"user {user_id[:8]}...: {e}"
                    )

            if total_removed > 0:
                logger.info(
                    f"[PENDING_EMBED] Total cleanup: removed {total_removed} expired "
                    f"pending embed entries across {len(user_ids)} users"
                )

            return total_removed

        except Exception as e:
            logger.error(
                f"[PENDING_EMBED] Error in cleanup_expired_pending_embeds: {e}",
                exc_info=True
            )
            return 0
