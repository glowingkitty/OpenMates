import logging
from fastapi import HTTPException
import time
import asyncio
from typing import Dict, Any, Optional

from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.services.server_stats_service import ServerStatsService
from backend.core.api.app.routes.websockets import manager as websocket_manager

logger = logging.getLogger(__name__)

class BillingService:
    def __init__(
        self,
        cache_service: CacheService,
        directus_service: DirectusService,
        encryption_service: EncryptionService,
        server_stats_service: Optional[ServerStatsService] = None,
    ):
        self.cache_service = cache_service
        self.directus_service = directus_service
        self.encryption_service = encryption_service
        self.server_stats_service = server_stats_service
        self.websocket_manager = websocket_manager
        # Strong references to in-flight auto top-up tasks.
        # asyncio discards unreferenced tasks before completion — keeping a set
        # prevents GC mid-payment and ensures exception callbacks fire.
        # Tasks remove themselves via add_done_callback.
        self._pending_topup_tasks: set[asyncio.Task] = set()

    async def charge_user_credits(
        self,
        user_id: str,
        credits_to_deduct: int,
        user_id_hash: str,
        app_id: str,
        skill_id: str,
        usage_details: Optional[Dict[str, Any]] = None,
        api_key_hash: Optional[str] = None,  # SHA-256 hash of API key for tracking
        device_hash: Optional[str] = None,  # SHA-256 hash of device for tracking
    ) -> None:
        """
        Deducts credits and records the usage entry.
        
        Args:
            user_id: Actual user ID for cache lookup
            credits_to_deduct: Number of credits to charge
            user_id_hash: Hashed user ID for privacy
            app_id: ID of the app that executed the skill (required, must not be empty)
            skill_id: ID of the skill that was executed (required, must not be empty)
            usage_details: Optional dict containing additional usage metadata:
                - chat_id: Chat ID if skill was triggered in a chat context
                - message_id: Message ID if skill was triggered from a message
                - model_used: Model identifier if applicable
                - input_tokens: Input token count if applicable
                - output_tokens: Output token count if applicable
                - tool_inference_iterations: Extra LLM calls from tool use (0 = no tools used).
                    Only present for AI Ask skill. Stored as cleartext integer for client-side display.
            api_key_hash: Optional SHA-256 hash of the API key that created this usage entry (for API key-based usage)
            device_hash: Optional SHA-256 hash of the device that created this usage entry (for API key-based usage)
        """
        if not isinstance(credits_to_deduct, int) or credits_to_deduct < 0:
            raise HTTPException(status_code=400, detail="Credits to deduct must be a non-negative integer.")
        
        # Validate required fields - app_id and skill_id must be provided and non-empty
        if not app_id or not isinstance(app_id, str) or not app_id.strip():
            logger.error(f"Invalid app_id provided for credit charge: {app_id}. Cannot create usage entry.")
            raise HTTPException(status_code=400, detail="app_id is required and must not be empty.")
        
        if not skill_id or not isinstance(skill_id, str) or not skill_id.strip():
            logger.error(f"Invalid skill_id provided for credit charge: {skill_id}. Cannot create usage entry.")
            raise HTTPException(status_code=400, detail="skill_id is required and must not be empty.")

        try:
            # 1. Get user profile using the cache service
            user = await self.cache_service.get_user_by_id(user_id)
            
            # If user not in cache, fetch from Directus and cache it
            if not user:
                logger.info(f"User {user_id} not found in cache, fetching from Directus")
                profile_success, user_profile, profile_message = await self.directus_service.get_user_profile(user_id)
                
                if not profile_success or not user_profile:
                    logger.error(f"User profile not found in Directus for user {user_id}: {profile_message}")
                    raise HTTPException(status_code=404, detail=f"User with ID {user_id} not found.")
                
                # Ensure user_id is present in the profile for caching
                if "user_id" not in user_profile:
                    user_profile["user_id"] = user_id
                if "id" not in user_profile:
                    user_profile["id"] = user_id
                
                # Cache the fetched profile
                await self.cache_service.set_user(user_profile, user_id=user_id)
                user = user_profile
                logger.info(f"Successfully fetched and cached user {user_id} from Directus")

            # Resolve vault_key_id: the cached profile may be stale (e.g., after an account
            # recovery reset which re-generates the Vault key). If the key is absent, re-fetch
            # the full profile from Directus before continuing. This is intentionally a fallback
            # rather than the primary path — normal logins always populate vault_key_id.
            if not user.get("vault_key_id"):
                logger.warning(
                    f"vault_key_id missing from cached profile for user_id={user_id}. "
                    "Re-fetching full profile from Directus (possible stale cache after account recovery)."
                )
                profile_success, user_profile, profile_message = await self.directus_service.get_user_profile(user_id)
                if profile_success and user_profile and user_profile.get("vault_key_id"):
                    if "user_id" not in user_profile:
                        user_profile["user_id"] = user_id
                    if "id" not in user_profile:
                        user_profile["id"] = user_id
                    await self.cache_service.set_user(user_profile, user_id=user_id)
                    user = user_profile
                    logger.info(
                        f"Re-fetched profile for user_id={user_id} — vault_key_id now available."
                    )
                else:
                    # vault_key_id is still unavailable. We can still charge credits in cache
                    # and skip the Directus encrypted balance update (it will self-heal on next
                    # login). Usage entry creation (which also needs vault_key_id) will be
                    # attempted later and guarded there too.
                    logger.error(
                        f"vault_key_id unavailable for user_id={user_id} even after re-fetch: {profile_message}. "
                        "Credits will be deducted in cache; Directus balance update and usage entry will be skipped."
                    )

            # Ensure credits are treated as integers, matching preprocessor logic
            current_credits = user.get("credits", 0)
            if not isinstance(current_credits, int):
                logger.warning(f"User credits for {user_id} were not an integer: {current_credits}. Converting to 0.")
                current_credits = 0

            # 2. Check for sufficient balance and calculate new balance
            # Skip balance check if payment is disabled (self-hosted mode)
            from backend.core.api.app.utils.server_mode import is_payment_enabled
            payment_enabled = is_payment_enabled()

            # Maximum allowed overdraft (negative credit balance). Skills are always charged to
            # ensure users are billed even when a multi-step request (web searches, image
            # generations) consumes slightly more than the remaining balance. When the user
            # purchases credits again, the overdraft is subtracted from the purchased amount.
            # See docs/architecture/billing.md for the full overdraft policy.
            OVERDRAFT_LIMIT = -500
            
            if payment_enabled:
                # Payment enabled — allow up to OVERDRAFT_LIMIT before refusing the charge.
                # This prevents multi-skill requests (which start concurrently) from failing
                # mid-flight just because the user is a few credits short.
                if current_credits <= OVERDRAFT_LIMIT:
                    # Hard stop: user is already at or beyond the overdraft limit.
                    logger.warning(
                        f"User {user_id} has exceeded overdraft limit "
                        f"(credits={current_credits}, limit={OVERDRAFT_LIMIT}). "
                        "Refusing credit charge."
                    )
                    raise HTTPException(
                        status_code=402,
                        detail="Insufficient credits. Please purchase more credits to continue.",
                    )
                # Allow the charge even if it takes the balance below 0 (overdraft).
                new_credits = current_credits - credits_to_deduct
                if new_credits < OVERDRAFT_LIMIT:
                    # Clamp: don't go deeper than the limit in a single charge.
                    new_credits = OVERDRAFT_LIMIT
                    credits_to_deduct = current_credits - OVERDRAFT_LIMIT
                if new_credits < 0:
                    logger.warning(
                        f"User {user_id} balance going into overdraft: "
                        f"{current_credits} - {credits_to_deduct} = {new_credits}. "
                        "Skill charge allowed (overdraft policy)."
                    )
            else:
                # Payment disabled (self-hosted mode) - skip balance check but still track usage
                # Set new_credits to current_credits (no deduction) but still create usage entry
                logger.info(f"Payment disabled (self-hosted mode). Skipping credit balance check for user {user_id}. Credits remain: {current_credits}")
                new_credits = current_credits
                # Note: credits_to_deduct is still used for usage entry tracking, but not actually deducted
            user['credits'] = new_credits  # Store as integer in the dictionary for caching

            # 2.5 Update server stats
            if self.server_stats_service:
                await self.server_stats_service.increment_stat("credits_used", credits_to_deduct)
                await self.server_stats_service.update_liability(-credits_to_deduct)

            # 3. Update user in cache
            await self.cache_service.set_user(user, user_id=user_id)

            # 3.5. Check if low balance auto top-up should trigger (only if payment enabled)
            if payment_enabled:
                await self._check_and_trigger_low_balance_topup(user_id, user, new_credits)

            # 4. Update Directus with the encrypted string representation of the integer (only if payment enabled)
            # In self-hosted mode, we still track usage but don't update credit balance in Directus
            if payment_enabled:
                vault_key_id = user.get("vault_key_id")
                if not vault_key_id:
                    # vault_key_id is still unavailable after the re-fetch above.
                    # Cache is already updated with the new balance; the DB will self-heal on the
                    # next login when the profile is rebuilt from Directus. Log as error but do
                    # NOT raise — the charge must succeed even without DB persistence.
                    logger.error(
                        f"Skipping Directus credit balance update for user_id={user_id} "
                        "because vault_key_id is unavailable. Cache balance is correct and "
                        "will sync to Directus on next login."
                    )
                else:
                    encrypted_new_credits_tuple = await self.encryption_service.encrypt_with_user_key(
                        plaintext=str(new_credits),
                        key_id=vault_key_id
                    )
                    encrypted_new_credits = encrypted_new_credits_tuple[0]  # Extract encrypted string
                    # Persist to Directus with retry logic
                    max_retries = 3
                    retry_delay = 5  # seconds
                    for attempt in range(max_retries):
                        update_successful = await self.directus_service.update_user(
                            user_id, {"encrypted_credit_balance": encrypted_new_credits}
                        )
                        if update_successful:
                            logger.info(f"Successfully updated user {user_id} credits in Directus on attempt {attempt + 1}.")
                            break
                        else:
                            logger.warning(
                                f"Attempt {attempt + 1} to update user {user_id} credits in Directus failed. "
                                f"Retrying in {retry_delay} seconds..."
                            )
                            if attempt < max_retries - 1:
                                await asyncio.sleep(retry_delay)
                    else:
                        # This block executes if the loop completes without a `break`
                        logger.critical(
                            f"CRITICAL: Failed to update user {user_id} credits in Directus after {max_retries} attempts. "
                            f"The user has been charged in cache, but the database update failed. Manual intervention required."
                        )
                        # We do NOT revert the cache. The charge is valid.
                        # We raise an exception to inform the client of the persistent failure.
                        raise HTTPException(
                            status_code=500,
                            detail="Your transaction was completed, but there was a delay in saving the final balance. Please refresh shortly."
                        )
            else:
                logger.debug(f"Payment disabled (self-hosted mode). Skipping Directus credit balance update for user {user_id}.")
            
            logger.info(f"Successfully charged {credits_to_deduct} credits from user {user_id}. New balance: {new_credits}")

            # Track paid request timestamp for Daily Inspiration eligibility.
            # The daily inspiration generation job uses this to identify active users
            # (only users who made a paid request in the last 24h get new inspirations).
            # Non-fatal: if caching fails, the user may not get personalized inspirations
            # on this cycle but the core billing flow is unaffected.
            # Skip for incognito chats (is_incognito is checked below when usage_details is parsed,
            # but we need it here too — read it directly from usage_details).
            _is_incognito_charge = (
                usage_details.get("is_incognito", False) if usage_details else False
            )
            if not _is_incognito_charge:
                try:
                    # Pass the user's UI language so generated inspirations match their locale.
                    # The language is available on the cached user profile (set during login).
                    _user_language = user.get("language", "en") or "en"
                    await self.cache_service.track_inspiration_paid_request(
                        user_id=user_id, language=_user_language
                    )
                except Exception as e_track:
                    logger.warning(
                        f"Failed to track paid request for daily inspiration (non-fatal): {e_track}"
                    )

            # 4.5. Update Server Global Stats (Incremental)
            # Track credits used and decrease total liability
            if payment_enabled:
                await self.cache_service.increment_stat("credits_used", credits_to_deduct)
                await self.cache_service.update_liability(-credits_to_deduct)

            # 4.6. Track token usage for cost analytics (Phase 6)
            # Increment total_input_tokens and total_output_tokens from usage_details
            if usage_details:
                try:
                    input_tok = usage_details.get("input_tokens")
                    output_tok = usage_details.get("output_tokens")
                    if input_tok and isinstance(input_tok, int) and input_tok > 0:
                        await self.cache_service.increment_stat("total_input_tokens", input_tok)
                    if output_tok and isinstance(output_tok, int) and output_tok > 0:
                        await self.cache_service.increment_stat("total_output_tokens", output_tok)
                except Exception as _tok_err:
                    logger.warning(f"Failed to increment token counters: {_tok_err}")

            # 5. Broadcast the new credit balance to all user devices
            await self.websocket_manager.broadcast_to_user(
                user_id=user_id,
                message={
                    "type": "user_credits_updated",
                    "payload": {"credits": new_credits}
                }
            )

            # 6. Create usage entry
            # Extract optional fields from usage_details, ensuring we only pass non-empty values
            # chat_id and message_id should be included when skill is triggered in a chat context
            timestamp = int(time.time())
            
            # Extract chat_id and message_id from usage_details if available
            # These are important for linking usage entries to chat sessions
            # CRITICAL: For incognito chats, use "incognito" as chat_id for aggregation
            chat_id = None
            message_id = None
            is_incognito = False
            if usage_details:
                # Check if this is an incognito chat
                is_incognito = usage_details.get("is_incognito", False)
                
                # Only use chat_id and message_id if they are non-empty strings
                chat_id_val = usage_details.get("chat_id")
                if chat_id_val and isinstance(chat_id_val, str) and chat_id_val.strip():
                    if is_incognito:
                        # For incognito chats, use "incognito" as chat_id for aggregation
                        chat_id = "incognito"
                        logger.debug("Using 'incognito' as chat_id for incognito chat usage tracking")
                    else:
                        chat_id = chat_id_val.strip()
                
                message_id_val = usage_details.get("message_id")
                if message_id_val and isinstance(message_id_val, str) and message_id_val.strip():
                    message_id = message_id_val.strip()
            
            # Determine source: "api_key" if api_key_hash is provided (external API), 
            # otherwise "chat" if chat_id is provided (web app), else "direct"
            if api_key_hash:
                source = "api_key"
            elif chat_id:
                source = "chat"
            else:
                source = "direct"
            
            # Extract tool_inference_iterations from usage_details (AI Ask skill only).
            # This is the count of extra LLM calls triggered by tool use in this turn.
            # 0 = no tool calls were made; stored as cleartext integer in the usage entry.
            _tool_inference_iterations: Optional[int] = None
            if usage_details:
                _raw_tii = usage_details.get("tool_inference_iterations")
                if isinstance(_raw_tii, int):
                    _tool_inference_iterations = _raw_tii

            _vault_key_id_for_usage = user.get("vault_key_id")
            if not _vault_key_id_for_usage:
                # Usage entry encryption is not possible without vault_key_id.
                # Log as error but do not fail the charge — billing always succeeds.
                logger.error(
                    f"Skipping usage entry creation for user_id={user_id} "
                    f"({app_id}/{skill_id}) because vault_key_id is unavailable."
                )
            else:
                await self.directus_service.usage.create_usage_entry(
                    user_id_hash=user_id_hash,
                    app_id=app_id.strip(),  # Ensure no leading/trailing whitespace
                    skill_id=skill_id.strip(),  # Ensure no leading/trailing whitespace
                    usage_type="skill_execution",
                    timestamp=timestamp,
                    credits_charged=credits_to_deduct,
                    user_vault_key_id=_vault_key_id_for_usage,
                    model_used=usage_details.get("model_used") if usage_details else None,
                    chat_id=chat_id,  # Cleartext - for client-side matching with IndexedDB
                    message_id=message_id,  # Cleartext - for client-side matching with IndexedDB
                    source=source,  # "chat" or "api_key"
                    cost_system_prompt_credits=usage_details.get("system_prompt_credits") if usage_details else None,
                    cost_history_credits=usage_details.get("history_credits") if usage_details else None,
                    cost_response_credits=usage_details.get("response_credits") if usage_details else None,
                    actual_input_tokens=usage_details.get("input_tokens") if usage_details else None,
                    actual_output_tokens=usage_details.get("output_tokens") if usage_details else None,
                    user_input_tokens=usage_details.get("user_input_tokens") if usage_details else None,
                    system_prompt_tokens=usage_details.get("system_prompt_tokens") if usage_details else None,
                    api_key_hash=api_key_hash,  # API key hash for tracking which API key created this usage
                    device_hash=device_hash,  # Device hash for tracking which device created this usage
                    server_provider=usage_details.get("server_provider") if usage_details else None,
                    server_region=usage_details.get("server_region") if usage_details else None,
                    tool_inference_iterations=_tool_inference_iterations,
                )

        except HTTPException as e:
            # Re-raise HTTPExceptions to be handled by FastAPI
            raise e
        except Exception as e:
            logger.error(f"An unexpected error occurred while charging credits for user {user_id}: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail="An internal error occurred during credit deduction.")

    async def refund_user_credits(
        self,
        user_id: str,
        credits_to_refund: int,
        user_id_hash: str,
        app_id: str,
        skill_id: str,
        reason: str = "",
    ) -> None:
        """
        Refund (add back) credits to a user after a failed task.

        Mirrors charge_user_credits but in the reverse direction:
        - Adds credits to the cached user balance.
        - Updates Directus with the new encrypted balance.
        - Broadcasts the new balance to all user devices.

        No usage entry is created — a refund is not a skill execution.

        Args:
            user_id:          Actual user ID for cache lookup.
            credits_to_refund: Number of credits to restore (must be > 0).
            user_id_hash:     Hashed user ID for logging.
            app_id:           App that originally charged the credits.
            skill_id:         Skill that originally charged the credits.
            reason:           Human-readable description of why the refund was issued.
        """
        if not isinstance(credits_to_refund, int) or credits_to_refund <= 0:
            raise HTTPException(
                status_code=400,
                detail="Credits to refund must be a positive integer.",
            )

        from backend.core.api.app.utils.server_mode import is_payment_enabled
        payment_enabled = is_payment_enabled()

        try:
            # 1. Get user from cache (fall back to Directus on miss)
            user = await self.cache_service.get_user_by_id(user_id)
            if not user:
                logger.info(f"[Refund] User {user_id} not in cache — fetching from Directus")
                profile_success, user_profile, profile_message = (
                    await self.directus_service.get_user_profile(user_id)
                )
                if not profile_success or not user_profile:
                    logger.error(
                        f"[Refund] User profile not found in Directus for user {user_id}: {profile_message}"
                    )
                    raise HTTPException(status_code=404, detail=f"User {user_id} not found.")
                if "user_id" not in user_profile:
                    user_profile["user_id"] = user_id
                if "id" not in user_profile:
                    user_profile["id"] = user_id
                await self.cache_service.set_user(user_profile, user_id=user_id)
                user = user_profile

            current_credits = user.get("credits", 0)
            if not isinstance(current_credits, int):
                current_credits = 0

            if payment_enabled:
                new_credits = current_credits + credits_to_refund
            else:
                # Self-hosted mode: credit balance is not tracked, skip actual update.
                logger.info(
                    f"[Refund] Payment disabled (self-hosted mode). Skipping refund for user {user_id}."
                )
                return

            user["credits"] = new_credits

            # 2. Update server stats (reverse of charge)
            if self.server_stats_service:
                await self.server_stats_service.increment_stat("credits_used", -credits_to_refund)
                await self.server_stats_service.update_liability(credits_to_refund)

            # 3. Update cache
            await self.cache_service.set_user(user, user_id=user_id)

            # 4. Persist to Directus with retry
            _refund_vault_key_id = user.get("vault_key_id")
            if not _refund_vault_key_id:
                logger.error(
                    f"[Refund] vault_key_id unavailable for user_id={user_id}. "
                    "Cache balance updated but Directus update skipped (will self-heal on login)."
                )
                # Skip Directus update — fall through to broadcast/stats below
            else:
                encrypted_new_credits_tuple = await self.encryption_service.encrypt_with_user_key(
                    plaintext=str(new_credits),
                    key_id=_refund_vault_key_id,
                )
                encrypted_new_credits = encrypted_new_credits_tuple[0]

                max_retries = 3
                retry_delay = 5
                for attempt in range(max_retries):
                    update_successful = await self.directus_service.update_user(
                        user_id, {"encrypted_credit_balance": encrypted_new_credits}
                    )
                    if update_successful:
                        logger.info(
                            f"[Refund] Updated credits in Directus on attempt {attempt + 1}."
                        )
                        break
                    logger.warning(
                        f"[Refund] Attempt {attempt + 1} to update Directus failed. "
                        f"Retrying in {retry_delay}s…"
                    )
                    if attempt < max_retries - 1:
                        await asyncio.sleep(retry_delay)
                else:
                    logger.critical(
                        f"[Refund] CRITICAL: Failed to persist refund for user {user_id} "
                        f"after {max_retries} attempts. Cache updated but DB is stale."
                    )
                    # Do not raise — the user's in-memory balance is correct; the DB
                    # will self-heal on next login when the cache is rebuilt from Directus.

            # 5. Update global stats cache
            await self.cache_service.increment_stat("credits_used", -credits_to_refund)
            await self.cache_service.update_liability(credits_to_refund)

            # 6. Broadcast new balance to all devices
            await self.websocket_manager.broadcast_to_user(
                user_id=user_id,
                message={
                    "type": "user_credits_updated",
                    "payload": {"credits": new_credits},
                },
            )

            logger.info(
                f"[Refund] Refunded {credits_to_refund} credits to user {user_id[:8]}… "
                f"({app_id}/{skill_id}). New balance: {new_credits}. Reason: {reason[:200]}"
            )

        except HTTPException:
            raise
        except Exception as e:
            logger.error(
                f"[Refund] Unexpected error refunding credits for user {user_id}: {e}",
                exc_info=True,
            )
            raise HTTPException(
                status_code=500,
                detail="An internal error occurred during credit refund.",
            )

    async def _check_and_trigger_low_balance_topup(
        self,
        user_id: str,
        user: Dict[str, Any],
        new_credits: int
    ) -> None:
        """
        Checks if low balance auto top-up should trigger and initiates it asynchronously.
        This method is fire-and-forget to not block the credit deduction.
        """
        try:
            # Check if feature is enabled and threshold is set
            if not user.get('auto_topup_low_balance_enabled', False):
                return

            # Fixed threshold: always 100 credits (cannot be changed to simplify setup)
            # Enforce this even if database has a different value
            FIXED_THRESHOLD = 100
            threshold = user.get('auto_topup_low_balance_threshold')
            
            # If threshold is not set or is not 100, use the fixed value
            # This ensures consistency even if old data exists
            if threshold != FIXED_THRESHOLD:
                threshold = FIXED_THRESHOLD
                logger.debug(f"Using fixed threshold of {FIXED_THRESHOLD} credits for user {user_id} (stored value was {user.get('auto_topup_low_balance_threshold')})")

            # Check if balance is at or below threshold
            if new_credits > threshold:
                return

            logger.info(f"Low balance detected for user {user_id}: {new_credits} <= {threshold}. Triggering auto top-up.")

            # Trigger async top-up without blocking the current request.
            # We store a strong reference to prevent GC before completion and
            # attach a done callback so unhandled exceptions are logged rather
            # than silently dropped.  Tasks remove themselves when they finish.
            task = asyncio.create_task(
                self._trigger_low_balance_topup(user_id, user),
                name=f"auto_topup_{user_id[:8]}",
            )
            self._pending_topup_tasks.add(task)
            task.add_done_callback(self._pending_topup_tasks.discard)
            task.add_done_callback(
                lambda t: logger.error(
                    f"[BillingService] Auto top-up task for user {user_id[:8]} "
                    f"raised an unhandled exception: {t.exception()!r}",
                    exc_info=t.exception(),
                ) if not t.cancelled() and t.exception() else None
            )

        except Exception as e:
            # Log but don't raise - we don't want to fail the main credit deduction
            logger.error(f"Error checking low balance auto top-up for user {user_id}: {e}", exc_info=True)

    async def _trigger_low_balance_topup(
        self,
        user_id: str,
        user: Dict[str, Any]
    ) -> bool:
        """
        Triggers automatic credit purchase when balance falls below threshold.
        Runs asynchronously to not block the main credit deduction.

        Returns:
            True  — a Stripe charge was actually initiated and confirmed.
                    The caller should wait (asyncio.sleep) for the webhook to
                    add credits before re-checking the user's balance.
            False — no charge was attempted (cooldown, missing config, no email,
                    no payment method, etc.).  The caller must NOT wait.
        """
        try:
            # 1. Check cooldown period - but only if user now has sufficient credits
            # If they still have 0 credits, the previous auto top-up likely failed to add credits
            current_credits = user.get('credits', 0)
            last_triggered = await self._get_last_topup_timestamp(user)

            if last_triggered and (time.time() - last_triggered) < 3600:
                # If user has credits now, respect the cooldown
                if current_credits > 100:  # Above the auto top-up threshold
                    logger.info(f"Low balance auto top-up for user {user_id} on cooldown (last trigger: {int(time.time() - last_triggered)}s ago)")
                    return False
                else:
                    # If user still has insufficient credits, previous auto top-up likely failed
                    # Allow retry but with a shorter cooldown (5 minutes) to prevent spam
                    if (time.time() - last_triggered) < 300:  # 5 minutes
                        logger.info(f"Auto top-up retry for user {user_id} on short cooldown (last trigger: {int(time.time() - last_triggered)}s ago, waiting 5min)")
                        return False
                    else:
                        logger.info(f"Auto top-up retry for user {user_id} allowed - previous attempt may have failed to add credits")

            # 2. Get customer ID - required for payment method verification
            customer_id = user.get('stripe_customer_id')
            if not customer_id:
                logger.warning(f"No Stripe customer ID found for user {user_id} auto top-up. Feature may not be configured properly.")
                return False

            # 3. Decrypt payment method
            logger.debug(f"Decrypting payment method for user {user_id} auto top-up")
            payment_method_id = await self._get_decrypted_payment_method(user)
            if not payment_method_id:
                logger.warning(f"No payment method found for user {user_id} auto top-up. Feature may not be configured properly.")
                return False
            logger.debug(f"Successfully decrypted payment method for user {user_id}: pm_****{payment_method_id[-4:]}")

            # 4. Get configuration
            credits_amount = user.get('auto_topup_low_balance_amount')
            if not credits_amount or credits_amount <= 0:
                logger.warning(f"Invalid credits amount for user {user_id} auto top-up: {credits_amount}")
                return False

            currency = user.get('auto_topup_low_balance_currency', 'eur').lower()

            # 5. Get pricing info from config
            price_data = await self._get_price_for_tier(credits_amount, currency)
            if not price_data:
                logger.error(f"No pricing found for {credits_amount} credits in {currency} for user {user_id}")
                return False

            # 6. Get decrypted email for receipt
            logger.debug(f"Decrypting email for user {user_id} auto top-up")
            email = await self._get_decrypted_email(user)
            logger.debug(f"Email decryption result for user {user_id}: {'success' if email else 'failed/empty'}")
            if not email:
                logger.warning(f"No email found for user {user_id} auto top-up — skipping to avoid Stripe InvalidRequestError.")
                return False

            # 7. Create PaymentIntent using existing payment service
            # Initialize SecretsManager with cache service
            from backend.core.api.app.utils.secrets_manager import SecretsManager
            from backend.core.api.app.services.payment.payment_service import PaymentService
            import os
            
            secrets_manager = SecretsManager(cache_service=self.cache_service)
            await secrets_manager.initialize()
            
            # Determine if production or sandbox environment
            is_production = os.getenv('ENVIRONMENT', 'development') == 'production'
            
            # Create and initialize PaymentService
            payment_service = PaymentService(secrets_manager=secrets_manager)
            await payment_service.initialize(is_production=is_production)

            # Create order with correct parameters
            # PaymentService.create_order expects: (amount, currency, email, credits_amount, customer_id)
            order_result = await payment_service.create_order(
                amount=price_data['amount'],  # Amount in cents from pricing config
                currency=currency,
                email=email,
                credits_amount=credits_amount,
                customer_id=customer_id  # Required for auto top-up with saved payment method
            )

            if not order_result or not order_result.get('client_secret'):
                logger.error(f"Failed to create payment intent for user {user_id} auto top-up")
                return False

            # Cache the order for webhook processing (critical for credit addition)
            payment_intent_id = order_result['id']
            cache_success = await self.cache_service.set_order(
                order_id=payment_intent_id,
                user_id=user_id,
                credits_amount=credits_amount,
                currency=currency,
                status="auto_topup_pending",
                is_auto_topup=True  # Flag to indicate this is auto top-up (no client email key)
            )

            if not cache_success:
                logger.error(f"Failed to cache auto top-up order {payment_intent_id} for user {user_id}. Webhook processing will fail.")
                return False

            # 8. Validate payment method belongs to customer and confirm payment
            import stripe
            stripe.api_key = await self._get_stripe_api_key()

            try:
                # Verify payment method belongs to customer (same validation as in payments.py)
                payment_method = stripe.PaymentMethod.retrieve(payment_method_id)
                if payment_method.customer != customer_id:
                    logger.error(f"Payment method {payment_method_id} does not belong to customer {customer_id} for user {user_id}")
                    return False

                # Use 'id' field from order_result (PaymentIntent ID)
                # Include return_url for automatic payment methods that might redirect
                confirmed_intent = stripe.PaymentIntent.confirm(
                    order_result['id'],
                    payment_method=payment_method_id,
                    return_url="https://app.openmates.com/billing/return"  # Dummy URL for auto top-up (not used)
                )

                logger.info(f"Auto top-up payment confirmed for user {user_id}: {credits_amount} credits, Payment Intent: {confirmed_intent.id}")

                # Update cached order status to completed so webhook can process it
                await self.cache_service.update_order_status(payment_intent_id, "auto_topup_confirmed")

            except stripe.error.StripeError as e:
                logger.error(f"Stripe error confirming auto top-up payment for user {user_id}: {e.user_message}", exc_info=True)
                # Update cached order status to failed
                await self.cache_service.update_order_status(payment_intent_id, "auto_topup_failed")
                return False

            # 9. Update last triggered timestamp
            await self._update_last_topup_timestamp(user_id)

            logger.info(f"✅ Auto top-up successfully triggered for user {user_id}: {credits_amount} credits via {currency.upper()}")

            # Charge was successfully initiated — caller should wait for webhook to add credits
            return True

        except Exception as e:
            logger.error(f"❌ Auto top-up failed for user {user_id}: {e}", exc_info=True)
            # Don't raise - this is a background operation
            return False

    async def _get_last_topup_timestamp(self, user: Dict[str, Any]) -> Optional[float]:
        """
        Retrieves the last auto top-up timestamp.
        Checks cache first (plaintext float), falls back to decrypting from Directus if needed.
        Returns timestamp as float (Unix time) or None if not set.
        """
        try:
            # Check cache first (stored as float)
            cached_timestamp = user.get('auto_topup_last_triggered')
            if cached_timestamp is not None:
                return float(cached_timestamp)

            # Fallback: decrypt from encrypted field if not in cache
            encrypted_timestamp = user.get('encrypted_auto_topup_last_triggered')
            if not encrypted_timestamp:
                return None

            try:
                decrypted_timestamp = await self.encryption_service.decrypt_with_user_key(
                    ciphertext=encrypted_timestamp,
                    key_id=user['vault_key_id']
                )

                # Store in cache for next time
                timestamp_float = float(decrypted_timestamp)
                user['auto_topup_last_triggered'] = timestamp_float

                return timestamp_float
            except Exception as vault_error:
                logger.warning(f"Failed to decrypt auto_topup_last_triggered, treating as not set: {vault_error}")
                # Return None to indicate no timestamp available, which allows auto top-up to proceed
                return None
        except Exception as e:
            logger.warning(f"Error getting last topup timestamp: {e}")
            return None

    async def _update_last_topup_timestamp(self, user_id: str) -> None:
        """
        Updates the last auto top-up timestamp to current time.
        Follows cache-first pattern: update cache, then Directus.
        Cache stores plaintext timestamp (float), Directus stores encrypted.
        """
        try:
            # Get user from cache
            user = await self.cache_service.get_user_by_id(user_id)
            if not user:
                logger.error(f"User {user_id} not found when updating topup timestamp")
                return

            # Current timestamp
            current_time = time.time()

            # 1. Update cache first (store as float in cache)
            user['auto_topup_last_triggered'] = current_time
            await self.cache_service.set_user(user, user_id=user_id)

            # 2. Encrypt timestamp for Directus
            encrypted_timestamp_tuple = await self.encryption_service.encrypt_with_user_key(
                plaintext=str(current_time),
                key_id=user['vault_key_id']
            )
            encrypted_timestamp = encrypted_timestamp_tuple[0]

            # 3. Update Directus
            await self.directus_service.update_user(
                user_id,
                {"encrypted_auto_topup_last_triggered": encrypted_timestamp}
            )

            logger.debug(f"Updated last topup timestamp for user {user_id}: {current_time}")

        except Exception as e:
            logger.error(f"Error updating last topup timestamp for user {user_id}: {e}", exc_info=True)

    async def _get_decrypted_payment_method(self, user: Dict[str, Any]) -> Optional[str]:
        """
        Decrypts and returns the saved payment method ID.
        Returns None if not found or decryption fails.
        """
        try:
            encrypted_pm = user.get('encrypted_payment_method_id')
            if not encrypted_pm:
                return None

            decrypted_pm = await self.encryption_service.decrypt_with_user_key(
                ciphertext=encrypted_pm,
                key_id=user['vault_key_id']
            )

            return decrypted_pm
        except Exception as e:
            logger.error(f"Error decrypting payment method: {e}", exc_info=True)
            return None

    async def _get_decrypted_email(self, user: Dict[str, Any]) -> str:
        """
        Decrypts and returns user email for receipts.
        For auto top-up, uses server-encrypted email field.
        Returns empty string if decryption fails.
        """
        try:
            # First try auto top-up specific email (server-encrypted)
            encrypted_email_auto_topup = user.get('encrypted_email_auto_topup')
            if encrypted_email_auto_topup:
                try:
                    decrypted_email = await self.encryption_service.decrypt_with_user_key(
                        ciphertext=encrypted_email_auto_topup,
                        key_id=user['vault_key_id']
                    )
                    if decrypted_email:
                        logger.debug("Successfully decrypted auto top-up email")
                        return decrypted_email
                    logger.warning("Vault decryption returned empty for auto top-up email")
                except Exception as auto_email_error:
                    logger.warning(f"Failed to decrypt auto top-up email, falling back to regular email: {auto_email_error}")
            return ""
        except Exception as e:
            logger.warning(f"Error decrypting email: {e}")
            return ""

    async def _get_price_for_tier(self, credits_amount: int, currency: str) -> Optional[Dict[str, Any]]:
        """
        Gets price information for a credit tier from pricing config.
        Returns dict with 'amount' (in cents) and 'currency', or None if not found.
        """
        try:
            # Import pricing config
            import yaml
            import os

            # Try absolute path first (Docker standard)
            pricing_file = "/shared/config/pricing.yml"
            
            if not os.path.exists(pricing_file):
                # Fallback to relative path (local development)
                pricing_file = os.path.join(
                    os.path.dirname(__file__),
                    '../../../../../shared/config/pricing.yml'
                )

            logger.debug(f"Loading pricing config from: {pricing_file}")
            with open(pricing_file, 'r') as f:
                pricing_config = yaml.safe_load(f)

            # Find matching tier
            for tier in pricing_config.get('pricingTiers', []):
                if tier.get('credits') == credits_amount:
                    price = tier.get('price', {}).get(currency)
                    if price is not None:
                        # Convert to cents (Stripe expects smallest currency unit).
                        # EUR and USD are the only currencies used with Stripe.
                        amount_cents = int(price * 100)

                        return {
                            'amount': amount_cents,
                            'currency': currency
                        }

            logger.warning(f"No pricing found for {credits_amount} credits in {currency}")
            return None

        except Exception as e:
            logger.error(f"Error loading pricing config: {e}", exc_info=True)
            return None

    async def _get_stripe_api_key(self) -> str:
        """
        Gets Stripe API key from secrets manager.
        This is a simplified version - in production you'd use the StripeService.
        """
        try:
            from backend.core.api.app.utils.secrets_manager import SecretsManager
            secrets_manager = SecretsManager()

            # Determine if production or sandbox
            import os
            is_production = os.getenv('ENVIRONMENT', 'development') == 'production'

            key_suffix = "production_secret_key" if is_production else "sandbox_secret_key"
            secret_path = "kv/data/providers/stripe"

            api_key = await secrets_manager.get_secret(
                secret_path=secret_path,
                secret_key=key_suffix
            )

            if not api_key:
                raise ValueError("Stripe API key not found in vault")

            return api_key

        except Exception as e:
            logger.error(f"Error getting Stripe API key: {e}", exc_info=True)
            raise
