"""
Celery tasks for archiving old usage entries.

This module contains tasks that run periodically to archive usage entries
older than 3 months to S3, keeping the Directus database lean and performant.
"""

import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any

from backend.core.api.app.tasks.celery_config import app
from backend.core.api.app.tasks.base_task import BaseServiceTask
from backend.core.api.app.services.usage_archive_service import UsageArchiveService

logger = logging.getLogger(__name__)


@app.task(name="usage.archive_old_entries", base=BaseServiceTask, bind=True)
async def archive_old_usage_entries(self):
    """
    Monthly Celery task to archive usage entries older than 3 months.
    
    This task:
    1. Calculates the cutoff month (3 months ago)
    2. Finds all users with usage entries in that month
    3. For each user, archives their usage entries for that month
    4. Updates summary records to mark them as archived
    5. Deletes archived entries from Directus
    
    Runs on the 1st of each month at 2 AM UTC.
    """
    log_prefix = "UsageArchiveTask:"
    logger.info(f"{log_prefix} Starting archive task for old usage entries")
    
    try:
        # Initialize services via BaseServiceTask
        await self.initialize_services()
        
        # Initialize archive service
        archive_service = UsageArchiveService(
            s3_service=self._s3_service,
            encryption_service=self._encryption_service,
            directus_service=self._directus_service
        )
        
        # Calculate cutoff month (3 months ago)
        cutoff_date = datetime.now() - timedelta(days=90)  # Approximately 3 months
        cutoff_year_month = cutoff_date.strftime("%Y-%m")
        cutoff_timestamp = int(cutoff_date.timestamp())
        
        logger.info(f"{log_prefix} Archiving usage entries older than {cutoff_year_month} (timestamp: {cutoff_timestamp})")
        
        # Find all unique users with usage entries in the cutoff month
        # We need to find entries from the cutoff month specifically
        year, month = map(int, cutoff_year_month.split("-"))
        start_date = datetime(year, month, 1)
        if month == 12:
            end_date = datetime(year + 1, 1, 1)
        else:
            end_date = datetime(year, month + 1, 1)
        
        start_timestamp = int(start_date.timestamp())
        end_timestamp = int(end_date.timestamp())
        
        # Query for all usage entries in the cutoff month
        params = {
            "filter": {
                "created_at": {
                    "_gte": start_timestamp,
                    "_lt": end_timestamp
                }
            },
            "fields": "id,user_id_hash",
            "limit": -1  # Fetch all to get unique users
        }
        
        entries = await self._directus_service.sdk.get_items("usage", params=params, no_cache=True)
        
        if not entries:
            logger.info(f"{log_prefix} No usage entries found for month {cutoff_year_month}")
            return {"success": True, "archived_users": 0, "message": "No entries to archive"}
        
        # Get unique user_id_hashes
        unique_users = set(entry.get("user_id_hash") for entry in entries if entry.get("user_id_hash"))
        
        logger.info(f"{log_prefix} Found {len(unique_users)} users with usage entries in {cutoff_year_month}")
        
        # Archive entries for each user
        archived_count = 0
        failed_count = 0
        errors = []
        
        for user_id_hash in unique_users:
            try:
                # Get user's vault_key_id for encryption
                # We need to find the user_id from user_id_hash to get vault_key_id
                # Query user profiles to find matching user
                user_profiles = await self._directus_service.sdk.get_items(
                    "user_profiles",
                    params={
                        "filter": {},
                        "fields": "id,vault_key_id",
                        "limit": -1
                    },
                    no_cache=True
                )
                
                # Find user with matching user_id_hash
                # We need to hash each user_id and compare
                import hashlib
                user_vault_key_id = None
                for profile in user_profiles:
                    user_id = profile.get("id")
                    if user_id:
                        hashed = hashlib.sha256(user_id.encode()).hexdigest()
                        if hashed == user_id_hash:
                            user_vault_key_id = profile.get("vault_key_id")
                            break
                
                if not user_vault_key_id:
                    logger.warning(f"{log_prefix} Could not find vault_key_id for user_id_hash {user_id_hash}")
                    failed_count += 1
                    errors.append(f"User {user_id_hash}: vault_key_id not found")
                    continue
                
                # Archive this user's entries for the month
                s3_key = await archive_service.archive_user_month_usage(
                    user_id_hash=user_id_hash,
                    year_month=cutoff_year_month,
                    user_vault_key_id=user_vault_key_id
                )
                
                if s3_key:
                    archived_count += 1
                    logger.info(f"{log_prefix} Successfully archived usage for user {user_id_hash}, month {cutoff_year_month}")
                else:
                    failed_count += 1
                    errors.append(f"User {user_id_hash}: Archive failed")
                    logger.error(f"{log_prefix} Failed to archive usage for user {user_id_hash}, month {cutoff_year_month}")
                    
            except Exception as e:
                failed_count += 1
                error_msg = f"User {user_id_hash}: {str(e)}"
                errors.append(error_msg)
                logger.error(f"{log_prefix} Error archiving usage for user {user_id_hash}: {e}", exc_info=True)
        
        result = {
            "success": True,
            "archived_users": archived_count,
            "failed_users": failed_count,
            "cutoff_month": cutoff_year_month,
            "errors": errors[:10]  # Limit errors to first 10
        }
        
        logger.info(f"{log_prefix} Archive task completed: {archived_count} users archived, {failed_count} failed")
        return result
        
    except Exception as e:
        logger.error(f"{log_prefix} Archive task failed: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e)
        }
