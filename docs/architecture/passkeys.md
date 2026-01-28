# Passkey Implementation for OpenMates

## Overview

This document describes the passkey implementation for OpenMates' authentication flow. Passkeys provide passwordless authentication using WebAuthn (FIDO2) while maintaining zero-knowledge encryption principles. The implementation preserves the user's privacy and security model.

**Status**: ✅ **IMPLEMENTED** - Passkey signup and login are fully functional.

**Backend Library**: Uses [`py_webauthn`](https://github.com/duo-labs/py_webauthn) (v2.7.0) for robust WebAuthn ceremony verification, replacing manual signature verification for improved reliability and compatibility.

**Implementation Files**:
- **Backend**: [`backend/core/api/app/routes/auth_routes/auth_passkey.py`](../../backend/core/api/app/routes/auth_routes/auth_passkey.py)
- **Frontend Signup**: [`frontend/packages/ui/src/components/signup/steps/secureaccount/SecureAccountTopContent.svelte`](../../frontend/packages/ui/src/components/signup/steps/secureaccount/SecureAccountTopContent.svelte) - Handles passkey registration during signup
- **Frontend Login**: [`frontend/packages/ui/src/components/Login.svelte`](../../frontend/packages/ui/src/components/Login.svelte) - Main login component with passkey support
- **Crypto Service**: [`frontend/packages/ui/src/services/cryptoService.ts`](../../frontend/packages/ui/src/services/cryptoService.ts)
- **Database Schema**: [`backend/core/directus/schemas/user_passkeys.yml`](../../backend/core/directus/schemas/user_passkeys.yml)

## Security-First Approach: PRF Requirement

**We prioritize security over convenience.** True zero-knowledge encryption requires PRF support.

### Why PRF is Required for Zero-Knowledge Encryption

**Current password model (zero-knowledge)**:
- Password → PBKDF2(password, salt) → wrappingKey
- Server receives: encrypted_master_key + lookup_hash
- Server can't decrypt without password (only client has it)

**Passkey model WITHOUT PRF (not zero-knowledge)**:
- credential_id → HKDF(credential_id, salt) → wrappingKey
- credential_id is PUBLIC, so attacker can derive wrappingKey if server breached
- Violates zero-knowledge principle

**Passkey model WITH PRF (zero-knowledge)**:
- passkey.sign(prf_eval_first) → PRF signature (using private key, where `prf_eval_first = SHA256(rp_id)[:32]`)
- HKDF(PRF_signature, user_email_salt) → wrappingKey
- Server receives: encrypted_master_key + credential_id
- Attacker can't derive PRF signature without passkey's private key
- True zero-knowledge preserved ✓

### PRF (Pseudo-Random Function) Support

**What is PRF?**
- WebAuthn extension that allows the authenticator to sign arbitrary data using its private key
- Signature is deterministic for the same input (same `prf_eval_first` always produces same signature for same passkey)
- We use global salt: `prf_eval_first = SHA256(rp_id)[:32]` (same for all users on same domain)
- Each user's signature is unique (different private key per passkey)
- Private key never leaves the device

**Device Support**:
- ✓ macOS (Passkeys in iCloud Keychain, security keys)
- ✓ iOS (Face ID/Touch ID)
- ✓ Android (Biometrics, Google Password Manager)
- ✓ Windows (Windows Hello, recent security keys)
- ✗ Older devices, some older security keys

**Fallback for Non-PRF Devices:**
If user's device doesn't support PRF, they can:
1. **Use password + 2FA** (already zero-knowledge)
2. **Switch to a PRF-supporting passkey manager** (e.g., iCloud Keychain, Google Password Manager, Passkey)
3. **Use a security key that supports PRF**

**User Experience:**
- During signup: Check device PRF support
- If not supported: Show clear message with options
- Don't allow non-PRF passkey registration (prevents false sense of security)

## Passkey Architecture

### Signup Flow

**Frontend Components**:
- [`SecureAccountTopContent.svelte`](../../frontend/packages/ui/src/components/signup/steps/secureaccount/SecureAccountTopContent.svelte) - User selects passkey or password
- [`PasskeyRegistrationBottomContent.svelte`](../../frontend/packages/ui/src/components/signup/steps/passkey/PasskeyRegistrationBottomContent.svelte) - Handles passkey registration

**Backend Endpoints**:
- `POST /auth/passkey/registration/initiate` - Generates challenge and returns WebAuthn options
- `POST /auth/passkey/registration/complete` - Validates attestation and stores passkey

**Key Storage**:
- Passkey stored in `user_passkeys` table (see schema below)
- Master key wrapped using PRF-derived wrapping key
- Email encrypted with master key and stored as `encrypted_email_with_master_key` for passwordless login

**Implementation**: See [`auth_passkey.py`](../../backend/core/api/app/routes/auth_routes/auth_passkey.py) for registration endpoints.

### Login Flow

**Frontend Components**:
- [`Login.svelte`](../../frontend/packages/ui/src/components/Login.svelte) - Main login component with passkey support (handles complete passkey login flow)

**Backend Endpoints**:
- `POST /auth/passkey/assertion/initiate` - Generates assertion challenge
- `POST /auth/passkey/assertion/verify` - Verifies passkey assertion and returns user data

**Passwordless Login Flow**:
1. User clicks "Login with passkey" (no email entry required)
2. Frontend calls `POST /auth/passkey/assertion/initiate` to get WebAuthn challenge
3. Backend generates challenge with PRF extension using global salt: `SHA256(rp_id)[:32]`
4. User authenticates with passkey (biometric/PIN)
5. Frontend receives PRF signature from authenticator
6. Frontend calls `POST /auth/passkey/assertion/verify` with credential response
7. Backend verifies passkey signature using `py_webauthn` library
8. Backend identifies user by `credential_id` → `hashed_user_id` → `user_id` (via `user_passkeys` table)
9. Backend starts cache warming asynchronously (similar to password login `/lookup` endpoint)
10. Backend returns `encrypted_email_with_master_key`, `encrypted_master_key`, `user_email_salt`, and encryption key data
11. Client derives wrapping key from PRF signature: `HKDF(PRF_signature, user_email_salt)`
12. Client unwraps master key from `encrypted_master_key`
13. Client decrypts email from `encrypted_email_with_master_key` using master key
14. Client derives `email_encryption_key = SHA256(email + user_email_salt)` and `lookup_hash = SHA256(PRF_signature + user_email_salt)`
15. Client completes authentication by calling `POST /auth/login` with `lookup_hash` and `login_method: 'passkey'`
16. Backend verifies `lookup_hash` and creates session
17. Frontend waits for cache warming to complete (via WebSocket sync status) before loading main interface

**Implementation**:
- Backend: [`auth_passkey.py`](../../backend/core/api/app/routes/auth_routes/auth_passkey.py) for assertion verification
- Frontend: [`Login.svelte`](../../frontend/packages/ui/src/components/Login.svelte) for passkey login flow

### Master Key Wrapping

**Challenge**: How to maintain zero-knowledge encryption with passkeys?

**Solution: PRF-Based Master Key Wrapping with Global Salt**

1. During passkey registration, client uses global salt for PRF extension: `prf_eval_first = SHA256(rp_id)[:32]`
2. PRF signature is derived from passkey's private key signing the global salt (only client can create this)
3. Wrapping key derived via `HKDF(PRF_signature, user_email_salt, "masterkey_wrapping")`
4. Master key encrypted with wrapping key and stored on server
5. On login, same global salt is used, ensuring deterministic PRF signature
6. Same process recovers master key deterministically

**Why Global Salt?**
- Enables true passwordless login: no email lookup required before passkey authentication
- Deterministic: same `rp_id` always produces same `prf_eval_first` for all users on same domain
- Secure: Each passkey's private key is unique, so PRF signatures remain unique per user
- Solves "chicken-and-egg" problem: server can send `prf_eval_first` without knowing user identity

**Implementation**: See [`cryptoService.ts`](../../frontend/packages/ui/src/services/cryptoService.ts) for key derivation functions:
- `deriveWrappingKeyFromPRF()` - Derives wrapping key from PRF signature
- `encryptKey()` / `decryptKey()` - Wraps/unwraps master key
- `hashKeyFromPRF()` - Generates lookup_hash from PRF signature

### Email Retrieval for Passwordless Login

**Challenge**: Server needs email for notifications, but user doesn't enter email during passwordless login.

**Solution**: Email encrypted with master key and stored on server as `encrypted_email_with_master_key`.

**Flow**:
1. During signup: Email encrypted with master key → stored on server
2. During login: Server returns `encrypted_email_with_master_key`
3. Client decrypts email using master key (derived from PRF signature)
4. Client derives `email_encryption_key = SHA256(email + user_email_salt)`
5. Client sends `email_encryption_key` to server for notifications
6. Server can decrypt `encrypted_email` (encrypted with `email_encryption_key`) for notifications

**Implementation**: See [`Login.svelte`](../../frontend/packages/ui/src/components/Login.svelte) for email decryption and master key unwrapping logic.

## Database Schema

**Table**: `user_passkeys`
- `hashed_user_id` - SHA256 hash of user_id (indexed, for privacy-preserving lookups)
- `user_id` - Direct reference to user_id (for efficient reverse lookups)
- `credential_id` - Base64-encoded credential ID from WebAuthn (unique)
- `public_key_jwk` - Public key in JWK format (for backward compatibility)
- `public_key_cose` - Public key in COSE format (base64-encoded CBOR bytes) - **Primary format for `py_webauthn` verification**
- `aaguid` - Authenticator Attestation Globally Unique Identifier
- `sign_count` - Counter for detecting cloned authenticators
- `encrypted_device_name` - Optional user-friendly device name (encrypted)
- `registered_at`, `last_used_at` - Timestamps

**Note**: `prf_eval_first` is no longer stored in the database. The global salt approach (`SHA256(rp_id)[:32]`) is used instead, ensuring determinism without per-user storage.

**Schema Definition**: [`user_passkeys.yml`](../../backend/core/directus/schemas/user_passkeys.yml)

**Users Table Additions**:
- `encrypted_email_with_master_key` - Email encrypted with master key (for passwordless login)

**Schema Definition**: [`users.yml`](../../backend/core/directus/schemas/users.yml)

## API Endpoints

### Registration Flow
- `POST /auth/passkey/registration/initiate` - See [`auth_passkey.py`](../../backend/core/api/app/routes/auth_routes/auth_passkey.py) - Generates WebAuthn registration options with PRF extension using global salt
- `POST /auth/passkey/registration/complete` - See [`auth_passkey.py`](../../backend/core/api/app/routes/auth_routes/auth_passkey.py) - Verifies attestation using `py_webauthn` library and stores passkey

### Login Flow
- `POST /auth/passkey/assertion/initiate` - See [`auth_passkey.py`](../../backend/core/api/app/routes/auth_routes/auth_passkey.py) - Generates WebAuthn challenge with PRF extension using global salt
- `POST /auth/passkey/assertion/verify` - See [`auth_passkey.py`](../../backend/core/api/app/routes/auth_routes/auth_passkey.py) - Verifies passkey signature, starts cache warming, returns encrypted user data
- `POST /auth/login` - See [`auth_login.py`](../../backend/core/api/app/routes/auth_routes/auth_login.py) - Completes authentication with `lookup_hash` and `login_method: 'passkey'`

## Security Considerations

### 1. PRF Support Verification
- **Requirement**: Check device PRF support before signup
- **Detection**: Test `navigator.credentials.create()` with PRF extension
- **User Experience**: Show clear message if PRF not supported
- **Fallback**: Offer password + 2FA or passkey manager with PRF support
- **No Degradation**: Never allow non-PRF passkey registration

**Implementation**: See [`SecureAccountTopContent.svelte`](../../frontend/packages/ui/src/components/signup/steps/secureaccount/SecureAccountTopContent.svelte) for PRF validation during passkey registration.

### 2. Sign Count Validation
- Detects cloned authenticators (if sign_count doesn't increase)
- If sign_count ≤ previous, flag as suspicious
- Require additional verification (email confirmation, 2FA)
- Log security event for audit trail

**Implementation**: See [`auth_passkey.py`](../../backend/core/api/app/routes/auth_routes/auth_passkey.py) for sign count validation.

### 3. Challenge Freshness
- Generate new challenge for each registration/assertion
- Challenge expires after 5 minutes if unused
- Prevent replay attacks by validating timestamp

**Implementation**: See [`auth_passkey.py`](../../backend/core/api/app/routes/auth_routes/auth_passkey.py) for challenge caching.

### 4. User ID Lookup Efficiency
- `user_passkeys` table includes `user_id` for efficient reverse lookups
- Query by `hashed_user_id` (indexed) → get `user_id` directly
- No batch-querying of users table required

**Implementation**: See [`directus.py`](../../backend/core/api/app/services/directus/directus.py) for efficient lookup method.

### 5. Cache Warming for Passkey Login
- Cache warming starts immediately after passkey verification when `user_id` is known
- Similar to password login: `/lookup` endpoint starts cache warming, `/passkey/assertion/verify` starts cache warming
- Asynchronous task dispatch: doesn't block passkey verification response
- Frontend waits for cache to be primed (via WebSocket sync status) before loading main interface
- Ensures instant sync experience: chats and data ready when user completes authentication

**Implementation**: See [`auth_passkey.py`](../../backend/core/api/app/routes/auth_routes/auth_passkey.py) for cache warming logic.

## Fallback Scenarios

1. **Browser doesn't support WebAuthn**
   - Show error message with browser recommendations
   - Force user back to password-only signup

2. **User loses passkey**
   - Recovery key is the primary recovery method (mandatory during signup)
   - Email-based account recovery available (see [Account Recovery](./account_recovery.md))

3. **Passkey login fails**
   - Fall back to password login (if password exists)
   - Show "Didn't work? Try password instead"
   - Limit attempts (rate limiting)

4. **Cloned authenticator detected**
   - Flag account as potentially compromised
   - Require 2FA verification
   - Send security alert email
   - Log event for audit trail

## UX Considerations

### Signup
- Clear messaging: "Passkeys are faster and more secure"
- Explain: "You won't need to remember a password"
- Device selection: Recommend saving on phone (resident credential)
- Error handling: Clear messages for failed registration

### Login
- "Sign in with Passkey" as primary option
- Auto-fill supported devices (resident credentials)
- Fallback: "Use email and password instead"
- Device verification: Show which device is being used

### Settings
- View registered passkeys with device names and last used date
- Option to rename passkey
- Option to remove passkey
- Warning: Can't remove last passkey without recovery method

## Migration Path for Existing Users

**Current State**: Users have password-based accounts

**Option 1: Optional Passkey Addition**
- Allow users to add passkey in settings
- Keep password as backup
- User can toggle default login method

**Option 2: Encourage Migration**
- In-app prompt: "Upgrade to passkey for better security"
- One-click migration (user taps passkey button)
- Can still keep password or remove it

**Recommendation**: Start with **Option 1**
- Less disruptive
- Users control their security
- Can encourage in settings/onboarding later

## Future Enhancements

1. **Conditional UI**: Auto-fill passkey on login page (autofill UI)
2. **Backup Codes for Passkey**: Generate backup codes during passkey signup
3. **Passkey Sync**: Cloud-synced passkeys across devices (iCloud Keychain, Google Password Manager)
4. **Cross-Device Sign-in**: Use phone as authenticator for web login
5. **Passkey Renaming**: User-friendly device names in settings
6. **Account Recovery**: Email-based recovery if all passkeys lost

## References

- [WebAuthn Specification](https://www.w3.org/TR/webauthn-2/)
- [WebAuthn PRF Extension](https://w3c.github.io/webauthn/#prf)
- [FIDO2 Overview](https://fidoalliance.org/fido2/)
- [Web Crypto API](https://www.w3.org/TR/WebCryptoAPI/)
- [RFC 5869: HKDF](https://tools.ietf.org/html/rfc5869)
- [OWASP: Authentication Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html)
- [OWASP: Passkeys](https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html#passkeys)
