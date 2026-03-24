---
status: active
last_verified: 2026-03-24
key_files:
  - backend/core/api/app/routes/settings.py
  - backend/core/api/app/tasks/user_cache_tasks.py
  - backend/core/api/app/services/compliance.py
  - backend/scripts/delete_user_account.py
  - frontend/packages/ui/src/components/settings/account/SettingsDeleteAccount.svelte
---

# Account Deletion

> Fully implemented account deletion with preview, re-authentication, auto-refunds, phased data cleanup via Celery task, and compliance logging.

## Why This Exists

- GDPR right to erasure: users must be able to delete all personal data
- Zero-knowledge architecture means deletion must cover both server-side and client-encrypted data
- Authentication data must be deleted first to prevent re-login during async cleanup
- Auto-refunds for unused credits (last 14 days, excluding gift cards)

## How It Works

### User Flow

**Location:** Settings -> Account -> Delete Account. Frontend: [SettingsDeleteAccount.svelte](../../frontend/packages/ui/src/components/settings/account/SettingsDeleteAccount.svelte).

1. **Preview:** `GET /api/v1/settings/delete-account-preview` returns total credits, refundable credits, eligible invoices, gift card info. See `_calculate_delete_account_preview()` in [settings.py](../../backend/core/api/app/routes/settings.py).

2. **Confirm:** user toggles ON data deletion acknowledgement (`confirm_data_deletion: true`).

3. **Authenticate:** user re-authenticates via one of three methods:
   - `passkey` -- credential ID verified against `user_passkeys`
   - `2fa_otp` -- OTP code verified via `verify_device_2fa()`
   - `email_otp` -- 6-digit email code verified via `/verify-action-code` endpoint (action: `"delete_account"`)

4. **Execute:** `POST /api/v1/settings/delete-account` triggers Celery task `delete_user_account`, logs out all sessions immediately, returns success.

### Phased Deletion (Celery Task)

The task `delete_user_account_task()` in [user_cache_tasks.py](../../backend/core/api/app/tasks/user_cache_tasks.py) runs asynchronously in 5 phases:

**Phase 1 -- Authentication (critical, must succeed first):**
- Delete passkeys (`user_passkeys`)
- Delete API keys + devices (`api_keys`, `api_key_devices`)
- Clear 2FA data (`encrypted_tfa_secret`, `tfa_backup_codes_hashes`, etc.)
- Clear lookup hashes
- Clear email auth data (`hashed_email`, `user_email_salt`, `encrypted_email_address`, `encrypted_email_with_master_key`)
- Delete encryption keys (`encryption_keys` collection)

**Phase 2 -- Payments & Subscriptions:**
- Auto-refund eligible invoices from last 14 days (via Stripe or Polar API). See `refund_payment()` in `PaymentService`
- Mark invoices as refunded, deduct credits, record in Invoice Ninja (Stripe/Revolut only, not Polar MoR)
- Dispatch credit note email if `email_encryption_key` available
- Delete gift cards and redemption records
- Delete invoices (TODO: S3 PDF cleanup)

**Phase 3 -- User Content:**
- Delete chats, messages, embeds (respecting FK constraints: messages first, then embeds, then chats)
- Delete orphaned embeds by `hashed_user_id`
- Delete usage data + all summary collections (monthly/daily chat/app/API key summaries)
- Delete app settings & memories
- Delete drafts, new chat suggestions, embed keys, credit notes, creator income records

**Phase 4 -- Cache Cleanup:**
- Delete from Dragonfly: `user_profile:{user_id}`, `user_device:{user_id}:*`, `user_device_list:{user_id}`, chat caches (`chat_ids_versions`, `active_chats_lru`, per-chat keys), app settings cache

**Phase 5 -- Compliance & Final Deletion:**
- Log via `ComplianceService.log_account_deletion()` in [compliance.py](../../backend/core/api/app/services/compliance.py) (audit log, 2-year retention)
- Delete user record from `directus_users` (final step)

### Error Handling

Each phase logs errors but continues to the next (except Phase 1 failures which are critical). No explicit retry logic currently -- errors are logged with full stack traces for manual investigation.

### Admin Deletion Script

[delete_user_account.py](../../backend/scripts/delete_user_account.py) provides CLI-based deletion:

```bash
# Dry-run:
docker exec -it api python /app/backend/scripts/delete_user_account.py --email user@example.com --dry-run

# Delete with confirmation:
docker exec -it api python /app/backend/scripts/delete_user_account.py --email user@example.com

# Skip confirmation:
docker exec -it api python /app/backend/scripts/delete_user_account.py --email user@example.com --yes

# Policy violation:
docker exec -it api python /app/backend/scripts/delete_user_account.py --email user@example.com \
    --deletion-type policy_violation --reason "Terms of service violation"
```

The script hashes the email via Vault HMAC (same as frontend), looks up user by `hashed_email`, shows a preview, then triggers the same `delete_user_account` Celery task. Deletion types: `admin_action` (default), `policy_violation`, `user_requested`.

## Edge Cases

- **Refund window:** only invoices from last 14 days are eligible. Gift card credits are never refundable.
- **Polar vs Stripe refunds:** Polar uses `provider_order_id` (UUID); if missing, falls back to API lookup by checkout ID. Invoice Ninja recording skipped for Polar (merchant of record).
- **S3 cleanup:** invoice PDFs and credit note PDFs are TODO -- currently only Directus records are deleted.
- **Vault key deletion:** marked as TODO in the implementation; depends on Vault service method availability.
- **Email encryption key:** only available when user is present in browser during deletion. If absent, credit note email is skipped (logged).

## Related Docs

- [Account Backup](./account-backup.md) -- export before deletion (planned)
- [Security Architecture](./security.md) -- encryption and authentication context
- [Account Recovery](./account-recovery.md) -- destructive reset (different from deletion)
