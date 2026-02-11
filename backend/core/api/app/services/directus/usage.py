# backend/core/api/app/services/directus/usage.py
#
# This module contains the DirectusService methods for interacting with the
# 'usage' collection in Directus.

import logging
import asyncio
from typing import Dict, Any, Optional, List
from datetime import datetime

from backend.core.api.app.utils.encryption import EncryptionService

logger = logging.getLogger(__name__)

class UsageMethods:
    def __init__(self, sdk, encryption_service: EncryptionService):
        self.sdk = sdk
        self.encryption_service = encryption_service
        self.collection = "usage"

    async def create_usage_entry(
        self,
        user_id_hash: str,
        app_id: str,
        skill_id: str,
        usage_type: str,
        timestamp: int,
        credits_charged: int,
        user_vault_key_id: str,
        model_used: Optional[str] = None,
        chat_id: Optional[str] = None,
        message_id: Optional[str] = None,
        source: str = "chat",  # "chat", "api_key", or "direct"
        cost_system_prompt_credits: Optional[int] = None,
        cost_history_credits: Optional[int] = None,
        cost_response_credits: Optional[int] = None,
        actual_input_tokens: Optional[int] = None,
        actual_output_tokens: Optional[int] = None,
        user_input_tokens: Optional[int] = None,
        system_prompt_tokens: Optional[int] = None,
        api_key_hash: Optional[str] = None,  # SHA-256 hash of API key for tracking
        device_hash: Optional[str] = None,  # SHA-256 hash of device for tracking
    ) -> Optional[str]:
        """
        Creates a new usage entry in Directus.
        Stores app_id, skill_id, chat_id, message_id in cleartext for performance and client-side matching.
        Only encrypts sensitive fields (credits, tokens, model).
        
        Args:
            user_id_hash: Hashed user ID for privacy
            app_id: ID of the app that was used (required, must not be empty, stored in cleartext)
            skill_id: ID of the skill that was executed (required, must not be empty, stored in cleartext)
            usage_type: Type of usage (e.g., "skill_execution", "api_call")
            timestamp: Unix timestamp in seconds
            credits_charged: Number of credits charged
            user_vault_key_id: ID of the user's vault key for encryption
            model_used: Optional model identifier (encrypted)
            chat_id: Optional chat ID (stored in cleartext for client-side matching, should be provided for chat-based usage)
            message_id: Optional message ID (stored in cleartext for client-side matching, should be provided for chat-based usage)
            source: Source of usage - "chat" (default), "api_key", or "direct"
            cost_system_prompt_credits: Optional system prompt credit cost
            cost_history_credits: Optional history credit cost
            cost_response_credits: Optional response credit cost
            actual_input_tokens: Optional TOTAL input token count (only saved for AI Ask skill)
            actual_output_tokens: Optional output token count (only saved for AI Ask skill)
            user_input_tokens: Optional user query input token count (only saved for AI Ask skill)
            system_prompt_tokens: Optional system prompt + history token count (only saved for AI Ask skill)
            api_key_hash: Optional SHA-256 hash of the API key that created this usage entry (for API key-based usage)
            device_hash: Optional SHA-256 hash of the device that created this usage entry (for API key-based usage)
        """
        log_prefix = f"DirectusService ({self.collection}):"
        logger.info(f"{log_prefix} Creating new usage entry for user '{user_id_hash}' (app_id='{app_id}', skill_id='{skill_id}').")

        try:
            # Validate required fields - app_id and skill_id must be non-empty
            if not app_id or not isinstance(app_id, str) or not app_id.strip():
                logger.error(f"{log_prefix} Invalid app_id provided: '{app_id}'. Cannot create usage entry.")
                return None
            
            if not skill_id or not isinstance(skill_id, str) or not skill_id.strip():
                logger.error(f"{log_prefix} Invalid skill_id provided: '{skill_id}'. Cannot create usage entry.")
                return None
            
            # Normalize app_id and skill_id by stripping whitespace
            app_id = app_id.strip()
            skill_id = skill_id.strip()
            
            # Normalize source (default to "chat" if invalid)
            if source not in ["chat", "api_key", "direct"]:
                logger.warning(f"{log_prefix} Invalid source '{source}', defaulting to 'chat'")
                source = "chat"
            
            # Normalize chat_id and message_id (strip if provided)
            normalized_chat_id = chat_id.strip() if chat_id and isinstance(chat_id, str) and chat_id.strip() else None
            normalized_message_id = message_id.strip() if message_id and isinstance(message_id, str) and message_id.strip() else None
            
            # Validate: If source is "chat", chat_id should be provided
            if source == "chat" and not normalized_chat_id:
                logger.warning(f"{log_prefix} Source is 'chat' but chat_id is missing. Entry will be created without chat_id.")
            
            # Encryption key is the user vault key for usage entries
            encryption_key_id = user_vault_key_id

            # Encrypt model_used if provided (sensitive field)
            encrypted_model_used = None
            if model_used:
                encrypted_model_used_tuple = await self.encryption_service.encrypt_with_user_key(
                    key_id=encryption_key_id, plaintext=model_used
                )
                encrypted_model_used = encrypted_model_used_tuple[0] if encrypted_model_used_tuple else None

            # CRITICAL: Only save tokens for AI Ask skill (app_id='ai', skill_id='ask')
            # Other skills don't use LLM tokens directly, so storing tokens is incorrect
            should_save_tokens = (app_id == "ai" and skill_id == "ask")
            
            if actual_input_tokens is not None or actual_output_tokens is not None:
                if not should_save_tokens:
                    logger.warning(
                        f"{log_prefix} Tokens provided for non-AI-Ask skill (app_id='{app_id}', skill_id='{skill_id}'). "
                        f"Tokens will not be saved. Only AI Ask skill should have tokens."
                    )
                    actual_input_tokens = None
                    actual_output_tokens = None

            # Encrypt credit and token fields (only tokens if AI Ask skill)
            encrypted_credits_costs_total_tuple = await self.encryption_service.encrypt_with_user_key(
                key_id=encryption_key_id, plaintext=str(credits_charged)
            )
            
            # Encrypt detailed credit costs if provided
            encrypted_credits_costs_system_prompt = None
            if cost_system_prompt_credits is not None:
                res = await self.encryption_service.encrypt_with_user_key(
                    key_id=encryption_key_id, plaintext=str(cost_system_prompt_credits)
                )
                encrypted_credits_costs_system_prompt = res[0] if res else None

            encrypted_credits_costs_history = None
            if cost_history_credits is not None:
                res = await self.encryption_service.encrypt_with_user_key(
                    key_id=encryption_key_id, plaintext=str(cost_history_credits)
                )
                encrypted_credits_costs_history = res[0] if res else None

            encrypted_credits_costs_response = None
            if cost_response_credits is not None:
                res = await self.encryption_service.encrypt_with_user_key(
                    key_id=encryption_key_id, plaintext=str(cost_response_credits)
                )
                encrypted_credits_costs_response = res[0] if res else None

            encrypted_input_tokens = None
            encrypted_output_tokens = None
            encrypted_user_input_tokens = None
            encrypted_system_prompt_tokens = None

            if should_save_tokens:
                if actual_input_tokens is not None:
                    encrypted_input_tokens_tuple = await self.encryption_service.encrypt_with_user_key(
                        key_id=encryption_key_id, plaintext=str(actual_input_tokens)
                    )
                    encrypted_input_tokens = encrypted_input_tokens_tuple[0] if encrypted_input_tokens_tuple else None
                
                if actual_output_tokens is not None:
                    encrypted_output_tokens_tuple = await self.encryption_service.encrypt_with_user_key(
                        key_id=encryption_key_id, plaintext=str(actual_output_tokens)
                    )
                    encrypted_output_tokens = encrypted_output_tokens_tuple[0] if encrypted_output_tokens_tuple else None

                if user_input_tokens is not None:
                    res = await self.encryption_service.encrypt_with_user_key(
                        key_id=encryption_key_id, plaintext=str(user_input_tokens)
                    )
                    encrypted_user_input_tokens = res[0] if res else None

                if system_prompt_tokens is not None:
                    res = await self.encryption_service.encrypt_with_user_key(
                        key_id=encryption_key_id, plaintext=str(system_prompt_tokens)
                    )
                    encrypted_system_prompt_tokens = res[0] if res else None

            encrypted_credits_costs_total = encrypted_credits_costs_total_tuple[0] if encrypted_credits_costs_total_tuple else None

            if not encrypted_credits_costs_total:
                logger.error(f"{log_prefix} Failed to encrypt total credits. Aborting usage entry creation.")
                return None

            # Build payload with cleartext app_id, skill_id, chat_id, message_id for performance and client-side matching
            payload = {
                "user_id_hash": user_id_hash,
                "app_id": app_id,  # Cleartext - not personally identifiable
                "skill_id": skill_id,  # Cleartext - not personally identifiable
                "type": usage_type,
                "source": source,  # "chat", "api_key", or "direct"
                "created_at": timestamp,
                "updated_at": timestamp,
                "encrypted_credits_costs_total": encrypted_credits_costs_total,
            }
            
            # Add optional cleartext fields (for client-side matching with IndexedDB)
            if normalized_chat_id:
                payload["chat_id"] = normalized_chat_id
            if normalized_message_id:
                payload["message_id"] = normalized_message_id
            
            # Add optional API key and device tracking fields (for API key-based usage)
            if api_key_hash:
                payload["api_key_hash"] = api_key_hash
            if device_hash:
                payload["device_hash"] = device_hash
            
            # Add optional encrypted fields
            if encrypted_model_used:
                payload["encrypted_model_used"] = encrypted_model_used
            if encrypted_input_tokens:
                payload["encrypted_input_tokens"] = encrypted_input_tokens
            if encrypted_output_tokens:
                payload["encrypted_output_tokens"] = encrypted_output_tokens
            if encrypted_user_input_tokens:
                payload["encrypted_user_input_tokens"] = encrypted_user_input_tokens
            if encrypted_system_prompt_tokens:
                payload["encrypted_system_prompt_tokens"] = encrypted_system_prompt_tokens
            
            if encrypted_credits_costs_system_prompt:
                payload["encrypted_credits_costs_system_prompt"] = encrypted_credits_costs_system_prompt
            if encrypted_credits_costs_history:
                payload["encrypted_credits_costs_history"] = encrypted_credits_costs_history
            if encrypted_credits_costs_response:
                payload["encrypted_credits_costs_response"] = encrypted_credits_costs_response

            success, response_data = await self.sdk.create_item(self.collection, payload)
            
            if success and response_data and response_data.get("id"):
                entry_id = response_data["id"]
                logger.info(f"{log_prefix} Successfully created usage entry with ID: {entry_id}")
                
                # Update monthly summaries incrementally (fire-and-forget, non-blocking)
                # This ensures summaries are always up-to-date for fast queries
                try:
                    await self._update_monthly_summaries(
                        user_id_hash=user_id_hash,
                        timestamp=timestamp,
                        credits_charged=credits_charged,
                        chat_id=normalized_chat_id,
                        app_id=app_id,
                        api_key_hash=api_key_hash
                    )
                except Exception as e_summary:
                    # Log error but don't fail usage entry creation
                    logger.error(f"{log_prefix} Error updating monthly summaries: {e_summary}", exc_info=True)
                
                # Update daily summaries incrementally (fire-and-forget, non-blocking)
                # Daily summaries power the Overview tab in usage settings
                try:
                    await self._update_daily_summaries(
                        user_id_hash=user_id_hash,
                        timestamp=timestamp,
                        credits_charged=credits_charged,
                        chat_id=normalized_chat_id,
                        app_id=app_id,
                        api_key_hash=api_key_hash
                    )
                except Exception as e_daily:
                    # Log error but don't fail usage entry creation
                    logger.error(f"{log_prefix} Error updating daily summaries: {e_daily}", exc_info=True)
                
                return entry_id
            else:
                logger.error(f"{log_prefix} Failed to create usage entry. Response: {response_data}")
                return None

        except Exception as e:
            logger.error(f"{log_prefix} Error creating usage entry: {e}", exc_info=True)
            return None
    
    async def _update_monthly_summaries(
        self,
        user_id_hash: str,
        timestamp: int,
        credits_charged: int,
        chat_id: Optional[str],
        app_id: str,
        api_key_hash: Optional[str]
    ):
        """
        Update monthly summaries incrementally when a usage entry is created.
        This method updates or creates summary records for chats, apps, and API keys.
        
        Args:
            user_id_hash: Hashed user identifier
            timestamp: Unix timestamp in seconds
            credits_charged: Number of credits charged
            chat_id: Optional chat ID (for chat summaries)
            app_id: App identifier (for app summaries)
            api_key_hash: Optional API key hash (for API key summaries)
        """
        log_prefix = f"DirectusService (usage summaries):"
        
        try:
            # Convert timestamp to year_month format (YYYY-MM)
            dt = datetime.fromtimestamp(timestamp)
            year_month = dt.strftime("%Y-%m")
            
            # Update chat summary if chat_id is provided and it's not an API request
            # API requests with chat_id should only show up under API usage, not chat usage
            if chat_id and not api_key_hash:
                await self._update_summary(
                    collection="usage_monthly_chat_summaries",
                    user_id_hash=user_id_hash,
                    identifier_key="chat_id",
                    identifier_value=chat_id,
                    year_month=year_month,
                    credits_charged=credits_charged,
                    log_prefix=log_prefix,
                    summary_type="chat"
                )
            
            # Update app summary (always, since app_id is required)
            await self._update_summary(
                collection="usage_monthly_app_summaries",
                user_id_hash=user_id_hash,
                identifier_key="app_id",
                identifier_value=app_id,
                year_month=year_month,
                credits_charged=credits_charged,
                log_prefix=log_prefix,
                summary_type="app"
            )
            
            # Update API key summary if api_key_hash is provided
            if api_key_hash:
                await self._update_summary(
                    collection="usage_monthly_api_key_summaries",
                    user_id_hash=user_id_hash,
                    identifier_key="api_key_hash",
                    identifier_value=api_key_hash,
                    year_month=year_month,
                    credits_charged=credits_charged,
                    log_prefix=log_prefix,
                    summary_type="api_key"
                )
            
        except Exception as e:
            logger.error(f"{log_prefix} Error updating monthly summaries: {e}", exc_info=True)
            # Don't raise - this is a non-critical operation
    
    async def _update_summary(
        self,
        collection: str,
        user_id_hash: str,
        identifier_key: str,
        identifier_value: str,
        year_month: str,
        credits_charged: int,
        log_prefix: str,
        summary_type: Optional[str] = None  # Optional summary type for cache invalidation
    ):
        """
        Update or create a monthly summary record.
        
        Args:
            collection: Name of the summary collection
            user_id_hash: Hashed user identifier
            identifier_key: Key name for the identifier (e.g., "chat_id", "app_id", "api_key_hash")
            identifier_value: Value of the identifier
            year_month: Month identifier in format "YYYY-MM"
            credits_charged: Number of credits to add
            log_prefix: Logging prefix
        """
        try:
            # Try to find existing summary
            params = {
                "filter": {
                    "user_id_hash": {"_eq": user_id_hash},
                    identifier_key: {"_eq": identifier_value},
                    "year_month": {"_eq": year_month}
                },
                "fields": "id,total_credits,entry_count",
                "limit": 1
            }
            
            existing_summaries = await self.sdk.get_items(collection, params=params, no_cache=True)
            
            if existing_summaries and len(existing_summaries) > 0:
                # Update existing summary
                summary = existing_summaries[0]
                summary_id = summary.get("id")
                current_credits = summary.get("total_credits", 0)
                current_count = summary.get("entry_count", 0)
                
                update_data = {
                    "total_credits": current_credits + credits_charged,
                    "entry_count": current_count + 1,
                    "updated_at": int(datetime.now().timestamp())
                }
                
                await self.sdk.update_item(collection, summary_id, update_data)
                logger.debug(f"{log_prefix} Updated {collection} summary {summary_id} (+{credits_charged} credits, +1 entry)")
                
                # Invalidate cache for this summary type (last 3 months)
                # This ensures cache is updated when summaries change
                if summary_type:
                    for months in [1, 2, 3]:
                        cache_key = f"usage_summaries:{user_id_hash}:{summary_type}:{months}"
                        await self.sdk.cache.delete(cache_key)
                        logger.debug(f"{log_prefix} Invalidated cache: {cache_key}")
            else:
                # Create new summary
                current_timestamp = int(datetime.now().timestamp())
                
                create_data = {
                    "user_id_hash": user_id_hash,
                    identifier_key: identifier_value,
                    "year_month": year_month,
                    "total_credits": credits_charged,
                    "entry_count": 1,
                    "is_archived": False,
                    "archive_s3_key": None,
                    "created_at": current_timestamp,
                    "updated_at": current_timestamp
                }
                
                success, result = await self.sdk.create_item(collection, create_data)
                if success and result:
                    logger.debug(f"{log_prefix} Created new {collection} summary for {identifier_key}={identifier_value}, month={year_month}")
                    
                    # Invalidate cache for this summary type (last 3 months)
                    # This ensures cache is updated when new summaries are created
                    if summary_type:
                        for months in [1, 2, 3]:
                            cache_key = f"usage_summaries:{user_id_hash}:{summary_type}:{months}"
                            await self.sdk.cache.delete(cache_key)
                            logger.debug(f"{log_prefix} Invalidated cache: {cache_key}")
                else:
                    logger.warning(f"{log_prefix} Failed to create {collection} summary: {result}")
                    
        except Exception as e:
            logger.error(f"{log_prefix} Error updating {collection} summary: {e}", exc_info=True)
            # Don't raise - this is a non-critical operation

    async def _update_daily_summaries(
        self,
        user_id_hash: str,
        timestamp: int,
        credits_charged: int,
        chat_id: Optional[str],
        app_id: str,
        api_key_hash: Optional[str]
    ):
        """
        Update daily summaries incrementally when a usage entry is created.
        Mirrors the monthly summary pattern but groups by date (YYYY-MM-DD).
        Daily summaries power the Overview tab in the usage settings page.
        
        Args:
            user_id_hash: Hashed user identifier
            timestamp: Unix timestamp in seconds
            credits_charged: Number of credits charged
            chat_id: Optional chat ID (for chat summaries)
            app_id: App identifier (for app summaries)
            api_key_hash: Optional API key hash (for API key summaries)
        """
        log_prefix = "DirectusService (daily summaries):"
        
        try:
            # Convert timestamp to date format (YYYY-MM-DD)
            dt = datetime.fromtimestamp(timestamp)
            date_str = dt.strftime("%Y-%m-%d")
            
            # Update chat daily summary if chat_id is provided and it's not an API request
            if chat_id and not api_key_hash:
                await self._update_daily_summary(
                    collection="usage_daily_chat_summaries",
                    user_id_hash=user_id_hash,
                    identifier_key="chat_id",
                    identifier_value=chat_id,
                    date_str=date_str,
                    credits_charged=credits_charged,
                    log_prefix=log_prefix
                )
            
            # Update app daily summary (always, since app_id is required)
            await self._update_daily_summary(
                collection="usage_daily_app_summaries",
                user_id_hash=user_id_hash,
                identifier_key="app_id",
                identifier_value=app_id,
                date_str=date_str,
                credits_charged=credits_charged,
                log_prefix=log_prefix
            )
            
            # Update API key daily summary if api_key_hash is provided
            if api_key_hash:
                await self._update_daily_summary(
                    collection="usage_daily_api_key_summaries",
                    user_id_hash=user_id_hash,
                    identifier_key="api_key_hash",
                    identifier_value=api_key_hash,
                    date_str=date_str,
                    credits_charged=credits_charged,
                    log_prefix=log_prefix
                )
            
            # Invalidate daily overview cache
            # Clear common day ranges so the overview tab refreshes
            for days in [7, 14, 30]:
                cache_key = f"usage_daily_overview:{user_id_hash}:{days}"
                await self.sdk.cache.delete(cache_key)
                
        except Exception as e:
            logger.error(f"{log_prefix} Error updating daily summaries: {e}", exc_info=True)
            # Don't raise - this is a non-critical operation
    
    async def _update_daily_summary(
        self,
        collection: str,
        user_id_hash: str,
        identifier_key: str,
        identifier_value: str,
        date_str: str,
        credits_charged: int,
        log_prefix: str
    ):
        """
        Update or create a daily summary record.
        Similar to _update_summary but uses 'date' (YYYY-MM-DD) instead of 'year_month'.
        Daily tables don't have is_archived/archive_s3_key fields.
        
        Args:
            collection: Name of the daily summary collection
            user_id_hash: Hashed user identifier
            identifier_key: Key name for the identifier (e.g., "chat_id", "app_id", "api_key_hash")
            identifier_value: Value of the identifier
            date_str: Date in format "YYYY-MM-DD"
            credits_charged: Number of credits to add
            log_prefix: Logging prefix
        """
        try:
            # Try to find existing daily summary
            params = {
                "filter": {
                    "user_id_hash": {"_eq": user_id_hash},
                    identifier_key: {"_eq": identifier_value},
                    "date": {"_eq": date_str}
                },
                "fields": "id,total_credits,entry_count",
                "limit": 1
            }
            
            existing = await self.sdk.get_items(collection, params=params, no_cache=True)
            
            if existing and len(existing) > 0:
                # Update existing daily summary
                summary = existing[0]
                summary_id = summary.get("id")
                current_credits = summary.get("total_credits", 0)
                current_count = summary.get("entry_count", 0)
                
                update_data = {
                    "total_credits": current_credits + credits_charged,
                    "entry_count": current_count + 1,
                    "updated_at": int(datetime.now().timestamp())
                }
                
                await self.sdk.update_item(collection, summary_id, update_data)
                logger.debug(f"{log_prefix} Updated {collection} {summary_id} (+{credits_charged} credits, +1 entry)")
            else:
                # Create new daily summary
                current_timestamp = int(datetime.now().timestamp())
                
                create_data = {
                    "user_id_hash": user_id_hash,
                    identifier_key: identifier_value,
                    "date": date_str,
                    "total_credits": credits_charged,
                    "entry_count": 1,
                    "created_at": current_timestamp,
                    "updated_at": current_timestamp
                }
                
                success, result = await self.sdk.create_item(collection, create_data)
                if success and result:
                    logger.debug(f"{log_prefix} Created new {collection} for {identifier_key}={identifier_value}, date={date_str}")
                else:
                    logger.warning(f"{log_prefix} Failed to create {collection}: {result}")
                    
        except Exception as e:
            logger.error(f"{log_prefix} Error updating {collection}: {e}", exc_info=True)
            # Don't raise - this is a non-critical operation
    
    async def get_daily_overview(
        self,
        user_id_hash: str,
        days: int = 7
    ) -> List[Dict[str, Any]]:
        """
        Fetch daily usage overview combining all three daily summary tables.
        Returns a list of day objects, each containing all usage items for that day
        (chats, apps, API keys combined). Used by the Overview tab in usage settings.
        
        Args:
            user_id_hash: Hashed user identifier
            days: Number of days to fetch (default: 7)
            
        Returns:
            List of day objects: [{date: "2026-02-11", total_credits: 450, items: [...]}]
            Sorted by date descending (most recent first).
        """
        log_prefix = "DirectusService (daily overview):"
        logger.info(f"{log_prefix} Fetching daily overview for user '{user_id_hash}', last {days} days")
        
        try:
            # Check cache first
            cache_key = f"usage_daily_overview:{user_id_hash}:{days}"
            cached = await self.sdk.cache.get(cache_key)
            if cached:
                logger.debug(f"{log_prefix} Cache HIT for daily overview")
                return cached
            
            # Calculate list of date strings for the requested days
            from datetime import timedelta
            dates = []
            for i in range(days):
                day_date = datetime.now() - timedelta(days=i)
                dates.append(day_date.strftime("%Y-%m-%d"))
            
            # Query all three daily summary tables in parallel
            # Each table returns items for the requested date range
            common_filter = {
                "user_id_hash": {"_eq": user_id_hash},
                "date": {"_in": dates}
            }
            
            chat_params = {
                "filter": common_filter,
                "fields": "chat_id,date,total_credits,entry_count",
                "sort": ["-date"],
                "limit": -1
            }
            app_params = {
                "filter": common_filter,
                "fields": "app_id,date,total_credits,entry_count",
                "sort": ["-date"],
                "limit": -1
            }
            api_key_params = {
                "filter": common_filter,
                "fields": "api_key_hash,date,total_credits,entry_count",
                "sort": ["-date"],
                "limit": -1
            }
            
            # Fetch all three in parallel for performance
            import asyncio
            chat_summaries, app_summaries, api_key_summaries = await asyncio.gather(
                self.sdk.get_items("usage_daily_chat_summaries", params=chat_params, no_cache=True),
                self.sdk.get_items("usage_daily_app_summaries", params=app_params, no_cache=True),
                self.sdk.get_items("usage_daily_api_key_summaries", params=api_key_params, no_cache=True),
            )
            
            # Combine all items grouped by date
            # Structure: {date: {items: [...], total_credits: N}}
            days_map: Dict[str, Dict[str, Any]] = {}
            
            # Process chat summaries
            for summary in (chat_summaries or []):
                date = summary.get("date")
                if not date:
                    continue
                if date not in days_map:
                    days_map[date] = {"date": date, "total_credits": 0, "items": []}
                days_map[date]["items"].append({
                    "type": "chat",
                    "chat_id": summary.get("chat_id"),
                    "app_id": None,
                    "api_key_hash": None,
                    "total_credits": summary.get("total_credits", 0),
                    "entry_count": summary.get("entry_count", 0)
                })
                days_map[date]["total_credits"] += summary.get("total_credits", 0)
            
            # Process app summaries
            for summary in (app_summaries or []):
                date = summary.get("date")
                if not date:
                    continue
                if date not in days_map:
                    days_map[date] = {"date": date, "total_credits": 0, "items": []}
                days_map[date]["items"].append({
                    "type": "app",
                    "chat_id": None,
                    "app_id": summary.get("app_id"),
                    "api_key_hash": None,
                    "total_credits": summary.get("total_credits", 0),
                    "entry_count": summary.get("entry_count", 0)
                })
                # Note: Don't add to total_credits here since app usage overlaps with chat usage
                # (every chat usage also creates an app summary). We'll deduplicate below.
            
            # Process API key summaries
            for summary in (api_key_summaries or []):
                date = summary.get("date")
                if not date:
                    continue
                if date not in days_map:
                    days_map[date] = {"date": date, "total_credits": 0, "items": []}
                days_map[date]["items"].append({
                    "type": "api_key",
                    "chat_id": None,
                    "app_id": None,
                    "api_key_hash": summary.get("api_key_hash"),
                    "total_credits": summary.get("total_credits", 0),
                    "entry_count": summary.get("entry_count", 0)
                })
                days_map[date]["total_credits"] += summary.get("total_credits", 0)
            
            # Recalculate total_credits per day as sum of chat + API key credits
            # (app credits overlap with chat credits, so we exclude them from the day total)
            for date_key, day_data in days_map.items():
                chat_total = sum(
                    item["total_credits"] for item in day_data["items"] if item["type"] == "chat"
                )
                api_key_total = sum(
                    item["total_credits"] for item in day_data["items"] if item["type"] == "api_key"
                )
                day_data["total_credits"] = chat_total + api_key_total
            
            # Sort items within each day by credits descending (most expensive first)
            for day_data in days_map.values():
                day_data["items"].sort(key=lambda x: x.get("total_credits", 0), reverse=True)
            
            # Convert to sorted list (most recent date first)
            result = sorted(days_map.values(), key=lambda x: x["date"], reverse=True)
            
            # Also include empty days in the response so the frontend knows which days exist
            # (This helps the frontend distinguish "no data" from "not loaded")
            existing_dates = set(days_map.keys())
            for date in dates:
                if date not in existing_dates:
                    result.append({"date": date, "total_credits": 0, "items": []})
            
            # Re-sort after adding empty days
            result.sort(key=lambda x: x["date"], reverse=True)
            
            # Cache for 5 minutes
            if result:
                await self.sdk.cache.set(cache_key, result, ttl=300)
                logger.debug(f"{log_prefix} Cached daily overview ({len(result)} days)")
            
            logger.info(f"{log_prefix} Returning {len(result)} days for daily overview")
            return result
            
        except Exception as e:
            logger.error(f"{log_prefix} Error fetching daily overview: {e}", exc_info=True)
            return []

    async def get_user_usage_entries(
        self,
        user_id_hash: str,
        user_vault_key_id: str,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        sort: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Fetches usage entries for a user and decrypts encrypted fields.
        
        Args:
            user_id_hash: Hashed user ID to filter usage entries
            user_vault_key_id: User's vault key ID for decryption
            limit: Optional limit for pagination
            offset: Optional offset for pagination
            sort: Optional sort field (e.g., "-created_at" for descending)
            
        Returns:
            List of decrypted usage entries
        """
        log_prefix = f"DirectusService ({self.collection}):"
        logger.info(f"{log_prefix} Fetching usage entries for user '{user_id_hash}'")
        
        try:
            # Build query parameters - don't use sort parameter due to Directus permission issues
            # We'll sort client-side instead to avoid 403 errors
            # Fetch more entries than needed for pagination (we'll sort and slice client-side)
            # Use a reasonable max limit to avoid fetching too much data
            fetch_limit = (limit or 10) * 2 if limit else 100  # Fetch 2x the requested limit for sorting buffer
            params = {
                "filter": {
                    "user_id_hash": {
                        "_eq": user_id_hash
                    }
                },
                "fields": "*",
                "limit": min(fetch_limit, 1000)  # Cap at 1000 to avoid performance issues
            }
            
            # Note: Not using sort parameter in Directus query due to permission issues
            # We'll sort client-side after fetching and decrypting
            # Also not using offset in Directus query - we'll apply it after sorting
            
            # Fetch usage entries from Directus using the SDK's get_items method
            entries = await self.sdk.get_items(self.collection, params=params, no_cache=True)
            
            if not entries:
                logger.info(f"{log_prefix} No usage entries found for user '{user_id_hash}'")
                return []
            
            # Process entries: Use cleartext fields directly, decrypt only encrypted fields
            # OPTIMIZATION: Decrypt all encrypted fields in parallel using asyncio.gather() to reduce latency
            async def process_entry(entry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
                """Process a single usage entry: use cleartext fields, decrypt encrypted fields in parallel"""
                try:
                    # Use cleartext fields directly (no backward compatibility)
                    processed_entry = {
                        "id": entry.get("id"),
                        "type": entry.get("type"),
                        "source": entry.get("source", "chat"),
                        "created_at": entry.get("created_at"),
                        "updated_at": entry.get("updated_at"),
                        "app_id": entry.get("app_id"),  # Cleartext - always available for new entries
                        "skill_id": entry.get("skill_id"),  # Cleartext - always available for new entries
                        "chat_id": entry.get("chat_id"),  # Cleartext - for client-side matching
                        "message_id": entry.get("message_id"),  # Cleartext - for client-side matching
                        "api_key_hash": entry.get("api_key_hash"),  # Cleartext - API key hash for tracking (nullable)
                        "device_hash": entry.get("device_hash"),  # Cleartext - device hash for tracking (nullable)
                    }
                    
                    # Collect all decryption tasks for encrypted fields only
                    decrypt_tasks = {}
                    
                    # Decrypt encrypted fields (credits, tokens, model)
                    encrypted_model_used = entry.get("encrypted_model_used")
                    if encrypted_model_used:
                        decrypt_tasks["model_used"] = self.encryption_service.decrypt_with_user_key(
                            encrypted_model_used, user_vault_key_id
                        )
                    
                    encrypted_credits = entry.get("encrypted_credits_costs_total")
                    if encrypted_credits:
                        decrypt_tasks["credits"] = self.encryption_service.decrypt_with_user_key(
                            encrypted_credits, user_vault_key_id
                        )
                    
                    encrypted_input_tokens = entry.get("encrypted_input_tokens")
                    if encrypted_input_tokens:
                        decrypt_tasks["input_tokens"] = self.encryption_service.decrypt_with_user_key(
                            encrypted_input_tokens, user_vault_key_id
                        )
                    
                    encrypted_output_tokens = entry.get("encrypted_output_tokens")
                    if encrypted_output_tokens:
                        decrypt_tasks["output_tokens"] = self.encryption_service.decrypt_with_user_key(
                            encrypted_output_tokens, user_vault_key_id
                        )

                    encrypted_user_input_tokens = entry.get("encrypted_user_input_tokens")
                    if encrypted_user_input_tokens:
                        decrypt_tasks["user_input_tokens"] = self.encryption_service.decrypt_with_user_key(
                            encrypted_user_input_tokens, user_vault_key_id
                        )

                    encrypted_system_prompt_tokens = entry.get("encrypted_system_prompt_tokens")
                    if encrypted_system_prompt_tokens:
                        decrypt_tasks["system_prompt_tokens"] = self.encryption_service.decrypt_with_user_key(
                            encrypted_system_prompt_tokens, user_vault_key_id
                        )
                    
                    encrypted_credits_system_prompt = entry.get("encrypted_credits_costs_system_prompt")
                    if encrypted_credits_system_prompt:
                        decrypt_tasks["credits_system_prompt"] = self.encryption_service.decrypt_with_user_key(
                            encrypted_credits_system_prompt, user_vault_key_id
                        )

                    encrypted_credits_history = entry.get("encrypted_credits_costs_history")
                    if encrypted_credits_history:
                        decrypt_tasks["credits_history"] = self.encryption_service.decrypt_with_user_key(
                            encrypted_credits_history, user_vault_key_id
                        )

                    encrypted_credits_response = entry.get("encrypted_credits_costs_response")
                    if encrypted_credits_response:
                        decrypt_tasks["credits_response"] = self.encryption_service.decrypt_with_user_key(
                            encrypted_credits_response, user_vault_key_id
                        )
                    
                    # Execute all decryptions in parallel for this entry
                    if decrypt_tasks:
                        results = await asyncio.gather(*decrypt_tasks.values(), return_exceptions=True)
                        
                        # Process results
                        for i, (field_name, result) in enumerate(zip(decrypt_tasks.keys(), results)):
                            if isinstance(result, Exception):
                                logger.warning(f"{log_prefix} Failed to decrypt {field_name} for entry {entry.get('id')}: {result}")
                                continue
                            
                            if result:
                                if field_name == "credits":
                                    try:
                                        processed_entry["credits"] = int(result)
                                    except ValueError:
                                        logger.warning(f"{log_prefix} Invalid credits value: {result}")
                                        processed_entry["credits"] = 0
                                elif field_name in ["input_tokens", "output_tokens", "user_input_tokens", "system_prompt_tokens"]:
                                    try:
                                        processed_entry[field_name] = int(result) if result else None
                                    except ValueError:
                                        processed_entry[field_name] = None
                                elif field_name in ["credits_system_prompt", "credits_history", "credits_response"]:
                                    try:
                                        processed_entry[field_name] = int(result) if result else 0
                                    except ValueError:
                                        processed_entry[field_name] = 0
                                else:
                                    processed_entry[field_name] = result
                    
                    # Ensure credits is always set (default to 0 if missing)
                    if "credits" not in processed_entry:
                        processed_entry["credits"] = 0
                    
                    return processed_entry
                    
                except Exception as e:
                    logger.error(f"{log_prefix} Error decrypting usage entry {entry.get('id')}: {e}", exc_info=True)
                    return None
            
            # Process all entries in parallel (each entry's encrypted fields are decrypted in parallel)
            processing_results = await asyncio.gather(
                *[process_entry(entry) for entry in entries],
                return_exceptions=True
            )
            
            # Filter out None results (failed processing)
            processed_entries = [
                result for result in processing_results
                if result is not None and not isinstance(result, Exception)
            ]
            
            logger.debug(f"{log_prefix} Processed {len(processed_entries)}/{len(entries)} entries successfully")
            
            # Sort client-side by created_at descending (newest first)
            # This avoids Directus permission issues with sort parameter
            processed_entries.sort(key=lambda x: x.get("created_at", 0), reverse=True)
            
            # Apply pagination after sorting (if limit/offset were specified)
            # Note: For efficiency, we should ideally sort in Directus, but due to permission issues
            # we sort client-side. For large datasets, consider increasing the limit or implementing
            # server-side cursor-based pagination.
            if limit or offset:
                start_idx = offset or 0
                end_idx = start_idx + (limit or len(processed_entries))
                processed_entries = processed_entries[start_idx:end_idx]
            
            logger.info(f"{log_prefix} Successfully fetched and processed {len(processed_entries)} usage entries (sorted and paginated client-side)")
            return processed_entries
            
        except Exception as e:
            logger.error(f"{log_prefix} Error fetching usage entries: {e}", exc_info=True)
            return []
    
    async def get_monthly_summaries(
        self,
        user_id_hash: str,
        summary_type: str,  # "chat", "app", or "api_key"
        months: int = 3
    ) -> List[Dict[str, Any]]:
        """
        Fetch monthly usage summaries for a user.
        Uses cache for the last 3 months to ensure max performance and reliable data.
        
        Args:
            user_id_hash: Hashed user identifier
            summary_type: Type of summary ("chat", "app", or "api_key")
            months: Number of months to fetch (default: 3)
            
        Returns:
            List of summary records grouped by month
        """
        log_prefix = f"DirectusService (usage summaries):"
        logger.info(f"{log_prefix} Fetching {summary_type} summaries for user '{user_id_hash}', last {months} months")
        
        try:
            collection_name = f"usage_monthly_{summary_type}_summaries"
            
            # Calculate list of year_month strings for the requested months
            from datetime import datetime, timedelta
            year_months = []
            for i in range(months):
                month_date = datetime.now() - timedelta(days=i * 30)
                year_month = month_date.strftime("%Y-%m")
                year_months.append(year_month)
            
            # Check cache first (for last 3 months)
            cache_key = f"usage_summaries:{user_id_hash}:{summary_type}:{months}"
            if months <= 3:
                cached_summaries = await self.sdk.cache.get(cache_key)
                if cached_summaries:
                    logger.debug(f"{log_prefix} Cache HIT for {summary_type} summaries")
                    return cached_summaries
            
            # Query summaries using _in operator with list of year_month strings
            params = {
                "filter": {
                    "user_id_hash": {"_eq": user_id_hash},
                    "year_month": {"_in": year_months}
                },
                "fields": "*",
                "sort": ["-year_month"],  # Newest first
                "limit": -1
            }
            
            summaries = await self.sdk.get_items(collection_name, params=params, no_cache=True)
            
            # Cache the last 3 months for future requests
            if months <= 3 and summaries:
                # Cache for 5 minutes to balance freshness and performance
                # Update cache when summaries are updated in _update_summary
                await self.sdk.cache.set(cache_key, summaries, ttl=300)
                logger.debug(f"{log_prefix} Cached {len(summaries)} {summary_type} summaries")
            
            logger.info(f"{log_prefix} Found {len(summaries)} {summary_type} summaries for user '{user_id_hash}'")
            return summaries
            
        except Exception as e:
            logger.error(f"{log_prefix} Error fetching {summary_type} summaries: {e}", exc_info=True)
            return []
    
    async def get_usage_entries_for_summary(
        self,
        user_id_hash: str,
        user_vault_key_id: str,
        summary_type: str,  # "chat", "app", or "api_key"
        identifier: str,  # chat_id, app_id, or api_key_hash
        year_month: str  # "YYYY-MM"
    ) -> List[Dict[str, Any]]:
        """
        Fetch usage entries for a specific summary (chat/app/api_key) in a specific month.
        Checks if archived and loads from appropriate source.
        
        Args:
            user_id_hash: Hashed user identifier
            user_vault_key_id: User's vault key ID for decryption
            summary_type: Type of summary ("chat", "app", or "api_key")
            identifier: Identifier value (chat_id, app_id, or api_key_hash)
            year_month: Month identifier in format "YYYY-MM"
            
        Returns:
            List of decrypted usage entries
        """
        log_prefix = f"DirectusService (usage details):"
        logger.info(f"{log_prefix} Fetching {summary_type} usage entries for '{identifier}', month '{year_month}'")
        
        try:
            collection_name = f"usage_monthly_{summary_type}_summaries"
            identifier_key = {
                "chat": "chat_id",
                "app": "app_id",
                "api_key": "api_key_hash"
            }[summary_type]
            
            # Find summary record to check if archived
            params = {
                "filter": {
                    "user_id_hash": {"_eq": user_id_hash},
                    identifier_key: {"_eq": identifier},
                    "year_month": {"_eq": year_month}
                },
                "fields": "id,is_archived,archive_s3_key",
                "limit": 1
            }
            
            summaries = await self.sdk.get_items(collection_name, params=params, no_cache=True)
            
            if not summaries:
                logger.warning(f"{log_prefix} No summary found for {summary_type} '{identifier}', month '{year_month}'")
                return []
            
            summary = summaries[0]
            is_archived = summary.get("is_archived", False)
            
            if is_archived:
                # Load from archive (this will be handled by the API endpoint using archive service)
                logger.info(f"{log_prefix} Summary is archived, will load from S3")
                return []  # Return empty, API endpoint will handle archive retrieval
            else:
                # Load from Directus usage collection
                # Parse year_month to get timestamp range
                year, month = map(int, year_month.split("-"))
                start_date = datetime(year, month, 1)
                if month == 12:
                    end_date = datetime(year + 1, 1, 1)
                else:
                    end_date = datetime(year, month + 1, 1)
                
                start_timestamp = int(start_date.timestamp())
                end_timestamp = int(end_date.timestamp())
                
                # Build filter based on summary type
                filter_dict = {
                    "user_id_hash": {"_eq": user_id_hash},
                    "created_at": {
                        "_gte": start_timestamp,
                        "_lt": end_timestamp
                    }
                }
                
                if summary_type == "chat":
                    filter_dict["chat_id"] = {"_eq": identifier}
                    # Only include entries where source is 'chat' (web app usage)
                    # This excludes API requests that might be associated with this chat
                    filter_dict["source"] = {"_eq": "chat"}
                elif summary_type == "app":
                    filter_dict["app_id"] = {"_eq": identifier}
                elif summary_type == "api_key":
                    filter_dict["api_key_hash"] = {"_eq": identifier}
                
                params = {
                    "filter": filter_dict,
                    "fields": "*",
                    "sort": ["-created_at"],
                    "limit": -1
                }
                
                entries = await self.sdk.get_items("usage", params=params, no_cache=True)
                
                # Decrypt entries (same logic as get_user_usage_entries)
                # For now, return raw entries - API endpoint will handle decryption
                # Actually, we should decrypt here for consistency
                return await self._decrypt_usage_entries(entries, user_vault_key_id)
                
        except Exception as e:
            logger.error(f"{log_prefix} Error fetching usage entries for summary: {e}", exc_info=True)
            return []
    
    async def get_chat_total_credits(
        self,
        user_id_hash: str,
        chat_id: str
    ) -> int:
        """
        Get the total credits used for a specific chat across all months.
        Uses the usage_monthly_chat_summaries table which stores total_credits
        in cleartext, so no decryption is needed. Very fast.
        
        Args:
            user_id_hash: Hashed user identifier
            chat_id: The chat ID to look up
            
        Returns:
            Total credits used for this chat (sum across all months)
        """
        log_prefix = "DirectusService (usage chat total):"
        logger.debug(f"{log_prefix} Getting total credits for chat '{chat_id}'")
        
        try:
            params = {
                "filter": {
                    "user_id_hash": {"_eq": user_id_hash},
                    "chat_id": {"_eq": chat_id}
                },
                "fields": "total_credits",
                "limit": -1
            }
            
            summaries = await self.sdk.get_items(
                "usage_monthly_chat_summaries", params=params, no_cache=True
            )
            
            total = sum(s.get("total_credits", 0) for s in summaries)
            logger.debug(f"{log_prefix} Chat '{chat_id}' total credits: {total} (from {len(summaries)} month(s))")
            return total
            
        except Exception as e:
            logger.error(f"{log_prefix} Error getting chat total credits: {e}", exc_info=True)
            return 0

    async def get_message_credits(
        self,
        user_id_hash: str,
        message_id: str,
        user_vault_key_id: str
    ) -> Optional[int]:
        """
        Get the credits charged for a specific message.
        Queries the usage collection by message_id and decrypts the credits field.
        Typically returns a single entry since each message generates one usage record.
        
        Args:
            user_id_hash: Hashed user identifier
            message_id: The message ID to look up
            user_vault_key_id: User's vault key ID for decryption
            
        Returns:
            Credits charged for this message, or None if not found
        """
        log_prefix = "DirectusService (usage message):"
        logger.debug(f"{log_prefix} Getting credits for message '{message_id}'")
        
        try:
            params = {
                "filter": {
                    "user_id_hash": {"_eq": user_id_hash},
                    "message_id": {"_eq": message_id}
                },
                "fields": "encrypted_credits_costs_total",
                "limit": 1
            }
            
            entries = await self.sdk.get_items("usage", params=params, no_cache=True)
            
            if not entries:
                logger.debug(f"{log_prefix} No usage entry found for message '{message_id}'")
                return None
            
            encrypted_credits = entries[0].get("encrypted_credits_costs_total")
            if not encrypted_credits:
                logger.debug(f"{log_prefix} No encrypted credits for message '{message_id}'")
                return 0
            
            decrypted = await self.encryption_service.decrypt_with_user_key(
                encrypted_credits, user_vault_key_id
            )
            
            try:
                credits = int(decrypted)
            except (ValueError, TypeError):
                credits = 0
            
            logger.debug(f"{log_prefix} Message '{message_id}' credits: {credits}")
            return credits
            
        except Exception as e:
            logger.error(f"{log_prefix} Error getting message credits: {e}", exc_info=True)
            return None

    async def _decrypt_usage_entries(
        self,
        entries: List[Dict[str, Any]],
        user_vault_key_id: str
    ) -> List[Dict[str, Any]]:
        """
        Decrypt usage entries (helper method).
        Similar to get_user_usage_entries but for already-fetched entries.
        """
        log_prefix = f"DirectusService (usage):"
        
        async def process_entry(entry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
            try:
                processed_entry = {
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
                
                decrypt_tasks = {}
                
                encrypted_model_used = entry.get("encrypted_model_used")
                if encrypted_model_used:
                    decrypt_tasks["model_used"] = self.encryption_service.decrypt_with_user_key(
                        encrypted_model_used, user_vault_key_id
                    )
                
                encrypted_credits = entry.get("encrypted_credits_costs_total")
                if encrypted_credits:
                    decrypt_tasks["credits"] = self.encryption_service.decrypt_with_user_key(
                        encrypted_credits, user_vault_key_id
                    )
                
                encrypted_input_tokens = entry.get("encrypted_input_tokens")
                if encrypted_input_tokens:
                    decrypt_tasks["input_tokens"] = self.encryption_service.decrypt_with_user_key(
                        encrypted_input_tokens, user_vault_key_id
                    )
                
                encrypted_output_tokens = entry.get("encrypted_output_tokens")
                if encrypted_output_tokens:
                    decrypt_tasks["output_tokens"] = self.encryption_service.decrypt_with_user_key(
                        encrypted_output_tokens, user_vault_key_id
                    )

                encrypted_user_input_tokens = entry.get("encrypted_user_input_tokens")
                if encrypted_user_input_tokens:
                    decrypt_tasks["user_input_tokens"] = self.encryption_service.decrypt_with_user_key(
                        encrypted_user_input_tokens, user_vault_key_id
                    )

                encrypted_system_prompt_tokens = entry.get("encrypted_system_prompt_tokens")
                if encrypted_system_prompt_tokens:
                    decrypt_tasks["system_prompt_tokens"] = self.encryption_service.decrypt_with_user_key(
                        encrypted_system_prompt_tokens, user_vault_key_id
                    )
                
                encrypted_credits_system_prompt = entry.get("encrypted_credits_costs_system_prompt")
                if encrypted_credits_system_prompt:
                    decrypt_tasks["credits_system_prompt"] = self.encryption_service.decrypt_with_user_key(
                        encrypted_credits_system_prompt, user_vault_key_id
                    )

                encrypted_credits_history = entry.get("encrypted_credits_costs_history")
                if encrypted_credits_history:
                    decrypt_tasks["credits_history"] = self.encryption_service.decrypt_with_user_key(
                        encrypted_credits_history, user_vault_key_id
                    )

                encrypted_credits_response = entry.get("encrypted_credits_costs_response")
                if encrypted_credits_response:
                    decrypt_tasks["credits_response"] = self.encryption_service.decrypt_with_user_key(
                        encrypted_credits_response, user_vault_key_id
                    )
                
                if decrypt_tasks:
                    results = await asyncio.gather(*decrypt_tasks.values(), return_exceptions=True)
                    
                    for i, (field_name, result) in enumerate(zip(decrypt_tasks.keys(), results)):
                        if isinstance(result, Exception):
                            logger.warning(f"{log_prefix} Failed to decrypt {field_name}: {result}")
                            continue
                        
                        if result:
                            if field_name == "credits":
                                try:
                                    processed_entry["credits"] = int(result)
                                except ValueError:
                                    processed_entry["credits"] = 0
                            elif field_name in ["input_tokens", "output_tokens", "user_input_tokens", "system_prompt_tokens"]:
                                try:
                                    processed_entry[field_name] = int(result) if result else None
                                except ValueError:
                                    processed_entry[field_name] = None
                            elif field_name in ["credits_system_prompt", "credits_history", "credits_response"]:
                                try:
                                    processed_entry[field_name] = int(result) if result else 0
                                except ValueError:
                                    processed_entry[field_name] = 0
                            else:
                                processed_entry[field_name] = result
                
                if "credits" not in processed_entry:
                    processed_entry["credits"] = 0
                
                return processed_entry
                
            except Exception as e:
                logger.error(f"{log_prefix} Error decrypting entry: {e}", exc_info=True)
                return None
        
        processing_results = await asyncio.gather(
            *[process_entry(entry) for entry in entries],
            return_exceptions=True
        )
        
        processed_entries = [
            result for result in processing_results
            if result is not None and not isinstance(result, Exception)
        ]
        
        return processed_entries
