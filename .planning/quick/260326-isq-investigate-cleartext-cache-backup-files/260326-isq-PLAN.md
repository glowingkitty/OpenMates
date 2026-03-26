---
phase: quick
plan: 260326-isq
type: execute
wave: 1
depends_on: []
files_modified:
  - .planning/quick/260326-isq-investigate-cleartext-cache-backup-files/FINDINGS.md
autonomous: true
requirements: []
must_haves:
  truths:
    - "Every /shared/cache/ backup file is cataloged with its encryption status"
    - "Every Redis cache key that stores user content is identified"
    - "All cleartext leakage vectors on the host filesystem are documented"
    - "Architectural recommendations are provided for each finding"
  artifacts:
    - path: ".planning/quick/260326-isq-investigate-cleartext-cache-backup-files/FINDINGS.md"
      provides: "Complete audit of cleartext cache/backup leakage"
      contains: "## Findings"
  key_links: []
---

<objective>
Investigate all cache backup files written to the host filesystem via Docker volumes
(/shared/cache/) and any other paths where cleartext user data may leak to disk.
Catalog each backup mechanism, determine what data it contains, whether it is
encrypted, and produce architectural recommendations.

Purpose: This is an encryption-focused app where chat content is E2E encrypted.
Any cleartext user data persisted to the host filesystem is a privacy violation.
The inspiration cache backup was recently fixed with Vault transit encryption,
but other backup files (web_analytics, pending_orders) and Redis cache keys
need the same audit.

Output: FINDINGS.md with full scope of cleartext leakage and fix recommendations.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@backend/core/api/app/services/cache_inspiration_mixin.py
@backend/core/api/app/services/cache_order_mixin.py
@backend/core/api/app/services/web_analytics_service.py
@backend/core/api/app/services/cache_chat_mixin.py
@backend/core/api/app/services/cache_base.py
@backend/core/api/app/services/cache.py
@backend/core/api/app/services/cache_reminder_mixin.py
@backend/core/api/app/services/cache_demo_chat_mixin.py
@backend/core/api/app/services/cache_debug_mixin.py
@backend/core/api/main.py
@backend/core/docker-compose.yml
</context>

<tasks>

<task type="auto">
  <name>Task 1: Audit all disk-persisted cache backup files</name>
  <files>.planning/quick/260326-isq-investigate-cleartext-cache-backup-files/FINDINGS.md</files>
  <action>
    Systematically investigate every file written to /shared/cache/ or any other
    host-mounted path. For each backup file found:

    1. KNOWN BACKUP FILES — Read the full implementation of each:
       - cache_inspiration_mixin.py: INSPIRATION_CACHE_BACKUP_PATH (/shared/cache/inspiration_cache_backup.json)
         - Already Vault-encrypted. Document what data it contains (topic suggestions with user interest signals,
           paid-request tracking). Note the legacy cleartext detection/deletion logic as a reference pattern.
       - cache_order_mixin.py: ORDER_BACKUP_PATH (/shared/cache/pending_orders_backup.json)
         - Check if Vault-encrypted or cleartext. Document what order data it contains.
       - web_analytics_service.py: WEB_ANALYTICS_BACKUP_PATH (/shared/cache/web_analytics_backup.json)
         - Check if Vault-encrypted or cleartext. Document what analytics data it contains
           (page views, user IDs, IP addresses, session data, etc.).

    2. SEARCH FOR OTHER DISK WRITES — Grep the entire backend for:
       - Any other paths under /shared/cache/ or /shared/ that write files
       - json.dump() or open(..., "w") patterns in service files
       - Any other backup/persist/dump/save_to_disk patterns
       - Docker volume mounts in docker-compose.yml that expose host paths

    3. For each file found, document:
       - File path and what triggers the write (shutdown hook, periodic, etc.)
       - Exact data fields stored (especially any that contain user messages, topics, IPs, emails)
       - Whether Vault transit encryption is applied before writing
       - Privacy risk level: CRITICAL (user messages/content), HIGH (user behavior/interests),
         MEDIUM (aggregate analytics), LOW (non-user system data)

    4. SEARCH REDIS CACHE KEYS — Examine all cache mixin files to catalog what
       user data is stored in Redis/Dragonfly and whether any of it is cleartext
       user content that could leak if the Redis instance is compromised:
       - cache_chat_mixin.py: What chat data is cached? Encrypted or cleartext?
       - cache_reminder_mixin.py: Reminder content?
       - cache_demo_chat_mixin.py: Demo chat content?
       - cache_debug_mixin.py: Debug data with user content?
       - Any other cache mixins

    5. Check main.py shutdown/startup hooks to understand the full lifecycle
       of backup creation and restoration.

    6. Write FINDINGS.md with this structure:
       ## Executive Summary
       ## Disk Backup Files
       (table: path, data type, encrypted?, privacy risk, recommendation)
       ## Redis Cache Keys
       (table: key pattern, data type, contains user content?, risk)
       ## Docker Volume Exposure
       (which volumes mount /shared/ to host, who has access)
       ## Architectural Recommendations
       - Pattern: Follow inspiration_cache_mixin Vault transit pattern for all disk writes
       - Specific fix needed for each unencrypted backup
       - Whether Redis itself needs encryption-at-rest
       - Priority ordering of fixes
  </action>
  <verify>
    <automated>test -f .planning/quick/260326-isq-investigate-cleartext-cache-backup-files/FINDINGS.md && grep -c "##" .planning/quick/260326-isq-investigate-cleartext-cache-backup-files/FINDINGS.md | grep -q "[3-9]" && echo "PASS" || echo "FAIL"</automated>
  </verify>
  <done>
    FINDINGS.md exists with at minimum: executive summary, catalog of all 3 known backup files
    with encryption status, Redis cache key audit, Docker volume analysis, and prioritized
    architectural recommendations. Every cleartext leakage vector is identified with a
    specific remediation path.
  </done>
</task>

</tasks>

<verification>
- FINDINGS.md covers all 3 known backup files under /shared/cache/
- Each backup file has encryption status clearly marked (encrypted vs cleartext)
- Redis cache keys are cataloged with user-content risk assessment
- Docker volume exposure is documented
- Recommendations reference the existing Vault transit pattern from inspiration_cache_mixin
</verification>

<success_criteria>
Complete inventory of all cleartext data leakage vectors with actionable fix recommendations.
No code changes made — investigation and documentation only.
</success_criteria>

<output>
After completion, create `.planning/quick/260326-isq-investigate-cleartext-cache-backup-files/260326-isq-SUMMARY.md`
</output>
