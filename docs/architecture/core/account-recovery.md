---
status: active
last_verified: 2026-03-24
key_files:
  - backend/core/api/app/routes/auth_routes/auth_recovery.py
  - backend/core/api/app/schemas/auth_recovery.py
  - backend/core/api/app/tasks/email_tasks/recovery_account_email_task.py
  - frontend/packages/ui/src/components/AccountRecovery.svelte
  - frontend/packages/ui/src/components/PasswordAndTfaOtp.svelte
  - frontend/packages/ui/src/components/signup/steps/recoverykey/RecoveryKeyTopContent.svelte
---

# Account Recovery

> Recovery flows for users who lose access to their login method. Recovery key preserves all data; full account reset is a destructive last resort.

## Why This Exists

- Zero-knowledge architecture means the server cannot reset passwords or decrypt data on the user's behalf
- Users who lose their password/passkey but have their recovery key can log in normally (no data loss)
- Users who lose everything need a last-resort reset that deletes all client-encrypted data

## How It Works

### Recovery Key Login (Non-Destructive)

Users with their recovery key use "Login with recovery key" on the login page. This uses the same PBKDF2 key derivation as password login to unwrap the master key. All data is preserved.

Recovery keys are **mandatory during signup**: auto-generated, auto-downloaded as `openmates_recovery_key.txt`, and the user must confirm storage before proceeding. See `RecoveryKeyTopContent.svelte`.

### Account Reset Flow (Destructive)

Entry point: Login page -> Password/2FA step -> (under "Login with recovery key") -> "Can't login to account?"

**Step 1 -- Request code:** server sends 6-digit code to user's email. Code valid 15 minutes, rate limited 3/email/hour. Endpoint: `POST /auth/recovery/request-code`.

**Step 2 -- Verify and confirm:** user enters code + toggles ON data loss acknowledgement (all chats, app settings, memories, embeds permanently deleted). Both conditions required. Endpoint: `POST /auth/recovery/verify-code` returns a one-time verification token (10-min TTL).

**Step 3 -- New credentials:** user chooses passkey or password.

- **Passkey:** WebAuthn registration with PRF, new master key generated and wrapped with PRF-derived key
- **Password:** new password entered; if user lacks 2FA, must set it up first (password always requires 2FA)

Endpoint: `POST /auth/recovery/reset-account` with verification token + new credential data.

**Step 4 -- Completion:** user redirected to login page with success notification. User is NOT auto-logged in. 2FA setup during recovery (if needed) uses `POST /auth/recovery/setup-2fa`.

All endpoints in [auth_recovery.py](../../backend/core/api/app/routes/auth_routes/auth_recovery.py). Frontend: [AccountRecovery.svelte](../../frontend/packages/ui/src/components/AccountRecovery.svelte), entry via [PasswordAndTfaOtp.svelte](../../frontend/packages/ui/src/components/PasswordAndTfaOtp.svelte).

## Data Preservation vs Deletion

### Preserved (Server-Side Vault Encrypted)

`encrypted_credit_balance`, `encrypted_username`, `encrypted_profileimage_url`, `encrypted_invoice_counter`, `encrypted_gifted_credits_for_signup`, `encrypted_tfa_secret` (if previously configured), `encrypted_tfa_app_name`.

### Preserved (Cleartext)

`stripe_customer_id`, `stripe_subscription_id`, `subscription_*`, `payment_tier`, `account_id`, `is_admin`, `darkmode`, `language`.

### Deleted (Client-Side Encrypted)

All chats, messages, app settings, memories, embeds, hidden demo chats, encryption keys, passkeys, API keys, `encrypted_settings`.

## Edge Cases

- **2FA preserved after reset:** if previously configured, `encrypted_tfa_secret` is Vault-encrypted and survives the reset. Users prompted for 2FA on next login.
- **No 2FA + password reset:** user must set up 2FA during recovery (security policy: password + 2FA are inseparable)
- **Rate limiting:** code request 3/email/hour, verification 5 attempts/hour, 2FA setup 10/hour, full reset 10/account/24h

## Related Docs

- [Signup & Login](./signup-and-auth.md) -- authentication flows
- [Zero-Knowledge Storage](./zero-knowledge-storage.md) -- why reset destroys data
- [Passkeys](./passkeys.md) -- passkey re-registration during recovery
- [Security Architecture](./security.md) -- overall security model
