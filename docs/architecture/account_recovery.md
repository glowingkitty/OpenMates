# Account Recovery Architecture

> For users who lose access to their login method (password/passkey) and cannot use their recovery key.

## Overview

Account recovery allows users to regain access to their accounts when they've lost their password, passkey, AND recovery key. Given OpenMates' zero-knowledge architecture, this requires a **full account reset** that deletes all client-encrypted data.

**Status**: ✅ **IMPLEMENTED**

## Important: Recovery Key vs Account Reset

### Have Recovery Key → Normal Login

Users who have their recovery key should use the **"Login with recovery key"** option on the login page. This preserves ALL data:
- All chats, messages, and conversation history
- App settings and memories
- Embeds and saved content
- No data loss whatsoever

**Recommendation**: Users should always keep their recovery key in a safe place.

### Lost Everything → Account Reset

The account reset flow is a **last resort** for users who have lost:
1. Their password (if using password login)
2. Their passkey device (if using passkey login)  
3. Their recovery key

**WARNING**: Account reset permanently deletes all client-encrypted data.

## Account Reset Flow

### Entry Point

Login page → Password/2FA step → (under "Login with recovery key" option) → "Can't login to account?" button

### Step 1: Request Reset Code (Automatic)

When user clicks "Can't login to account?", the email they already entered is used to automatically request a reset code.

- Server sends 6-digit verification code to email
- Code valid for 15 minutes
- Rate limited: 3 requests per email per hour

### Step 2: Enter Code & Confirm Data Loss

User must:
1. Enter the 6-digit verification code from email
2. Toggle ON the confirmation that they accept:
   - All chats, messages, and conversation history will be deleted
   - All app settings and memories will be deleted
   - All embeds will be deleted
   - This action cannot be undone

Only when BOTH conditions are met can the "Reset account" button be clicked.

### Step 3: Account Reset Execution

When reset is triggered:
1. Verify code is valid
2. Delete all client-encrypted data (chats, settings, memories, embeds)
3. Clear all encryption keys and passkeys
4. Invalidate all sessions
5. Show login method setup (password)

### Step 4: Set Up New Login

User sets up new login credentials:
- **Password** - new password for the account

After setup, user is logged in but with a fresh account (preserved data only).

**Note**: Passkey setup during account recovery is not supported. Users can add a passkey later via account settings after logging in with their new password.

## Data Preservation

### Preserved (Server-Side Vault Encrypted)

| Field | Description |
|-------|-------------|
| `encrypted_credit_balance` | User's credit balance |
| `encrypted_username` | Username |
| `encrypted_profileimage_url` | Profile image URL |
| `encrypted_invoice_counter` | Invoice counter |
| `encrypted_gifted_credits_for_signup` | Gifted credits |
| `encrypted_tfa_secret` | 2FA secret (if configured) |
| `encrypted_tfa_app_name` | 2FA app name |

### Preserved (Cleartext)

| Field | Description |
|-------|-------------|
| `stripe_customer_id` | Stripe customer reference |
| `stripe_subscription_id` | Active subscription |
| `subscription_*` | Subscription details |
| `payment_tier` | Payment tier level |
| `account_id` | Account identifier |
| `is_admin` | Admin status |
| `darkmode`, `language` | Preferences |

### Deleted (Client-Side Master Key Encrypted)

| Data Type | Description |
|-----------|-------------|
| **All Chats** | Conversations and messages |
| **App Settings & Memories** | Per-app configurations |
| **User Settings** | `encrypted_settings` |
| **Embeds** | Saved embed content |
| **Hidden Demo Chats** | Dismissed demos |
| **All Encryption Keys** | Password/passkey wrapped keys |
| **All Passkeys** | WebAuthn credentials |
| **API Keys** | User's API keys |

## API Endpoints

### POST `/auth/recovery/request-code`

Request account reset by providing email. Sends a 6-digit verification code via email.

**Request:**
```json
{
  "email": "user@example.com",
  "language": "en",
  "darkmode": false
}
```

**Response:**
```json
{
  "success": true,
  "message": "If an account exists with this email, a verification code will be sent."
}
```

### POST `/auth/recovery/reset-account`

Execute account reset with verification code and new credentials.

**Request:**
```json
{
  "email": "user@example.com",
  "code": "123456",
  "acknowledge_data_loss": true,
  "new_login_method": "password",
  "hashed_email": "...",
  "encrypted_email": "...",
  "encrypted_email_with_master_key": "...",
  "user_email_salt": "...",
  "lookup_hash": "...",
  "encrypted_master_key": "...",
  "salt": "...",
  "key_iv": "..."
}
```

**Response:**
```json
{
  "success": true,
  "message": "Account reset successfully. Please log in with your new credentials.",
  "user_id": "...",
  "username": "JohnDoe"
}
```

## Security Considerations

### Rate Limiting

- Reset code request: 3 per email per hour
- Code verification: 5 attempts per code
- Full reset: 1 per account per 24 hours

### Email Verification

- 6-digit code valid for 15 minutes
- Code invalidated after successful use
- New code required for each reset attempt

### Audit Logging

All reset attempts are logged:
- `recovery_requested` - Code sent
- `recovery_full_reset` - Reset executed

### Post-Reset Security

After full reset:
- All previous sessions are invalidated
- All previous passkeys are removed
- All previous encryption keys are deleted
- All API keys are deleted
- User must set up new login method
- 2FA settings are preserved (if previously configured)

## Implementation Files

### Backend
- [`backend/core/api/app/routes/auth_routes/auth_recovery.py`](../../backend/core/api/app/routes/auth_routes/auth_recovery.py) - Recovery endpoints
- [`backend/core/api/app/schemas/auth_recovery.py`](../../backend/core/api/app/schemas/auth_recovery.py) - Request/response schemas
- [`backend/core/api/app/tasks/email_tasks/recovery_account_email_task.py`](../../backend/core/api/app/tasks/email_tasks/recovery_account_email_task.py) - Email sending task
- Email template: [`backend/core/api/templates/email/account-recovery.mjml`](../../backend/core/api/templates/email/account-recovery.mjml)

### Frontend
- [`frontend/packages/ui/src/components/AccountRecovery.svelte`](../../frontend/packages/ui/src/components/AccountRecovery.svelte) - Account reset flow component
- [`frontend/packages/ui/src/components/PasswordAndTfaOtp.svelte`](../../frontend/packages/ui/src/components/PasswordAndTfaOtp.svelte) - Entry point with "Can't login?" button
- Entry point: Login.svelte → Password/2FA step → (under "Login with recovery key") → "Can't login to account?" button

## Mandatory Recovery Key During Signup

As of the latest update, recovery keys are **mandatory** during signup:
- Auto-generated when user reaches recovery key step
- Auto-downloaded as `openmates_recovery_key.txt`
- User must confirm storage before proceeding

This ensures all users have a recovery option that preserves their data.

**Implementation**: [`RecoveryKeyTopContent.svelte`](../../frontend/packages/ui/src/components/signup/steps/recoverykey/RecoveryKeyTopContent.svelte)

## Related Documentation

- [Signup & Login](./signup_login.md) - Authentication flows
- [Zero-Knowledge Storage](./zero_knowledge_storage.md) - Encryption architecture
- [Passkeys](./passkeys.md) - Passkey-specific details
- [Security Overview](./security.md) - Security principles
