"""
Usage Archive Service

This service handles archiving usage entries to S3 and retrieving them.
Archived data is encrypted with the user's vault key and compressed with gzip.
"""

import logging
import json
import gzip
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Tuple
from io import BytesIO

from backend.core.api.app.services.s3.service import S3UploadService
from backend.core.api.app.services.s3.config import get_bucket_name
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.services.directus.directus import DirectusService

logger = logging.getLogger(__name__)


class UsageArchiveService:
    """
    Service for archiving usage entries to S3 and retrieving them.
    
    Archives are stored as encrypted, gzip-compressed JSON files in S3.
    The archive format includes all usage entries for a user in a specific month.
    """
    
    def __init__(
        self,
        s3_service: S3UploadService,
        encryption_service: EncryptionService,
        directus_service: DirectusService
    ):
        self.s3_service = s3_service
        self.encryption_service = encryption_service
        self.directus_service = directus_service
        self.archive_bucket_key = "usage_archives"
    
    def _get_year_month_from_timestamp(self, timestamp: int) -> str:
        """
        Convert Unix timestamp to YYYY-MM format.
        
        Args:
            timestamp: Unix timestamp in seconds
            
        Returns:
            Year-month string in format "YYYY-MM"
        """
        dt = datetime.fromtimestamp(timestamp)
        return dt.strftime("%Y-%m")
    
    def _get_cutoff_timestamp(self, months_ago: int = 3) -> int:
        """
        Calculate the cutoff timestamp for archiving (N months ago).
        
        Args:
            months_ago: Number of months ago (default: 3)
            
        Returns:
            Unix timestamp in seconds
        """
        cutoff_date = datetime.now() - timedelta(days=months_ago * 30)
        return int(cutoff_date.timestamp())
    
    async def archive_user_month_usage(
        self,
        user_id_hash: str,
        year_month: str,
        user_vault_key_id: str
    ) -> Optional[str]:
        """
        Archives all usage entries for a user for a specific month to S3.
        
        This method:
        1. Fetches all usage entries for the user/month from Directus
        2. Creates archive JSON structure
        3. Compresses with gzip
        4. Encrypts with user's vault key
        5. Uploads to S3
        6. Updates summary records with is_archived=true and archive_s3_key
        7. Deletes entries from Directus usage collection (only after successful S3 upload)
        
        Args:
            user_id_hash: Hashed user identifier
            year_month: Month identifier in format "YYYY-MM"
            user_vault_key_id: User's vault key ID for encryption
            
        Returns:
            S3 key path if successful, None otherwise
        """
        log_prefix = f"UsageArchiveService:"
        logger.info(f"{log_prefix} Archiving usage entries for user '{user_id_hash}', month '{year_month}'")
        
        try:
            # 1. Parse year_month to get start and end timestamps
            year, month = map(int, year_month.split("-"))
            start_date = datetime(year, month, 1)
            if month == 12:
                end_date = datetime(year + 1, 1, 1)
            else:
                end_date = datetime(year, month + 1, 1)
            
            start_timestamp = int(start_date.timestamp())
            end_timestamp = int(end_date.timestamp())
            
            # 2. Fetch all usage entries for this user/month from Directus
            logger.info(f"{log_prefix} Fetching usage entries from Directus for user '{user_id_hash}', month '{year_month}'")
            params = {
                "filter": {
                    "user_id_hash": {"_eq": user_id_hash},
                    "created_at": {
                        "_gte": start_timestamp,
                        "_lt": end_timestamp
                    }
                },
                "fields": "*",
                "limit": -1  # Fetch all entries
            }
            
            entries = await self.directus_service.sdk.get_items("usage", params=params, no_cache=True)
            
            if not entries:
                logger.info(f"{log_prefix} No usage entries found for user '{user_id_hash}', month '{year_month}'")
                return None
            
            logger.info(f"{log_prefix} Found {len(entries)} usage entries to archive")
            
            # 3. Create archive JSON structure
            archive_data = {
                "user_id_hash": user_id_hash,
                "year_month": year_month,
                "archived_at": int(datetime.now().timestamp()),
                "entry_count": len(entries),
                "entries": entries
            }
            
            # 4. Serialize to JSON and compress with gzip
            json_str = json.dumps(archive_data, default=str)
            json_bytes = json_str.encode('utf-8')
            compressed_bytes = gzip.compress(json_bytes)
            
            logger.info(f"{log_prefix} Compressed archive: {len(json_bytes)} bytes -> {len(compressed_bytes)} bytes")
            
            # 5. Encrypt with user's vault key
            # Convert bytes to base64 string for encryption
            import base64
            compressed_b64 = base64.b64encode(compressed_bytes).decode('utf-8')
            encrypted_data, _ = await self.encryption_service.encrypt_with_user_key(
                compressed_b64,
                user_vault_key_id
            )
            
            # Convert encrypted string back to bytes for S3 upload
            encrypted_bytes = encrypted_data.encode('utf-8')
            
            logger.info(f"{log_prefix} Encrypted archive: {len(compressed_bytes)} bytes -> {len(encrypted_bytes)} bytes")
            
            # 6. Upload to S3
            s3_key = f"usage-archives/{user_id_hash}/{year_month}/usage.json.gz"
            bucket_name = get_bucket_name(self.archive_bucket_key)
            
            logger.info(f"{log_prefix} Uploading archive to S3: bucket={bucket_name}, key={s3_key}")
            await self.s3_service.upload_file(
                bucket_key=self.archive_bucket_key,
                file_key=s3_key,
                content=encrypted_bytes,
                content_type="application/gzip"
            )
            
            logger.info(f"{log_prefix} Successfully uploaded archive to S3: {s3_key}")
            
            # 7. Update summary records with is_archived=true and archive_s3_key
            # Update chat summaries
            await self._update_summaries_after_archive(
                user_id_hash=user_id_hash,
                year_month=year_month,
                archive_s3_key=s3_key,
                summary_type="chat"
            )
            
            # Update app summaries
            await self._update_summaries_after_archive(
                user_id_hash=user_id_hash,
                year_month=year_month,
                archive_s3_key=s3_key,
                summary_type="app"
            )
            
            # Update API key summaries
            await self._update_summaries_after_archive(
                user_id_hash=user_id_hash,
                year_month=year_month,
                archive_s3_key=s3_key,
                summary_type="api_key"
            )
            
            # 8. Delete entries from Directus usage collection
            # Only delete after successful S3 upload and summary updates
            logger.info(f"{log_prefix} Deleting {len(entries)} usage entries from Directus")
            for entry in entries:
                entry_id = entry.get("id")
                if entry_id:
                    try:
                        await self.directus_service.sdk.delete_item("usage", entry_id)
                    except Exception as e:
                        logger.error(f"{log_prefix} Failed to delete usage entry {entry_id}: {e}")
                        # Continue deleting other entries even if one fails
            
            logger.info(f"{log_prefix} Successfully archived usage entries for user '{user_id_hash}', month '{year_month}'")
            return s3_key
            
        except Exception as e:
            logger.error(f"{log_prefix} Error archiving usage entries for user '{user_id_hash}', month '{year_month}': {e}", exc_info=True)
            return None
    
    async def _update_summaries_after_archive(
        self,
        user_id_hash: str,
        year_month: str,
        archive_s3_key: str,
        summary_type: str
    ):
        """
        Update summary records after archiving to mark them as archived.
        
        Args:
            user_id_hash: Hashed user identifier
            year_month: Month identifier in format "YYYY-MM"
            archive_s3_key: S3 key path to archived data
            summary_type: Type of summary ("chat", "app", or "api_key")
        """
        log_prefix = f"UsageArchiveService:"
        collection_name = f"usage_monthly_{summary_type}_summaries"
        
        try:
            # Find all summary records for this user/month
            params = {
                "filter": {
                    "user_id_hash": {"_eq": user_id_hash},
                    "year_month": {"_eq": year_month}
                },
                "fields": "id",
                "limit": -1
            }
            
            summaries = await self.directus_service.sdk.get_items(collection_name, params=params, no_cache=True)
            
            if not summaries:
                logger.debug(f"{log_prefix} No {summary_type} summaries found to update for user '{user_id_hash}', month '{year_month}'")
                return
            
            # Update each summary record
            for summary in summaries:
                summary_id = summary.get("id")
                if summary_id:
                    try:
                        update_data = {
                            "is_archived": True,
                            "archive_s3_key": archive_s3_key
                        }
                        await self.directus_service.sdk.update_item(collection_name, summary_id, update_data)
                        logger.debug(f"{log_prefix} Updated {summary_type} summary {summary_id} with archive info")
                    except Exception as e:
                        logger.error(f"{log_prefix} Failed to update {summary_type} summary {summary_id}: {e}")
            
            logger.info(f"{log_prefix} Updated {len(summaries)} {summary_type} summaries for user '{user_id_hash}', month '{year_month}'")
            
        except Exception as e:
            logger.error(f"{log_prefix} Error updating {summary_type} summaries after archive: {e}", exc_info=True)
    
    async def retrieve_archived_usage(
        self,
        user_id_hash: str,
        year_month: str,
        user_vault_key_id: str,
        filters: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Retrieve and decrypt archived usage entries from S3.
        
        Args:
            user_id_hash: Hashed user identifier
            year_month: Month identifier in format "YYYY-MM"
            user_vault_key_id: User's vault key ID for decryption
            filters: Optional filters to apply (e.g., {"chat_id": "chat_123"})
            
        Returns:
            List of decrypted usage entries (filtered if filters provided)
        """
        log_prefix = f"UsageArchiveService:"
        logger.info(f"{log_prefix} Retrieving archived usage for user '{user_id_hash}', month '{year_month}'")
        
        try:
            # 1. Construct S3 key
            s3_key = f"usage-archives/{user_id_hash}/{year_month}/usage.json.gz"
            bucket_name = get_bucket_name(self.archive_bucket_key)
            
            # 2. Download from S3
            logger.info(f"{log_prefix} Downloading archive from S3: bucket={bucket_name}, key={s3_key}")
            encrypted_bytes = await self.s3_service.get_file(bucket_name, s3_key)
            
            if not encrypted_bytes:
                logger.warning(f"{log_prefix} Archive not found in S3: {s3_key}")
                return []
            
            # 3. Decrypt
            encrypted_str = encrypted_bytes.decode('utf-8')
            decrypted_b64 = await self.encryption_service.decrypt_with_user_key(
                encrypted_str,
                user_vault_key_id
            )
            
            if not decrypted_b64:
                logger.error(f"{log_prefix} Failed to decrypt archive")
                return []
            
            # 4. Decompress
            import base64
            compressed_bytes = base64.b64decode(decrypted_b64)
            json_bytes = gzip.decompress(compressed_bytes)
            json_str = json_bytes.decode('utf-8')
            
            # 5. Parse JSON
            archive_data = json.loads(json_str)
            entries = archive_data.get("entries", [])
            
            logger.info(f"{log_prefix} Retrieved {len(entries)} entries from archive")
            
            # 6. Apply filters if provided
            if filters:
                filtered_entries = []
                for entry in entries:
                    match = True
                    for key, value in filters.items():
                        if entry.get(key) != value:
                            match = False
                            break
                    if match:
                        filtered_entries.append(entry)
                entries = filtered_entries
                logger.info(f"{log_prefix} Filtered to {len(entries)} entries")
            
            # 7. Decrypt encrypted fields in entries (same as get_user_usage_entries)
            # Note: The entries from archive still have encrypted fields, so we need to decrypt them
            decrypted_entries = []
            for entry in entries:
                try:
                    decrypted_entry = {
                        "id": entry.get("id"),
                        "type": entry.get("type"),
                        "source": entry.get("source", "chat"),
                        "created_at": entry.get("created_at"),
                        "updated_at": entry.get("updated_at"),
                        "app_id": entry.get("app_id"),
                        "skill_id": entry.get("skill_id"),
                        "chat_id": entry.get("chat_id"),
                        "message_id": entry.get("message_id"),
                        "api_key_hash": entry.get("api_key_hash"),
                        "device_hash": entry.get("device_hash"),
                    }
                    
                    # Decrypt encrypted fields
                    encrypted_credits = entry.get("encrypted_credits_costs_total")
                    if encrypted_credits:
                        decrypted_credits = await self.encryption_service.decrypt_with_user_key(
                            encrypted_credits, user_vault_key_id
                        )
                        if decrypted_credits:
                            try:
                                decrypted_entry["credits"] = int(decrypted_credits)
                            except ValueError:
                                decrypted_entry["credits"] = 0
                        else:
                            decrypted_entry["credits"] = 0
                    else:
                        decrypted_entry["credits"] = 0
                    
                    encrypted_model = entry.get("encrypted_model_used")
                    if encrypted_model:
                        decrypted_model = await self.encryption_service.decrypt_with_user_key(
                            encrypted_model, user_vault_key_id
                        )
                        if decrypted_model:
                            decrypted_entry["model_used"] = decrypted_model
                    
                    encrypted_input_tokens = entry.get("encrypted_input_tokens")
                    if encrypted_input_tokens:
                        decrypted_input = await self.encryption_service.decrypt_with_user_key(
                            encrypted_input_tokens, user_vault_key_id
                        )
                        if decrypted_input:
                            try:
                                decrypted_entry["input_tokens"] = int(decrypted_input)
                            except ValueError:
                                pass
                    
                    encrypted_output_tokens = entry.get("encrypted_output_tokens")
                    if encrypted_output_tokens:
                        decrypted_output = await self.encryption_service.decrypt_with_user_key(
                            encrypted_output_tokens, user_vault_key_id
                        )
                        if decrypted_output:
                            try:
                                decrypted_entry["output_tokens"] = int(decrypted_output)
                            except ValueError:
                                pass
                    
                    decrypted_entries.append(decrypted_entry)
                    
                except Exception as e:
                    logger.error(f"{log_prefix} Error decrypting archived entry {entry.get('id')}: {e}")
                    continue
            
            logger.info(f"{log_prefix} Successfully decrypted {len(decrypted_entries)} entries from archive")
            return decrypted_entries
            
        except Exception as e:
            logger.error(f"{log_prefix} Error retrieving archived usage: {e}", exc_info=True)
            return []
