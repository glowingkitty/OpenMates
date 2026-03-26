---
status: fixing
trigger: "cleartext-cache-backups: inspiration_cache_backup.json and other JSON backup files stored on the host filesystem contain cleartext user messages"
created: 2026-03-26T00:00:00Z
updated: 2026-03-26T00:00:00Z
---

## Current Focus

hypothesis: CONFIRMED - Three backup mechanisms write cleartext data to /shared/cache/ on Docker volume mount. Two contain privacy-sensitive data; one is safe.
test: Full codebase search for all json.dump + file write patterns, all BACKUP_PATH constants
expecting: n/a - root cause confirmed
next_action: Implement Vault encryption for inspiration topic suggestions in the disk backup, and remove email_encryption_key from order backup serialization

## Symptoms

expected: All user data at rest should be encrypted. No cleartext user messages in backup/cache files on disk.
actual: inspiration_cache_backup.json (and possibly others) contain cleartext user messages on host filesystem via Docker volume mounts.
errors: No runtime errors - design/architecture privacy violation.
reproduction: Restart Docker Compose server, check for *backup*.json or *cache*.json files in Docker volumes/bind mounts.
started: Unknown - likely since cache/backup mechanism was implemented.

## Eliminated

- hypothesis: pending_reminders_backup.json contains cleartext user data
  evidence: The existing backup file shows Vault-encrypted fields (vault:v1:...) for prompt and chat_title. Reminder backup code was already removed from main.py (line 1328 comment). The file on disk is a leftover from before removal.
  timestamp: 2026-03-26

- hypothesis: web_analytics_backup.json contains user-identifiable data
  evidence: Web analytics service explicitly states "No PII stored anywhere". Backup contains only aggregate counters (page loads, country distribution, device class, browser family). No user content, no IPs, no identifying information.
  timestamp: 2026-03-26

## Evidence

- timestamp: 2026-03-26
  checked: All BACKUP_PATH constants and json.dump + file write patterns in backend/core/api/app/services/
  found: Three active backup mechanisms write to /shared/cache/:
    1. inspiration_cache_backup.json (cache_inspiration_mixin.py line 38)
    2. pending_orders_backup.json (cache_order_mixin.py line 10)
    3. web_analytics_backup.json (web_analytics_service.py line 48)
    Plus one removed: pending_reminders_backup.json (leftover file on disk, code removed)
  implication: Need to assess each for cleartext privacy violations

- timestamp: 2026-03-26
  checked: What inspiration topic suggestions actually contain
  found: LLM-generated "interest phrases" derived from user conversations. Example from debug output: "tenant heating rights and regulations", "indoor temperature maintenance for health". These clearly reveal what users discussed.
  implication: PRIVACY VIOLATION - topic suggestions are cleartext user interest data written to disk. The docstring claiming "no plaintext PII" is misleading - while not direct chat content, these phrases reveal user interests and topics.

- timestamp: 2026-03-26
  checked: What paid_request tracking data contains
  found: Only timestamp + language code (e.g. {"last_paid_request_timestamp": 1234567890, "language": "en"})
  implication: Low risk - timestamp and language code are not privacy-sensitive

- timestamp: 2026-03-26
  checked: What order backup contains
  found: Order metadata including: order_id, status, amount, currency, support_email, email_encryption_key, user_id, subscription_id
  implication: PRIVACY CONCERN - support_email is cleartext PII. email_encryption_key is a cryptographic key stored in cleartext on disk.

- timestamp: 2026-03-26
  checked: Docker volume mount for /shared
  found: Bind mount `../../shared:/shared` in docker-compose.yml (line 41 and many others). This means /shared/cache/ files are directly on the host filesystem at OpenMates/shared/cache/
  implication: All backup files are accessible on the host without any container boundary

- timestamp: 2026-03-26
  checked: .gitignore coverage for backup files
  found: Only web_analytics_backup.json and pending_reminders_backup.json are gitignored. inspiration_cache_backup.json and pending_orders_backup.json are NOT gitignored.
  implication: These files could accidentally be committed to the repository

- timestamp: 2026-03-26
  checked: Dragonfly (Redis) persistence
  found: Dragonfly uses a named Docker volume (cache-data:/data) and snapshots by default. All Redis data including cleartext topic suggestions exists in the snapshot.
  implication: Separate concern - Dragonfly snapshots are in a Docker volume (not a bind mount), so less accessible but still cleartext at rest. Out of scope for this fix but worth noting.

- timestamp: 2026-03-26
  checked: EncryptionService availability during shutdown
  found: encryption_service.close() is called at line 1410-1411, AFTER the cache dumps at lines 1307-1343. So Vault encryption IS available during the dump phase.
  implication: We CAN use Vault encryption to encrypt the backup data before writing to disk

## Resolution

root_cause: Three backup mechanisms in the backend write cleartext data to /shared/cache/ via Docker bind mount on graceful shutdown. The inspiration_cache_backup.json contains cleartext user interest phrases (topic suggestions derived from conversations). The pending_orders_backup.json contains cleartext email addresses and encryption keys. The web_analytics_backup.json is safe (aggregate counters only). Additionally, two backup files are missing from .gitignore.

fix:
1. Encrypt inspiration topic suggestions with Vault transit encryption before writing to disk backup. Decrypt on restore.
2. Encrypt order backup support_email field. Remove email_encryption_key from disk backup entirely (it can be re-fetched from the live order flow).
3. Add missing .gitignore entries for inspiration_cache_backup.json and pending_orders_backup.json
4. Clean up leftover pending_reminders_backup.json from disk
5. Update misleading docstring about "no plaintext PII"

verification:
files_changed: []
