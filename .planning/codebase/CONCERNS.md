# Codebase Concerns

**Analysis Date:** 2026-03-26

---

## Tech Debt

**skill_executor.py imported by all non-AI skills (module boundary violation):**
- Issue: `backend/apps/ai/processing/skill_executor.py` re-exports `check_rate_limit`, `wait_for_rate_limit`, `sanitize_external_content`, and `execute_skill_via_celery` via `__all__`. Nine-plus non-AI skill apps import these from an AI-specific module, violating the layer boundary that requires shared logic to live in `backend/shared/`.
- Files: `backend/apps/ai/processing/skill_executor.py` lines 58–69
- Impact: Any refactor of the AI processing layer breaks unrelated skill apps. Coupling makes it impossible to split the AI worker from other workers independently.
- Fix approach: Move the four re-exported helpers to `backend/shared/python_utils/skill_utils.py` and update all import sites in the same commit (two-commit rule applies).

**SettingsBilling.svelte is not split into sub-components:**
- Issue: `frontend/packages/ui/src/components/settings/SettingsBilling.svelte` contains all four billing sub-views (buy-credits, auto-topup, low-balance, monthly) in a single file. A comment at line 133 documents the required split but it has not been done.
- Files: `frontend/packages/ui/src/components/settings/SettingsBilling.svelte`
- Impact: File grows with each billing feature; harder to review and test billing changes in isolation.
- Fix approach: Create `settings/billing/SettingsBillingBuyCredits.svelte`, `SettingsBillingAutoTopup.svelte`, `SettingsBillingLowBalance.svelte`, `SettingsBillingMonthly.svelte` per the existing comment.

**ActiveChat.svelte is a 12,405-line god component:**
- Issue: `frontend/packages/ui/src/components/ActiveChat.svelte` has 111 import statements and contains rendering logic, WebSocket coordination, embed fullscreen handling, and keyboard shortcuts all in one file.
- Files: `frontend/packages/ui/src/components/ActiveChat.svelte`
- Impact: Every chat-related bug fix touches this file. High merge conflict rate. SSR analysis is blocked (see Svelte 5 circular dependency concern below).
- Fix approach: Extract embed fullscreen orchestration, keyboard shortcut registration, and scroll management into dedicated Svelte components or service modules.

**Redis connection constructed per-skill-call (DRY violation and resource waste):**
- Issue: At least six skill files each independently read `DRAGONFLY_PASSWORD`, construct a Redis URL, and call `aioredis.from_url()`. Each call potentially opens a new connection instead of reusing a pool.
- Files: `backend/apps/pdf/skills/search_skill.py`, `backend/apps/pdf/skills/read_skill.py`, `backend/apps/pdf/skills/view_skill.py`, `backend/apps/images/skills/search_skill.py`, `backend/apps/images/skills/view_skill.py`, `backend/apps/images/tasks/generate_task.py`, `backend/apps/images/tasks/vectorize_task.py`
- Impact: Unnecessary connection churn under concurrent skill execution.
- Fix approach: Add a `get_redis_client()` factory to `backend/shared/python_utils/` that returns a shared async Redis pool, used by all skills.

**Svelte 5 runes circular dependency disables component chunking:**
- Issue: All component chunking in the Vite build config is commented out at `frontend/apps/web_app/vite.config.ts` lines 133–146 with `TODO: Re-enable after fixing Svelte 5 runes circular dependency issues`. Circular dependency warnings are also suppressed (line 165).
- Files: `frontend/apps/web_app/vite.config.ts`
- Impact: No code-splitting for signup, settings, or chat components. Every page loads the full bundle. Suppressed warnings hide real dependency graph problems.
- Fix approach: Identify which Svelte 5 rune store creates the cycle (likely a store that imports from another store's internal module, violating the stated convention). Fix the import, then re-enable chunking.

**Missing architecture docs referenced in code:**
- Issue: `docs/architecture/shopping-cookie-pool.md` and `docs/billing.md` are referenced in code comments but do not exist.
- Files: `backend/apps/shopping/providers/rewe_provider.py` line 43, `backend/apps/ai/processing/main_processor.py` line 4418
- Impact: Onboarding developers have no documented reference for these systems.
- Fix approach: Write the missing documents or remove the references.

**`@html` used with i18n strings that include user-controlled content (potential XSS):**
- Issue: `frontend/packages/ui/src/components/signup/steps/profilepicture/ProfilePictureTopContent.svelte` line 43 uses `{@html $text('chat.welcome.hey_user').replace('{username}', escapeHtml(displayUsername))}`. The pattern is correct here (`escapeHtml` is called), but several other `{@html $text(...)}` uses in the signup flow pass translation strings directly without confirming the strings contain no interpolated user data.
- Files: `frontend/packages/ui/src/components/Community.svelte`, `frontend/packages/ui/src/components/signup/steps/backupcodes/BackupCodesTopContent.svelte`, `frontend/packages/ui/src/components/signup/steps/secureaccount/SecureAccountTopContent.svelte`, `frontend/packages/ui/src/components/signup/steps/credits/CreditsTopContent.svelte`
- Impact: Low risk if translation strings are hardcoded, but any future interpolation of user data into these keys without escaping would be an XSS vector.
- Fix approach: Audit all `{@html $text(...)}` usages to verify no user-controlled data is ever interpolated without `escapeHtml()`.

---

## Known Bugs / Incomplete Features

**Reminder cancellation is simulated, not real:**
- Issue: `frontend/packages/ui/src/components/embeds/reminder/ReminderEmbedFullscreen.svelte` line 139 has `// TODO: Implement actual cancel API call`. The cancel button runs a `setTimeout(500ms)` and sets `isCancelled = true` locally — no backend call is made. The reminder will still fire.
- Files: `frontend/packages/ui/src/components/embeds/reminder/ReminderEmbedFullscreen.svelte`
- Impact: Users who press "Cancel" on a reminder see it marked cancelled in the UI but the Celery beat task fires at the scheduled time regardless.
- Fix approach: Call the cancel-reminder skill via WebSocket or a dedicated REST endpoint. Update embed state on success.

**Skill task cancellation is not implemented:**
- Issue: `backend/apps/base_skill.py` line 106 has `# TODO: Ensure Celery tasks spawned from skills are cancellable.` The `cancel_task` method exists but is commented out (lines 732–739).
- Files: `backend/apps/base_skill.py`
- Impact: No way for users or the system to stop long-running skill tasks mid-execution. Long AI generation tasks that the user aborts continue consuming resources.
- Fix approach: Implement `cancel_task` using `celery_app.control.revoke(task_id, terminate=True)` and wire it to the WebSocket cancellation message.

**Embed rekeying (CID migration) is not implemented:**
- Issue: `frontend/packages/ui/src/services/embedStore.ts` line 2303: `// TODO: Implement rekeying logic`. The `rekeyStreamToCid` method throws if called.
- Files: `frontend/packages/ui/src/services/embedStore.ts`
- Impact: Stream embeds cannot be finalized/migrated to content-addressed storage. Any code path that calls `rekeyStreamToCid` will error.
- Fix approach: Implement hash computation and CID-based storage update before the method is invoked in a real flow.

**PDF export in usage page is a stub:**
- Issue: `frontend/packages/ui/src/components/settings/SettingsUsage.svelte` line 888: `// TODO: Implement PDF export using a library like jsPDF`. The button exists in UI but has no implementation.
- Files: `frontend/packages/ui/src/components/settings/SettingsUsage.svelte`
- Impact: Usage PDF export button does nothing.

**Chat local sync not sent to server:**
- Issue: `frontend/packages/ui/src/components/chats/Chat.svelte` line 1828 and `chatSyncServiceHandlersAI.ts` line 2122 both have `// TODO: Sync to server` notes. Certain chat state updates (e.g., user profile sync, some chat field updates) are saved locally to IndexedDB only.
- Files: `frontend/packages/ui/src/components/chats/Chat.svelte`, `frontend/packages/ui/src/services/chatSyncServiceHandlersAI.ts`
- Impact: Changes made on one device may not appear on another until server sync is implemented.

**App settings memory deletion not synced to server:**
- Issue: `frontend/packages/ui/src/stores/appSettingsMemoriesStore.ts` line 706 and `personalDataStore.ts` line 635 note that deletion of app_settings_memories is local-only because the backend does not yet support the delete operation.
- Files: `frontend/packages/ui/src/stores/appSettingsMemoriesStore.ts`, `frontend/packages/ui/src/stores/personalDataStore.ts`
- Impact: Deleted memories reappear after re-sync from server.

**Encryption fields not added for new chat fields:**
- Issue: `frontend/packages/ui/src/services/db/chatCrudOperations.ts` lines 182 and 271 note that new chat model fields are not yet encrypted or decrypted in the IndexedDB layer.
- Files: `frontend/packages/ui/src/services/db/chatCrudOperations.ts`
- Impact: New fields stored in plaintext in IndexedDB, inconsistent with the E2EE model for existing fields.

**Passkey schema lacks proper lookup_hash field:**
- Issue: `backend/core/api/app/routes/auth_routes/auth_passkey.py` line 2072: `# TODO: Fix schema to have proper lookup_hash field`.
- Files: `backend/core/api/app/routes/auth_routes/auth_passkey.py`
- Impact: Passkey lookup may use a suboptimal field, impacting lookup performance or correctness at scale.

---

## Security Considerations

**Payment webhook returns HTTP 200 on chargeback and internal processing failures:**
- Risk: Two confirmed audit findings (tagged `audit-2026-03-19`). (1) Chargeback processing exceptions fall through to HTTP 200 — the payment provider stops retrying so fraudulent chargebacks may not revoke credits. (2) Any unhandled exception in the entire webhook handler returns `{"status": "internal_server_error"}` with HTTP 200 — providers interpret 2xx as success and stop retrying, meaning missed events are never replayed.
- Files: `backend/core/api/app/routes/payments.py` lines 1748, 2323
- Current mitigation: Error is logged. Credits deducted on original purchase are not reversed automatically.
- Fix: Raise `HTTPException(500)` for both cases so the payment provider retries delivery.

**Creator tip: credits deducted but income entry may not be recorded:**
- Risk: At `backend/core/api/app/routes/creators.py` line 199, if the income entry creation fails after credits are charged, the code logs an error and returns success. The user is charged but the creator receives no income record.
- Files: `backend/core/api/app/routes/creators.py`
- Current mitigation: Error log only.
- Fix approach: Wrap credit deduction and income entry creation in a compensating transaction or retry loop. On income entry failure, reverse the credit deduction before returning.

**Bare `except: pass` in WebSocket offline sync handler:**
- Risk: `backend/core/api/app/routes/handlers/websocket_handlers/offline_sync_handler.py` lines 265 and 274 use bare `except: pass`. Errors sending the sync-complete message and per-change error messages are swallowed without logging.
- Files: `backend/core/api/app/routes/handlers/websocket_handlers/offline_sync_handler.py`
- Current mitigation: None — failures are completely invisible.
- Fix: Replace with `except Exception as e: logger.warning(...)` at minimum.

**Invoice and credit note PDFs not deleted from S3 on account deletion:**
- Risk: `backend/core/api/app/tasks/user_cache_tasks.py` lines 1401 and 1553 have `# TODO: Delete invoice PDFs from S3`. Account deletion removes database records but leaves PDF files in S3.
- Files: `backend/core/api/app/tasks/user_cache_tasks.py`
- Current mitigation: Directus records are deleted, making the S3 objects unreachable through normal application paths.
- Fix: Iterate invoice/credit note `encrypted_s3_object_key` values and call `s3_service.delete_object()` before deleting database records.

**`window.open` calls missing `noopener`:**
- Risk: `frontend/packages/ui/src/components/signup/SignupNav.svelte` line 150 and `Signup.svelte` line 920 call `window.open(url, '_blank')` without a third `noopener` argument. The opened page gains `window.opener` access.
- Files: `frontend/packages/ui/src/components/signup/SignupNav.svelte`, `frontend/packages/ui/src/components/signup/Signup.svelte`
- Current mitigation: URLs are hardcoded to trusted domains.
- Fix: Change to `window.open(url, '_blank', 'noopener,noreferrer')`.

**`OneTimeCodesBottomContent.svelte` external link missing `rel`:**
- Risk: Line 238 has `<a href={getAppStoreUrl()} target="_blank" class="text-button">` with no `rel="noopener noreferrer"`.
- Files: `frontend/packages/ui/src/components/signup/steps/onetimecodes/OneTimeCodesBottomContent.svelte`
- Fix: Add `rel="noopener noreferrer"`.

---

## Performance Bottlenecks

**`list_apps` API makes O(N×M×K) sequential Vault HTTP calls:**
- Problem: For each app × skill × provider combination, `is_skill_available()` may call `secrets_manager.get_secret()` (a synchronous Vault HTTP call) and `get_skill_providers_with_pricing()` (an internal HTTP call). These are sequential, not parallelized.
- Files: `backend/core/api/app/routes/apps_api.py` lines 1212–1228
- Cause: No caching at the handler level; `asyncio.gather` not used.
- Improvement path: Cache `secrets_manager.get_secret()` results per request in a local dict; parallelize per-skill checks with `asyncio.gather`.

**Missing composite DB index on usage monthly summary tables:**
- Problem: `backend/core/api/app/services/directus/usage.py` line 428: queries on `usage_monthly_chat_summaries`, `usage_monthly_app_summaries`, and `usage_monthly_api_key_summaries` filter on `(user_id_hash, year_month)` with no composite index. This query runs on every AI message that charges credits.
- Files: `backend/core/api/app/services/directus/usage.py`
- Cause: Index migration never written.
- Improvement path: Create a migration script that runs `CREATE INDEX CONCURRENTLY IF NOT EXISTS <table>_user_month_idx ON public.<table> (user_id_hash, year_month)` for each of the three tables. The audit comment at line 430 includes the exact SQL.

**`main_processor.py` is 4,737 lines and runs on every AI request:**
- Problem: The main AI processing function in `backend/apps/ai/processing/main_processor.py` is deeply nested and processes every incoming message. Debug log statements (`[QUERY_DEBUG]`, `[EMBED_DEBUG]`, `[TOON CONVERSION DEBUG]`) are called at `logger.info` level — they execute on every request regardless of whether debug output is needed.
- Files: `backend/apps/ai/processing/main_processor.py`
- Cause: Debug instrumentation left in at `INFO` level rather than `DEBUG` level.
- Improvement path: Downgrade `[QUERY_DEBUG]`, `[EMBED_DEBUG]`, and `[TOON CONVERSION DEBUG]` logger calls to `logger.debug`. Same for `ask_skill.py` `DEBUG_STREAM` lines (611, 645, 655, 680) and `stream_consumer.py` `[CODE_BLOCK_DEBUG]` lines.

---

## Fragile Areas

**REWE cookie pool depends on manually refreshed Vault secret:**
- Files: `backend/apps/shopping/providers/rewe_provider.py`
- Why fragile: Cloudflare `cf_clearance` cookies expire and must be manually refreshed in Vault. There is no automated refresh and no alerting when the pool is stale. The `ValueError: pass` at line 209 silently ignores malformed cookie pool entries.
- Architecture doc referenced but missing: `docs/architecture/shopping-cookie-pool.md`
- Safe modification: Always test REWE search with a fresh cookie pool entry in Vault before merging changes to the provider.
- Test coverage: No automated test for the cookie pool selection logic.

**OpenRouter health check does not verify actual request routing:**
- Files: `backend/core/api/app/tasks/health_check_tasks.py` lines 460–466, 659
- Why fragile: The health check sends requests but they do not appear in OpenRouter's activity log. Whether the check actually validates end-to-end connectivity is unknown (audit finding from 2026-03-19).
- Safe modification: Do not rely on the OpenRouter health check as a definitive signal. Cross-reference with OpenRouter's own activity dashboard.

**WebSocket handlers with suppressed errors produce invisible failures:**
- Files: `backend/core/api/app/routes/handlers/websocket_handlers/offline_sync_handler.py`
- Why fragile: Bare `except: pass` at lines 265 and 274 means a crashed send does not appear in any log. WebSocket disconnection issues during offline sync go undetected.
- Safe modification: When modifying offline sync, add integration test assertions that check error messages are delivered to client.

**Celery skill tasks cannot be cancelled by the application:**
- Files: `backend/apps/base_skill.py` lines 106, 732–739
- Why fragile: If a skill hangs (e.g., external API timeout), the only way to stop it is to terminate the Celery worker process. There is no graceful per-task cancellation path.
- Safe modification: Do not add new long-running skills without first implementing the `cancel_task` path.

---

## Test Coverage Gaps

**Images search skill has no automated tests:**
- What's not tested: `backend/apps/images/skills/search_skill.py` — the file header says `# Tests: backend/tests/apps/images/test_search_skill.py (TODO)`. The test file does not exist.
- Files: `backend/apps/images/skills/search_skill.py`, `backend/tests/test_rest_api_images.py` (line 29 notes CLI integration tests pending)
- Risk: Image search regressions go undetected.
- Priority: Medium

**Nutrition REWE skill product detail scraping is unimplemented:**
- What's not tested: `backend/apps/nutrition/skills/rewe_online.py` line 9 documents that product nutrition details are in HTML on the product detail page but are not scraped. No test exists for nutrition data completeness.
- Files: `backend/apps/nutrition/skills/rewe_online.py`
- Risk: Users receive incomplete nutrition data silently.
- Priority: Low

**Rate limiter `user_id` fields are always null in anonymous context:**
- What's not tested: `backend/apps/ai/processing/rate_limiting.py` lines 273–274 set `user_id: None` and `user_id_hash: None` because user context is not available at that point. No test verifies rate limiting behavior for anonymous or partially-authenticated requests.
- Files: `backend/apps/ai/processing/rate_limiting.py`
- Risk: Rate limiting may not correctly attribute requests for certain authentication states.
- Priority: Medium

**`focus_mode_id` and `settings_memory_type` omitted from internal API payload:**
- What's not tested: `backend/core/api/app/routes/internal_api.py` lines 492–493 pass `None` for both fields with TODO comments. No test covers the case where these fields are populated.
- Files: `backend/core/api/app/routes/internal_api.py`
- Risk: Focus mode and settings memory features may not function correctly when triggered via the internal API.
- Priority: Medium

---

## Dependencies at Risk

**REWE provider uses Cloudflare-protected scraping:**
- Risk: REWE's Cloudflare configuration could change at any time, invalidating the cookie pool approach without warning. There is no documented fallback and no migration plan.
- Impact: Shopping skill fails silently for REWE searches until cookies are manually refreshed in Vault.
- Migration plan: Evaluate REWE's official partner/affiliate API as an alternative.

---

*Concerns audit: 2026-03-26*
