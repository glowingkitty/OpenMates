# Signup & login architecture

> **Implementation Status:**
> - ✅ **IMPLEMENTED**: Email + Password + OTP 2FA signup and login
> - ⚠️ **PLANNED**: Passkey authentication (not yet implemented)
> - ⚠️ **PLANNED**: Magic link login (not yet implemented)
>
> Keep in mind there can still be differences between this planned architecture and the current code implementation.

## Zero-Knowledge Authentication Flow

Our system uses zero-knowledge authentication where the server never sees plaintext passwords, backup codes, or master encryption keys. Authentication is performed by successfully decrypting encrypted data on the client side.

## Signup

### Step 1 - Basics

- User is asked for username and email address and to confirm terms of service and privacy policy
- User clicks continue to start server request
- Server checks if email address is already in use or not and continues to step 2 (confirm email address) if not yet in use

### Step 2 - Confirm email address

- One time confirmation code is sent to email address
- User enters one time code from email and it's validated once entered. If code is valid, signup continues with step 3 (secure account)
- User can also choose to click "Send again"

## Step 3 – Secure Account ✅ **IMPLEMENTED** (Password only)

- **Currently implemented:** User sets up password-based authentication
- **Planned (not yet implemented):** User will be able to choose between passkey or password authentication

### Password Setup (Current Implementation)
- Continue to step 3.1 (setup password)

### Passkey Setup ⚠️ **PLANNED** (not yet implemented)
- If passkey is selected:
	- A request is sent to the server to initiate passkey registration.
	- The server responds with a WebAuthn PublicKeyCredentialCreationOptions object.
	- The frontend uses the browser's WebAuthn API to prompt the user to create a passkey
	- Once the user consents, the browser generates the credential and returns it to the frontend.
	- The frontend sends the credential data to the server.
	- The server verifies the attestation and stores the passkey's credential ID, signCount and public key in the user data in the database.
	- User device is generating encryption key for user and uses WebAuthn PRF extension (supported by iOS 18 & newer, Chrome, Android, Windows 11. If failing: ask user to consider different password manager that supports WebAuthn PRF or signup via password) to encrypt the encryption key, before uploading wrapped encryption key to server
	- User account is created on server
	- User is logged in on device (and consider the "Stay logged in" toggle selection in step 3 to decide where to store decrypted encryption key - in session-storage or local-storage).
	- Continue to step 4 (setup backup codes)

## Step 3.1 - Setup Password ✅ **IMPLEMENTED**

- Enter password & confirm password
- When user clicks continue:
	- **On the user's device, a master encryption key and a unique salt are generated. A wrapping key is derived from the password and salt using Argon2. This wrapping key is used to encrypt the master key.**
	- **The user's hashed email (for lookup), encrypted email (for operations), the salt, and the wrapped master key are sent to the server. The plaintext password is never sent and is not stored on the server in any form.**
	- User account is created on server
	- User is logged in on device (and consider the "Stay logged in" toggle selection in step 3 to decide where to store decrypted encryption key - in session-storage or local-storage).
	- Continue to step 3.2 (setup otp 2fa)

## Step 3.2 - Setup OTP 2FA ✅ **IMPLEMENTED**

- User scans QR code with authenticator app (e.g., Google Authenticator, Authy)
- User enters 6-digit OTP code to verify setup
- Server validates OTP and stores encrypted 2FA secret
- Continue to step 4 (setup backup codes)

## Step 4 - Setup Backup Codes ✅ **IMPLEMENTED**

- Ask if user wants to setup backup codes
- Explain pro: login option in case access to 2FA OTP is lost
- Explain risk: anyone with backup code can login to user account, security risk if not securely stored
- If user chooses to create backup codes: **Backup codes are generated on the server and shown once to the user. They can be used as a second factor (replacing OTP) during password login.**

## Step 5 - Upload profile image

... (work in progress)

## Login Flow

### Password Login ✅ **IMPLEMENTED**:
1. User enters email and password
2. Client computes hashed email for lookup
3. Server returns user's salt, wrapped master key, and Argon2 parameters
4. Client derives wrapping key using Argon2(password, salt, params)
5. Client attempts to decrypt wrapped master key
6. User enters OTP code (or backup code)
7. Server verifies OTP/backup code
8. If verified: server sends encrypted chats/data
9. Client decrypts user data using master key

### Backup Code Login ✅ **IMPLEMENTED**:
1. User enters email and password (same as password login)
2. User selects "Use backup code instead" when prompted for OTP
3. User enters backup code
4. Server verifies backup code and marks it as used
5. Success = authentication, user is logged in

### Passkey Login ⚠️ **PLANNED** (not yet implemented):
1. User clicks "Login with passkey"
2. Browser prompts for passkey authentication
3. Client receives WebAuthn PRF value
4. Client derives lookup_hash and decrypts wrapped master key
5. If successful: user is logged in

### Magic Link Login ⚠️ **PLANNED** (not yet implemented):
See docs/architecture/security.md for planned magic link flow details.

### API Key Access ⚠️ **PLANNED** (not yet implemented):
1. Client sends API key in request header
2. Server hashes API key for lookup
3. If IP is approved: server returns salt, wrapped master key, and encrypted data
4. If IP is pending: server notifies user for approval
5. Client decrypts master key using API key and proceeds with decryption