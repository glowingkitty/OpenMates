# Account Recovery Architecture

> For users who lose access to their login method (password/passkey) and cannot use their recovery key.

## Overview

Account recovery allows users to regain access to their accounts when they've lost their password, passkey, AND recovery key. Given OpenMates' zero-knowledge architecture, this requires a **full account reset** that deletes all client-encrypted data.

**Status**: ✅ **IMPLEMENTED** (including mandatory 2FA for password users)

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

### Step 3: Verify Code

Server verifies the code and returns a one-time verification token (valid for 10 minutes).

### Step 4: Select Login Method

User chooses between:

- **Passkey** (Recommended) - Register a new passkey with PRF extension
- **Password** - Set up a new password

### Step 5: Set Up New Credentials

#### Passkey Flow

1. WebAuthn registration is initiated with PRF extension
2. New master key is generated
3. Master key is wrapped with PRF-derived key
4. Loading screen shown during reset process
5. Account is reset (all client-encrypted data deleted)
6. New encryption keys and passkey are stored
7. User is redirected to login page with success notification

#### Password Flow

1. User enters new password (+ confirmation)
2. **If user doesn't have 2FA configured**:
   - User must set up 2FA before reset can complete (per security policy)
   - QR code + secret shown for 2FA app
   - User selects their 2FA app from a dropdown
   - User enters verification code from their 2FA app
3. New master key is generated
4. Master key is wrapped with password-derived key
5. Loading screen shown during reset process
6. Account is reset (all client-encrypted data deleted)
7. New encryption key is stored
8. If 2FA was set up: 2FA secret + app name saved (vault encrypted)
9. User is redirected to login page with success notification

**Security Note**: Password-based authentication always requires 2FA. If a user didn't have 2FA configured previously, they must set it up during the recovery flow before the reset can proceed.

### Step 6: Login with New Credentials

After reset completes:

- User is **NOT** automatically logged in
- User sees a success notification: "Account reset complete! Please login with your new credentials."
- User must manually login with their new password or passkey

**Note on 2FA**:

- If 2FA was previously configured, the encrypted 2FA secret is preserved server-side (vault encrypted). Users will be prompted for 2FA on their next login.
- If 2FA was NOT previously configured and user chooses password login, they MUST set up 2FA during the recovery flow (enforced by security policy that password + 2FA are inseparable).

### Planned Improvements (TODO)

1. **Confirmation Email**: After successful account reset, a confirmation email should be sent to the user to inform them that their account was reset.

## Data Preservation

### Preserved (Server-Side Vault Encrypted)

| Field                                 | Description                |
| ------------------------------------- | -------------------------- |
| `encrypted_credit_balance`            | User's credit balance      |
| `encrypted_username`                  | Username                   |
| `encrypted_profileimage_url`          | Profile image URL          |
| `encrypted_invoice_counter`           | Invoice counter            |
| `encrypted_gifted_credits_for_signup` | Gifted credits             |
| `encrypted_tfa_secret`                | 2FA secret (if configured) |
| `encrypted_tfa_app_name`              | 2FA app name               |

### Preserved (Cleartext)

| Field                    | Description               |
| ------------------------ | ------------------------- |
| `stripe_customer_id`     | Stripe customer reference |
| `stripe_subscription_id` | Active subscription       |
| `subscription_*`         | Subscription details      |
| `payment_tier`           | Payment tier level        |
| `account_id`             | Account identifier        |
| `is_admin`               | Admin status              |
| `darkmode`, `language`   | Preferences               |

### Deleted (Client-Side Master Key Encrypted)

| Data Type                   | Description                   |
| --------------------------- | ----------------------------- |
| **All Chats**               | Conversations and messages    |
| **App Settings & Memories** | Per-app configurations        |
| **User Settings**           | `encrypted_settings`          |
| **Embeds**                  | Saved embed content           |
| **Hidden Demo Chats**       | Dismissed demos               |
| **All Encryption Keys**     | Password/passkey wrapped keys |
| **All Passkeys**            | WebAuthn credentials          |
| **API Keys**                | User's API keys               |

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

### POST `/auth/recovery/verify-code`

Verify the recovery code and get a verification token for subsequent requests.

**Request:**

```json
{
  "email": "user@example.com",
  "code": "123456"
}
```

**Response:**

```json
{
  "success": true,
  "message": "Verification successful. Please set up your new login method.",
  "verification_token": "...",
  "has_2fa": false
}
```

### POST `/auth/recovery/setup-2fa`

Generate 2FA setup data during recovery (for users without 2FA).

**Request:**

```json
{
  "email": "user@example.com",
  "verification_token": "..."
}
```

**Response:**

```json
{
  "success": true,
  "message": "2FA setup data generated. Please scan the QR code and enter the verification code.",
  "secret": "ABCD1234...",
  "otpauth_url": "otpauth://totp/OpenMates:user@example.com?..."
}
```

### POST `/auth/recovery/reset-account`

Execute account reset with verification token and new credentials.

**Request:**

```json
{
  "email": "user@example.com",
  "verification_token": "...",
  "acknowledge_data_loss": true,
  "new_login_method": "password",
  "hashed_email": "...",
  "encrypted_email": "...",
  "encrypted_email_with_master_key": "...",
  "user_email_salt": "...",
  "lookup_hash": "...",
  "encrypted_master_key": "...",
  "salt": "...",
  "key_iv": "...",
  "tfa_secret": "...",
  "tfa_verification_code": "123456",
  "tfa_app_name": "Google Authenticator"
}
```

**Note**: `tfa_secret`, `tfa_verification_code`, and `tfa_app_name` are required if:

- `new_login_method` is `password`, AND
- User doesn't already have 2FA configured

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
- Code verification: 5 attempts per hour
- 2FA setup during recovery: 10 per hour
- Full reset: 10 per account per 24 hours (email verification provides main security)

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

- [Signup & Login](./signup-and-auth.md) - Authentication flows
- [Zero-Knowledge Storage](./zero-knowledge-storage.md) - Encryption architecture
- [Passkeys](./passkeys.md) - Passkey-specific details
- [Security Overview](./security.md) - Security principles
